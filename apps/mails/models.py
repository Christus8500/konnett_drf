from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.choices import EmailOutboxStatus
from apps.core.models import TimeStampedModel, UUIDModel

# Create your models here.


class MailboxMessage(UUIDModel, TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mailbox_messages",
    )
    subject = models.CharField(max_length=255)
    body = models.TextField()

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_read=True) | models.Q(read_at__isnull=True),
                name="mailbox_unread_has_no_read_at",
            ),
        ]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at", "updated_at"])


    def __str__(self):
        return f"{self.subject} - {self.user}"


class EmailOutbox(UUIDModel, TimeStampedModel):
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )
    recipient = models.EmailField()
    email_type = models.CharField(max_length=100, db_index=True)
    payload =  models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=EmailOutboxStatus.choices,
        default=EmailOutboxStatus.PENDING,
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    processing_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    # `processing` helps prevent two workers from intentionally claiming the same record. 
    # `next_attempt_at` controls when a failed email can be retried. 
    # `processing_at` allows the periodic task to recover a record if a worker crashes.

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["status", "processing_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=EmailOutboxStatus.SENT)
                    | models.Q(sent_at__isnull=False)
                ),
                name="outbox_sent_has_sent_at",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=EmailOutboxStatus.PROCESSING)
                    | models.Q(processing_at__isnull=False)
                ),
                name="outbox_processing_has_processing_at",
            ),
        ]

    def __str__(self):
        return f"{self.email_type} to {self.recipient} ({self.status})"
