from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.konnett_points.cache import invalidate_transactions, invalidate_withdrawals
from apps.konnett_points.models import PointTransaction, WithdrawalRequest


@receiver(post_save, sender=PointTransaction)
def point_transaction_saved(sender, instance, **kwargs):
    user_id = instance.wallet.user_id  # wallet is already cached on freshly created rows
    transaction.on_commit(lambda: invalidate_transactions(user_id))


@receiver(post_save, sender=WithdrawalRequest)
def withdrawal_request_saved(sender, instance, **kwargs):
    user_id = instance.user_id
    transaction.on_commit(lambda: invalidate_withdrawals(user_id))