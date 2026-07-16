from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.providers.models import ProviderProfile, ProviderVerification
from apps.core.choices import ProviderVerificationStatus

# Signal receiver function that listens for the post_save signal of the ProviderProfile model. 
# When a ProviderProfile instance is created, it automatically creates a corresponding ProviderVerification instance linked to that profile.
@receiver(post_save, sender=ProviderProfile)
def create_provider_verification(sender, instance, **kwargs):
    ProviderVerification.objects.get_or_create(provider=instance)


# Signal receiver function that updates the is_verified field of the associated ProviderProfile instance based on the status of the ProviderVerification instance.
@receiver(post_save, sender=ProviderVerification)
def update_provider_is_verified(sender, instance, **kwargs):
    instance.provider.is_verified = (
        instance.status == ProviderVerificationStatus.VERIFIED
    )
    instance.provider.save(update_fields=["is_verified"])