from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.conf import settings
from django.core.validators import MinValueValidator

from apps.core.models import UUIDModel, TimeStampedModel
from apps.core.choices import PaymentStatus, TransactionType, WithdrawalStatus, UserRole

# Create your models here.


# PointWallet model represents a user's point balance.
class PointWallet(UUIDModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="point_wallet",
    )
    available_points = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        default=0,
    )
    locked_points = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        default=0,
    )

    def __str__(self):
        return (
            f"{self.user.first_name} {self.user.last_name} - "
            f"AP: {self.available_points} points, "
            f"LP: {self.locked_points} points"
        )


# PointPurchase model represents a purchase of points by a customer.
class PointPurchase(UUIDModel, TimeStampedModel):
    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="point_purchases",
    )
    money_amount = models.DecimalField(
        max_digits=20, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    points = models.PositiveIntegerField()
    # 10% of the purchased points
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

    def __str__(self):
        return f"{self.customer.fullname} bought {self.points} points"


# WithdrawalRequest model represents a request by a provider to withdraw points from their PointWallet.
class WithdrawalRequest(UUIDModel, TimeStampedModel):
    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE,
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

    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="processed_withdrawal_request",
    )
    processed_at = models.DateTimeField(blank=True, null=True)

    reject_reason = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.processed_by and self.processed_at is None:
            self.processed_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.provider} requested {self.points}points withdrawal"


class ApprovedWithdrawalRequest(UUIDModel):
    withdrawal = models.ForeignKey(
        WithdrawalRequest,
        on_delete=models.CASCADE,
        related_name="approved_withdrawal_request",
    )
    paid = models.BooleanField(default=False)
    paid_on = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.paid and self.paid_on is None:
            self.paid_on = timezone.now()
        super().save(*args, **kwargs)


# PointTransaction model represents a transaction of points in a user's PointWallet.
class PointTransaction(UUIDModel, TimeStampedModel):
    wallet = models.ForeignKey(
        PointWallet, on_delete=models.CASCADE, related_name="point_transactions"
    )
    purchase = models.ForeignKey(
        PointPurchase,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="transaction",
    )
    job = models.ForeignKey(
        "jobs.JobRequest",
        on_delete=models.CASCADE,
        null=True,
        related_name="point_transactions",
    )
    withdrawal_request = models.ForeignKey(
        WithdrawalRequest,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
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
        ]

    def __str__(self):
        return f"{self.wallet.user.first_name} {self.wallet.user.last_name}'s Wallet > {self.transaction_type.upper()} > {self.points} points"
