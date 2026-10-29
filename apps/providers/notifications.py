from html import escape

from apps.core.utils import send_email
from apps.core.choices import ProviderVerificationStatus


def send_verification_email(user, status, admin_comment=None):
    first_name = user.first_name or "there"
    approved_text_content = (
        f"Hi {first_name},\n\n"
        "Your verification was successful. Check your profile for the change.\n\n"
        "You can now enjoy the features of a KONNETT provider.\n\n"
    )
    rejected_text_content = (
        f"Hi {first_name},\n\n"
        "Your verification was rejected. Here's the admin comment about it:\n"
        f"{admin_comment}.\n\n"
        "Check the comment and see if its something you can remedy and try again.\n\n"
    )

    approved_html_content = (
        f"<p>Hi {escape(first_name)},</p>"
        "<p>Your verification was successful. Check your profile for the change.</p>"
        "<p>You can now enjoy the features of a KONNETT provider.</p>"
    )
    rejected_html_content = (
        f"<p>Hi {escape(first_name)},</p>"
        "<p>Your verification was rejected. Here's the admin comment about it:.</p>"
        f"<p>{escape(str(admin_comment))}</p>"
        "<p>Check the comment and see if its something you can remedy and try again.</p>"
    )

    text_content = (
        approved_text_content
        if status == ProviderVerificationStatus.VERIFIED
        else rejected_text_content
    )

    html_content = (
        approved_html_content
        if ProviderVerificationStatus.VERIFIED
        else rejected_html_content
    )

    return send_email(
        subject=f"Verification Approved",
        to=user.email,
        text_content=text_content,
        html_content=html_content,
    )
