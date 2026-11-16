import logging
import uuid

from django.db import transaction

from rest_framework import serializers

from apps.accounts.bank_details import BankDetailsPasswordMixin, apply_user_update

from apps.customers.models import CustomerProfile

from apps.core.validators import validate_image

from apps.mails.services import queue_email
from apps.mails.tasks import process_email_outbox


logger = logging.getLogger(__name__)
BANK_FIELDS = ("account_number", "account_name", "bank_name")

# Serializer for the CustomerProfile model, handling serialization and deserialization of customer profile data.


class CustomerProfileSerializer(BankDetailsPasswordMixin, serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    email_verified = serializers.BooleanField(
        source="user.email_verified", read_only=True)
    current_password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"}
    )
    phone_number = serializers.CharField(
        source="user.phone_number", required=False)
    first_name = serializers.CharField(
        source="user.first_name", required=False)
    last_name = serializers.CharField(source="user.last_name", required=False)

    account_number = serializers.CharField(
        source="user.account_number", required=False)
    account_name = serializers.CharField(
        source="user.account_name", required=False)
    bank_name = serializers.CharField(source="user.bank_name", required=False)

    profile_image = serializers.ImageField(
        validators=[validate_image], required=False)

    class Meta:
        model = CustomerProfile
        fields = [
            "id", "user_id", "first_name", "last_name", "email", "email_verified",
            "phone_number", "account_number", "account_name", "bank_name",
            "address", "city", "state", "profile_image",
            "created_at", "updated_at", "current_password",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    # Writes user fields through apply_user_update (bank cooldown, logging, alert email).
    @transaction.atomic
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        apply_user_update(instance.user, user_data)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
