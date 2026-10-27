import uuid

from django.db import models


# Create your models here.
# TimeStampedModel: An abstract base model that provides created_at and updated_at fields to track the creation and modification timestamps of model instances.
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# UUIDModel: An abstract base model that provides a UUID primary key field for model instances.
class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Address(UUIDModel):
    address = models.TextField()
    city = models.CharField(max_length=255)
    state = models.CharField(max_length=255)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.address}, {self.city}, {self.state}"
    