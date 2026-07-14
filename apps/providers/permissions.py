from rest_framework.permissions import BasePermission

# Permission class to check if the requesting user is the owner of a provider verification instance.
class IsProviderVerificationOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        return obj.provider.user == request.user