from django.db import models


# Choices for various fields in the application
class UserRole(models.TextChoices):
    ADMIN = "konnett001", "Administrator"
    CUSTOMER = "customer", "Customer"
    PROVIDER = "provider", "Provider"


# Choices for provider verification status
class ProviderVerificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"


# Choices for job status
class JobRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    AWAITING_CONFIRMATION = "awaiting_confirmation", "Awaiting Confirmation"
    COMPLETED = "completed", "Completed"
    DISPUTED = "disputed", "Disputed"
    CANCELLED = "cancelled", "Cancelled"


# Choices for offer status
class JobOfferStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"


# Choices for dispute decision
class JobDisputeDecision(models.TextChoices):
    RELEASE_POINTS = "release_points", "Release Points"
    REFUND_POINTS = "refund_points", "Refund Points"


# Choices for payment status
class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESSFUL = "successful", "Successful"
    FAILED = "failed", "Failed"


#  Choices for konnet points transaction type
class TransactionType(models.TextChoices):
    PURCHASE = "purchase", "Purchase"
    LOCK = "lock", "Lock"
    UNLOCK = "unlock", "Unlock"
    PROVIDER_PAY = "provider_pay", "Provider Pay"
    EARNED = "earned", "Earned"
    WITHDRAWAL = "withdrawal", "Withdrawal"
    REFUND = "refund", "Refund"
    ADJUSTMENT = "adjustment", "Adjustment"
    ADMIN_FEE = "admin_fee", "Admin Fee"


#  Choices for withdrawal status
class WithdrawalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    PAID = "paid", "Paid"
