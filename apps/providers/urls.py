from django.urls import path

from apps.providers.views import ProviderProfileView, ProviderVerificationView, update_provider_verification_status

urlpatterns = [
    path("profile/<uuid:user_id>/", ProviderProfileView.as_view(), name="provider_profile"),
    path("verification/<uuid:provider_id>/", ProviderVerificationView.as_view(), name="provider_verification"),

    path("verification/update_status/", update_provider_verification_status, name="update_provider_verification_status"),
]