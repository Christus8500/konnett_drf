from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.accounts.views import *


router = DefaultRouter()
router.register('users', UserViewSet, basename='user')

urlpatterns = [
    path('accounts/', include(router.urls))
]
