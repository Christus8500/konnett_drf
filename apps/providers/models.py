from django.db import models
from django.utils import timezone
from django.conf import settings

from apps.core.models import UUIDModel, TimeStampedModel
from apps.core.choices import ProviderVerificationStatus


# Create your models here.

#Image upload function:: so that each provider will have their own kyc folder
def kyc_image_upload(instance, filename):
    return f"providers/kyc/{instance.provider.id}/{filename}"

#Image upload function:: so that each provider will have their own profile image folder
def profile_image_upload(instance, filename):
    return f"providers/profile_images/{instance.id}/{filename}"


# ProviderProfile: A model representing the profile of a provider, linked to a user instance.
class ProviderProfile(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="provider_profile")

    business_name = models.CharField(max_length=255, blank=True, null=True)
    bio = models.TextField(blank=True)
    years_of_experience = models.PositiveIntegerField(default=0)
    is_available = models.BooleanField(default=True)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    completed_jobs = models.PositiveIntegerField(default=0)
    profile_image = models.ImageField(upload_to=profile_image_upload, blank=True, null=True)

    #property method to get the full name of the customer by combining first and last names from the linked user instance.
    @property
    def fullname(self):
        return f'{self.user.first_name} {self.user.last_name}'.strip()

    def __str__(self):
        return self.fullname
    

# ProviderVerification: A model representing the verification status of a provider, linked to a ProviderProfile instance.
class ProviderVerification(UUIDModel):
    provider = models.OneToOneField(ProviderProfile, on_delete=models.CASCADE)
    id_document = models.FileField(upload_to=kyc_image_upload, blank=True, null=True)
    selfie_image = models.ImageField(upload_to=kyc_image_upload, blank=True, null=True)
    status = models.CharField(
        max_length=20, 
        choices=ProviderVerificationStatus.choices, 
        default=ProviderVerificationStatus.PENDING
    )
    submitted_at = models.DateTimeField(blank=True, null=True)

    # Override the save method to set the submitted_at field when either document is uploaded for the first time.
    def save(self, *args, **kwargs):
        # Set submitted_at the first time either document is uploaded
        if not self.submitted_at and (self.id_document or self.selfie_image):
            self.submitted_at = timezone.now()

        super().save(*args, **kwargs)