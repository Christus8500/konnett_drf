from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from apps.customers.models import CustomerProfile


@receiver(post_save, sender=CustomerProfile)
def customer_profile_saved(sender, instance, **kwargs):
    cache_key = f"customer:profile:{instance.user_id}"
    cache.delete(cache_key)


@receiver(post_delete, sender=CustomerProfile)
def customer_profile_deleted(sender, instance, **kwargs):
    cache_key = f"customer:profile:{instance.user_id}"
    cache.delete(cache_key)
