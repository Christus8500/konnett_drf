import hashlib
import logging
import time

from django.conf import settings
from django.db import transaction, IntegrityError
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import mixins, viewsets, generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.throttling import ScopedRateThrottle

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from apps.core.utils import FORBIDDEN, THROTTLED, UNAUTHORIZED, VALIDATION_ERROR, get_cache, set_cache

from apps.accounts.serializers import (
    ErrorResponseSerializer,
    LoginResponseSerializer,
    MessageResponseSerializer,
    RegisterResponseSerializer,
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

logger = logging.getLogger(__name__)


def _client_ip(request):
    # PythonAnywhere's load balancer puts the real client IP in X-Real-IP.
    # Falls back to REMOTE_ADDR for local development.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "unknown")


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
@extend_schema_view(
    list=extend_schema(
        tags=["Users (admin)"],
        summary="List all users",
        description="Returns all users. Cached. Admin only.",
        responses={
            200: UserSerializer(many=True),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
        },
    ),
    retrieve=extend_schema(
        tags=["Users (admin)"],
        summary="Retrieve a user",
        responses={
            200: UserSerializer,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: OpenApiResponse(description="User not found."),
        },
    ),
    destroy=extend_schema(
        tags=["Users (admin)"],
        summary="Delete a user",
        responses={
            204: OpenApiResponse(description="User deleted."),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: OpenApiResponse(description="User not found."),
        },
    ),
)
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
            logger.debug("Admin user list served from cache")
            return Response(cached_data)

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        set_cache(cache_key, serializer.data,
                  timeout=settings.BIG_CACHE_TIMEOUT)

        return Response(serializer.data)

    def perform_destroy(self, instance):
        # Audit trail: who deleted whom.
        logger.warning(
            "User deleted by admin admin_id=%s deleted_user_id=%s",
            self.request.user.pk,
            instance.pk,
        )
        super().perform_destroy(instance)


# RegisterView: A view for handling user registration requests. Accessible by any user.
# NOTE: the decorator is on the class (not on create()) because spectacular
# resolves the HTTP-method handler (post), and create() is only called by it.
@extend_schema(
    tags=["Auth"],
    summary="Register a new user",
    description=(
        "Creates a user, returns JWT tokens, and queues an account "
        "verification email."
    ),
    request=RegisterSerializer,
    responses={
        201: RegisterResponseSerializer,
        400: VALIDATION_ERROR,
    },
)
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
        transaction.on_commit(
            lambda: logger.info(
                "User registered user_id=%s verification_outbox_id=%s",
                user.pk,
                email.pk,
            )
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
        tags=["Auth"],
        summary="Log in",
        description="Authenticates with credentials and returns JWT tokens.",
        request=LoginSerializer,
        responses={
            200: LoginResponseSerializer,
            400: OpenApiResponse(description="Invalid credentials or malformed request."),
        },
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            # Don't log the submitted email/password.
            logger.warning("Failed login attempt ip=%s", _client_ip(request))
            raise

        user = serializer.validated_data["user"]

        refresh = RefreshToken.for_user(user)

        logger.info("User logged in user_id=%s", user.pk)

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


# UserView: A view for retrieving the currently authenticated user's information. Only accessible by authenticated users.
@extend_schema(
    tags=["Users"],
    summary="Get current user",
    description="Returns the currently authenticated user. Cached.",
    responses={200: UserSerializer, 401: UNAUTHORIZED},
)
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
            logger.debug("Current user served from cache user_id=%s", user_id)
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_verification"

    @extend_schema(
        tags=["Auth"],
        summary="Verify email address",
        description="Confirms a user's email using the link sent after registration.",
        parameters=[
            OpenApiParameter(
                name="uid",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="URL-safe base64 encoded user ID.",
            ),
            OpenApiParameter(
                name="token",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Verification token.",
            ),
        ],
        responses={
            200: MessageResponseSerializer,
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request):
        uid = request.query_params.get("uid")
        token = request.query_params.get("token")

        if not uid or not token:
            logger.warning(
                "Email verification missing params ip=%s", _client_ip(request)
            )
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
            logger.warning(
                "Email verification with unknown/malformed uid ip=%s",
                _client_ip(request),
            )
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
            logger.warning(
                "Email verification with invalid/expired token user_id=%s ip=%s",
                user.pk,
                _client_ip(request),
            )
            return Response(
                {"error": "Invalid or expired verification link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.email_verified = True

        user.save(update_fields=["email_verified", "updated_at"])

        logger.info("Email verified user_id=%s", user.pk)

        return Response(
            {"message": "Email verified successfully."},
            status=status.HTTP_200_OK,
        )


# ---------- Password reset ----------
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(
        tags=["Password"],
        summary="Request a password reset email",
        description=(
            "Always returns 200 whether or not the account exists, so that "
            "registered emails cannot be enumerated."
        ),
        request=PasswordResetRequestSerializer,
        responses={
            200: MessageResponseSerializer,
            400: VALIDATION_ERROR,
            429: THROTTLED,
        },
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if user:
            _queue_password_reset(user)
        else:
            # Server-side only; the client response is identical either way.
            # Email intentionally not logged.
            logger.info(
                "Password reset requested for unknown/inactive account ip=%s",
                _client_ip(request),
            )

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

    @extend_schema(
        tags=["Password"],
        summary="Request a password reset email (authenticated)",
        description="Sends a reset link to the authenticated user's email. No request body.",
        request=None,
        responses={
            200: MessageResponseSerializer,
            401: UNAUTHORIZED,
            429: THROTTLED,
        },
    )
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

    @extend_schema(
        tags=["Password"],
        summary="Confirm a password reset",
        description="Sets a new password using the uid/token from the reset email.",
        request=PasswordResetConfirmSerializer,
        responses={
            200: MessageResponseSerializer,
            400: OpenApiResponse(description="Invalid/expired token or weak password."),
            429: THROTTLED,
        },
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            logger.warning(
                "Password reset confirm failed validation ip=%s",
                _client_ip(request),
            )
            raise
        user = serializer.save()

        # Notify the user in their mailbox.
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

    @extend_schema(
        tags=["Email change"],
        summary="Request an email address change",
        description=(
            "Sends a confirmation link to the new address and a notice to "
            "the current address."
        ),
        request=EmailChangeRequestSerializer,
        responses={
            200: MessageResponseSerializer,
            400: VALIDATION_ERROR,
            401: UNAUTHORIZED,
            429: THROTTLED,
        },
    )
    def post(self, request):
        serializer = EmailChangeRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = request.user
        new_email = serializer.validated_data["new_email"]

        bucket = int(time.time() // 300)
        email_hash = hashlib.sha256(
            new_email.lower().encode()).hexdigest()[:16]
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

        # Only the hash of the new address is logged, never the address itself.
        logger.info(
            "Email change requested user_id=%s new_email_hash=%s "
            "confirm_outbox_id=%s (created=%s) notice_outbox_id=%s (created=%s)",
            user.pk,
            email_hash,
            confirm_mail.pk,
            confirm_mail.created_at,
            notice_mail.pk,
            notice_mail.created_at,
        )

        return Response(
            {"message": "A confirmation link was sent to your new email address."},
            status=status.HTTP_200_OK,
        )


class EmailChangeConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_change"

    @extend_schema(
        tags=["Email change"],
        summary="Confirm an email address change",
        description="Applies the pending email change using the token from the confirmation email.",
        request=EmailChangeConfirmSerializer,
        responses={
            200: MessageResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "Invalid/expired token (field errors), or the email is "
                    "already taken (`{\"error\": \"Email already exists.\"}`)."
                )
            ),
            429: THROTTLED,
        },
    )
    def post(self, request):
        serializer = EmailChangeConfirmSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            logger.warning(
                "Email change confirm failed validation ip=%s",
                _client_ip(request),
            )
            raise
        try:
            serializer.save()
        except IntegrityError:  # race with another signup using the same email
            logger.warning(
                "Email change confirm hit IntegrityError (email already taken) ip=%s",
                _client_ip(request),
            )
            return Response(
                {"error": "Email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        logger.info("Email change confirmed ip=%s", _client_ip(request))
        return Response(
            {"message": "Email updated successfully."},
            status=status.HTTP_200_OK,
        )
