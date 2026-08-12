from decimal import Decimal

from rest_framework import serializers

from apps.konnett_points.models import (
    PointWallet,
    PointPurchase,
    PointTransaction,
    WithdrawalRequest,
)

from apps.providers.models import ProviderProfile


class UserPointWalletSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = PointWallet
        fields = ["id", "user", "available_points", "locked_points"]
        read_only_fields = fields


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

    def validate_money_amount(self, value):
        if value % 1 != 0:
            raise serializers.ValidationError("Only whole naira amounts are allowed.")
        elif value < 100:
            raise serializers.ValidationError("Minimum amount is 100")
        return value


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

    def get_purchase_id(self, obj):
        return obj.purchase_id

    def get_job_id(self, obj):
        return obj.job_id

    def get_withdrawal_request_id(self, obj):
        return obj.withdrawal_request_id


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    class ProviderInfoSerializer(serializers.ModelSerializer):
        provider_email = serializers.CharField(source="user.email", read_only=True)
        provider_phone_number = serializers.CharField(source="user.phone_number", read_only=True)

        class Meta:
            model = ProviderProfile
            fields = [
                "business_name",
                "provider_email",
                "provider_phone_number",
                "profile_image",
                "account_number",
                "account_name",
                "bank_name",
            ]

    provider = ProviderInfoSerializer(read_only=True)
    processed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "provider",
            "points",
            "withdrawal_reference",
            "status",
            "created_at",
            "processed_by",
            "processed_at",
        ]
        read_only_fields = [
            "id",
            "provider",
            "withdrawal_reference",
            "status",
            "created_at",
            "processed_by",
            "processed_at",
        ]
