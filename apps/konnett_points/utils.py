from django.utils import timezone

from apps.core.choices import PaymentStatus
from apps.konnett_points.models import PointTransaction, PointPurchase

def update_wallet_available_points_balance(wallet, available_points=0):
    """
    Updates the available points in the given PointWallet based on the sum of all related PointTransaction instances.
    """
    wallet.available_points += available_points
    wallet.save()


def lock_points(wallet, points_to_lock):
    """
    Locks the specified number of points in the given PointWallet.
    """
    if wallet.available_points < points_to_lock:
        raise ValueError("Insufficient available points to lock.")
    
    wallet.available_points -= points_to_lock
    wallet.locked_points += points_to_lock
    wallet.save()


def unlock_points(wallet, points_to_unlock):
    """
    Unlocks the specified number of points in the given PointWallet.
    """
    if wallet.locked_points < points_to_unlock:
        raise ValueError("Insufficient locked points to unlock.")
    
    wallet.locked_points -= points_to_unlock
    wallet.available_points += points_to_unlock
    wallet.save()


def transfer_points(sender_wallet, receiver_wallet, points_to_transfer):
    """
    Transfers points from the sender's PointWallet to the receiver's PointWallet.
    """
    
    sender_wallet.locked_points -= points_to_transfer
    receiver_wallet.earned_points += points_to_transfer
    
    sender_wallet.save()
    receiver_wallet.save()


def deduct_earned_points(wallet, points_to_deduct):
    """
    Deducts the specified number of earned points from the given PointWallet.
    """
    if wallet.earned_points < points_to_deduct:
        raise ValueError("Insufficient earned points to deduct.")
    
    wallet.earned_points -= points_to_deduct
    wallet.save()


def create_point_transaction(wallet, points, transaction_type, reference=None, job=None):
    """
    Creates a new PointTransaction instance for the given PointWallet and JobRequest.
    """
    transaction = PointTransaction.objects.create(
        wallet=wallet,
        job=job,
        points=points,
        transaction_type=transaction_type,
        reference=reference
    )
    return transaction


def create_point_purchase_record(customer, money_amount, points, payment_reference, status=PaymentStatus.PENDING, purchased_at=timezone.now()):
    """
    Creates a new PointPurchase instance for the given CustomerProfile.
    """
    purchase = PointPurchase.objects.create(
        customer=customer,
        money_amount=money_amount,
        points=points,
        payment_reference=payment_reference,
        status=status,
        purchased_at=purchased_at
    )
    return purchase


def update_point_purchase_status_and_purchased_at(purchase, new_status, new_purchased_at=timezone.now()):
    """
    Updates the status and purchased_at fields of the given PointPurchase instance.
    """
    purchase.status = new_status
    if new_purchased_at:
        purchase.purchased_at = new_purchased_at
    purchase.save(update_fields=["status", "purchased_at"])
    