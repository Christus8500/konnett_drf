from rest_framework import generics, viewsets
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.filters import OrderingFilter, SearchFilter

from django_filters.rest_framework import DjangoFilterBackend

from apps.services.serializers import CategorySerializer, ServiceReadSerializer, ServiceWriteSerializer
from apps.services.models import Category, Service
from apps.services.filters import ServiceFilter
from apps.core.permissions import IsProvider, IsProviderOwner, IsVerifiedProvider

# Create your views here.

# ViewSet for managing categories, allowing any user to list and retrieve categories 
# but restricting create, update, and delete actions to admin users.
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        return [IsAdminUser()]


# View for listing and creating services, allowing any user to list services but restricting creation to providers.
class ListCreateServiceView(generics.ListCreateAPIView):
    queryset = Service.objects.select_related(
        "provider",
        "provider__user",
        "category"
    )
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_class = ServiceFilter
    search_fields = ["title", "description"]
    ordering_fields = ["minimum_price", "created_at"]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return ServiceReadSerializer
        return ServiceWriteSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsProvider(), IsVerifiedProvider()]

    # Override the perform_create method to associate the newly created service with the logged-in provider.
    def perform_create(self, serializer):
        serializer.save(provider=self.request.user.provider_profile)


# View for retrieving, updating, and deleting a specific service, allowing any user to retrieve a service but restricting update and delete actions to the service's provider.
class RetrieveUpdateDeleteServiceView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Service.objects.select_related(
        "provider",
        "provider__user",
        "category"
    )

    def get_serializer_class(self):
        if self.request.method == "GET":
            return ServiceReadSerializer
        return ServiceWriteSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsProviderOwner()]


# Get all services for the logged-in provider, only accessible to providers
class MyServiceListView(generics.ListAPIView):
    serializer_class = ServiceReadSerializer
    permission_classes = [IsProvider]

    def get_queryset(self):
        return Service.objects.filter(provider__user=self.request.user).select_related("provider", "provider__user", "category")