from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.cache import cache

from apps.konnett_points.models import PointTransaction, WithdrawalRequest


@receiver(post_save, sender=PointTransaction)
def user_point_transaction_saved(sender, instance, **kwargs):
    cache_key = f"wallet:{instance.wallet_id}:transactions"
    cache.delete_pattern(f"*{cache_key}*")


@receiver(post_save, sender=WithdrawalRequest)
def withdrawal_request_saved(sender, instance, **kwargs):
    provider_cache_key = f"withdrawal_requests:provider:{instance.provider_id}"

    admin_cache_key = "withdrawal_requests:admin:pending"

    cache.delete_pattern(f"*{provider_cache_key}*")
    cache.delete(admin_cache_key)
