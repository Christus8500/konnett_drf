from django.db import models
from django.utils import timezone
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator

from apps.core.choices import JobRequestStatus, JobOfferStatus, JobDisputeDecision
from apps.core.models import UUIDModel, TimeStampedModel


# custom upload paths for job request and completion images
def job_request_image_upload(instance, filename):
    return f"jobs/{instance.job.id}/job_requests/{filename}"


def job_completion_image_upload(instance, filename):
    return f"jobs/{instance.job.id}/job_completion/{filename}"


# Create your models here.
class JobRequest(UUIDModel, TimeStampedModel):
    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="job_requests",
    )
    category = models.ForeignKey(
        "services.Category", on_delete=models.CASCADE, related_name="job_requests"
    )
    title = models.CharField(max_length=255)
    description = models.TextField()

    points_amount = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    deadline = models.DateTimeField(blank=True, null=True)

    primary_location = models.ForeignKey(
        "core.Address",
        on_delete=models.PROTECT,
        related_name="primary_jobs",
    )
    secondary_location = models.ForeignKey(
        "core.Address",
        on_delete=models.PROTECT,
        related_name="secondary_jobs",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=JobRequestStatus.choices,
        default=JobRequestStatus.PENDING,
        db_index=True,
    )
    completed_at = models.DateTimeField(blank=True, null=True)

    admin_fee_points = models.PositiveIntegerField(null=True, blank=True)
    provider_earning_points = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    # The save method is overridden to automatically set the completed_at field to the current time when the job status is changed to COMPLETED and completed_at is not already set.
    def save(self, *args, **kwargs):
        if self.status == JobRequestStatus.COMPLETED and self.completed_at is None:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title}, by {self.customer}"


class JobRequestImage(UUIDModel):
    job = models.ForeignKey(
        JobRequest, on_delete=models.CASCADE, related_name="job_request_images"
    )
    image = models.ImageField(upload_to=job_request_image_upload)

    def __str__(self):
        return f"Image for {self.job}"


class JobCompletionImage(UUIDModel):
    job = models.ForeignKey(
        JobRequest, on_delete=models.CASCADE, related_name="job_completion_images"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="job_completion_images",
    )
    image = models.ImageField(upload_to=job_completion_image_upload)

    def __str__(self):
        return f"Completion image for {self.job}, by {self.provider}"


# TODO: 
# Let the provider know of or see the admin fee,
# 10% of the job points
class JobRequestOffer(UUIDModel, TimeStampedModel):
    job = models.ForeignKey(
        JobRequest, on_delete=models.CASCADE, related_name="job_offers"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="job_offers"
    )
    status = models.CharField(
        max_length=30, choices=JobOfferStatus.choices, default=JobOfferStatus.PENDING
    )

    # The Meta class defines a unique constraint to ensure that a provider can only make one offer per job.
    # It also specifies the default ordering of JobRequestOffer instances by their creation date in descending order.
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "provider"],
                name="unique_job_provider_offer",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} → {self.job}"


class JobDispute(UUIDModel):
    job = models.OneToOneField(
        JobRequest,
        on_delete=models.CASCADE,
        related_name="dispute",
    )
    customer_reason = models.TextField()
    admin_note = models.TextField(blank=True, null=True)
    decision = models.CharField(
        max_length=20, choices=JobDisputeDecision.choices, blank=True, null=True
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="resolved_job_disputes",
    )
    resolved_at = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.decision and self.resolved_at is None:
            self.resolved_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Dispute - {self.job.title}"


class ProviderRating(UUIDModel, TimeStampedModel):
    job = models.OneToOneField(
        JobRequest,
        on_delete=models.CASCADE,
        related_name="provider_rating",
    )

    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="ratings",
    )

    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="provider_ratings",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ]
    )

    def __str__(self):
        return f"{self.provider} - {self.rating}/5"
    