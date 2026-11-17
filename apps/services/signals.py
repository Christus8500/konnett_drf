import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.services.models import Category, Service


logger = logging.getLogger(__name__)


def _delete_patterns(*patterns):
    """
    Delete cache keys matching the patterns AFTER the surrounding transaction
    commits (immediately if there is none). Deleting before commit lets a
    concurrent request re-cache the old data. A Redis outage is logged and
    never breaks the save/delete that triggered it.
    """

    def run():
        for pattern in patterns:
            try:
                cache.delete_pattern(pattern)
            except Exception:
                logger.exception("Cache invalidation failed pattern=%s", pattern)

    transaction.on_commit(run)


def _service_patterns(provider_id=None):
    return [
        "*services:list*",  # public list, one key per page/filter combination
        # per-provider private list, one key per page
        f"my-services:{provider_id}:*" if provider_id else "my-services:*",
    ]


@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
def category_changed(sender, instance, **kwargs):
    # Services embed their category, so a rename or delete changes service lists too.
    _delete_patterns("*categories:list*", *_service_patterns())


@receiver(post_save, sender=Service)
@receiver(post_delete, sender=Service)
def service_changed(sender, instance, **kwargs):
    _delete_patterns(*_service_patterns(instance.provider_id))