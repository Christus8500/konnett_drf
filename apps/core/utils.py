import random
import secrets
import string

from django.utils import timezone

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


def generate_random_code(length=6):
    """
    Generate a random alphanumeric code of a specified length.

    Args:
        length (int): The length of the random code to generate. Default is 6.

    Returns:
        str: A randomly generated alphanumeric code.
    """
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def calculate_average_rating(queryset):
    """
    Calculate the average of a specified field in a Django queryset.

    Args:
        queryset (QuerySet): The Django queryset to calculate the average from.

    Returns:
        float: The average value of the specified field, or None if the queryset is empty.
    """
    return queryset.aggregate(average=Avg("rating"))["average"] or 0
