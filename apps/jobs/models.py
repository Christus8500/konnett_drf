import uuid
from django.db import models

# Create your models here.
class ServiceRequest(models.Model):

    STATUS_CHOICES = (
        ("open", "Open"),
        ("assigned", "Assigned"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    customer = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE
    )

    category = models.ForeignKey(
        "services.ServiceCategory",
        on_delete=models.CASCADE
    )

    title = models.CharField(max_length=255)

    description = models.TextField()

    budget = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    address = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="open"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)


class ServiceRequestImage(models.Model):

    request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="images"
    )

    image = models.ImageField(
        upload_to="requests/"
    )


class ProviderApplication(models.Model):

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
    )

    request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE
    )

    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("request", "provider")


class JobAssignment(models.Model):

    request = models.OneToOneField(
        ServiceRequest,
        on_delete=models.CASCADE
    )

    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE
    )

    assigned_at = models.DateTimeField(auto_now_add=True)


class CompletionProof(models.Model):

    request = models.OneToOneField(
        ServiceRequest,
        on_delete=models.CASCADE
    )

    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE
    )

    notes = models.TextField(blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)


class CompletionProofImage(models.Model):

    proof = models.ForeignKey(
        CompletionProof,
        on_delete=models.CASCADE
    )

    image = models.ImageField(
        upload_to="completion_proofs/"
    )