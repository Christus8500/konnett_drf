import logging

from django.conf import settings
from django.shortcuts import get_object_or_404

from rest_framework import generics
from rest_framework.response import Response

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view

from apps.core.permissions import IsCustomer
from apps.core.utils import (
    FORBIDDEN,
    UNAUTHORIZED,
    VALIDATION_ERROR,
    get_cache,
    set_cache,
)

from apps.customers.models import CustomerProfile
from apps.customers.serializers import CustomerProfileSerializer

logger = logging.getLogger(__name__)

NOT_FOUND = OpenApiResponse(description="Customer profile not found.")


# Create your views here.
@extend_schema_view(
    get=extend_schema(
        tags=["Customers"],
        summary="Get my customer profile",
        description="Returns the authenticated customer's profile. Cached.",
        responses={
            200: CustomerProfileSerializer,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    ),
    patch=extend_schema(
        tags=["Customers"],
        summary="Update my customer profile",
        description="Partially updates the authenticated customer's profile.",
        request=CustomerProfileSerializer,
        responses={
            200: CustomerProfileSerializer,
            400: VALIDATION_ERROR,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    ),
)
class CustomerProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = CustomerProfileSerializer
    permission_classes = [IsCustomer]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return CustomerProfile.objects.select_related("user", "address").filter(user=self.request.user)

    def get_object(self):
        obj = get_object_or_404(self.get_queryset(), user=self.request.user)
        self.check_object_permissions(self.request, obj)
        return obj

    def retrieve(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = f"customer:profile:{user_id}"

        cached_data = get_cache(cache_key)

        if cached_data is not None:
            logger.debug(
                "Customer profile served from cache user_id=%s", user_id)
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
        data = serializer.validated_data
        fields = sorted([k for k in data if k != "user"] +
                        list(data.get("user", {})))
        logger.info(
            "Customer profile updated user_id=%s fields=%s", self.request.user.pk, fields
        )
