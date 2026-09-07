from django.db import transaction

from rest_framework import serializers

from apps.providers.models import ProviderProfile, ProviderVerification

from apps.core.validators import validate_image
from apps.core.models import Address
from apps.core.serializers import AddressSerializer
from apps.core.choices import ProviderVerificationStatus



# Serializer for the ProviderProfile model, handling serialization and deserialization of provider profile data.
class ProviderProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", required=False, read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", required=False)
    email = serializers.EmailField(source="user.email", required=False)
    first_name = serializers.CharField(source="user.first_name", required=False)
    last_name = serializers.CharField(source="user.last_name", required=False)

    profile_image = serializers.ImageField(
        validators=[validate_image],
        required=False,
    )

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
        model = ProviderProfile
        fields = [
            "id",
            "user_id",
            "phone_number",
            "email",
            "first_name",
            "last_name",
            "business_name",
            "is_available",
            "bio",
            "profile_image",
            "is_verified",
            "years_of_experience",
            "average_rating",
            "ratings_count",
            "completed_jobs",
            "address",
            "city",
            "state",
            "latitude",
            "longitude",
            "account_number",
            "account_name",
            "bank_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user_id",
            "email",
            "is_verified",
            "average_rating",
            "ratings_count",
            "completed_jobs",
            "created_at",
            "updated_at",
        ]

    def validate_years_of_experience(self, value):
        if value < 0:
            raise serializers.ValidationError("Years of experience cannot be negative.")
        return value

    # Validation method to ensure that the business name is unique across all provider profiles, excluding the current instance being updated.
    def validate_business_name(self, value):
        if (
            ProviderProfile.objects.filter(business_name=value)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise serializers.ValidationError("Business name already exists.")
        return value

    # Overriding the serializer update method
    # So the serializer will know how to update the values on the "User" and "Address" table
    @transaction.atomic
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        address_data = validated_data.pop("address", {})

        # Update user fields
        user = instance.user

        for attr, value in user_data.items():
            setattr(user, attr, value)

        if user_data:
            user.save()

        # Create or update provider address
        if address_data:
            if instance.address:
                address = instance.address

                for attr, value in address_data.items():
                    setattr(address, attr, value)

                address.save()
            else:
                address = Address.objects.create(**address_data)

                instance.address = address

        # Update provider profile fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        return instance


# Serializer for the ProviderVerification model, handling serialization and deserialization of provider verification data.
class ProviderVerificationSerializer(serializers.ModelSerializer):
    provider_id = serializers.UUIDField(source="provider.id")
    provider_name = serializers.CharField(source="provider.fullname")
    provider_email = serializers.CharField(source="provider.user.email")
    status = serializers.CharField(read_only=True)
    selfie_image = serializers.ImageField(validators=[validate_image], required=False)

    class Meta:
        model = ProviderVerification
        fields = [
            "id",
            "provider_id",
            "provider_name",
            "provider_email",
            "id_document",
            "selfie_image",
            "status",
            "submitted_at",
        ]
        read_only_fields = [
            "id",
            "provider_id",
            "provider_name",
            "provider_email",
            "status",
            "submitted_at",
        ]

    # Overriding the serializer update method to prevent updates if the verification status is already approved.
    # If the status is not approved, it sets the status to pending and saves the instance.
    def update(self, instance, validated_data):
        if instance.status == ProviderVerificationStatus.VERIFIED:
            raise serializers.ValidationError("Verification has already been approved.")
        instance.status = ProviderVerificationStatus.PENDING
        instance.save(update_fields=["status"])
        return super().update(instance, validated_data)
