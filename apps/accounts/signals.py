from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.choices import UserRole
from apps.accounts.models import User
from apps.customers.models import CustomerProfile
from apps.providers.models import ProviderProfile
from apps.konnett_points.models import PointWallet


# Creating user profiles based on the role of the user after a new user instance is created.
# If the user is a customer, a CustomerProfile is created. If the user is a provider, a ProviderProfile is created with the business name set to the user's full name.
# A wallet is also created for every new user, except for administrators.
@receiver(post_save, sender=User)
def create_user_profile_and_wallet(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.role == UserRole.ADMIN:
        return

    PointWallet.objects.create(user=instance)

    if instance.role == UserRole.CUSTOMER:
        CustomerProfile.objects.create(user=instance)

    elif instance.role == UserRole.PROVIDER:
        ProviderProfile.objects.create(
            user=instance, business_name=f"{instance.first_name} {instance.last_name}"
        )
