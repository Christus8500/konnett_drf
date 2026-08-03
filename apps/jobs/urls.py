from django.urls import path, include

from rest_framework.routers import DefaultRouter

from apps.jobs.views import JobRequestViewSet, JobRequestImageCreateView, JobRequestImageDeleteView, JobOfferView, JobOfferAcceptView, JobOfferRejectView, JobOfferWithdrawView, JobCompletionImageCreateView, JobRequestCompletionView, JobConfirmCompletionView, JobDisputeCreateView, JobDisputeDetailView, AdminResolveDisputeView


router = DefaultRouter()
router.register("", JobRequestViewSet, basename="job")

urlpatterns = [
    ####*  JOBS  ####
    path("", include(router.urls)),

    ####*  JOB IMAGES  ####
    path("<uuid:pk>/images/", JobRequestImageCreateView.as_view(),
         name="job-image-upload"),
    path("images/<uuid:pk>/", JobRequestImageDeleteView.as_view(),
         name="job-image-delete"),

    ####*  OFFERS  ####
    path("<uuid:pk>/offers/", JobOfferView.as_view(), name="job-offers"),
    path("provider/offers/", JobOfferView.as_view(), name="provider-offers"),
    path("offers/<uuid:pk>/accept/",
         JobOfferAcceptView.as_view(), name="job-offer-accept"),
    path("offers/<uuid:pk>/reject/",
         JobOfferRejectView.as_view(), name="job-offer-reject"),
    path("offers/<uuid:pk>/withdraw/",
         JobOfferWithdrawView.as_view(), name="job-offer-withdraw"),

    ####*  COMPLETIONS  ####
    path("<uuid:pk>/completion-images/", JobCompletionImageCreateView.as_view(),
         name="job-completion-image-create"),
    path("<uuid:pk>/request-completion/",
         JobRequestCompletionView.as_view(), name="job-request-completion"),
    path("<uuid:pk>/confirm-completion/",
         JobConfirmCompletionView.as_view(), name="job-confirm-completion"),

    ####*  DISPUTES  ####
    path("<uuid:pk>/dispute/", JobDisputeCreateView.as_view(),
         name="job-dispute-create"),
    path("disputes/<uuid:pk>/", JobDisputeDetailView.as_view(),
         name="job-dispute-detail"),
    path("disputes/<uuid:pk>/resolve/",
         AdminResolveDisputeView.as_view(), name="job-dispute-resolve"),
]
