from datetime import timedelta
import logging

from celery import shared_task

from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist

from apps.core.choices import EmailOutboxStatus

from apps.mails.models import EmailOutbox

from apps.accounts.utils import (
    send_account_verification_email,
    send_bank_details_changed_email,
    send_password_reset_email,
    send_email_change_confirmation,
    send_email_change_notice,
)

User = get_user_model()
logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BACKOFF_BASE_MINUTES = 1
BACKOFF_CAP_MINUTES = 30
PERMANENT_ERRORS = (ObjectDoesNotExist, KeyError, ValueError)

def _retry_delay(attempts):
    """attempts = number of failures so far (1-based)."""
    minutes = min(BACKOFF_BASE_MINUTES * 2 ** (attempts - 1), BACKOFF_CAP_MINUTES)
    return timedelta(minutes=minutes)


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

    elif email.email_type == "password_reset":
        user = User.objects.get(pk=email.payload["user_id"])
        send_password_reset_email(user=user)

    elif email.email_type == "email_change":
        user = User.objects.get(pk=email.payload["user_id"])
        send_email_change_confirmation(
            user=user, new_email=email.payload["new_email"])

    elif email.email_type == "email_change_notice":
        user = User.objects.get(pk=email.payload["user_id"])
        send_email_change_notice(
            user=user, new_email=email.payload["new_email"], to_email=email.recipient)

    elif email.email_type == "bank_details_changed":
        user = User.objects.get(pk=email.payload["user_id"])
        send_bank_details_changed_email(user=user)

    elif email.email_type == "withdrawal_status":
        withdrawal = WithdrawalRequest.objects.select_related("user").get(
            pk=email.payload["withdrawal_pk"]
        )
        send_withdrawal_email(
            user=withdrawal.user,
            withdrawal=withdrawal,
            status=email.payload["status"],
            reject_reason=email.payload.get("reject_reason") or None,
        )

    elif email.email_type == "provider_verification":
        verification_pk = email.payload["verification_pk"]
        verification = ProviderVerification.objects.select_related(
            "provider__user"
        ).get(pk=verification_pk)
        send_provider_verification_email(
            user=verification.provider.user,
            status=email.payload["status"],
            admin_comment=email.payload.get("admin_comment") or None,
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
        permanent = isinstance(exc, PERMANENT_ERRORS)
        with transaction.atomic():
            failed = (
                EmailOutbox.objects.select_for_update()
                .filter(pk=email_outbox_id, status=EmailOutboxStatus.PROCESSING)
                .first()
            )

            if failed is None:
                return
            failed.attempts += 1
            failed.last_error = str(exc)[:2000]
            failed.processing_at = None
            if permanent or failed.attempts >= MAX_ATTEMPTS:
                failed.status = EmailOutboxStatus.FAILED
                logger.error(
                    "Outbox email permanently failed outbox_id=%s type=%s attempts=%s error=%s",
                    failed.pk, failed.email_type, failed.attempts, exc,
                )
            else:
                failed.status = EmailOutboxStatus.PENDING
                failed.next_attempt_at = timezone.now() + _retry_delay(failed.attempts)
                logger.warning(
                    "Outbox email attempt failed outbox_id=%s type=%s attempts=%s error=%s",
                    failed.pk, failed.email_type, failed.attempts, exc,
                )
            failed.save(update_fields=[
                "attempts", "status", "last_error", "processing_at", "next_attempt_at",
            ])

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


@shared_task
def purge_old_outbox_emails(sent_days=30, failed_days=90, batch_size=1000):
    now = timezone.now()
    total = 0

    for status, days in (
        (EmailOutboxStatus.SENT, sent_days),
        (EmailOutboxStatus.FAILED, failed_days),
    ):
        cutoff = now - timedelta(days=days)
        while True:
            ids = list(
                EmailOutbox.objects.filter(status=status, created_at__lt=cutoff)
                .values_list("pk", flat=True)[:batch_size]
            )
            if not ids:
                break
            deleted, _ = EmailOutbox.objects.filter(pk__in=ids).delete()
            total += deleted

    logger.info("Purged %s old outbox emails", total)
    return f"{total} deleted"