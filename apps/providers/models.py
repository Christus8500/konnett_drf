from decimal import Decimal

from django.conf import settings
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.utils import timezone

from apps.core.choices import ProviderVerificationStatus
from apps.core.models import TimeStampedModel, UUIDModel
from apps.core.utils import unique_filename

# Create your models here.


def provider_profile_image_upload(instance, filename):
    return f"providers/profile_images/{instance.id}/{unique_filename(filename)}"


def kyc_id_document_upload(instance, filename):
    return f"providers/kyc/{instance.provider_id}/id/{unique_filename(filename)}"


def kyc_selfie_upload(instance, filename):
    return f"providers/kyc/{instance.provider_id}/selfie/{unique_filename(filename)}"


# ProviderProfile: A model representing the profile of a provider, linked to a user instance.
class ProviderProfile(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_profile",
    )

    business_name = models.CharField(max_length=255, blank=True, default="")
    is_available = models.BooleanField(default=True)

    bio = models.TextField(blank=True, default="")
    profile_image = models.ImageField(
        upload_to=provider_profile_image_upload,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
    )
    is_verified = models.BooleanField(default=False)

    years_of_experience = models.PositiveSmallIntegerField(default=0)
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("5"))],
    )
    ratings_count = models.PositiveIntegerField(default=0)
    completed_jobs = models.PositiveIntegerField(default=0)

    address = models.ForeignKey(
        "core.Address",
        on_delete=models.SET_NULL,
        related_name="provider_profiles",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "provider profile"
        verbose_name_plural = "provider profiles"
        indexes = [
            models.Index(fields=["is_verified", "is_available"]),
            models.Index(fields=["-average_rating"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(average_rating__gte=0, average_rating__lte=5),
                name="provider_average_rating_between_0_and_5",
            ),
        ]

    @property
    def full_name(self):
        return self.user.full_name

    def __str__(self):
        return self.business_name or self.full_name or self.user.email


# ProviderVerification: A model representing the verification status of a provider, linked to a ProviderProfile instance.
class ProviderVerification(UUIDModel, TimeStampedModel):
    provider = models.OneToOneField(
        ProviderProfile, on_delete=models.CASCADE, related_name="provider_verification"
    )
    id_document = models.FileField(
        upload_to=kyc_id_document_upload,
        blank=True,
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png"])],
    )
    selfie_image = models.ImageField(
        upload_to=kyc_selfie_upload,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png"])],
    )
    status = models.CharField(
        max_length=20,
        choices=ProviderVerificationStatus.choices,
        default=ProviderVerificationStatus.NOT_SUBMITTED,
        db_index=True,
    )
    admin_comment = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "provider verification"
        verbose_name_plural = "provider verifications"

    def __str__(self):
        return f"{self.provider} - {self.get_status_display()}"

    # Override the save method to set the submitted_at field when either document is uploaded for the first time.
    def save(self, *args, **kwargs):
        has_documents = bool(self.id_document or self.selfie_image)

        # First upload: record the time and move from NOT_SUBMITTED to PENDING
        if has_documents:
            if not self.submitted_at:
                self.submitted_at = timezone.now()
            if self.status == ProviderVerificationStatus.NOT_SUBMITTED:
                self.status = ProviderVerificationStatus.PENDING

        super().save(*args, **kwargs)
