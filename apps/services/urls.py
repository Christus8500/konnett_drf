from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.services.views import CategoryViewSet, ListCreateServiceView, RetrieveUpdateDeleteServiceView, MyServiceListView

router = DefaultRouter()
router.register("", CategoryViewSet, basename="category")

urlpatterns = [
    path("categories/", include(router.urls)),

    path("", ListCreateServiceView.as_view()),
    path("<uuid:pk>/", RetrieveUpdateDeleteServiceView.as_view()),
    path("my-services/", MyServiceListView.as_view()),
]