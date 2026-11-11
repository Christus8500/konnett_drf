import hashlib
import time

from django.conf import settings
from django.db import transaction, IntegrityError
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import mixins, viewsets, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.throttling import ScopedRateThrottle

from drf_spectacular.utils import extend_schema

from apps.core.utils import get_cache, set_cache

from apps.accounts.serializers import (
    LoginResponseSerializer,
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    EmailChangeRequestSerializer,
    EmailChangeConfirmSerializer,
)
from apps.accounts.models import User

from apps.mails.services import create_mailbox_message, queue_email
from apps.mails.tasks import process_email_outbox


# Create your views here.
def _queue_password_reset(user):
    # Time bucket: repeated requests within 5 minutes collapse into one email,
    # while a later request is allowed to send a fresh one.
    bucket = int(time.time() // 300)
    outbox_email, _ = queue_email(
        idempotency_key=f"password-reset:{user.pk}:{bucket}",
        recipient=user.email,
        email_type="password_reset",
        payload={"user_id": str(user.pk)},
    )
    transaction.on_commit(
        lambda email_id=outbox_email.pk: process_email_outbox.delay(email_id)
    )


# UserViewSet: A viewset that allows listing, retrieving, updating, and deleting user instances. Only accessible by admin users.
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["get", "delete"]

    def list(self, request, *args, **kwargs):
        cache_key = "admin:users"

        cached_data = get_cache(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        set_cache(cache_key, serializer.data, timeout=settings.BIG_CACHE_TIMEOUT)

        return Response(serializer.data)


# RegisterView: A view for handling user registration requests. Only accessible by any user.
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    # Overriding create() to handle user registration. It validates the incoming data, creates a new user instance, generates JWT tokens for the user, and returns a response with the created user's data and tokens.
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)

        transaction.on_commit(
            lambda: create_mailbox_message(
                user=user,
                subject="Account Created",
                body="Your account was created successfully",
            )
        )

        # QUeue verification email after the transaction is committed
        email, _ = queue_email(
            idempotency_key=f"account-verification:{user.pk}",
            recipient=user.email,
            email_type="account_verification",
            payload={"user_pk": str(user.pk)},
        )

        transaction.on_commit(
            lambda email_id=email.pk: process_email_outbox.delay(email_id)
        )

        return Response(
            {
                "message": "Registration successful.",
                "user": UserSerializer(user).data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )


# LoginView: A view for handling user login requests. Only accessible by any user.
class LoginView(APIView):
    permission_classes = [AllowAny]

    # Overriding post() to handle user login. It validates the incoming data, authenticates the user, generates JWT tokens for the authenticated user, and returns a response with the user's data and tokens.
    @extend_schema(
        request=LoginSerializer,
        responses=LoginResponseSerializer,
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


# UserView: A view for retrieving the currently authenticated user's information. Only accessible by authenticated users.
class UserView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = f"user:{user_id}"

        cached_data = get_cache(cache_key)

        if cached_data is not None:
            return Response(cached_data)

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        set_cache(
            cache_key,
            serializer.data,
            timeout=settings.BIG_CACHE_TIMEOUT,
        )

        return Response(serializer.data)


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        uid = request.query_params.get("uid")
        token = request.query_params.get("token")

        if not uid or not token:
            return Response(
                {"error": "Invalid verification link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user_id = force_str(urlsafe_base64_decode(uid))

            user = User.objects.get(pk=user_id)

        except (
            TypeError,
            ValueError,
            OverflowError,
            DjangoValidationError,
            User.DoesNotExist,
        ):
            return Response(
                {"error": "Invalid verification link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.email_verified:
            return Response(
                {"message": "Email is already verified."},
                status=status.HTTP_200_OK,
            )

        if not default_token_generator.check_token(
            user,
            token,
        ):
            return Response(
                {"error": "Invalid or expired verification link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.email_verified = True

        user.save(update_fields=["email_verified"])

        return Response(
            {"message": "Email verified successfully."},
            status=status.HTTP_200_OK,
        )


# ---------- Password reset ----------
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetRequestSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if user:
            _queue_password_reset(user)

        # Same response whether or not the account exists, so emails can't be enumerated.
        return Response(
            {
                "message": "If an account with that email exists, a reset link has been sent."
            },
            status=status.HTTP_200_OK,
        )


class AuthenticatedPasswordResetView(APIView):
    """Logged-in user asks for a reset link from settings. No email input needed."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(request=None, responses={200: None})
    def post(self, request):
        _queue_password_reset(request.user)
        return Response(
            {"message": "A reset link was sent to your email address."},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Optional: notify the user in their mailbox.
        create_mailbox_message(
            user=user,
            subject="Password changed",
            body="Your password was changed successfully.",
        )

        return Response(
            {"message": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )


# ---------- Email change ----------
class EmailChangeRequestView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_change"

    @extend_schema(request=EmailChangeRequestSerializer, responses={200: None})
    def post(self, request):
        serializer = EmailChangeRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = request.user
        new_email = serializer.validated_data["new_email"]

        bucket = int(time.time() // 300)
        email_hash = hashlib.sha256(new_email.lower().encode()).hexdigest()[:16]
        key_suffix = f"{user.pk}:{email_hash}:{bucket}"

        with transaction.atomic():
            confirm_mail, _ = queue_email(
                idempotency_key=f"email-change:{key_suffix}",
                recipient=new_email,
                email_type="email_change",
                payload={"user_id": str(user.pk), "new_email": new_email},
            )
            notice_mail, _ = queue_email(
                idempotency_key=f"email-change-notice:{key_suffix}",
                recipient=user.email,
                email_type="email_change_notice",
                payload={"user_id": str(user.pk), "new_email": new_email},
            )
            for mail_obj in (confirm_mail, notice_mail):
                transaction.on_commit(
                    lambda eid=mail_obj.pk: process_email_outbox.delay(eid)
                )

        return Response(
            {"message": "A confirmation link was sent to your new email address."},
            status=status.HTTP_200_OK,
        )


class EmailChangeConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_change"

    @extend_schema(request=EmailChangeConfirmSerializer, responses={200: None})
    def post(self, request):
        serializer = EmailChangeConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except IntegrityError:  # race with another signup using the same email
            return Response(
                {"error": "Email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"message": "Email updated successfully."},
            status=status.HTTP_200_OK,
        )
