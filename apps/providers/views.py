from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.core.permissions import IsOwner, IsOwnerOrAdmin, IsProviderOwner
from apps.core.choices import ProviderVerificationStatus
from apps.providers.models import ProviderProfile, ProviderVerification
from apps.providers.serializers import ProviderProfileSerializer, ProviderVerificationSerializer

# Create your views here.

# View for retrieving and updating the ProviderProfile instance associated with a specific user.
class ProviderProfileView(generics.RetrieveUpdateAPIView):
    queryset = ProviderProfile.objects.select_related('user')
    serializer_class = ProviderProfileSerializer

    #Using the provider's user_id for lookup
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    #Allow only fetch and update
    http_method_names = ["get", "patch"]

    #Overriding get_permissions(): Admin can fetch any provider profile, but only the owner can update their own profile.
    def get_permissions(self):
        self.permission_classes = [IsOwnerOrAdmin]
        if self.request.method == 'PATCH':
            self.permission_classes = [IsOwner]
        return super().get_permissions()
    

# View for retrieving and updating the ProviderVerification instance associated with a specific provider.
class ProviderVerificationView(generics.RetrieveUpdateAPIView):
    queryset = ProviderVerification.objects.select_related("provider", "provider__user")
    serializer_class = ProviderVerificationSerializer

    #Using the provider_id for lookup
    lookup_field = "provider__id"
    lookup_url_kwarg = "provider_id"

    #Allow only fetch and update
    http_method_names = ["get", "patch"]

    def perform_update(self, serializer):
        verification = self.get_object()

        if verification.provider.is_verified:
            raise ValidationError("You are already verified.")

        serializer.save()

    def get_permissions(self):
        if self.request.method == "PATCH":
            self.permission_classes = [IsProviderOwner]
        else:
            self.permission_classes = [IsAdminUser | IsProviderOwner]
        return super().get_permissions()


# API view for updating the verification status of a provider. This view is restricted to admin users only.
@api_view(["PATCH"])
@permission_classes([IsAdminUser])
def update_provider_verification_status(request, provider_id):
    verification_status = request.data.get("verification_status")

    if verification_status not in ProviderVerificationStatus.values:
        return Response(
            {"error": "Invalid verification status."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        verification = ProviderVerification.objects.get(provider_id=provider_id)
    except ProviderVerification.DoesNotExist:
        return Response(
            {"error": "Provider verification not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if (
        verification.provider.is_verified
        and verification_status == ProviderVerificationStatus.VERIFIED
    ):  
        return Response(
            {"detail": "This provider is already verified."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    previous_status = verification.status
    verification.status = verification_status
    verification.save(update_fields=["status"])

    return Response(
        {
            "message": f"Verification status updated from {previous_status} to {verification.status}.",
            "verification_status": verification.status,
        },
        status=status.HTTP_200_OK,
    )
    
