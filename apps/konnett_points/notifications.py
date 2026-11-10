from django.db import transaction
from html import escape

from apps.mails.services import create_mailbox_message

from apps.core.utils import send_email
from apps.core.choices import WithdrawalStatus
from apps.core.constants import ADMIN_FEE_RATE_PERCENT

from apps.mails.tasks import process_email_outbox
from apps.mails.services import queue_email


def create_point_purchase_initiated_notification(user, purchase):
    return create_mailbox_message(
        user=user,
        subject="Point Purchase Initiated",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your purchase #{purchase.payment_reference} of {purchase.points} points has been initiated.\n\n"
            f"Please note that {ADMIN_FEE_RATE_PERCENT}% of the purchased points will be deducted as the administrative fee.\n\n"
            f"Administrative fee is {purchase.admin_fee_points}.\n\n"
            f"Your credited points is {purchase.credited_points}.\n\n"
            "Thanks."
        ),
    )


def create_point_purchase_failed_notification(user, purchase):
    return create_mailbox_message(
        user=user,
        subject="Point Purchase Failed",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your purchase #{purchase.payment_reference} of {purchase.points} points has failed.\n\n"
            "If the issue was not from your end, contact support. Don't try to retry the purchase.\n\n"
            "Thanks."
        ),
    )


def create_point_purchase_successful_notification(user, purchase):
    return create_mailbox_message(
        user=user,
        subject="Point Purchase Successful",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your purchase #{purchase.payment_reference} of {purchase.points} points has been successful.\n\n"
            f"Please note that {ADMIN_FEE_RATE_PERCENT}% of the purchased points will be deducted as the administrative fee.\n\n"
            f"Administrative fee is {purchase.admin_fee_points}.\n\n"
            f"Your credited points is {purchase.credited_points}.\n\n"
            "Thanks."
        ),
    )


def create_withdrawal_request_received_notification(user, points_to_withdraw):
    return create_mailbox_message(
        user=user,
        subject="Withdrawal Request Received",
        body=(
            f"Hi {user.first_name},\n\n"
            f"We have received your request to withdraw {points_to_withdraw} points.\n\n"
            f"Our team is reviewing the request, we will contact you on any updates.\n\n"
            "Withdrawal Bank Details:\n\n"
            f"Account Number: {user.account_number}\n"
            f"Account Name: {user.account_name}\n"
            f"Bank Name: {user.bank_name}\n"
        ),
    )


def send_point_purchase_email(user, purchase, *, successful: bool):
    status = "successful" if successful else "failed"

    first_name = user.first_name or "there"
    reference = str(purchase.payment_reference)
    points = str(purchase.points)

    text_content = (
        f"Hi {first_name},\n\n"
        f"Your purchase #{reference} of {points} points "
        f"{'was completed successfully.' if successful else 'has failed.'}\n\n"
    )

    html_content = (
        f"<p>Hi {escape(first_name)},</p>"
        f"<p>Your purchase #{escape(reference)} of "
        f"{escape(points)} points "
        f"{'was completed successfully.' if successful else 'has failed.'}</p>"
    )

    if successful:
        admin_fee = str(purchase.admin_fee_points)
        credited_points = str(purchase.credited_points)

        text_content += (
            f"Please note that {ADMIN_FEE_RATE_PERCENT}% of the purchased points "
            "will be deducted as the administrative fee.\n\n"
            f"Administrative fee: {admin_fee} points.\n\n"
            f"Points credited to your account: {credited_points}.\n\n"
        )

        html_content += (
            f"<p>Please note that {ADMIN_FEE_RATE_PERCENT}% of the purchased points "
            "will be deducted as the administrative fee.</p>"
            f"<p>Administrative fee: {escape(admin_fee)} points.</p>"
            f"<p>Points credited to your account: "
            f"{escape(credited_points)}.</p>"
        )
    else:
        text_content += (
            "If you believe this failure was an error, "
            "please contact support before attempting another purchase.\n\n"
        )

        html_content += (
            "<p>If you believe this failure was an error, "
            "please contact support before attempting another purchase.</p>"
        )

    text_content += "Thanks."
    html_content += "<p>Thanks.</p>"

    send_email(
        subject=f"Point Purchase {status.title()}",
        to=user.email,
        text_content=text_content,
        html_content=html_content,
    )


def send_point_purchase_failed_email(user, purchase):
    return send_point_purchase_email(user, purchase, successful=False)


def send_point_purchase_successful_email(user, purchase):
    return send_point_purchase_email(user, purchase, successful=True)


def send_withdrawal_email(user, withdrawal, status, reject_reason=None):
    first_name = user.first_name or "there"
    reference = str(withdrawal.withdrawal_reference)
    points = str(withdrawal.points)

    if status == WithdrawalStatus.APPROVED:
        subject = "Withdrawal Request Approved"
        lines = [
            f"Your withdrawal request #{reference} of {points} points "
            "was approved successfully.",
            "Your bank will be credited in time.",
            "Withdrawal Bank Details:",
            f"Account Number: {user.account_number}",
            f"Account Name: {user.account_name}",
            f"Bank Name: {user.bank_name}",
        ]
    elif status == WithdrawalStatus.REJECTED:
        subject = "Withdrawal Request Rejected"
        lines = [
            f"Your withdrawal request #{reference} of {points} points " "was rejected.",
            "The reason is:",
            str(reject_reason) if reject_reason else "No reason was provided.",
        ]
    elif status == WithdrawalStatus.PAID:
        subject = "Withdrawal Request Processed"
        lines = [
            f"Your withdrawal request #{reference} of {points} points "
            "was successful.",
            "Payment has been made to your bank.",
            "Withdrawal Bank Details:",
            f"Account Number: {user.account_number}",
            f"Account Name: {user.account_name}",
            f"Bank Name: {user.bank_name}",
        ]
    else:
        raise ValueError(f"Unsupported withdrawal status: {status}")

    text_content = f"Hi {first_name},\n\n" + "\n\n".join(lines)
    html_content = f"<p>Hi {escape(first_name)},</p>" + "".join(
        f"<p>{escape(line)}</p>" for line in lines
    )

    return send_email(
        subject=subject,
        to=user.email,
        text_content=text_content,
        html_content=html_content,
    )


def queue_withdrawal_email(withdrawal, status, reject_reason=None):
    status = str(status)

    email, _ = queue_email(
        idempotency_key=f"withdrawal-{status}:{withdrawal.pk}",
        recipient=withdrawal.user.email,
        email_type="withdrawal_status",
        payload={
            "withdrawal_pk": str(withdrawal.pk),  # UUID is not JSON serializable
            "status": status,
            "reject_reason": reject_reason or "",
        },
    )

    transaction.on_commit(lambda: process_email_outbox.delay(email.pk))
