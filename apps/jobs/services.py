from django.db import transaction
from django.db.models import F, Avg, Count
from django.utils import timezone

from apps.core.choices import (
    DisputeSource,
    TransactionType,
    JobRequestStatus,
    JobOfferStatus,
)

from apps.providers.models import ProviderProfile

from apps.jobs.models import JobDispute, JobRequest, JobRequestOffer, ProviderRating
from apps.jobs.notifications import (
    create_job_cancelled_notification,
    create_job_completed_by_deadline_notification,
    notify_dispute_opened,
)

from apps.konnett_points.utils import (
    pay_provider,
    release_reserved_points,
)

import logging

logger = logging.getLogger(__name__)


@transaction.atomic
def expire_job(job):
    """
    Automatically handle a job that has reached its deadline.

    Rules:

    PENDING:
        Cancel + refund customer 100%.

    OPEN:
        Cancel + refund customer 100%.

    IN_PROGRESS:
        Move to DISPUTED (source=system_deadline). Nobody is paid until
        an admin resolves it.

    AWAITING_CONFIRMATION:
        Once the deadline AND the review window (REVIEW_WINDOW_HOURS after the
        completion request) have both passed: mark COMPLETED and pay the
        provider in full.

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

    if job.deadline is None:
        return False

    # Delivered jobs get the full review window, even if the provider
    # requested completion just before the deadline.
    if job.status == JobRequestStatus.AWAITING_CONFIRMATION:
        due_at = job.auto_release_at
    else:
        due_at = job.deadline

    if due_at > timezone.now():
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
        job.save(update_fields=["status", "updated_at"])

        release_reserved_points(job, transaction_type=TransactionType.REFUND)

        JobRequestOffer.objects.filter(pk__in=[o.pk for o in pending_offers]).update(
            status=JobOfferStatus.REJECTED
        )

        users = [job.customer.user] + [o.provider.user for o in pending_offers]
        transaction.on_commit(
            lambda: create_job_cancelled_notification(
                users=users,
                job=job,
                robust=True,
            )
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
    # IN PROGRESS: open a system dispute. Nobody is paid;
    # an admin decides using the evidence collected.
    # --------------------------------------------------
    if job.status == JobRequestStatus.IN_PROGRESS:
        updates_count = job.job_progress_updates.count()

        JobDispute.objects.get_or_create(
            job=job,
            defaults={
                "source": DisputeSource.SYSTEM_DEADLINE,
                "system_reason": (
                    "Deadline reached while the job was still in progress. "
                    f"Provider marked started: {'yes' if job.started_at else 'no'}. "
                    f"Progress updates submitted: {updates_count}."
                ),
            },
        )

        job.status = JobRequestStatus.DISPUTED
        job.save(update_fields=["status", "updated_at"])

        # Notify the provider, the customer and the admins.
        notify_dispute_opened(job, provider.user, system=True)

        logger.info("Job %s moved to disputed at deadline.", job.pk)

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
    job.save(update_fields=["status", "completed_at", "updated_at"])

    provider.completed_jobs = F("completed_jobs") + 1
    provider.save(update_fields=["completed_jobs", "updated_at"])

    # Notify the customer and provider of the changes
    transaction.on_commit(
        lambda: create_job_completed_by_deadline_notification(
            users=users,
            job=job,
            robust=True,
        )
    )

    return True


def create_provider_rating(job, provider_id, rating, comment):
    """Call inside transaction.atomic. Locks the provider row to protect stats."""
    provider = (
        ProviderProfile.objects.select_for_update(of=("self",))
        .select_related("user", "address")
        .get(pk=provider_id)
    )
    ProviderRating.objects.create(
        job=job,
        provider=provider,
        customer=job.customer,
        rating=rating,
        comment=comment,
    )
    stats = ProviderRating.objects.filter(provider=provider).aggregate(
        average=Avg("rating"), count=Count("id")
    )
    provider.average_rating = round(stats["average"] or 0, 2)
    provider.ratings_count = stats["count"]
    provider.save(update_fields=["average_rating", "ratings_count", "updated_at"])
    return provider
