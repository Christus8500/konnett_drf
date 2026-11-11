from django.urls import path

from apps.providers.views import (
    ProviderProfileView,
    ProviderVerificationView,
    AdminPendingProviderVerificationsListView,
    update_provider_verification_status,
)

from apps.jobs.views import MyRatingsListView, ProviderRatingsPublicListView

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
    path("ratings/me/", MyRatingsListView.as_view(), name="my-ratings"),
    path(
        "<uuid:provider_id>/ratings/",
        ProviderRatingsPublicListView.as_view(),
        name="provider-ratings",
    ),
]
