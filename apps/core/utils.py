import random
import string

from django.db.models import Avg

def generate_reference(prefix="KNT"):
    """
    Generate a random reference string with a given prefix.

    Args:
        prefix (str): The prefix to prepend to the reference string. Default is "REF".

    Returns:
        str: A randomly generated reference string.
    """
    random_string = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"{prefix}-{random_string}"


def generate_random_code(length=6):
    """
    Generate a random alphanumeric code of a specified length.

    Args:
        length (int): The length of the random code to generate. Default is 6.

    Returns:
        str: A randomly generated alphanumeric code.
    """
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def calculate_average_rating(queryset):
    """
    Calculate the average of a specified field in a Django queryset.

    Args:
        queryset (QuerySet): The Django queryset to calculate the average from.

    Returns:
        float: The average value of the specified field, or None if the queryset is empty.
    """
    return queryset.aggregate(average=Avg('rating'))['average'] or 0