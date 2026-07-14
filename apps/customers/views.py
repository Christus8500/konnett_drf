from rest_framework import generics

from apps.core.permissions import IsOwner, IsOwnerOrAdmin
from apps.customers.models import CustomerProfile
from apps.customers.serializers import CustomerProfileSerializer


# Create your views here.
class CustomerProfileView(generics.RetrieveUpdateAPIView):
    queryset = CustomerProfile.objects.select_related('user')
    serializer_class = CustomerProfileSerializer
    
    #Using the customer's user_id for lookup
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
