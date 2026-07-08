from rest_framework import serializers

from apps.customers.models import CustomerProfile
from apps.core.validators import validate_image

class CustomerProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", required=False)
    first_name = serializers.CharField(source="user.first_name", required=False)
    last_name = serializers.CharField(source="user.last_name", required=False)

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
            "phone_number",
            "address",
            "city",
            "state",
            "profile_image",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user_id", "created_at", "updated_at"]

    #Overriding the serializer update method
    #So the serializer will know how to update values on the "User" table
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

