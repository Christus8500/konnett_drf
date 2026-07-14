from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.providers.models import ProviderProfile, ProviderVerification

@receiver(post_save, sender=ProviderProfile)
def create_provider_verification(sender, instance, **kwargs):
    ProviderVerification.objects.get_or_create(provider=instance)