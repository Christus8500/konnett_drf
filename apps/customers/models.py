import uuid
from django.db import models
from django.conf import settings

# Create your models here.

class CustomerProfile(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile"
    )

    address = models.TextField(
        blank=True,
        null=True
    )

    city = models.CharField(
        max_length=100,
        blank=True
    )

    state = models.CharField(
        max_length=100,
        blank=True
    )

    profile_image = models.ImageField(
        upload_to="customers/profile_images/",
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.first_name} - {self.user.email}'