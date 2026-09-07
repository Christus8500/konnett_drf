from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from apps.providers.models import ProviderProfile, ProviderVerification

from apps.core.choices import ProviderVerificationStatus


# Signal receiver function that listens for the post_save signal of the ProviderProfile model.
# When a ProviderProfile instance is created, it automatically creates a corresponding ProviderVerification instance linked to that profile.
@receiver(post_save, sender=ProviderProfile)
def provider_profile_saved(sender, instance, **kwargs):
    cache_key = f"provider:profile:{instance.user_id}"
    cache.delete(cache_key)

    ProviderVerification.objects.get_or_create(provider=instance)


@receiver(post_delete, sender=ProviderProfile)
def provider_profile_deleted(sender, instance, **kwargs):
    cache_key = f"provider:profile:{instance.user_id}"
    cache.delete(cache_key)


# Signal receiver function that updates the is_verified field of the associated ProviderProfile instance based on the status of the ProviderVerification instance.
@receiver(post_save, sender=ProviderVerification)
def update_provider_is_verified(sender, instance, **kwargs):
    instance.provider.is_verified = (
        instance.status == ProviderVerificationStatus.VERIFIED
    )
    instance.provider.save(update_fields=["is_verified"])
