from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.html import escape
from django.utils.http import urlsafe_base64_encode

from apps.core.utils import send_email

from apps.accounts.tokens import (
    password_reset_token_generator,
    make_email_change_token,
)


def send_account_verification_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    verification_url = (
        f"{settings.BACKEND_URL}/api/accounts/verify-email/?uid={uid}&token={token}"
    )

    raw_first_name = user.first_name or "there"
    safe_first_name = escape(raw_first_name)
    safe_url = escape(verification_url)

    text_content = (
        f"Hello {raw_first_name},\n\n"
        "Please verify your email address by visiting:\n\n"
        f"{verification_url}\n\n"
        "If you did not create this account, you can ignore this email."
    )

    html_content = f"""
        <h2>Welcome to Konnett!</h2>

        <p>Hello {safe_first_name},</p>

        <p>Thank you for creating a Konnett account.</p>

        <p>Please verify your email address:</p>

        <p>
            <a
                href="{safe_url}"
                style="
                    display: inline-block;
                    padding: 12px 20px;
                    background-color: #000000;
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 5px;
                "
            >
                Verify My Email
            </a>
        </p>

        <p>If you did not create this account, you can ignore this email.</p>
    """

    # Let exceptions propagate so the outbox worker can retry.
    send_email(
        subject="Verify your Konnett email",
        to=user.email,
        text_content=text_content,
        html_content=html_content,
    )


def send_password_reset_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = password_reset_token_generator.make_token(user)

    reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

    raw_first_name = user.first_name or "there"
    safe_first_name = escape(raw_first_name)
    safe_url = escape(reset_url)

    text_content = (
        f"Hello {raw_first_name},\n\n"
        "We received a request to reset your Konnett password. "
        "Use the link below to choose a new one:\n\n"
        f"{reset_url}\n\n"
        "This link expires in 24 hours.\n\n"
        "If you did not request this, you can ignore this email. "
        "Your password will not change."
    )

    html_content = f"""
        <h2>Reset your Konnett password</h2>

        <p>Hello {safe_first_name},</p>

        <p>We received a request to reset your password.</p>

        <p>
            <a
                href="{safe_url}"
                style="
                    display: inline-block;
                    padding: 12px 20px;
                    background-color: #000000;
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 5px;
                "
            >
                Reset My Password
            </a>
        </p>

        <p>This link expires in 24 hours.</p>

        <p>If you did not request this, you can ignore this email.
        Your password will not change.</p>
    """

    send_email(
        subject="Reset your Konnett password",
        to=user.email,
        text_content=text_content,
        html_content=html_content,
    )


def send_email_change_confirmation(user, new_email):
    token = make_email_change_token(user, new_email)
    url = f"{settings.FRONTEND_URL}/confirm-email-change?token={token}"
    send_email(
        subject="Confirm your new Konnett email",
        to=new_email,
        text_content=(
            f"Hello {user.first_name or 'there'},\n\n"
            f"Confirm this address as your new Konnett email:\n\n{url}\n\n"
            "This link expires in 24 hours. If you did not request this, ignore this email."
        ),
        html_content=(
            f"<p>Hello {escape(user.first_name or 'there')},</p>"
            f'<p><a href="{escape(url)}">Confirm my new email</a></p>'
            "<p>This link expires in 24 hours. If you did not request this, ignore this email.</p>"
        ),
    )


def send_email_change_notice(user, new_email):
    # Goes to the OLD address so the real owner can react.
    send_email(
        subject="Email change requested on your Konnett account",
        to=user.email,
        text_content=(
            f"A request was made to change your account email to {new_email}.\n"
            "If this was not you, change your password immediately."
        ),
        html_content=(
            f"<p>A request was made to change your account email to "
            f"<strong>{escape(new_email)}</strong>.</p>"
            "<p>If this was not you, change your password immediately.</p>"
        ),
    )
