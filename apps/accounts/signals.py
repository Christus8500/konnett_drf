from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User
from apps.customers.models import CustomerProfile
from apps.providers.models import ProviderProfile


#Creating user profiles based on the role of the user after a new user instance is created. 
# If the user is a customer, a CustomerProfile is created. If the user is a provider, a ProviderProfile is created with the business name set to the user's full name.
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