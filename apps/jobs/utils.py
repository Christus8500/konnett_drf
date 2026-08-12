from apps.core.choices import JobRequestStatus, JobOfferStatus


# Updates the status of a job based on the status of its offers.
def update_job_status_from_offers(job):
    if job.status not in (
        JobRequestStatus.PENDING,
        JobRequestStatus.OPEN,
    ):
        return

    has_pending_offer = job.job_offers.filter(status=JobOfferStatus.PENDING).exists()

    new_status = (
        JobRequestStatus.OPEN if has_pending_offer else JobRequestStatus.PENDING
    )

    if job.status != new_status:
        job.status = new_status
        job.save(update_fields=["status"])
