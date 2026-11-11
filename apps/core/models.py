import uuid
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


# Create your models here.
# TimeStampedModel: An abstract base model that provides created_at and updated_at fields to track the creation and modification timestamps of model instances.
class TimeStampedModel(models.Model):
    """Adds created_at / updated_at to any model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# UUIDModel: An abstract base model that provides a UUID primary key field for model instances.
class UUIDModel(models.Model):
    """Uses a UUID as the primary key."""

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
        validators=[
            MinValueValidator(Decimal("-90")),
            MaxValueValidator(Decimal("90")),
        ],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-180")),
            MaxValueValidator(Decimal("180")),
        ],
    )

    class Meta:
        verbose_name_plural = "addresses"
        indexes = [models.Index(fields=["state", "city"])]

    def __str__(self):
        return f"{self.address}, {self.city}, {self.state}"
