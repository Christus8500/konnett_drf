from django.utils import timezone

from rest_framework.exceptions import ValidationError

from apps.core.choices import PaymentStatus
from apps.core.utils import generate_reference
from apps.core.constants import TRANSACTION_REFERENCE_PREFIX, PURCHASE_REFERENCE_PREFIX
from apps.konnett_points.models import PointTransaction, PointPurchase


def credit_available_points(wallet, available_points=0):
    """
    Updates the available points in the given PointWallet based on the sum of all related PointTransaction instances.
    """
    wallet.available_points += available_points
    wallet.save(update_fields=["available_points"])


def lock_points(wallet, points_to_lock):
    """
    Locks the specified number of points in the given PointWallet.
    """
    if wallet.available_points < points_to_lock:
        raise ValidationError(
            {"available_points": "Insufficient available points to lock."}
        )

    wallet.available_points -= points_to_lock
    wallet.locked_points += points_to_lock
    wallet.save(update_fields=["available_points", "locked_points"])


def unlock_points(wallet, points_to_unlock):
    """
    Unlocks the specified number of points in the given PointWallet.
    """
    if wallet.locked_points < points_to_unlock:
        raise ValidationError(
            {"locked_points": "Insufficient locked points to unlock."}
        )

    wallet.locked_points -= points_to_unlock
    wallet.available_points += points_to_unlock
    wallet.save(update_fields=["locked_points", "available_points"])


def transfer_points_to_provider(customer_wallet, provider_wallet, points_to_transfer):
    """
    Transfers points from the customer's Locked Points to the provider's Earned Points.
    """
    if customer_wallet.locked_points < points_to_transfer:
        raise ValidationError(
            {"locked_points": "Insufficient locked points to transfer."}
        )

    customer_wallet.locked_points -= points_to_transfer
    provider_wallet.earned_points += points_to_transfer

    customer_wallet.save(update_fields=["locked_points"])
    provider_wallet.save(update_fields=["earned_points"])


def deduct_earned_points(wallet, points_to_deduct):
    """
    Deducts the specified number of earned points from the given PointWallet.
    """
    if wallet.earned_points < points_to_deduct:
        raise ValidationError(
            {"earned_points": "Insufficient earned points to deduct."}
        )

    wallet.earned_points -= points_to_deduct
    wallet.save()


def create_point_transaction(
    wallet,
    points,
    transaction_type,
    purchase=None,
    job=None,
):
    """
    Creates a new PointTransaction instance for the given PointWallet and JobRequest.
    """
    return PointTransaction.objects.create(
        wallet=wallet,
        purchase=purchase,
        job=job,
        points=points,
        transaction_type=transaction_type,
        transaction_reference=generate_reference(TRANSACTION_REFERENCE_PREFIX),
    )


def create_point_purchase_record(
    customer,
    money_amount,
    points,
    status=PaymentStatus.PENDING,
    purchased_at=None,
):
    """
    Creates a new PointPurchase instance for the given CustomerProfile.
    """
    if purchased_at is None:
        purchased_at = timezone.now()

    return PointPurchase.objects.create(
        customer=customer,
        money_amount=money_amount,
        points=points,
        payment_reference=generate_reference(PURCHASE_REFERENCE_PREFIX),
        status=status,
        purchased_at=purchased_at,
    )


def update_point_purchase_status_and_purchased_at(
    purchase, new_status, new_purchased_at=None
):
    """
    Updates the status and purchased_at fields of the given PointPurchase instance.
    """
    purchase.status = new_status

    if new_purchased_at is None:
        new_purchased_at = timezone.now()

    purchase.purchased_at = new_purchased_at
    purchase.save(update_fields=["status", "purchased_at"])
