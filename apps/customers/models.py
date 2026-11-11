import os
import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from apps.core.models import UUIDModel, TimeStampedModel

# Create your models here.


# Image upload function:: so that each customer will have their own profile image folder
def profile_image_upload(instance, filename):
    """Store each customer's images in their own folder, with a unique filename."""
    extension = os.path.splitext(filename)[1].lower()
    return f"customers/profile_images/{instance.user_id}/{uuid.uuid4().hex}{extension}"


# CustomerProfile: A model representing the profile of a customer, linked to a user instance.
class CustomerProfile(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    address = models.TextField(blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    profile_image = models.ImageField(
        upload_to=profile_image_upload,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
    )

    class Meta:
        verbose_name = "customer profile"
        verbose_name_plural = "customer profiles"

        
    @property
    def full_name(self):
        return self.user.full_name

    def __str__(self):
        return self.full_name or self.user.email
