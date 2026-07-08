from django.db import models


# Choices for various fields in the application
class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    CUSTOMER = "customer", "Customer"
    PROVIDER = "provider", "Provider"


# Choices for job status
class JobStatus(models.TextChoices):
    OPEN = "open", "Open"
    OFFER_ACCEPTED = "offer_accepted", "Offer Accepted"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


# Choices for offer status
class OfferStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


# Choices for provider verification status
class ProviderVerificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"


# Choices for payment status
class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"