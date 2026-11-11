from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.choices import PaymentStatus, TransactionType, WithdrawalStatus
from apps.core.models import TimeStampedModel, UUIDModel

# Create your models here.


# PointWallet model represents a user's point balance.
class PointWallet(UUIDModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="point_wallet",
    )
    available_points = models.PositiveIntegerField(default=0)
    locked_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return (
            f"{self.user.email} - "
            f"AP: {self.available_points}, LP: {self.locked_points}"
        )


# PointPurchase model represents a purchase of points by a customer.
class PointPurchase(UUIDModel, TimeStampedModel):
    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="point_purchases",
    )
    money_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    points = models.PositiveIntegerField()
    # 10% of the purchased points(update ADMIN_FEE_RATE_PERCENT in constants if percentage changes)
    admin_fee_points = models.PositiveIntegerField(default=0)
    # Actual points credited to the customer's wallet
    credited_points = models.PositiveIntegerField(default=0)
    payment_reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=30,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    purchased_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    points=models.F("admin_fee_points") + models.F("credited_points")
                ),
                name="purchase_points_equal_fee_plus_credited",
            ),
        ]

    def __str__(self):
        return f"{self.customer.fullname} bought {self.points} points"


# WithdrawalRequest model represents a request by a user to withdraw points from their PointWallet.
class WithdrawalRequest(UUIDModel, TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="withdrawal_requests",
    )
    points = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(
        max_length=30,
        choices=WithdrawalStatus.choices,
        default=WithdrawalStatus.PENDING,
        db_index=True,
    )
    withdrawal_reference = models.CharField(max_length=100, unique=True)

    # Snapshot of the bank details at request time, so changing them on the
    # User afterwards can't redirect an already-approved payout.
    account_number = models.CharField(max_length=10)
    account_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)

    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_withdrawal_requests",
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(points__gte=1),
                name="withdrawal_points_gte_1",
            ),
            # Optional: one open request per user at a time. Remove if you
            # want to allow several pending requests.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status=WithdrawalStatus.PENDING),
                name="one_pending_withdrawal_per_user",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.processed_by_id and self.processed_at is None:
            self.processed_at = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "processed_at"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} requested {self.points} points withdrawal"


class ApprovedWithdrawalRequest(UUIDModel):
    withdrawal = models.OneToOneField(
        WithdrawalRequest,
        on_delete=models.PROTECT,
        related_name="approved_withdrawal_request",
    )
    paid = models.BooleanField(default=False, db_index=True)
    paid_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["withdrawal"],
                name="one_approved_record_per_withdrawal",
            )
        ]

    def save(self, *args, **kwargs):
        if self.paid and self.paid_on is None:
            self.paid_on = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "paid_on"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Approved: {self.withdrawal}"


# PointTransaction model represents a transaction of points in a user's PointWallet.
class PointTransaction(UUIDModel, TimeStampedModel):
    wallet = models.ForeignKey(
        PointWallet, on_delete=models.PROTECT, related_name="point_transactions"
    )
    purchase = models.ForeignKey(
        PointPurchase,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    job = models.ForeignKey(
        "jobs.JobRequest",
        on_delete=models.PROTECT,
        null=True,
        related_name="point_transactions",
    )
    withdrawal_request = models.ForeignKey(
        WithdrawalRequest,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="point_transactions",
    )
    points = models.IntegerField()
    transaction_type = models.CharField(
        max_length=30, choices=TransactionType.choices, db_index=True
    )
    transaction_reference = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
            models.Index(fields=["job", "transaction_type"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(points=0),
                name="point_transaction_points_not_zero",
            ),
            # Database-level backstop against paying out / refunding a job twice
            models.UniqueConstraint(
                fields=["job", "wallet", "transaction_type"],
                condition=models.Q(
                    transaction_type__in=[
                        TransactionType.LOCK,
                        TransactionType.EARNED,
                        TransactionType.PROVIDER_PAY,
                        TransactionType.REFUND,
                    ]
                ),
                name="one_settlement_entry_per_job_wallet_type",
            ),
        ]

    def __str__(self):
        return (
            f"{self.wallet.user.email} > "
            f"{self.transaction_type.upper()} > {self.points} points"
        )
