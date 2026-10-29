from html import escape

from apps.core.utils import send_email
from apps.core.choices import ProviderVerificationStatus


def send_verification_email(user, status, admin_comment=None):
    first_name = user.first_name or "there"

    if status == ProviderVerificationStatus.VERIFIED:
        subject = "Verification Approved"

        text_content = (
            f"Hi {first_name},\n\n"
            "Your verification was successful. Check your profile for the change.\n\n"
            "You can now enjoy the features of a KONNETT provider.\n\n"
        )

        html_content = (
            f"<p>Hi {escape(first_name)},</p>"
            "<p>Your verification was successful. "
            "Check your profile for the change.</p>"
            "<p>You can now enjoy the features of a KONNETT provider.</p>"
        )

    elif status == ProviderVerificationStatus.REJECTED:
        subject = "Verification Rejected"
        comment = admin_comment or "No additional comment provided."

        text_content = (
            f"Hi {first_name},\n\n"
            "Your verification was rejected. Here's the admin comment:\n"
            f"{comment}\n\n"
            "Please review the comment, address the issue, and try again.\n"
        )

        html_content = (
            f"<p>Hi {escape(first_name)},</p>"
            "<p>Your verification was rejected. "
            "Here's the admin comment:</p>"
            f"<p>{escape(str(comment))}</p>"
            "<p>Please review the comment, address the issue, "
            "and try again.</p>"
        )

    else:
        raise ValueError("Unsupported verification email status.")

    return send_email(
        subject=subject,
        to=user.email,
        text_content=text_content,
        html_content=html_content,
    )
