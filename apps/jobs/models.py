from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.choices import JobRequestStatus, JobOfferStatus, JobDisputeDecision
from apps.core.models import UUIDModel, TimeStampedModel
from apps.core.constants import MINIMUM_JOB_POINTS
from apps.providers.models import unique_filename


# custom upload paths for job request and completion images
def job_request_image_upload(instance, filename):
    return f"jobs/{instance.job_id}/job_requests/{unique_filename(filename)}"


def job_completion_image_upload(instance, filename):
    return f"jobs/{instance.job_id}/job_completion/{unique_filename(filename)}"
    return f"jobs/{instance.job.id}/job_completion/{filename}"


# Create your models here.
class JobRequest(UUIDModel, TimeStampedModel):
    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="job_requests",
    )
    category = models.ForeignKey(
        "services.Category", on_delete=models.PROTECT, related_name="job_requests"
    )
    title = models.CharField(max_length=255)
    description = models.TextField()

    points_amount = models.PositiveIntegerField(
        validators=[MinValueValidator(MINIMUM_JOB_POINTS)]
    )

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
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["category", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(points_amount__gte=MINIMUM_JOB_POINTS),
                name="job_points_amount_gte_minimum",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(admin_fee_points__isnull=True)
                    | models.Q(provider_earning_points__isnull=True)
                    | models.Q(
                        points_amount__gte=models.F("admin_fee_points")
                        + models.F("provider_earning_points")
                    )
                ),
                name="job_fee_plus_earning_lte_points",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.category_id
            and self.category.requires_secondary_location
            and not self.secondary_location_id
        ):
            raise ValidationError(
                {"secondary_location": "This category requires a secondary location."}
            )

    # The save method is overridden to automatically set the completed_at field to the current time when the job status is changed to COMPLETED and completed_at is not already set.
    def save(self, *args, **kwargs):
        if self.status == JobRequestStatus.COMPLETED and self.completed_at is None:
            self.completed_at = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "completed_at"}
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
        on_delete=models.PROTECT,
        related_name="job_completion_images",
    )
    image = models.ImageField(upload_to=job_completion_image_upload)

    def clean(self):
        super().clean()
        if self.job_id and self.provider_id:
            is_assigned = self.job.job_offers.filter(
                provider_id=self.provider_id, status=JobOfferStatus.ACCEPTED
            ).exists()
            if not is_assigned:
                raise ValidationError(
                    "Only the provider with the accepted offer can upload completion images."
                )

    def __str__(self):
        return f"Completion image for {self.job}, by {self.provider}"


# TODO:
# Let the provider know of or see the admin fee,
# 10% of the job points(update ADMIN_FEE_RATE_PERCENT in constants if percentage changes)
class JobRequestOffer(UUIDModel, TimeStampedModel):
    job = models.ForeignKey(
        JobRequest, on_delete=models.CASCADE, related_name="job_offers"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="job_offers"
    )
    status = models.CharField(
        max_length=30,
        choices=JobOfferStatus.choices,
        default=JobOfferStatus.PENDING,
        db_index=True,
    )

    # The Meta class defines a unique constraint to ensure that a provider can only make one offer per job.
    # It also specifies the default ordering of JobRequestOffer instances by their creation date in descending order.
    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "provider"],
                name="unique_job_provider_offer",
            ),
            models.UniqueConstraint(
                fields=["job"],
                condition=models.Q(status=JobOfferStatus.ACCEPTED),
                name="one_accepted_offer_per_job",
            ),
        ]

    def __str__(self):
        return f"{self.provider} → {self.job}"


class JobDispute(UUIDModel):
    job = models.OneToOneField(
        JobRequest,
        on_delete=models.CASCADE,
        related_name="dispute",
    )
    customer_reason = models.TextField()
    admin_note = models.TextField(blank=True, default="")
    decision = models.CharField(
        max_length=20,
        choices=JobDisputeDecision.choices,
        blank=True,
        default="",
        db_index=True,
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
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "resolved_at"}
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
    # TODO: Check the view for adding comments
    comment = models.TextField(blank=True, default="")

    is_visible = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="provider_rating_between_1_and_5",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.job_id:
            return
        if self.customer_id and self.customer_id != self.job.customer_id:
            raise ValidationError("Only the customer who posted the job can rate it.")
        if self.job.status != JobRequestStatus.COMPLETED:
            raise ValidationError("Only completed jobs can be rated.")
        if (
            self.provider_id
            and not self.job.job_offers.filter(
                provider_id=self.provider_id, status=JobOfferStatus.ACCEPTED
            ).exists()
        ):
            raise ValidationError("This provider did not do this job.")

    def __str__(self):
        return f"{self.provider} - {self.rating}/5"
