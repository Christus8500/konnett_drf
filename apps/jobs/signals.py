from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.jobs.models import JobRequestOffer
from apps.jobs.utils import update_job_status_from_offers


# When a JobRequestOffer instance is saved, this function is triggered to update the status of the associated job based on the current offers.
@receiver(post_save, sender=JobRequestOffer)
def update_job_status_on_offer_change(sender, instance, **kwargs):
    update_job_status_from_offers(instance.job)