from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from apps.core.choices import UserRole
from apps.accounts.models import User
from apps.customers.models import CustomerProfile
from apps.providers.models import ProviderProfile
from apps.konnett_points.models import PointWallet


# Creating user profiles based on the role of the user after a new user instance is created.
# If the user is a customer, a CustomerProfile is created. If the user is a provider, a ProviderProfile is created with the business name set to the user's full name.
# A wallet is also created for every new user, except for administrators.
@receiver(post_save, sender=User)
def user_saved(sender, instance, created, **kwargs):

    # Clear caches whenever a user is created or updated
    cache.delete("admin:users")
    cache.delete(f"user:{instance.id}")

    # Only create profiles/wallet for newly created users
    if not created:
        return

    if instance.role == UserRole.ADMIN:
        return

    PointWallet.objects.create(user=instance)

    if instance.role == UserRole.CUSTOMER:
        CustomerProfile.objects.create(user=instance)

    elif instance.role == UserRole.PROVIDER:
        ProviderProfile.objects.create(
            user=instance,
            business_name=f"{instance.first_name} {instance.last_name}",
        )


@receiver(post_delete, sender=User)
def user_deleted(sender, instance, **kwargs):
    cache.delete("admin:users")
    cache.delete(f"user:{instance.id}")
