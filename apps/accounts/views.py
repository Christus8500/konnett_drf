from django.conf import settings
from django.db import transaction
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from rest_framework import mixins, viewsets, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny

from drf_spectacular.utils import extend_schema

from apps.core.utils import get_cache, set_cache

from apps.accounts.serializers import (
    LoginResponseSerializer,
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
)
from apps.accounts.models import User
from apps.accounts.utils import send_verification_email

from apps.mails.services import create_mailbox_message


# Create your views here.
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

        send_verification_email(user)

        create_mailbox_message(
            user=user,
            subject="Account Created",
            body="Your account was created succesfully",
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
