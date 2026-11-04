from django.utils import timezone

from apps.mails.models import MailboxMessage, EmailOutbox


def create_mailbox_message(user, subject, body):
    return MailboxMessage.objects.create(
        user=user,
        subject=subject,
        body=body,
    )


def queue_email(
    *,
    idempotency_key,
    recipient,
    email_type,
    payload=None,
    purchase=None,
):
    return EmailOutbox.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "recipient": recipient,
            "purchase": purchase,
            "email_type": email_type,
            "payload": payload or {},
            "status": "pending",
            "next_attempt_at": timezone.now(),
        },
    )
