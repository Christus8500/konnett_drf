from django.db import models
from django.conf import settings

from apps.core.models import UUIDModel, TimeStampedModel

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

    def __str__(self):
        return f"{self.subject} - {self.user}"
