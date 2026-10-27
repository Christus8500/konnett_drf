from html import escape

from apps.mails.services import create_mailbox_message

from apps.core.utils import send_email
from apps.core.choices import WithdrawalStatus


def create_point_purchase_initiated_notification(user, purchase):
    return create_mailbox_message(
        user=user,
        subject="Point Purchase Initiated",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your purchase #{purchase.payment_reference} of {purchase.points} points has been initiated.\n\n"
            f"Please note that 10% of the purchased points will be deducted as the administrative fee.\n\n"
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
            f"Please note that 10% of the purchased points will be deducted as the administrative fee.\n\n"
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
            f"Our team is reviewing the request, we will contact you on any updates."
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
            "Please note that 10% of the purchased points "
            "will be deducted as the administrative fee.\n\n"
            f"Administrative fee: {admin_fee} points.\n\n"
            f"Points credited to your account: {credited_points}.\n\n"
        )

        html_content += (
            "<p>Please note that 10% of the purchased points "
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

    return send_email(
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
        text_content = (
            f"Hi {first_name},\n\n"
            f"Your withdrawal request #{reference} of {points} points "
            "was approved succesfully.\n\n"
            "Your bank will be credited in time."
        )
        html_content = (
            f"<p>Hi {escape(first_name)},</p>"
            f"<p> Your withdrawal request #{escape(reference)} of {escape(points)} points "
            "was approved succesfully.</p>"
            "<p>Your bank will be credited in time.</p>"
        )

        return send_email(
            subject=f"Withdrawal Request Approved",
            to=user.email,
            text_content=text_content,
            html_content=html_content,
        )

    elif status == WithdrawalStatus.REJECTED:
        text_content = (
            f"Hi {first_name},\n\n"
            f"Your withdrawal request #{reference} of {points} points "
            "was rejected.\n\n"
            "The reason is this:\n "
            f"{str(reject_reason)}\n\n\n"
        )
        html_content = (
            f"<p>Hi {escape(first_name)},</p>"
            f"<p> Your withdrawal request #{escape(reference)} of {escape(points)} points "
            "was rejected.</p>"
            "<p>The reason is this:</p>"
            f"<p>{escape(str(reject_reason))}</p>"
        )

        return send_email(
            subject=f"Withdrawal Request Rejected",
            to=user.email,
            text_content=text_content,
            html_content=html_content,
        )

    if status == WithdrawalStatus.PAID:
        text_content = (
            f"Hi {first_name},\n\n"
            f"Your withdrawal request, #{reference} of {points} points "
            "was succesful.\n\n"
            "Payment has been made to your bank."
        )
        html_content = (
            f"<p>Hi {escape(first_name)},</p>"
            f"<p> Your withdrawal request, #{escape(reference)} of {escape(points)} points "
            "was succesful.</p>"
            "<p>Payment has been made to your bank.</p>"
        )

        return send_email(
            subject=f"Withdrawal Request Processed",
            to=user.email,
            text_content=text_content,
            html_content=html_content,
        )
