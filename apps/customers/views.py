from django.conf import settings

from rest_framework import generics
from rest_framework.response import Response

from apps.core.permissions import IsCustomer
from apps.core.utils import get_cache, set_cache

from apps.customers.models import CustomerProfile
from apps.customers.serializers import CustomerProfileSerializer


# Create your views here.
class CustomerProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = CustomerProfileSerializer
    permission_classes = [IsCustomer]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return CustomerProfile.objects.select_related("user")

    def get_object(self):
        return self.get_queryset().get(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = f"customer:profile:{user_id}"

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
