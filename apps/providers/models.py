import uuid
from django.db import models
from django.conf import settings

# Create your models here.

class ProviderProfile(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_profile"
    )

    business_name = models.CharField(
        max_length=255
    )

    bio = models.TextField(
        blank=True
    )

    years_of_experience = models.PositiveIntegerField(
        default=0
    )

    is_available = models.BooleanField(
        default=True
    )

    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0
    )

    completed_jobs = models.PositiveIntegerField(
        default=0
    )    

    profile_image = models.ImageField(
        upload_to="providers/profile_images/",
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.business_name


class ProviderVerification(models.Model):

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    provider = models.OneToOneField(
        ProviderProfile,
        on_delete=models.CASCADE
    )

    id_document = models.FileField(
        upload_to="kyc/"
    )

    selfie_image = models.ImageField(
        upload_to="kyc/"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    submitted_at = models.DateTimeField(auto_now_add=True)