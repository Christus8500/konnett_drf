import django_filters
from apps.services.models import Service

# Filter class for the Service model, allowing filtering by category and active status.
class ServiceFilter(django_filters.FilterSet):
    class Meta:
        model = Service
        fields = [
            "category",
            "is_active",
        ]
