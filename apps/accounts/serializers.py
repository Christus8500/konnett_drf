from django.contrib.auth import authenticate
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from rest_framework import serializers

from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
    BlacklistedToken,
)

from apps.core.choices import UserRole

from apps.accounts.models import User
from apps.accounts.tokens import (
    password_reset_token_generator,
    read_email_change_token,
)
from apps.accounts.validators import validate_password


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
        style={"input_type": "password"},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "role",
            "password",
            "confirm_password",
        ]
        extra_kwargs = {
            "id": {"read_only": True},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already exists.")
        return value

    def validate_phone_number(self, value):
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("Phone number already exists.")
        return value

    def validate_role(self, value):
        if value not in [
            UserRole.PROVIDER,
            UserRole.CUSTOMER,
        ]:
            raise serializers.ValidationError(
                "You can only register as a provider or customer."
            )
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        return attrs

    # Extracting password and confirm_password from validated_data, creating a new user instance, setting the password, and saving the user to the database.
    # Finally, returning the created user instance.
    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    # Overriding validate() to authenticate the user using the provided email and password.
    # If authentication fails, a validation error is raised. If successful, the authenticated user is added to the validated data.
    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        user = authenticate(
            username=email,
            password=password,
        )

        if not user:
            raise serializers.ValidationError("Invalid email or password.")

        attrs["user"] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "phone_number",
            "first_name",
            "last_name",
            "role",
            "is_staff",
            "is_active",
        )
        read_only_fields = fields


class LoginResponseSerializer(serializers.Serializer):
    refresh = serializers.CharField()
    access = serializers.CharField()
    user = UserSerializer()


# ---------- Password reset ----------
class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
        style={"input_type": "password"},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (
            TypeError,
            ValueError,
            OverflowError,
            DjangoValidationError,  # raised for malformed UUIDs
            User.DoesNotExist,
        ):
            raise serializers.ValidationError("Invalid or expired reset link.")

        if not password_reset_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError("Invalid or expired reset link.")

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])

        # Optional: completing a reset proves the user controls the inbox.
        user.email_verified = True

        user.save(update_fields=["password", "email_verified"])

        # Resetting a password or changing an email does not invalidate refresh tokens that were already issued
        for t in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=t)

        return user


# ---------- Email change ----------
class EmailChangeRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        user = self.context["request"].user
        # Same normalization registration uses (lowercases the domain only).
        new_email = User.objects.normalize_email(attrs["new_email"].strip())

        if not user.check_password(attrs["password"]):
            raise serializers.ValidationError({"password": "Incorrect password."})
        if new_email.lower() == user.email.lower():
            raise serializers.ValidationError(
                {"new_email": "This is already your email."}
            )
        if User.objects.filter(email__iexact=new_email).exists():
            raise serializers.ValidationError({"new_email": "Email already exists."})

        attrs["new_email"] = new_email
        return attrs


class EmailChangeConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, attrs):
        invalid = serializers.ValidationError("Invalid or expired link.")
        try:
            data = read_email_change_token(attrs["token"])
            user = User.objects.get(pk=data["uid"], is_active=True)
        except (
            signing.BadSignature,
            KeyError,
            DjangoValidationError,
            User.DoesNotExist,
        ):
            raise invalid

        # Email already changed since the link was issued -> link is dead
        if user.email != data["old"]:
            raise invalid
        if User.objects.filter(email__iexact=data["new"]).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Email already exists.")

        attrs["user"] = user
        attrs["new_email"] = data["new"]
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.email = self.validated_data["new_email"]
        user.email_verified = True
        user.save(update_fields=["email", "email_verified"])

        # Resetting a password or changing an email does not invalidate refresh tokens that were already issued
        for t in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=t)

        return user
