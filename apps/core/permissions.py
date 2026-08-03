from django.core.exceptions import ObjectDoesNotExist

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOwnerOrAdmin(BasePermission):
    """
    Allows access only to Admin and object owners.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_staff:
            return True

        return obj.user == request.user


class IsOwner(BasePermission):
    """
    Allows access only to object owners.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        return obj.user == request.user
    

class IsCustomer(BasePermission):
    """
    Allows access only to customer users.
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "customer"
        )
    

class IsCustomerOwner(BasePermission):
    """
    Allows access only to the owner of a customer instance.
    """
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        return obj.customer.user == request.user
    

class IsProvider(BasePermission):
    """
    Allows access only to provider users.
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "provider"
        )
    

class IsProviderOwner(BasePermission):
    """
    Allows access only to the owner of a provider instance.
    """
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        return obj.provider.user == request.user
    

class IsVerifiedProvider(BasePermission):
    """
    Allows access only verified provider.
    """
    message = "Only verified providers can perform this action."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        provider = getattr(request.user, "provider_profile", None)

        return bool(provider and provider.is_verified)