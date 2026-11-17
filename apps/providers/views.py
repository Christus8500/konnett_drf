import logging

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from apps.core.permissions import IsProvider
from apps.core.choices import ProviderVerificationStatus
from apps.core.utils import (
    FORBIDDEN,
    UNAUTHORIZED,
    VALIDATION_ERROR,
    get_cache,
    set_cache,
)

from apps.providers.models import ProviderProfile, ProviderVerification
from apps.providers.serializers import (
    ProviderProfileSerializer,
    ProviderVerificationSerializer,
    VerificationErrorSerializer,
    VerificationStatusUpdateRequestSerializer,
    VerificationStatusUpdateResponseSerializer,
)
from apps.providers.notifications import queue_provider_verification_email

logger = logging.getLogger(__name__)

PROFILE_NOT_FOUND = OpenApiResponse(description="Provider profile not found.")
VERIFICATION_NOT_FOUND = OpenApiResponse(
    description="Provider verification not found.")


def _updated_field_names(validated_data):
    """Flatten nested user/address dicts into plain field names (never values)."""
    names = []
    for key, value in validated_data.items():
        if key in ("user", "address") and isinstance(value, dict):
            names.extend(value.keys())
        else:
            names.append(key)
    return sorted(names)

# Create your views here.


# View for retrieving and updating the ProviderProfile instance associated with a specific user.
@extend_schema_view(
    get=extend_schema(
        tags=["Providers"],
        summary="Get my provider profile",
        description="Returns the authenticated provider's profile. Cached.",
        responses={
            200: ProviderProfileSerializer,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: PROFILE_NOT_FOUND,
        },
    ),
    patch=extend_schema(
        tags=["Providers"],
        summary="Update my provider profile",
        description=(
            "Partially updates the authenticated provider's profile. Changing any "
            "bank detail (`account_number`, `account_name`, `bank_name`) requires "
            "`current_password`, sends an alert email, and starts a withdrawal "
            "cooling-off period."
        ),
        request=ProviderProfileSerializer,
        responses={
            200: ProviderProfileSerializer,
            400: VALIDATION_ERROR,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: PROFILE_NOT_FOUND,
        },
    ),
)
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
            logger.debug(
                "Provider profile served from cache user_id=%s", user_id)
            return Response(cached_data)

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        set_cache(
            cache_key,
            serializer.data,
            timeout=settings.BIG_CACHE_TIMEOUT,
        )

        return Response(serializer.data)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        # Field names only, never values (may contain personal data).
        logger.info(
            "Provider profile updated user_id=%s fields=%s",
            self.request.user.pk,
            _updated_field_names(serializer.validated_data),
        )


# View for retrieving and updating the ProviderVerification instance associated with a specific provider.
@extend_schema_view(
    get=extend_schema(
        tags=["Provider verification"],
        summary="Get my verification",
        responses={
            200: ProviderVerificationSerializer,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: VERIFICATION_NOT_FOUND,
        },
    ),
    patch=extend_schema(
        tags=["Provider verification"],
        summary="Submit or update my verification",
        description=(
            "Upload `id_document` (pdf, jpg, jpeg, png) and/or `selfie_image` (jpg, jpeg, png). "
            "Uploading either file resets the status to `pending` and updates `submitted_at`. "
            "A request with no files changes nothing. Not allowed once approved."
        ),
        request={"multipart/form-data": ProviderVerificationSerializer},
        responses={
            200: ProviderVerificationSerializer,
            400: OpenApiResponse(
                description="Validation error, or the provider is already verified."
            ),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: VERIFICATION_NOT_FOUND,
        },
    ),
)
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

    @transaction.atomic
    def perform_update(self, serializer):
        # Lock the row so an admin decision can't be overwritten by this save.
        verification = (
            ProviderVerification.objects.select_for_update(of=("self",))
            .select_related("provider__user")
            .get(pk=serializer.instance.pk)
        )
        # update() now works on the locked, fresh copy
        serializer.instance = verification

        if verification.provider.is_verified:
            logger.warning(
                "Verification update blocked: already verified user_id=%s provider_id=%s",
                self.request.user.pk, verification.provider_id,
            )
            raise ValidationError("You are already verified.")

        serializer.save()
        logger.info(
            "Provider verification submitted user_id=%s provider_id=%s status=%s fields=%s",
            self.request.user.pk, verification.provider_id,
            serializer.instance.status, sorted(
                serializer.validated_data.keys()),
        )


@extend_schema(
    tags=["Provider verification (admin)"],
    summary="List pending verifications",
    description=(
        "Pending verifications that have an ID document uploaded, oldest first."
    ),
    responses={
        200: ProviderVerificationSerializer,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
    },
)
class AdminPendingProviderVerificationsListView(generics.ListAPIView):
    queryset = (
        ProviderVerification.objects.select_related("provider__user")
        .filter(
            status=ProviderVerificationStatus.PENDING,
            id_document__isnull=False,
        )
        .exclude(id_document="")
        .order_by("created_at")  # stable order for pagination; oldest first
    )
    serializer_class = ProviderVerificationSerializer
    permission_classes = [IsAdminUser]


# API view for updating the verification status of a provider. This view is restricted to admin users only.
@extend_schema(
    tags=["Provider verification (admin)"],
    summary="Approve or reject a provider's verification",
    description=(
        "Sets the verification to `verified` or `rejected` and queues an email to "
        "the provider. A rejection requires a non-empty `admin_comment`."
    ),
    parameters=[
        OpenApiParameter(
            name="provider_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="ID of the provider profile.",
        )
    ],
    request=VerificationStatusUpdateRequestSerializer,
    responses={
        200: VerificationStatusUpdateResponseSerializer,
        400: OpenApiResponse(
            response=VerificationErrorSerializer,
            description=(
                "Invalid status, missing comment on rejection, or the provider is "
                "already verified. Body has `error` or `detail`."
            ),
        ),
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: OpenApiResponse(
            response=VerificationErrorSerializer,
            description="Provider verification not found.",
        ),
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
        verification = (
            ProviderVerification.objects.select_for_update(of=("self",))
            .select_related("provider__user")
            .get(provider_id=provider_id)
        )
    except ProviderVerification.DoesNotExist:
        logger.warning(
            "Verification status update for unknown provider admin_id=%s provider_id=%s",
            request.user.pk,
            provider_id,
        )
        return Response(
            {"error": "Provider verification not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if verification_status == ProviderVerificationStatus.REJECTED:
        if not admin_comment or not admin_comment.strip():
            return Response(
                {
                    "error": (
                        "Admin comment is required when rejecting a verification."
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
    verification.admin_comment = (
        admin_comment
        if verification_status == ProviderVerificationStatus.REJECTED
        else ""
    )

    verification.save(update_fields=["status", "admin_comment", "updated_at"])

    verification.provider.save(update_fields=["is_verified", "updated_at"])

    # Queue email.
    queue_provider_verification_email(
        verification, verification_status, admin_comment=admin_comment
    )

    # Admin comment text is intentionally not logged.
    logger.info(
        "Provider verification status updated admin_id=%s provider_id=%s from=%s to=%s",
        request.user.pk,
        provider_id,
        previous_status,
        verification.status,
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
