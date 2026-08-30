from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import generics, mixins, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated, AllowAny
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.throttling import UserRateThrottle, ScopedRateThrottle

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from apps.core.utils import generate_reference, get_cache, set_cache
from apps.core.constants import WITHDRAWAL_REFERENCE_PREFIX, MINIMUM_WITHDRAW_POINTS
from apps.core.choices import UserRole, PaymentStatus, TransactionType, WithdrawalStatus
from apps.core.permissions import IsCustomer, IsVerifiedProvider

from apps.konnett_points.models import (
    PointWallet,
    PointPurchase,
    PointTransaction,
    WithdrawalRequest,
)
from apps.konnett_points.serializers import (
    UserPointWalletSerializer,
    PointPurchaseSerializer,
    PointTransactionSerializer,
    WithdrawalRequestSerializer,
)
from apps.konnett_points.utils import (
    create_point_purchase_record,
    credit_available_points,
    update_purchase_status,
    create_point_transaction,
    lock_points,
    unlock_points,
    deduct_locked_points,
)
from apps.konnett_points.filters import PointTransactionFilter, WithdrawalRequestFilter

# Create your views here.


# UserWalletView retrieves the authenticated user's PointWallet information.
class UserWalletView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPointWalletSerializer

    def get_object(self):
        return PointWallet.objects.select_related("user").get(user=self.request.user)


