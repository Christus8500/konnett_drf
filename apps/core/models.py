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