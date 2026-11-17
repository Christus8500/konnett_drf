from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.providers.models import ProviderProfile, ProviderVerification

from apps.core.choices import ProviderVerificationStatus


def _clear_provider_profile_cache(user_id):
    key = f"provider:profile:{user_id}"
    # After commit, so a concurrent request can't re-cache the old data;
    # robust=True logs a cache outage instead of breaking the save.
    transaction.on_commit(lambda: cache.delete(key), robust=True)


# Runs on every save of a ProviderProfile: clears its cached profile and makes sure
# a ProviderVerification row exists (created on first save, self-healing afterwards).
@receiver(post_save, sender=ProviderProfile)
def provider_profile_saved(sender, instance, raw=False, **kwargs):
    if raw:  # loaddata fixtures
        return
    _clear_provider_profile_cache(instance.user_id)
    ProviderVerification.objects.get_or_create(provider=instance)


@receiver(post_delete, sender=ProviderProfile)
def provider_profile_deleted(sender, instance, **kwargs):
    _clear_provider_profile_cache(instance.user_id)


# Keeps ProviderProfile.is_verified in sync with the verification status.
# This is the single place that writes is_verified.
@receiver(post_save, sender=ProviderVerification)
def update_provider_is_verified(sender, instance, raw=False, **kwargs):
    if raw:
        return
    provider = instance.provider
    should_be_verified = instance.status == ProviderVerificationStatus.VERIFIED
    # Only write when the value changes: avoids a pointless save, a cache
    # clear and an extra get_or_create query on every document upload.
    if provider.is_verified != should_be_verified:
        provider.is_verified = should_be_verified
        provider.save(update_fields=["is_verified", "updated_at"])
