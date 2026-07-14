from rest_framework.permissions import BasePermission

class IsProviderVerificationOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        return obj.provider.user == request.user