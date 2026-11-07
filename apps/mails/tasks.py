from datetime import timedelta

from celery import shared_task

from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.core.choices import EmailOutboxStatus

from apps.mails.models import EmailOutbox

from apps.accounts.utils import send_account_verification_email

User = get_user_model()


def send_outbox_email(email):
    # Imported here to avoid a circular import with apps.konnett_points
    from apps.konnett_points.models import PointPurchase, WithdrawalRequest
    from apps.konnett_points.notifications import (
        send_point_purchase_successful_email,
        send_point_purchase_failed_email,
        send_withdrawal_email,
    )

    from apps.providers.models import ProviderVerification
    from apps.providers.notifications import send_provider_verification_email

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

    elif email.email_type == "withdrawal_status":
        withdrawal = WithdrawalRequest.objects.select_related("provider__user").get(
            pk=email.payload["withdrawal_pk"]
        )
        send_withdrawal_email(
            user=withdrawal.provider.user,
            withdrawal=withdrawal,
            status=email.payload["status"],
            reject_reason=email.payload.get("reject_reason") or None,
        )

    elif email.email_type == "provider_verification":
        verification_pk = email.payload["verification_pk"]
        verification = ProviderVerification.objects.select_related("provider__user").get(
            pk=verification_pk
        )
        send_provider_verification_email(
            user=verification.provider.user,
            status=email.payload["status"],
            admin_comment=email.payload.get("admin_comment") or None
        )

    else:
        raise ValueError(f"Unsupported email type: {email.email_type}")


@shared_task
def process_email_outbox(email_outbox_id):
    # Claim the record in a short transaction.
    with transaction.atomic():
        email = (
            EmailOutbox.objects.select_for_update()
            .filter(
                pk=email_outbox_id,
                status=EmailOutboxStatus.PENDING,
                next_attempt_at__lte=timezone.now(),
            )
            .first()
        )

        if email is None:
            return

        email.status = EmailOutboxStatus.PROCESSING
        email.processing_at = timezone.now()
        email.save(update_fields=["status", "processing_at"])

    # Do not hold a database transaction or row lock while contacting
    # the external email server.
    try:
        send_outbox_email(email)

    except Exception as exc:
        with transaction.atomic():
            failed = (
                EmailOutbox.objects.select_for_update()
                .filter(pk=email_outbox_id, status=EmailOutboxStatus.PROCESSING)
                .first()
            )

            if failed is None:
                return
            failed.attempts += 1
            failed.last_error = str(exc)
            failed.processing_at = None
            if failed.attempts >= 8:
                failed.status = EmailOutboxStatus.FAILED
            else:
                failed.status = EmailOutboxStatus.PENDING
                delay = min(2 ** (failed.attempts - 1), 360)
                failed.next_attempt_at = timezone.now() + timedelta(minutes=delay)
            failed.save(
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
        pk=email_outbox_id, status=EmailOutboxStatus.PROCESSING
    ).update(
        status=EmailOutboxStatus.SENT,
        sent_at=timezone.now(),
        processing_at=None,
        last_error="",
    )


@shared_task
def process_pending_emails():
    now = timezone.now()
    stuck_cutoff = now - timedelta(minutes=15)

    # Recover records left in processing if a worker crashed.
    # One query instead of one per row.
    EmailOutbox.objects.filter(
        status=EmailOutboxStatus.PROCESSING,
        processing_at__lt=stuck_cutoff,
    ).update(
        status=EmailOutboxStatus.PENDING,
        processing_at=None,
        next_attempt_at=now,
    )

    # Queue a limited batch of due pending records, oldest first.
    pending_ids = list(
        EmailOutbox.objects.filter(
            status=EmailOutboxStatus.PENDING,
            next_attempt_at__lte=now,
        )
        .order_by("next_attempt_at")
        .values_list("id", flat=True)[:100]
    )

    for email_id in pending_ids:
        process_email_outbox.delay(email_id)
