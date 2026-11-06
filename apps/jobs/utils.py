from django.db import transaction

from apps.core.choices import JobRequestStatus, JobOfferStatus

from apps.jobs.models import JobRequest


@transaction.atomic
def update_job_status_from_offers(job):
    """
    Moves a job between PENDING and OPEN based on its pending offers.
    Re-reads the job under a lock, so a stale `job` object is never trusted.
    Callers should already hold the job lock (job first, then offer).
    """
    locked = JobRequest.objects.select_for_update(of=("self",)).get(pk=job.pk)

    if locked.status in (JobRequestStatus.PENDING, JobRequestStatus.OPEN):
        has_pending_offer = locked.job_offers.filter(
            status=JobOfferStatus.PENDING
        ).exists()
        new_status = (
            JobRequestStatus.OPEN if has_pending_offer else JobRequestStatus.PENDING
        )
        if locked.status != new_status:
            locked.status = new_status
            locked.save(update_fields=["status"])

    # Keep the caller's in-memory object in sync.
    job.status = locked.status
