from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from apps.core.choices import PaymentStatus, TransactionType
from apps.core.utils import generate_reference
from apps.core.constants import (
    TRANSACTION_REFERENCE_PREFIX,
    PURCHASE_REFERENCE_PREFIX,
    ADMIN_FEE_RATE,
)

from apps.konnett_points.models import PointTransaction, PointPurchase

# ^ ################### WALLET HELPER FUNCTIONS ####################


def credit_available_points(wallet, points):
    """
    Add points to a wallet's available balance.
    """
    wallet.available_points += points
    wallet.save(update_fields=["available_points"])


def lock_points(wallet, points_to_lock):
    """
    Move points from available_points to locked_points.

    This is used whenever points need to be reserved and prevented
    from being spent or withdrawn until the operation is resolved.
    """
    if points_to_lock <= 0:
        raise ValidationError({"points": "Points to lock must be greater than zero."})

    if wallet.available_points < points_to_lock:
        raise ValidationError({"available_points": "Insufficient available points."})

    wallet.available_points -= points_to_lock
    wallet.locked_points += points_to_lock

    wallet.save(
        update_fields=[
            "available_points",
            "locked_points",
        ]
    )


def unlock_points(wallet, points_to_unlock):
    """
    Move points from locked_points back to available_points.
    """
    if points_to_unlock <= 0:
        raise ValidationError({"points": "Points to unlock must be greater than zero."})

    if wallet.locked_points < points_to_unlock:
        raise ValidationError({"locked_points": "Insufficient locked points."})

    wallet.locked_points -= points_to_unlock
    wallet.available_points += points_to_unlock

    wallet.save(
        update_fields=[
            "locked_points",
            "available_points",
        ]
    )


def deduct_locked_points(wallet, points_to_deduct):
    """
    Permanently deduct points from the wallet's locked balance.

    Used when a previously locked amount is successfully consumed,
    such as an approved withdrawal.
    """
    if points_to_deduct <= 0:
        raise ValidationError({"points": "Points to deduct must be greater than zero."})

    if wallet.locked_points < points_to_deduct:
        raise ValidationError({"locked_points": "Insufficient locked points."})

    wallet.locked_points -= points_to_deduct

    wallet.save(update_fields=["locked_points"])


# ^ ################### PURCHASE HELPERS ####################


def create_point_purchase_record(
    customer,
    money_amount,
    status=PaymentStatus.PENDING,
):
    points = int(money_amount)
    admin_fee_points = int(points * ADMIN_FEE_RATE)
    credited_points = points - admin_fee_points

    return PointPurchase.objects.create(
        customer=customer,
        money_amount=money_amount,
        points=points,
        admin_fee_points=admin_fee_points,
        credited_points=credited_points,
        payment_reference=generate_reference(PURCHASE_REFERENCE_PREFIX),
        status=status,
    )


def update_purchase_status(
    purchase,
    new_status,
    purchased_at=None,
):
    """
    Update the status of a PointPurchase.

    If purchased_at is supplied, use it.
    If the purchase becomes successful and no timestamp is supplied,
    use the current time.
    """
    purchase.status = new_status
    update_fields = ["status"]

    if purchased_at is not None:
        purchase.purchased_at = purchased_at
        update_fields.append("purchased_at")

    elif new_status == PaymentStatus.SUCCESSFUL:
        purchase.purchased_at = timezone.now()
        update_fields.append("purchased_at")

    purchase.save(update_fields=update_fields)

    return purchase


# ^ ################### TRANSACTION HELPERS ####################


def create_point_transaction(
    wallet,
    points,
    transaction_type,
    purchase=None,
    job=None,
    withdrawal_request=None,
):
    """
    Creates a PointTransaction for the given wallet.
    """
    return PointTransaction.objects.create(
        wallet=wallet,
        purchase=purchase,
        job=job,
        withdrawal_request=withdrawal_request,
        points=points,
        transaction_type=transaction_type,
        transaction_reference=generate_reference(TRANSACTION_REFERENCE_PREFIX),
    )


