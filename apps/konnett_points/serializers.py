from decimal import Decimal
from uuid import UUID

from django.contrib.auth import get_user_model

from rest_framework import serializers

from apps.core.constants import MINIMUM_WITHDRAW_POINTS
from apps.core.utils import mask_account_number

from apps.konnett_points.models import (
    PointWallet,
    PointPurchase,
    PointTransaction,
    WithdrawalRequest,
    ApprovedWithdrawalRequest,
)

User = get_user_model()


# UserPointWalletSerializer serializes the PointWallet model,
# including the user's email and available/locked points.
class UserPointWalletSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = PointWallet
        fields = ["id", "user", "available_points", "locked_points"]
        read_only_fields = fields


# PointPurchaseSerializer serializes the PointPurchase model,
# including customer details and purchase information.
class PointPurchaseSerializer(serializers.ModelSerializer):
    customer_fullname = serializers.CharField(
        source="customer.fullname", read_only=True
    )
    customer_email = serializers.EmailField(
        source="customer.user.email",
        read_only=True,
    )
    customer_phone_number = serializers.CharField(
        source="customer.user.phone_number",
        read_only=True,
    )

    class Meta:
        model = PointPurchase
        fields = [
            "id",
            "customer_fullname",
            "customer_email",
            "customer_phone_number",
            "money_amount",
            "points",
            "payment_reference",
            "status",
            "purchased_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "customer_fullname",
            "customer_email",
            "customer_phone_number",
            "points",
            "payment_reference",
            "status",
            "purchased_at",
            "created_at",
        ]

    # validate_money_amount ensures that the money amount is a whole number and meets the minimum requirement.
    def validate_money_amount(self, value):
        if value % 1 != 0:
            raise serializers.ValidationError("Only whole naira amounts are allowed.")
        elif value < 100:
            raise serializers.ValidationError("Minimum amount is 100")
        return value


# PointTransactionSerializer serializes the PointTransaction model,
# including wallet email, purchase ID, job ID, and withdrawal request ID.
class PointTransactionSerializer(serializers.ModelSerializer):
    wallet_email = serializers.EmailField(
        source="wallet.user.email",
        read_only=True,
    )
    purchase_id = serializers.SerializerMethodField()
    job_id = serializers.SerializerMethodField()
    withdrawal_request_id = serializers.SerializerMethodField()

    class Meta:
        model = PointTransaction
        fields = [
            "id",
            "wallet_email",
            "purchase_id",
            "points",
            "transaction_type",
            "job_id",
            "withdrawal_request_id",
            "transaction_reference",
            "created_at",
        ]
        read_only_fields = fields

    def get_purchase_id(self, obj) -> UUID | None:
        return obj.purchase_id

    def get_job_id(self, obj) -> UUID | None:
        return obj.job_id

    def get_withdrawal_request_id(self, obj) -> UUID | None:
        return obj.withdrawal_request_id


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    """For the person who made the request. Account number is masked."""

    account_number = serializers.SerializerMethodField()

    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "points",
            "withdrawal_reference",
            "status",
            "account_number",
            "account_name",
            "bank_name",
            "reject_reason",
            "created_at",
            "processed_at",
        ]
        read_only_fields = [
            "id",
            "withdrawal_reference",
            "status",
            "account_name",
            "bank_name",
            "reject_reason",
            "created_at",
            "processed_at",
        ]

    def get_account_number(self, obj) -> str:
        return mask_account_number(obj.account_number)

    def validate_points(self, value):
        if value < MINIMUM_WITHDRAW_POINTS:
            raise serializers.ValidationError(
                f"Minimum points to withdraw is {MINIMUM_WITHDRAW_POINTS}."
            )
        return value


class AdminWithdrawalRequestSerializer(serializers.ModelSerializer):
    """For admins paying out: full bank details from the request's snapshot."""

    user_fullname = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)
    processed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "user_fullname",
            "user_email",
            "user_phone_number",
            "user_role",
            "points",
            "withdrawal_reference",
            "status",
            "account_number",
            "account_name",
            "bank_name",
            "reject_reason",
            "created_at",
            "processed_by",
            "processed_at",
        ]
        read_only_fields = fields


class WithdrawalRejectSerializer(serializers.Serializer):
    reject_reason = serializers.CharField(max_length=1000)


class ApprovedWithdrawalRequestSerializer(serializers.ModelSerializer):
    withdrawal = AdminWithdrawalRequestSerializer(read_only=True)

    class Meta:
        model = ApprovedWithdrawalRequest
        fields = ["id", "withdrawal", "paid", "paid_on"]
        read_only_fields = fields
