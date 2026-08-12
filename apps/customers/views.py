from rest_framework import generics

from apps.core.permissions import IsCustomer
from apps.customers.models import CustomerProfile
from apps.customers.serializers import CustomerProfileSerializer


# Create your views here.
class CustomerProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = CustomerProfileSerializer
    permission_classes = [IsCustomer]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user.customer_profile
