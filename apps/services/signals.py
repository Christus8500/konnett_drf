from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from apps.services.models import Category, Service


@receiver(post_save, sender=Category)
def category_saved(sender, instance, **kwargs):
    cache.delete_pattern("*categories:list*")


@receiver(post_delete, sender=Category)
def category_deleted(sender, instance, **kwargs):
    cache.delete_pattern("*categories:list*")


@receiver(post_save, sender=Service)
def service_saved(sender, instance, **kwargs):
    # Public services can be affected
    cache.delete_pattern("*services:list*")

    # Only this provider's private service cache is affected
    cache.delete(f"my-services:{instance.provider_id}")


@receiver(post_delete, sender=Service)
def service_deleted(sender, instance, **kwargs):
    # Public services can be affected
    cache.delete_pattern("*services:list*")

    # Only this provider's private service cache is affected
    cache.delete(f"my-services:{instance.provider_id}")