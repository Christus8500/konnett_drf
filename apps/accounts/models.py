from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin

from apps.accounts.managers import UserManager
from apps.core.models import TimeStampedModel, UUIDModel
from apps.core.choices import UserRole


# Create your models here.

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
    
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return self.email