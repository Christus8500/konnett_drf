from rest_framework import serializers

from apps.accounts.bank_details import BankDetailsPasswordMixin
from apps.accounts.serializers import (
    USER_FIELDS,
    UserFieldsSerializer,
    ProfileUpdateMixin,
)

from apps.customers.models import CustomerProfile

from apps.core.validators import validate_image


# Serializer for the CustomerProfile model, handling serialization and deserialization of customer profile data.
class CustomerProfileSerializer(
    BankDetailsPasswordMixin,
    ProfileUpdateMixin,
    UserFieldsSerializer,
    serializers.ModelSerializer,
):
    profile_image = serializers.ImageField(validators=[validate_image], required=False)

    address = serializers.CharField(
        source="address.address",
        required=False,
    )

    city = serializers.CharField(
        source="address.city",
        required=False,
    )

    state = serializers.CharField(
        source="address.state",
        required=False,
    )
    latitude = serializers.DecimalField(
        source="address.latitude",
        max_digits=9,
        decimal_places=6,
        required=False,
    )
    longitude = serializers.DecimalField(
        source="address.longitude",
        max_digits=9,
        decimal_places=6,
        required=False,
    )

    class Meta:
        model = CustomerProfile
        fields = [
            "id",
            *USER_FIELDS,
            "address",
            "city",
            "state",
            "latitude",
            "longitude",
            "profile_image",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
