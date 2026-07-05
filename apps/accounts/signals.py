from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User
from apps.customers.models import CustomerProfile
from apps.providers.models import ProviderProfile


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.role == "customer":
        CustomerProfile.objects.create(user=instance)

    elif instance.role == "provider":
        ProviderProfile.objects.create(
            user=instance,
            business_name=f'{instance.first_name} {instance.last_name}'
        )