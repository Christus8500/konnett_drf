from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.choices import TransactionType, JobRequestStatus, JobOfferStatus
from apps.core.constants import JOB_IN_PROGRESS_PROVIDER_PERCENT

from apps.jobs.models import JobRequest, JobRequestOffer
from apps.jobs.notifications import (
    create_job_cancelled_notification,
    create_job_cancelled_provider_partial_pay_notification,
    create_job_completed_by_deadline_notification,
)

from apps.konnett_points.utils import (
    pay_provider,
    pay_provider_partial,
    release_reserved_points,
)


# TODO:
# Setup Celery and wire this
@transaction.atomic
def expire_job(job, in_progress_percentage=JOB_IN_PROGRESS_PROVIDER_PERCENT):
    """
    Automatically handle a job that has reached its deadline.

    Rules:

    PENDING:
        Cancel + refund customer 100%.

    OPEN:
        Cancel + refund customer 100%.

    IN_PROGRESS:
        Cancel + pay provider a percentage of the job points.
        Refund the remaining points to customer.

    AWAITING_CONFIRMATION:
        Cancel + pay provider in full.

    DISPUTED:
        Do nothing. Admin must resolve it.

    COMPLETED:
        Do nothing.

    CANCELLED:
        Do nothing.

    Returns:
        True  -> job was processed
        False -> job was not processed
    """

    # Lock the job so another request/worker cannot process
    # the same job at the same time.
    job = (
        JobRequest.objects.select_for_update()
        .select_related(
            "customer",
            "customer__user",
        )
        .get(pk=job.pk)
    )

    # No deadline means there is nothing to expire.
    if job.deadline is None:
        return False

    # Deadline has not been reached.
    if job.deadline > timezone.now():
        return False

    # --------------------------------------------------
    # DISPUTED
    # --------------------------------------------------
    # Do absolutely nothing.
    if job.status == JobRequestStatus.DISPUTED:
        return False

    # --------------------------------------------------
    # COMPLETED
    # --------------------------------------------------
    if job.status == JobRequestStatus.COMPLETED:
        return False

    # --------------------------------------------------
    # CANCELLED
    # --------------------------------------------------
    if job.status == JobRequestStatus.CANCELLED:
        return False

    # --------------------------------------------------
    # PENDING / OPEN
    # --------------------------------------------------
    if job.status in (
        JobRequestStatus.PENDING,
        JobRequestStatus.OPEN,
    ):
        job.status = JobRequestStatus.CANCELLED

        job.save(update_fields=["status"])

        # Return 100% of the customer's reserved points.
        release_reserved_points(
            job,
            transaction_type=TransactionType.REFUND,
        )

        # Notify the customer and all providers who made offers of cancelled job
        users = [job.customer.user]
        users.extend(
            offer.provider.user
            for offer in job.job_offers.select_related("provider__user").all()
        )
        create_job_cancelled_notification(
            users=users,
            job=job,
        )

        return True

    # --------------------------------------------------
    # Get accepted provider for payment-related states.
    # --------------------------------------------------
    if job.status in (
        JobRequestStatus.IN_PROGRESS,
        JobRequestStatus.AWAITING_CONFIRMATION,
    ):
        accepted_offer = (
            JobRequestOffer.objects.select_related(
                "provider",
                "provider__user",
            )
            .filter(
                job=job,
                status=JobOfferStatus.ACCEPTED,
            )
            .first()
        )

        # Safety check:
        # Never automatically pay a provider if there is
        # no accepted offer.
        if accepted_offer is None:
            return False

    # --------------------------------------------------
    # IN PROGRESS
    # --------------------------------------------------
    if job.status == JobRequestStatus.IN_PROGRESS:

        pay_provider_partial(
            job=job,
            accepted_offer=accepted_offer,
            percentage=in_progress_percentage,
        )

        job.status = JobRequestStatus.CANCELLED

        job.save(update_fields=["status"])

        # Notify the customer and provider of the changes
        users = [job.customer.user, accepted_offer.provider.user]
        create_job_cancelled_provider_partial_pay_notification(
            users=users,
            job=job,
        )

        return True

    # --------------------------------------------------
    # AWAITING CONFIRMATION
    # --------------------------------------------------
    if job.status == JobRequestStatus.AWAITING_CONFIRMATION:

        # Provider receives the normal full-job payment.
        pay_provider(
            job,
            accepted_offer,
        )

        job.status = JobRequestStatus.COMPLETED

        job.save(update_fields=["status", "completed_at"])

        accepted_offer.provider.completed_jobs = F("completed_jobs") + 1
        accepted_offer.provider.save(update_fields=["completed_jobs"])

        # Notify the customer and provider of the changes
        users = [job.customer.user, accepted_offer.provider.user]
        create_job_completed_by_deadline_notification(
            users=users,
            job=job,
        )

        return True

    # Unknown/unhandled status.
    return False
