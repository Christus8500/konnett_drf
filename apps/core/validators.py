from django.core.exceptions import ValidationError

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB

def validate_image(self, image):
    allowed = ["image/jpeg", "image/png"]

    if image.content_type not in allowed:
        raise ValidationError('Only JPEG and PNG images are allowed')
    
    if image.size > MAX_IMAGE_SIZE:
        raise ValidationError('Image file is too large.')
    

def validate_budget(value):
    if value < 0:
        raise ValidationError('Budget cannot be negative.')
    
    if value > 10_000_000:
        raise ValidationError('Budget cannot exceed 10,000,000.')