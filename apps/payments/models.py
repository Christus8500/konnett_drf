import uuid
from django.db import models

# Create your models here.

# class Payment(models.Model):

#     STATUS_CHOICES = (
#         ("pending", "Pending"),
#         ("held", "Held"),
#         ("released", "Released"),
#         ("refunded", "Refunded"),
#     )

#     id = models.UUIDField(
#         primary_key=True,
#         default=uuid.uuid4,
#         editable=False
#     )

#     request = models.OneToOneField(
#         "jobs.ServiceRequest",
#         on_delete=models.CASCADE
#     )

#     amount = models.DecimalField(
#         max_digits=12,
#         decimal_places=2
#     )

#     platform_fee = models.DecimalField(
#         max_digits=12,
#         decimal_places=2,
#         default=0
#     )

#     provider_amount = models.DecimalField(
#         max_digits=12,
#         decimal_places=2
#     )

#     transaction_reference = models.CharField(
#         max_length=255,
#         unique=True
#     )

#     status = models.CharField(
#         max_length=20,
#         choices=STATUS_CHOICES,
#         default="pending"
#     )

#     created_at = models.DateTimeField(auto_now_add=True)

