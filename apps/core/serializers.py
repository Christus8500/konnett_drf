from rest_framework import serializers

from apps.core.models import Address


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "id",
            "address",
            "city",
            "state",
            "latitude",
            "longitude",
        ]
        read_only_fields = ["id"]