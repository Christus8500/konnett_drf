from django.db.models import Q
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from apps.core.permissions import IsProvider
from apps.core.choices import ProviderVerificationStatus

from apps.providers.models import ProviderProfile, ProviderVerification
from apps.providers.serializers import (
    ProviderProfileSerializer,
    ProviderVerificationSerializer,
)

# Create your views here.


# View for retrieving and updating the ProviderProfile instance associated with a specific user.
class ProviderProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProviderProfileSerializer
    permission_classes = [IsProvider]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return ProviderProfile.objects.select_related("user")

    def get_object(self):
        return self.get_queryset().get(user=self.request.user)


# View for retrieving and updating the ProviderVerification instance associated with a specific provider.
class ProviderVerificationView(generics.RetrieveUpdateAPIView):
    serializer_class = ProviderVerificationSerializer
    permission_classes = [IsProvider]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return ProviderVerification.objects.select_related(
            "provider__user",
        )

    def get_object(self):
        return self.get_queryset().get(provider__user=self.request.user)

    def perform_update(self, serializer):
        verification = serializer.instance

        if verification.provider.is_verified:
            raise ValidationError("You are already verified.")

        serializer.save()


class AdminPendingProviderVerificationsListView(generics.ListAPIView):
    queryset = (
        ProviderVerification.objects.select_related("provider__user")
        .filter(
            status=ProviderVerificationStatus.PENDING,
            id_document__isnull=False,
        )
        .exclude(id_document="")
    )
    serializer_class = ProviderVerificationSerializer
    permission_classes = [IsAdminUser]


# API view for updating the verification status of a provider. This view is restricted to admin users only.
@extend_schema(
    request=OpenApiTypes.OBJECT,
    responses={
        200: OpenApiTypes.OBJECT,
        400: OpenApiTypes.OBJECT,
        404: OpenApiTypes.OBJECT,
    },
)
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
        verification = ProviderVerification.objects.select_related("provider").get(
            provider_id=provider_id
        )
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
