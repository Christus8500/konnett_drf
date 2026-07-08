from django.urls import path

from apps.customers.views import CustomerDetailView

urlpatterns = [
    path("profile/<uuid:user_id>/", CustomerDetailView.as_view(), name="profile")
]