# ^ ################### JOB POINT HELPERS ####################


@transaction.atomic
def reserve_job_points(job):
    """
    Reserve the customer's points for a newly created job.

    available_points -> locked_points
    """
    wallet = job.customer.user.point_wallet
    points_to_lock = job.points_amount

    lock_points(wallet, points_to_lock)

    return create_point_transaction(
        wallet=wallet,
        points=points_to_lock,
        transaction_type=TransactionType.LOCK,
        job=job,
    )


@transaction.atomic
def adjust_reserved_points(job, old_points_amount):
    """
    Adjust the customer's locked points when a job's point amount changes.

    If the new amount is higher:
        available_points -> locked_points

    If the new amount is lower:
        locked_points -> available_points
    """
    wallet = job.customer.user.point_wallet

    difference = job.points_amount - old_points_amount

    if difference == 0:
        return None

    if difference > 0:
        lock_points(wallet, difference)
    else:
        unlock_points(wallet, abs(difference))

    return create_point_transaction(
        wallet=wallet,
        points=difference,
        transaction_type=TransactionType.ADJUSTMENT,
        job=job,
    )


@transaction.atomic
def release_reserved_points(
    job,
    transaction_type=TransactionType.REFUND,
):
    """
    Return the customer's reserved points to their available balance.

    locked_points -> available_points
    """
    wallet = job.customer.user.point_wallet
    points_to_unlock = job.points_amount

    unlock_points(wallet, points_to_unlock)

    return create_point_transaction(
        wallet=wallet,
        points=points_to_unlock,
        transaction_type=transaction_type,
        job=job,
    )


@transaction.atomic
def pay_provider(job, accepted_offer):
    """
    Transfer the customer's locked points to the provider's
    available balance.

    Customer:
        locked_points -> deducted

    Provider:
        available_points -> increased
    """
    customer_wallet = job.customer.user.point_wallet
    provider_wallet = accepted_offer.provider.user.point_wallet

    points_to_transfer = job.points_amount

    if customer_wallet.locked_points < points_to_transfer:
        raise ValidationError({"locked_points": "Insufficient locked points."})

    admin_fee_points = int(points_to_transfer * ADMIN_FEE_RATE)
    provider_points = points_to_transfer - admin_fee_points

    # Remove the full amount from customer's locked balance
    customer_wallet.locked_points -= points_to_transfer
    # Give 90% to provider
    provider_wallet.available_points += provider_points

    customer_wallet.save(update_fields=["locked_points"])
    provider_wallet.save(update_fields=["available_points"])

    # Record the actual amount the provider earned
    provider_transaction = create_point_transaction(
        wallet=provider_wallet,
        points=provider_points,
        transaction_type=TransactionType.EARNED,
        job=job,
    )

    # Store the fee and provider earning on the job
    job.admin_fee_points = admin_fee_points
    job.provider_earning_points = provider_points

    job.save(
        update_fields=[
            "admin_fee_points",
            "provider_earning_points",
        ]
    )

    # Record customer's payment
    customer_transaction = create_point_transaction(
        wallet=customer_wallet,
        points=points_to_transfer,
        transaction_type=TransactionType.PROVIDER_PAY,
        job=job,
    )

    return customer_transaction, provider_transaction


# ^ ################### WITHDRAWAL HELPERS ####################


@transaction.atomic
def lock_withdrawal_points(wallet, points):
    """
    Lock a provider's points for a withdrawal request.

    available_points -> locked_points
    """
    lock_points(wallet, points)


@transaction.atomic
def approve_withdrawal_points(wallet, points):
    """
    Permanently deduct points that were locked for a withdrawal.

    locked_points -> deducted
    """
    deduct_locked_points(wallet, points)


@transaction.atomic
def reject_withdrawal_points(wallet, points):
    """
    Return rejected withdrawal points to the provider's
    available balance.

    locked_points -> available_points
    """
    unlock_points(wallet, points)
