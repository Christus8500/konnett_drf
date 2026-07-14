from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin

from apps.accounts.managers import UserManager
from apps.core.models import TimeStampedModel, UUIDModel
from apps.core.choices import UserRole


# Create your models here.

# User: A custom user model extending AbstractBaseUser and PermissionsMixin, representing a user in the system.
class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel, UUIDModel):
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    #Custom user manager for handling user creation and superuser creation
    objects = UserManager()
    
    # The field used for authentication is the email field, and the required fields for creating a user are first_name and last_name.
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return self.email