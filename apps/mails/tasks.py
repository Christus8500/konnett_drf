from datetime import timedelta

from celery import shared_task

from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.mails.models import EmailOutbox

from apps.konnett_points.models import PointPurchase
from apps.konnett_points.notifications import (
    send_point_purchase_successful_email,
    send_point_purchase_failed_email,
)

from apps.accounts.utils import send_account_verification_email

User = get_user_model


def send_outbox_email(email):
    if email.email_type == "point_purchase_successful":
        purchase_pk = email.payload["purchase_pk"]
        purchase = PointPurchase.objects.select_related("customer__user").get(
            pk=purchase_pk
        )
        send_point_purchase_successful_email(
            user=purchase.customer.user,
            purchase=purchase,
        )

    elif email.email_type == "point_purchase_failed":
        purchase_pk = email.payload["purchase_pk"]
        purchase = PointPurchase.objects.select_related("customer__user").get(
            pk=purchase_pk
        )
        send_point_purchase_failed_email(
            user=purchase.customer.user,
            purchase=purchase,
        )

    elif email.email_type == "account_verification":
        user = User.objects.get(pk=email.payload["user_id"])
        send_account_verification_email(
            user=user,
        )

    else:
        raise ValueError(f"Unsupported email type: {email.email_type}")


@shared_task
def process_email_outbox(email_outbox_id):
    # Claim the record in a short transaction.
    with transaction.atomic():
        email = (
            EmailOutbox.objects.select_for_update()
            .select_related("purchase__customer__user")
            .filter(
                pk=email_outbox_id,
                status="pending",
                next_attempt_at__lte=timezone.now(),
            )
            .first()
        )

        if email is None:
            return

        email.status = "processing"
        email.processing_at = timezone.now()
        email.save(update_fields=["status", "processing_at"])

    # Do not hold a database transaction or row lock while contacting
    # the external email server.
    try:
        send_outbox_email(email)

    except Exception as exc:
        with transaction.atomic():
            failed_email = EmailOutbox.objects.select_for_update().get(
                pk=email_outbox_id
            )

            failed_email.attempts += 1
            failed_email.status = "pending"
            failed_email.last_error = str(exc)
            failed_email.processing_at = None

            # Exponential delay: 1, 2, 4, 8... minutes, capped at 6 hours.
            delay_minutes = min(2 ** (failed_email.attempts - 1), 360)

            failed_email.next_attempt_at = timezone.now() + timedelta(
                minutes=delay_minutes
            )

            failed_email.save(
                update_fields=[
                    "attempts",
                    "status",
                    "last_error",
                    "processing_at",
                    "next_attempt_at",
                ]
            )

        return

    # Mark as sent only after the sender returns successfully.
    EmailOutbox.objects.filter(
        pk=email_outbox_id,
        status="processing",
    ).update(
        status="sent",
        sent_at=timezone.now(),
        processing_at=None,
        last_error="",
    )


@shared_task
def process_pending_emails():
    now = timezone.now()

    # Queue a limited batch of due pending records.
    pending_ids = list(
        EmailOutbox.objects.filter(
            status="pending",
            next_attempt_at__lte=now,
        ).values_list("id", flat=True)[:100]
    )

    for email_id in pending_ids:
        process_email_outbox.delay(email_id)

    # Recover records left in processing if a worker crashed.
    stuck_ids = list(
        EmailOutbox.objects.filter(
            status="processing",
            processing_at__lt=now - timedelta(minutes=15),
        ).values_list("id", flat=True)[:100]
    )

    for email_id in stuck_ids:
        EmailOutbox.objects.filter(
            pk=email_id,
            status="processing",
            processing_at__lt=now - timedelta(minutes=15),
        ).update(
            status="pending",
            processing_at=None,
            next_attempt_at=now,
        )
