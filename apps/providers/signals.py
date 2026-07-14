from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.providers.models import ProviderProfile, ProviderVerification

# Signal receiver function that listens for the post_save signal of the ProviderProfile model. 
# When a ProviderProfile instance is created, it automatically creates a corresponding ProviderVerification instance linked to that profile.
@receiver(post_save, sender=ProviderProfile)
def create_provider_verification(sender, instance, **kwargs):
    ProviderVerification.objects.get_or_create(provider=instance)