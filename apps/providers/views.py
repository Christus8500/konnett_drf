from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.core.permissions import IsOwner, IsOwnerOrAdmin
from apps.core.choices import ProviderVerificationStatus
from apps.providers.models import ProviderProfile, ProviderVerification
from apps.providers.serializers import ProviderProfileSerializer, ProviderVerificationSerializer
from apps.providers.permissions import IsProviderVerificationOwner

# Create your views here.
class ProviderProfileView(generics.RetrieveUpdateAPIView):
    queryset = ProviderProfile.objects.select_related('user')
    serializer_class = ProviderProfileSerializer

    #Using the provider's user_id for lookup
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    #Allow only fetch and update
    http_method_names = ["get", "patch"]

    #Overriding get_permissions(): Admin can fetch any customer profile, but only the owner can update their own profile.
    def get_permissions(self):
        self.permission_classes = [IsOwnerOrAdmin]
        if self.request.method == 'PATCH':
            self.permission_classes = [IsOwner]
        return super().get_permissions()
    

class ProviderVerificationView(generics.RetrieveUpdateAPIView):
    queryset = ProviderVerification.objects.select_related("provider", "provider__user")
    serializer_class = ProviderVerificationSerializer

    #Using the provider_id for lookup
    lookup_field = "provider__id"
    lookup_url_kwarg = "provider_id"

    #Allow only fetch and update
    http_method_names = ["get", "patch"]

    def get_permissions(self):
        if self.request.method == "PATCH":
            self.permission_classes = [IsProviderVerificationOwner]
        else:
            self.permission_classes = [IsAdminUser | IsProviderVerificationOwner]
        return super().get_permissions()


@api_view(["POST"])
@permission_classes([IsAdminUser])
def update_provider_verification_status(request):
    data = request.data
    provider_id = data.get("provider_id")
    verification_status = data.get("verification_status")

    if verification_status not in ProviderVerificationStatus.values:
        return Response(
            {"error": "Invalid status"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Find the verification
    try:
        verification = ProviderVerification.objects.get(provider__id=provider_id)        
    except ProviderVerification.DoesNotExist:
        return Response(
            {"error": f"Verification not found for provider {provider_id}"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    previous_verification_status = verification.status
    verification.status = verification_status
    verification.save()
    return Response({
        "success": f"Verification status updated from {previous_verification_status} to {verification_status}",
        # "verification": verification
    })
    
