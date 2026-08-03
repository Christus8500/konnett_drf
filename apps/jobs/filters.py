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
            "city": ["iexact"],
            "state": ["iexact"],
            "status": ["iexact"],
            "points_amount": ["exact", "lt", "gt", "range"]

        }