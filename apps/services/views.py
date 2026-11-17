import logging

from django.conf import settings
from django.db.models import ProtectedError

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import generics, viewsets
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.throttling import (
    UserRateThrottle,
    AnonRateThrottle,
)

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view

from apps.services.serializers import (
    CategorySerializer,
    ServiceReadSerializer,
    ServiceWriteSerializer,
)
from apps.services.models import Category, Service
from apps.services.filters import ServiceFilter

from apps.core.permissions import IsProvider, IsProviderOwner, IsVerifiedProvider
from apps.core.utils import (
    FORBIDDEN,
    THROTTLED,
    UNAUTHORIZED,
    VALIDATION_ERROR,
    build_list_cache_key,
    get_cache,
    paginator_param_names,
    set_cache,
)

logger = logging.getLogger(__name__)

CATEGORY_NOT_FOUND = OpenApiResponse(description="Category not found.")
CATEGORY_IN_USE = OpenApiResponse(
    description="The category is in use (e.g. by job requests) and cannot be deleted."
)
SERVICE_NOT_FOUND = OpenApiResponse(description="Service not found.")

# Create your views here.


# ViewSet for managing categories, allowing any user to list and retrieve categories
# but restricting create, update, and delete actions to admin users.
@extend_schema_view(
    list=extend_schema(
        tags=["Categories"],
        summary="List categories",
        description="Public. Returns all categories (not paginated). Cached.",
        responses={200: CategorySerializer(many=True), 429: THROTTLED},
    ),
    retrieve=extend_schema(
        tags=["Categories"],
        summary="Get a category",
        responses={200: CategorySerializer, 404: CATEGORY_NOT_FOUND},
    ),
    create=extend_schema(
        tags=["Categories"],
        summary="Create a category (admin)",
        request=CategorySerializer,
        responses={
            201: CategorySerializer,
            400: VALIDATION_ERROR,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
        },
    ),
    partial_update=extend_schema(
        tags=["Categories"],
        summary="Update a category (admin)",
        request=CategorySerializer,
        responses={
            200: CategorySerializer,
            400: VALIDATION_ERROR,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: CATEGORY_NOT_FOUND,
        },
    ),
    destroy=extend_schema(
        tags=["Categories"],
        summary="Delete a category (admin)",
        responses={
            204: OpenApiResponse(description="Category deleted."),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: CATEGORY_NOT_FOUND,
            409: CATEGORY_IN_USE,
        },
    ),
)
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    # list() below returns the full cached list, so don't advertise pagination in the schema.
    pagination_class = None

    http_method_names = ["get", "post", "patch", "delete"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        return [IsAdminUser()]

    def get_throttles(self):
        if self.action == "list":
            if self.request.user.is_authenticated:
                return [UserRateThrottle()]
            else:
                return [AnonRateThrottle()]
        return super().get_throttles()

    def list(self, request, *args, **kwargs):
        # Use this when filtering, searching etc is available
        # cache_key = f"categories:list:{request.GET.urlencode()}"
        cache_key = "categories:list"
        cached_data = get_cache(cache_key)

        if cached_data is not None:
            logger.debug("Category list served from cache")
            return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        set_cache(cache_key, serializer.data, timeout=settings.SMALL_CACHE_TIMEOUT)

        return Response(serializer.data)

    def perform_create(self, serializer):
        super().perform_create(serializer)
        logger.info(
            "Category created admin_id=%s category_id=%s",
            self.request.user.pk,
            serializer.instance.pk,
        )

    def perform_update(self, serializer):
        super().perform_update(serializer)
        logger.info(
            "Category updated admin_id=%s category_id=%s fields=%s",
            self.request.user.pk,
            serializer.instance.pk,
            sorted(serializer.validated_data.keys()),
        )

    def perform_destroy(self, instance):
        category_id = instance.pk
        super().perform_destroy(instance)  # raises ProtectedError if in use
        logger.warning(
            "Category deleted admin_id=%s category_id=%s",
            self.request.user.pk,
            category_id,
        )

    def destroy(self, request, *args, **kwargs):
        # JobRequest.category is on_delete=PROTECT, so deleting a category that
        # has jobs raises ProtectedError. Return 409 instead of a 500.
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
        except ProtectedError:
            logger.warning(
                "Category delete blocked: in use admin_id=%s category_id=%s",
                request.user.pk,
                instance.pk,
            )
            return Response(
                {"detail": "This category is in use and cannot be deleted."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# View for listing and creating services, allowing any user to list services but restricting creation to verified providers.
@extend_schema_view(
    get=extend_schema(
        tags=["Services"],
        summary="List services",
        description=(
            "Public. Supports the filter query parameters, `search` (title and "
            "description) and `ordering` (`minimum_points`, `created_at`). "
            "Returns all matching services (paginated). Cached briefly per "
            "query string."
        ),
        responses={200: ServiceReadSerializer, 429: THROTTLED},
    ),
    post=extend_schema(
        tags=["Services"],
        summary="Create a service (verified providers)",
        request=ServiceWriteSerializer,
        responses={
            201: ServiceWriteSerializer,
            400: VALIDATION_ERROR,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
        },
    ),
)
class ListCreateServiceView(generics.ListCreateAPIView):
    queryset = Service.objects.select_related("provider", "category")
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_class = ServiceFilter
    search_fields = ["title", "description"]
    ordering_fields = ["minimum_points", "created_at"]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return ServiceReadSerializer
        return ServiceWriteSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsVerifiedProvider()]

    def perform_create(self, serializer):
        provider = self.request.user.provider_profile
        serializer.save(provider=provider)
        logger.info(
            "Service created provider_id=%s service_id=%s",
            provider.pk,
            serializer.instance.pk,
        )

    def get_throttles(self):
        if self.request.method == "GET":
            if self.request.user.is_authenticated:
                return [UserRateThrottle()]
            else:
                return [AnonRateThrottle()]
        return super().get_throttles()

    def _allowed_cache_params(self):
        return (
            set(ServiceFilter.base_filters)
            | {SearchFilter.search_param, OrderingFilter.ordering_param}
            | paginator_param_names(self)
        )

    def list(self, request, *args, **kwargs):
        cache_key = build_list_cache_key(
            "services:list", request, self._allowed_cache_params()
        )

        cached_data = get_cache(cache_key)
        if cached_data is not None:
            logger.debug("Service list served from cache")
            return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            data = self.get_paginated_response(serializer.data).data
        else:
            data = self.get_serializer(queryset, many=True).data

        set_cache(cache_key, data, timeout=settings.SMALL_CACHE_TIMEOUT)
        return Response(data)


# View for retrieving, updating, and deleting a specific service, allowing any user to retrieve a service but restricting update and delete actions to the service's provider.
@extend_schema_view(
    get=extend_schema(
        tags=["Services"],
        summary="Get a service",
        responses={200: ServiceReadSerializer, 404: SERVICE_NOT_FOUND},
    ),
    patch=extend_schema(
        tags=["Services"],
        summary="Update a service (owner)",
        request=ServiceWriteSerializer,
        responses={
            200: ServiceWriteSerializer,
            400: VALIDATION_ERROR,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: SERVICE_NOT_FOUND,
        },
    ),
    delete=extend_schema(
        tags=["Services"],
        summary="Delete a service (owner)",
        responses={
            204: OpenApiResponse(description="Service deleted."),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: SERVICE_NOT_FOUND,
        },
    ),
)
class RetrieveUpdateDeleteServiceView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Service.objects.select_related("provider", "provider__user", "category")
    http_method_names = ["get", "patch", "delete"]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return ServiceReadSerializer
        return ServiceWriteSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsProviderOwner()]

    def perform_update(self, serializer):
        super().perform_update(serializer)
        logger.info(
            "Service updated user_id=%s service_id=%s fields=%s",
            self.request.user.pk,
            serializer.instance.pk,
            sorted(serializer.validated_data.keys()),
        )

    def perform_destroy(self, instance):
        service_id = instance.pk
        super().perform_destroy(instance)
        logger.info(
            "Service deleted user_id=%s service_id=%s",
            self.request.user.pk,
            service_id,
        )


# Get all services for the logged-in provider, only accessible to providers
@extend_schema(
    tags=["Services"],
    summary="List my services",
    description="Returns the authenticated provider's services, paginated. Cached per page.",
    responses={
        200: ServiceReadSerializer,   # spectacular adds the pagination wrapper
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        429: THROTTLED,
    },
)
class MyServiceListView(generics.ListAPIView):
    serializer_class = ServiceReadSerializer
    permission_classes = [IsProvider]
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Service.objects.none()

        return Service.objects.filter(provider__user=self.request.user).select_related(
            "provider", "category"
        )

    def list(self, request, *args, **kwargs):
        provider_id = request.user.provider_profile.id
        cache_key = build_list_cache_key(
            f"my-services:{provider_id}", request, paginator_param_names(self)
        )

        cached_data = get_cache(cache_key)
        if cached_data is not None:
            logger.debug("My services served from cache provider_id=%s", provider_id)
            return Response(cached_data)

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            data = self.get_paginated_response(serializer.data).data
        else:
            data = self.get_serializer(queryset, many=True).data

        set_cache(cache_key, data, timeout=settings.SMALL_CACHE_TIMEOUT)
        return Response(data)
