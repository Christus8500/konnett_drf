from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.choices import JobOfferStatus

from apps.jobs.models import JobRequestOffer
from apps.jobs.utils import update_job_status_from_offers


# When a JobRequestOffer instance is saved, this function is triggered to update the status of the associated job based on the current offers.
@receiver(post_save, sender=JobRequestOffer)
def update_job_status_on_offer_change(sender, instance, **kwargs):
    if kwargs.get("raw"):  # loaddata/fixtures
        return

    # An accepted offer moves the job to IN_PROGRESS in the accept view.
    # It must never push the job back to PENDING/OPEN.
    if instance.status == JobOfferStatus.ACCEPTED:
        return

    update_job_status_from_offers(instance.job)
