from decimal import Decimal
from uuid import UUID

from django.contrib.auth import get_user_model

from rest_framework import serializers

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


# WithdrawalRequestSerializer serializes the WithdrawalRequest model,
# including provider details and processed information.
class WithdrawalRequestSerializer(serializers.ModelSerializer):

    class UserInfoSerializer(serializers.ModelSerializer):
        fullname = serializers.SerializerMethodField()

        class Meta:
            model = User
            fields = [
                "fullname",
                "email",
                "phone_number",
                "role",
                "account_number",
                "account_name",
                "bank_name",
            ]

        def get_fullname(self, obj):
            return f"{obj.first_name} {obj.last_name}".strip()

    user = UserInfoSerializer(read_only=True)
    processed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "user",
            "points",
            "withdrawal_reference",
            "status",
            "reject_reason",
            "created_at",
            "processed_by",
            "processed_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "withdrawal_reference",
            "status",
            "reject_reason",
            "created_at",
            "processed_by",
            "processed_at",
        ]


class WithdrawalRejectSerializer(serializers.Serializer):
    reject_reason = serializers.CharField(max_length=1000)


class ApprovedWithdrawalRequestSerializer(serializers.ModelSerializer):
    withdrawal = WithdrawalRequestSerializer(read_only=True)

    class Meta:
        model = ApprovedWithdrawalRequest
        fields = [
            "withdrawal",
        ]
