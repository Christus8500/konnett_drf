from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.html import escape
from django.conf import settings

from apps.core.utils import send_email


def send_account_verification_email(user):
    uid = urlsafe_base64_encode(
        force_bytes(user.pk)
    )

    token = default_token_generator.make_token(user)

    verification_url = (
        f"{settings.BACKEND_URL}/api/accounts/"
        f"verify-email/?uid={uid}&token={token}"
    )

    first_name = escape(user.first_name)
    safe_url = escape(verification_url)

    send_email(
        subject="Verify your Konnett email",
        to=user.email,
        text_content=(
            f"Hello {first_name},\n\n"
            "Please verify your email address by visiting:\n\n"
            f"{safe_url}\n\n"
            "If you did not create this account, "
            "you can ignore this email."
        ),
        html_content=f"""
            <h2>Welcome to Konnett!</h2>

            <p>
                Hello {first_name},
            </p>

            <p>
                Thank you for creating a Konnett account.
            </p>

            <p>
                Please verify your email address:
            </p>

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

            <p>
                If you did not create this account,
                you can ignore this email.
            </p>
        """,
    )

