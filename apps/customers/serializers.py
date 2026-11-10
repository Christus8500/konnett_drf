from rest_framework import serializers

from apps.customers.models import CustomerProfile
from apps.core.validators import validate_image


# Serializer for the CustomerProfile model, handling serialization and deserialization of customer profile data.
class CustomerProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", required=False)
    email_verified = serializers.BooleanField(source="user.email_verified", required=False)
    phone_number = serializers.CharField(source="user.phone_number", required=False)
    first_name = serializers.CharField(source="user.first_name", required=False)
    last_name = serializers.CharField(source="user.last_name", required=False)
    
    account_number = serializers.CharField(source="user.account_number", required=False)
    account_name = serializers.CharField(source="user.account_name", required=False)
    bank_name = serializers.CharField(source="user.bank_name", required=False)

    profile_image = serializers.ImageField(
        validators=[validate_image],
        required=False,
    )

    class Meta:
        model = CustomerProfile
        fields = [
            "id",
            "user_id",
            "first_name",
            "last_name",
            "email",
            "email_verified",
            "phone_number",
            "account_number",
            "account_name",
            "bank_name",
            "address",
            "city",
            "state",
            "profile_image",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user_id", "email", "email_verified", "created_at", "updated_at"]

    # Overriding the serializer update method
    # So the serializer will know how to update the values on the "User" table
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})

        user = instance.user
        for attr, value in user_data.items():
            setattr(user, attr, value)
        user.save()

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance
