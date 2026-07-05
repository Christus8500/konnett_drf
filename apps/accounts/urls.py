from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import RegisterView, LoginView, UserView, UserViewSet


router = DefaultRouter()
router.register('users', UserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("me/", UserView.as_view(), name="me"),

    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
