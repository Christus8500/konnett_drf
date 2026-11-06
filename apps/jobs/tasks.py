import logging

from celery import shared_task
from django.utils import timezone

from apps.core.choices import JobRequestStatus

from apps.jobs.models import JobRequest
from apps.jobs.services import expire_job

logger = logging.getLogger(__name__)


@shared_task
def expire_overdue_jobs():
    job_ids = list(
        JobRequest.objects.filter(
            deadline__lte=timezone.now(),
            status__in=[
                JobRequestStatus.PENDING,
                JobRequestStatus.OPEN,
                JobRequestStatus.IN_PROGRESS,
                JobRequestStatus.AWAITING_CONFIRMATION,
            ],
        ).values_list("id", flat=True)
    )

    processed = failed = 0
    for job_id in job_ids:
        try:
            if expire_job(JobRequest(pk=job_id)):
                processed += 1
        except Exception:
            failed += 1
            logger.exception("Failed to expire job %s", job_id)

    return f"{processed} processed, {failed} failed."
    