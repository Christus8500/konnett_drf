import os

from django.db import models
from django.conf import settings

from apps.core.models import UUIDModel, TimeStampedModel

# Create your models here.

#Image upload function:: so that each customer will have their own profile image folder
def profile_image_upload(instance, filename):
    extension = os.path.splitext(filename)[1]
    return f"customers/profile_images/{instance.user.id}/profile{extension}"


#CustomerProfile: A model representing the profile of a customer, linked to a user instance.
class CustomerProfile(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile"
    )
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100,blank=True)
    state = models.CharField(max_length=100, blank=True)
    profile_image = models.ImageField(upload_to=profile_image_upload, blank=True, null=True)

    #property method to get the full name of the customer by combining first and last names from the linked user instance.
    @property
    def fullname(self):
        return f'{self.user.first_name} {self.user.last_name}'.strip()

    def __str__(self):
        return self.fullname
    