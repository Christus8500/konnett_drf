from django.core.exceptions import ValidationError

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB


MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}


def validate_file_size(file):
    if file.size > MAX_UPLOAD_SIZE:
        limit_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
        raise ValidationError(f"File is too large. Maximum size is {limit_mb} MB.")


def validate_image(image):
    if getattr(image, "content_type", None) not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("Only JPEG and PNG images are allowed.")
    validate_file_size(image)


# Validator function to check if the budget value is within the allowed range (0 to 10,000,000).
def validate_budget(value):
    if value < 0:
        raise ValidationError("Budget cannot be negative.")

    if value > 10_000_000:
        raise ValidationError("Budget cannot exceed 10,000,000.")
