import django_filters

from apps.jobs.models import JobRequest


# This filter class is used to filter JobRequest instances based on various fields such as category name, city, state, status, and points amount.
# It allows for case-insensitive exact matches and partial matches for category names, as well as exact matches for city and state.
# Additionally, it supports filtering by status and points amount with options for exact, less than, greater than, and range queries.
class JobFilter(django_filters.FilterSet):
    class Meta:
        model = JobRequest
        fields = {
            "category__name": ["iexact", "icontains"],
            "primary_location__city": ["iexact"],
            "primary_location__state": ["iexact"],
            "primary_location__latitude": ["exact"],
            "primary_location__longitude": ["exact"],
            "secondary_location__city": ["iexact"],
            "secondary_location__state": ["iexact"],
            "secondary_location__latitude": ["exact"],
            "secondary_location__longitude": ["exact"],
            "status": ["iexact"],
            "points_amount": ["exact", "lt", "gt", "range"],
        }
