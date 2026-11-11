from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from apps.accounts.managers import UserManager
from apps.core.choices import UserRole
from apps.core.models import TimeStampedModel, UUIDModel

phone_validator = RegexValidator(
    regex=r"^\+?[0-9]{7,15}$",
    message="Enter a valid phone number (7-15 digits, optional leading +).",
)

account_number_validator = RegexValidator(
    regex=r"^\d{10}$",
    message="Account number must be exactly 10 digits.",
)

# Create your models here.


# User: A custom user model extending AbstractBaseUser and PermissionsMixin, representing a user in the system.
class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel, UUIDModel):
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)

    phone_number = models.CharField(
        max_length=20, blank=True, default="", validators=[phone_validator]
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
        db_index=True,
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    account_number = models.CharField(
        max_length=10, blank=True, default="", validators=[account_number_validator]
    )
    account_name = models.CharField(max_length=255, blank=True, default="")
    bank_name = models.CharField(max_length=255, blank=True, default="")

    # Custom user manager for handling user creation and superuser creation
    objects = UserManager()

    # The field used for authentication is the email field, and the required fields for creating a user are first_name and last_name.
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="unique_lower_email"),
        ]

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name
