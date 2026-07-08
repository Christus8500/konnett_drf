import re
from rest_framework import serializers


#Validating password strength based on length, uppercase, lowercase, number, and special character requirements.
def validate_password(password):
    if len(password) < 8:
        raise serializers.ValidationError(
            "Password must be at least 8 characters long."
        )

    if not re.search(r"[A-Z]", password):
        raise serializers.ValidationError(
            "Password must contain at least one uppercase letter."
        )

    if not re.search(r"[a-z]", password):
        raise serializers.ValidationError(
            "Password must contain at least one lowercase letter."
        )

    if not re.search(r"\d", password):
        raise serializers.ValidationError(
            "Password must contain at least one number."
        )

    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]", password):
        raise serializers.ValidationError(
            "Password must contain at least one special character."
        )

    return password