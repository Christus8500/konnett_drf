from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    RegisterView,
    LoginView,
    UserView,
    UserViewSet,
    VerifyEmailView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    AuthenticatedPasswordResetView,
    EmailChangeRequestView,
    EmailChangeConfirmView,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("", include(router.urls)),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("me/", UserView.as_view(), name="me"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path(
        "verify-email/",
        VerifyEmailView.as_view(),
        name="verify-email",
    ),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path(
        "password-reset/me/",
        AuthenticatedPasswordResetView.as_view(),
        name="password-reset-me",
    ),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("email-change/", EmailChangeRequestView.as_view(), name="email-change"),
    path(
        "email-change/confirm/",
        EmailChangeConfirmView.as_view(),
        name="email-change-confirm",
    ),
]
