import random
import secrets
import string

from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Avg


def generate_reference(prefix="KNT"):
    """
    Generates a unique Konnett reference.

    Example:
        KNT-20260804-9F8A3C7D
    """
    date = timezone.now().strftime("%Y%m%d")
    random_part = secrets.token_hex(4).upper()

    return f"{prefix}-{date}-{random_part}"


# def generate_random_code(length=6):
#     """
#     Generate a random alphanumeric code of a specified length.

#     Args:
#         length (int): The length of the random code to generate. Default is 6.

#     Returns:
#         str: A randomly generated alphanumeric code.
#     """
#     return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


# def calculate_average_rating(queryset):
#     """
#     Calculate the average of a specified field in a Django queryset.

#     Args:
#         queryset (QuerySet): The Django queryset to calculate the average from.

#     Returns:
#         float: The average value of the specified field, or None if the queryset is empty.
#     """
#     return queryset.aggregate(average=Avg("rating"))["average"] or 0


# -- Caching
def get_cache(key):
    return cache.get(key)


def set_cache(key, value, timeout=300):
    cache.set(key, value, timeout)


def delete_cache(key):
    cache.delete(key)


# -- Email Sending
# email sending function that uses Django's EmailMultiAlternatives to send emails with optional HTML content, attachments, and various email headers.
def _normalize_emails(value):
    if not value:
        return []

    if isinstance(value, str):
        return [value]

    return list(value)


def send_email(
    *,
    subject,
    to,
    text_content,
    html_content=None,
    from_email=None,
    from_name=None,
    reply_to=None,
    cc=None,
    bcc=None,
    attachments=None,
):
    to = _normalize_emails(to)

    if not to:
        raise ValueError("At least one recipient email address is required.")

    sender_email = from_email or settings.DEFAULT_FROM_EMAIL
    sender_name = from_name or getattr(settings, "DEFAULT_FROM_NAME", "")

    formatted_sender = formataddr((sender_name, sender_email))

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=formatted_sender,
        to=to,
        cc=_normalize_emails(cc),
        bcc=_normalize_emails(bcc),
        reply_to=_normalize_emails(reply_to),
    )

    if html_content:
        email.attach_alternative(html_content, "text/html")

    for attachment in attachments or []:
        email.attach(*attachment)

    return email.send(fail_silently=False)
