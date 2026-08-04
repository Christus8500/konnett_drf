from django.db import transaction

from apps.core.choices import TransactionType
from apps.konnett_points.utils import (
    lock_points,
    unlock_points,
    transfer_points_to_provider,
    create_point_transaction,
)


@transaction.atomic
def reserve_job_points(job):
    """
    Reserve the customer's points for a newly created job.
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
    Adjust the customer's reserved points when a job's points amount changes.

    - If the new amount is higher, lock the difference.
    - If the new amount is lower, unlock the difference.
    - Create a single ADJUSTMENT transaction for the amount changed.
    """

    wallet = job.customer.user.point_wallet

    difference = job.points_amount - old_points_amount

    if difference == 0:
        return None

    if difference > 0:
        # Lock additional points
        lock_points(wallet, difference)
    else:
        # Release excess locked points
        unlock_points(wallet, abs(difference))

    return create_point_transaction(
        wallet=wallet,
        points=difference,
        transaction_type=TransactionType.ADJUSTMENT,
        job=job,
    )


@transaction.atomic
def release_reserved_points(job, transaction_type=TransactionType.REFUND):
    """
    Return the reserved points to the customer's available balance.
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
    Releases the customer's reserved points to the accepted provider.
    """

    customer_wallet = job.customer.user.point_wallet
    provider_wallet = accepted_offer.provider.user.point_wallet

    points_to_transfer = job.points_amount

    transfer_points_to_provider(
        customer_wallet, provider_wallet, points_to_transfer
    )

    customer_transaction = create_point_transaction(
        wallet=customer_wallet,
        points=points_to_transfer,
        transaction_type=TransactionType.PROVIDER_PAY,
        job=job,
    )

    provider_transaction = create_point_transaction(
        wallet=provider_wallet,
        points=points_to_transfer,
        transaction_type=TransactionType.EARNED,
        job=job,
    )

    return customer_transaction, provider_transaction
