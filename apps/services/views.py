from django.conf import settings

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import generics, viewsets
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.throttling import (
    UserRateThrottle,
    AnonRateThrottle,
)

from drf_spectacular.utils import extend_schema

from apps.services.serializers import (
    CategorySerializer,
    ServiceReadSerializer,
    ServiceWriteSerializer,
)
from apps.services.models import Category, Service
from apps.services.filters import ServiceFilter

from apps.core.permissions import IsProvider, IsProviderOwner, IsVerifiedProvider
from apps.core.utils import get_cache, set_cache

# Create your views here.


# ViewSet for managing categories, allowing any user to list and retrieve categories
# but restricting create, update, and delete actions to admin users.
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

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
            return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        set_cache(cache_key, serializer.data, timeout=settings.SMALL_CACHE_TIMEOUT)

        return Response(serializer.data)


# View for listing and creating services, allowing any user to list services but restricting creation to verified providers.
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
        serializer.save(provider=self.request.user.provider_profile)

    def get_throttles(self):
        if self.request.method == "GET":
            if self.request.user.is_authenticated:
                return [UserRateThrottle()]
            else:
                return [AnonRateThrottle()]
        return super().get_throttles()

    def list(self, request, *args, **kwargs):
        # Handling cases where the request has params like filters and searches etc
        cache_key = f"services:list:{request.GET.urlencode()}"

        cached_data = get_cache(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        set_cache(cache_key, serializer.data, timeout=settings.SMALL_CACHE_TIMEOUT)

        return Response(serializer.data)


# View for retrieving, updating, and deleting a specific service, allowing any user to retrieve a service but restricting update and delete actions to the service's provider.
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


# Get all services for the logged-in provider, only accessible to providers
@extend_schema(
    responses={
        200: ServiceReadSerializer(many=True),
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

        cache_key = f"my-services:{provider_id}"

        cached_data = get_cache(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        set_cache(
            cache_key,
            serializer.data,
            timeout=settings.SMALL_CACHE_TIMEOUT,
        )

        return Response(serializer.data)
