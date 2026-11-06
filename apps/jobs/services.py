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

import logging

logger = logging.getLogger(__name__)


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
        JobRequest.objects.select_for_update(of=("self",))
        .select_related("customer__user")
        .get(pk=job.pk)
    )

    if job.deadline is None or job.deadline > timezone.now():
        return False

    # --------------------------------------------------
    # DISPUTED, COMPLETED, CANCELLED
    # Do absolutely nothing.
    # --------------------------------------------------
    if job.status in (
        JobRequestStatus.DISPUTED,
        JobRequestStatus.COMPLETED,
        JobRequestStatus.CANCELLED,
    ):
        return False

    # --------------------------------------------------
    # PENDING / OPEN: cancel and refund 100%
    # --------------------------------------------------
    if job.status in (JobRequestStatus.PENDING, JobRequestStatus.OPEN):
        pending_offers = list(
            job.job_offers.select_related("provider__user").filter(
                status=JobOfferStatus.PENDING
            )
        )

        job.status = JobRequestStatus.CANCELLED
        job.save(update_fields=["status"])

        release_reserved_points(job, transaction_type=TransactionType.REFUND)

        JobRequestOffer.objects.filter(
            pk__in=[o.pk for o in pending_offers]
        ).update(status=JobOfferStatus.REJECTED)

        users = [job.customer.user] + [o.provider.user for o in pending_offers]
        transaction.on_commit(
            lambda: create_job_cancelled_notification(users=users, job=job)
        )
        return True

    
    if job.status not in (
        JobRequestStatus.IN_PROGRESS,
        JobRequestStatus.AWAITING_CONFIRMATION,
    ):
        return False
    
    # --------------------------------------------------
    # Get accepted provider for payment-related states.
    # --------------------------------------------------
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
        logger.error("Job %s is %s but has no accepted offer.", job.pk, job.status)
        return False

    provider = accepted_offer.provider
    users = [job.customer.user, provider.user]

    # --------------------------------------------------
    # IN PROGRESS: partial pay + refund the rest
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
        transaction.on_commit(
            lambda: create_job_cancelled_provider_partial_pay_notification(
                users=users, job=job
            )
        )

        return True

    # --------------------------------------------------
    # AWAITING CONFIRMATION: pay in full
    # --------------------------------------------------
    pay_provider(
        job,
        accepted_offer,
    )

    job.status = JobRequestStatus.COMPLETED
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "completed_at"])

    provider.completed_jobs = F("completed_jobs") + 1
    provider.save(update_fields=["completed_jobs"])

    # Notify the customer and provider of the changes
    transaction.on_commit(
        lambda: create_job_completed_by_deadline_notification(users=users, job=job)
    )

    return True
