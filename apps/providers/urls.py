from django.urls import path

from apps.providers.views import (
    ProviderProfileView,
    ProviderVerificationView,
    AdminPendingProviderVerificationsListView,
    update_provider_verification_status,
)

urlpatterns = [
    path("profile/", ProviderProfileView.as_view(), name="provider_profile"),
    path(
        "verification/",
        ProviderVerificationView.as_view(),
        name="provider_verification",
    ),
    path(
        "provider_verifications/",
        AdminPendingProviderVerificationsListView.as_view(),
        name="provider_verifications_list",
    ),
    path(
        "verification/<uuid:provider_id>/update_status/",
        update_provider_verification_status,
        name="update-provider-verification-status",
    ),
]
