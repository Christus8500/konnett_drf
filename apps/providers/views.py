from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from apps.core.permissions import IsProvider
from apps.core.choices import ProviderVerificationStatus
from apps.core.utils import get_cache, set_cache

from apps.providers.models import ProviderProfile, ProviderVerification
from apps.providers.serializers import (
    ProviderProfileSerializer,
    ProviderVerificationSerializer,
)
from apps.providers.notifications import send_verification_email

# Create your views here.


# View for retrieving and updating the ProviderProfile instance associated with a specific user.
class ProviderProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProviderProfileSerializer
    permission_classes = [IsProvider]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return ProviderProfile.objects.select_related("user", "address")

    def get_object(self):
        return get_object_or_404(
            self.get_queryset(),
            user=self.request.user,
        )

    def retrieve(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = f"provider:profile:{user_id}"

        cached_data = get_cache(cache_key)

        if cached_data is not None:
            return Response(cached_data)

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        set_cache(
            cache_key,
            serializer.data,
            timeout=settings.BIG_CACHE_TIMEOUT,
        )

        return Response(serializer.data)


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
        return get_object_or_404(
            self.get_queryset(),
            provider__user=self.request.user,
        )

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
@transaction.atomic
def update_provider_verification_status(request, provider_id):
    verification_status = request.data.get("verification_status")
    admin_comment = request.data.get("admin_comment")

    allowed_statuses = {
        ProviderVerificationStatus.VERIFIED,
        ProviderVerificationStatus.REJECTED,
    }

    if verification_status not in allowed_statuses:
        return Response(
            {"error": "Invalid verification status."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        verification = ProviderVerification.objects.select_related(
            "provider__user"
        ).get(provider_id=provider_id)
    except ProviderVerification.DoesNotExist:
        return Response(
            {"error": "Provider verification not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if verification_status == ProviderVerificationStatus.REJECTED:
        if not admin_comment or not admin_comment.strip():
            return Response(
                {
                    "error": (
                        "Admin comment is required when rejecting "
                        "a verification."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        admin_comment = admin_comment.strip()

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

    if verification_status == ProviderVerificationStatus.REJECTED:
        verification.admin_comment = admin_comment
        verification.provider.is_verified = False
    else:
        verification.admin_comment = ""
        verification.provider.is_verified = True

    verification.save(update_fields=["status", "admin_comment"])

    verification.provider.save(update_fields=["is_verified"])

    email_status = verification_status
    email_comment = admin_comment

    # -- BACKGROUND TASK --
    # Send email based on the verification status.
    transaction.on_commit(
        lambda: send_verification_email(
            user=verification.provider.user,
            status=email_status,
            admin_comment=email_comment,
        )
    )

    return Response(
        {
            "message": (
                f"Verification status updated from {previous_status} "
                f"to {verification.status}."
            ),
            "verification_status": verification.status,
        },
        status=status.HTTP_200_OK,
    )