# UserTransactionView retrieves the authenticated user's PointTransaction history.
class UserTransactionView(generics.ListAPIView):
    serializer_class = PointTransactionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PointTransactionFilter
    ordering_fields = ["processed_at"]
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PointTransaction.objects.none()

        return (
            PointTransaction.objects.filter(wallet=self.request.user.point_wallet)
            .select_related("wallet__user")
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        wallet_id = request.user.point_wallet.id

        cache_key = f"wallet:{wallet_id}:transactions:{request.GET.urlencode()}"
        cached_data = get_cache(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        set_cache(cache_key, serializer.data, timeout=settings.MEDIUM_CACHE_TIMEOUT)

        return Response(serializer.data)


# PointPurchaseView allows customers to create a new PointPurchase record.
class PointPurchaseView(generics.CreateAPIView):
    serializer_class = PointPurchaseSerializer
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "point_purchase"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        purchase = create_point_purchase_record(
            customer=request.user.customer_profile,
            money_amount=serializer.validated_data["money_amount"],
        )

        purchase = PointPurchase.objects.select_related("customer__user").get(
            pk=purchase.pk
        )

        response_serializer = self.get_serializer(purchase)
        headers = self.get_success_headers(response_serializer.data)

        return Response(
            response_serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


# PointPurchaseVerificationView handles the verification of point purchases via a webhook from the payment provider.
class PointPurchaseVerificationView(APIView):
    permission_classes = [AllowAny]
    http_method_names = ["post"]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @transaction.atomic
    def post(self, request):
        data = request.data

        # Todo IMPORTANT:
        # Implement this using your payment provider's webhook # signature/secret mechanism.
        # if not verify_webhook(request):
        #     return Response(
        #         {"detail": "Invalid webhook signature."},
        #         status=status.HTTP_401_UNAUTHORIZED,
        #     )

        payment_status = data.get("status")
        payment_reference = data.get("txRef")
        payment_amount = data.get("amount")
        purchased_at = data.get("createdAt")

        if not payment_reference:
            return Response(
                {"detail": "Payment reference is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lock the purchase record for update to prevent race conditions during verification.
        purchase = (
            PointPurchase.objects.select_for_update()
            .select_related(
                "customer__user",
            )
            .filter(payment_reference=payment_reference)
            .first()
        )

        # If the purchase record is not found, return a 404 response indicating that the point purchase was not found.
        if not purchase:
            return Response(
                {"detail": "Point purchase not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # If the purchase has already been processed successfully, return a message indicating that.
        if purchase.status == PaymentStatus.SUCCESSFUL:
            return Response(
                {"detail": "Purchase has already been processed."},
                status=status.HTTP_200_OK,
            )

        # If the payment status is "FAILED",
        # update the purchase status to "FAILED" and return a message indicating that the purchase has been marked as failed.
        if payment_status == PaymentStatus.FAILED:
            update_purchase_status(
                purchase,
                PaymentStatus.FAILED,
            )
            return Response(
                {"detail": "Purchase marked as failed."},
                status=status.HTTP_200_OK,
            )

        # If the payment status is not PaymentStatus' SUCCESSFUL',
        # return a 400 response indicating that the payment status is unsupported.
        if payment_status != PaymentStatus.SUCCESSFUL:
            return Response(
                {"detail": "Unsupported payment status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If the payment amount is provided,
        # validate it to ensure it is a valid decimal number and matches the expected amount for the purchase.
        # If the validation fails, return a 400 response with an appropriate error message.
        if payment_amount is not None:
            try:
                payment_amount = Decimal(str(payment_amount))
            except (InvalidOperation, TypeError):
                return Response(
                    {"detail": "Invalid payment amount."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if purchase.money_amount != payment_amount:
                return Response(
                    {"detail": "Payment amount does not match purchase."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # If the payment is successful and the amount is valid,
        # retrieve the user's PointWallet
        wallet = PointWallet.objects.select_for_update().get(
            user=purchase.customer.user
        )

        # If the purchase is successful, update the purchase status to "SUCCESSFUL"
        update_purchase_status(
            purchase,
            PaymentStatus.SUCCESSFUL,
            purchased_at=purchased_at,
        )
        # Credit the purchased points to the user's available points in their PointWallet
        credit_available_points(
            wallet,
            purchase.credited_points,
        )
        # Create a PointTransaction record to log the successful purchase transaction.
        create_point_transaction(
            wallet=wallet,
            points=purchase.credited_points,
            transaction_type=TransactionType.PURCHASE,
            purchase=purchase,
        )

        return Response(
            {
                "detail": "Point purchase verified successfully.",
                "purchase_reference": purchase.payment_reference,
                "points": purchase.credited_points,
            },
            status=status.HTTP_200_OK,
        )


# WithdrawalRequestListCreateView handles the creation and listing of withdrawal requests for providers.
class WithdrawalRequestListCreateView(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    generics.GenericAPIView,
):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = WithdrawalRequestSerializer    
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = WithdrawalRequestFilter

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsVerifiedProvider()]

        return [(IsAdminUser | IsVerifiedProvider)()]

    # get method handles the listing of withdrawal requests
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    # post method handles the creation of a new withdrawal request
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    # create method handles the creation of a new withdrawal request,
    # ensuring that the provider has enough available points and meets the minimum withdrawal requirement.
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = request.user.provider_profile

        minimum_withdraw_points = MINIMUM_WITHDRAW_POINTS
        points_to_withdraw = serializer.validated_data["points"]

        if points_to_withdraw < minimum_withdraw_points:
            raise ValidationError(
                {"points": f"Minimum points to withdraw is {minimum_withdraw_points}."}
            )

        wallet = PointWallet.objects.select_for_update().get(user=request.user)

        if wallet.available_points < points_to_withdraw:
            raise ValidationError({"points": "Insufficient available points."})

        lock_points(
            wallet,
            points_to_withdraw,
        )

        withdrawal = serializer.save(
            provider=provider,
            withdrawal_reference=generate_reference(WITHDRAWAL_REFERENCE_PREFIX),
        )

        create_point_transaction(
            wallet=wallet,
            points=points_to_withdraw,
            transaction_type=TransactionType.LOCK,
            withdrawal_request=withdrawal,
        )

        return Response(
            self.get_serializer(withdrawal).data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        if request.user.is_staff:
            cache_key = "withdrawal_requests:admin:pending"
        else:
            provider_id = request.user.provider_profile.id
            cache_key = f"withdrawal_requests:provider:{provider_id}:{request.GET.urlencode()}"

        cached_data = get_cache(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        set_cache(cache_key, serializer.data, timeout=settings.SMALL_CACHE_TIMEOUT)

        return Response(serializer.data)

    # get_queryset method filters the withdrawal requests based on the user's role and returns the appropriate queryset.
    # If the user is an admin, it returns all pending withdrawal requests.
    # If the user is a provider, it returns only their own withdrawal requests.
    def get_queryset(self):
        queryset = self.queryset.select_related(
            "provider__user",
            "processed_by",
        )

        if self.request.user.is_staff:
            return queryset.filter(status=WithdrawalStatus.PENDING)

        if self.request.user.role == UserRole.PROVIDER:
            return queryset.filter(
                provider=self.request.user.provider_profile
            ).order_by("-created_at")

        return queryset.none()

    def get_throttles(self):
        if self.request.method == "GET":
            return [UserRateThrottle()]
        return [ScopedRateThrottle(scope="withdrawals")]


# WithdrawalRequestRetrieveView retrieves a specific withdrawal request based on the provided ID.
# Admins can retrieve any withdrawal request, while providers can only retrieve their own requests.
class WithdrawalRequestRetrieveView(
    mixins.RetrieveModelMixin,
    generics.GenericAPIView,
):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = WithdrawalRequestSerializer

    def get_permissions(self):
        return [(IsAdminUser | IsVerifiedProvider)()]

    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def get_queryset(self):
        queryset = self.queryset.select_related(
            "provider__user",
            "processed_by",
        )

        if self.request.user.is_staff:
            return queryset

        if self.request.user.role == UserRole.PROVIDER:
            return queryset.filter(provider=self.request.user.provider_profile)

        return queryset.none()


# WithdrawalApproveView handles the approval of pending withdrawal requests by admins.
class WithdrawalApproveView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = WithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        # Lock the withdrawal request for update to prevent race conditions during approval.
        withdrawal = get_object_or_404(
            WithdrawalRequest.objects.select_for_update().select_related(
                "provider__user"
            ),
            pk=kwargs["pk"],
        )

        # If the withdrawal request is not in a pending state,
        # return a 400 response indicating that only pending withdrawals can be approved.
        if withdrawal.status != WithdrawalStatus.PENDING:
            return Response(
                {"detail": ("Only pending withdrawals can be approved.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lock the provider's PointWallet for update
        # to ensure that the available points are accurately checked and updated during the approval process.
        wallet = PointWallet.objects.select_for_update().get(
            user=withdrawal.provider.user
        )

        # If the provider does not have enough locked points for the withdrawal,
        # return a 400 response indicating that the provider does not have enough locked points for this
        if wallet.locked_points < withdrawal.points:
            return Response(
                {
                    "detail": (
                        "The provider does not have enough "
                        "locked points for this withdrawal."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Permanently remove the points from the wallet.
        #
        # locked_points -> deducted
        deduct_locked_points(
            wallet,
            withdrawal.points,
        )

        create_point_transaction(
            wallet=wallet,
            points=withdrawal.points,
            transaction_type=TransactionType.WITHDRAWAL,
            withdrawal_request=withdrawal,
        )

        withdrawal.status = WithdrawalStatus.APPROVED
        withdrawal.processed_by = request.user
        withdrawal.processed_at = timezone.now()

        withdrawal.save(
            update_fields=[
                "status",
                "processed_by",
                "processed_at",
            ]
        )

        return Response(
            self.get_serializer(withdrawal).data,
            status=status.HTTP_200_OK,
        )


# WithdrawalRejectView handles the rejection of pending withdrawal requests by admins.
class WithdrawalRejectView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = WithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        withdrawal = get_object_or_404(
            WithdrawalRequest.objects.select_for_update().select_related(
                "provider__user"
            ),
            pk=kwargs["pk"],
        )

        if withdrawal.status != WithdrawalStatus.PENDING:
            return Response(
                {"detail": ("Only pending withdrawals can be rejected.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wallet = PointWallet.objects.select_for_update().get(
            user=withdrawal.provider.user
        )

        if wallet.locked_points < withdrawal.points:
            return Response(
                {
                    "detail": (
                        "The provider does not have enough "
                        "locked points for this withdrawal."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Return the points to the provider.
        #
        # locked_points -> available_points
        unlock_points(
            wallet,
            withdrawal.points,
        )

        create_point_transaction(
            wallet=wallet,
            points=withdrawal.points,
            transaction_type=TransactionType.UNLOCK,
            withdrawal_request=withdrawal,
        )

        withdrawal.status = WithdrawalStatus.REJECTED
        withdrawal.processed_by = request.user
        withdrawal.processed_at = timezone.now()

        withdrawal.save(
            update_fields=[
                "status",
                "processed_by",
                "processed_at",
            ]
        )

        return Response(
            self.get_serializer(withdrawal).data,
            status=status.HTTP_200_OK,
        )
