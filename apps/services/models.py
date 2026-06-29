import uuid 
from django.db import models

# Create your models here.
class ServiceCategory(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(
        max_length=100,
        unique=True
    )

    description = models.TextField(blank=True)


class ProviderService(models.Model):

    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE
    )

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.CASCADE
    )