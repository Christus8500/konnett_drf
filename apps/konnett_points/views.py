from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from rest_framework import generics, mixins, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated, AllowAny
from rest_framework.exceptions import ValidationError

from apps.core.utils import generate_reference
from apps.core.constants import WITHDRAWAL_REFERENCE_PREFIX
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

# Create your views here.


class UserWalletView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPointWalletSerializer

    def get_object(self):
        return self.request.user.point_wallet


class UserTransactionView(generics.ListAPIView):
    serializer_class = PointTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            PointTransaction.objects.filter(wallet=self.request.user.point_wallet)
            .select_related("wallet")
            .order_by("-created_at")
        )


class PointPurchaseView(generics.CreateAPIView):
    serializer_class = PointPurchaseSerializer
    permission_classes = [IsCustomer]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        purchase = create_point_purchase_record(
            customer=request.user.customer_profile,
            money_amount=serializer.validated_data["money_amount"],
        )

        response_serializer = self.get_serializer(purchase)
        headers = self.get_success_headers(response_serializer.data)

        return Response(
            response_serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class PointPurchaseVerificationView(APIView):
    permission_classes = [AllowAny]
    http_method_names = ["post"]

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

        purchase = (
            PointPurchase.objects.select_for_update()
            .select_related(
                "customer__user",
            )
            .filter(payment_reference=payment_reference)
            .first()
        )

        if not purchase:
            return Response(
                {"detail": "Point purchase not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase.status == PaymentStatus.SUCCESSFUL:
            return Response(
                {"detail": "Purchase has already been processed."},
                status=status.HTTP_200_OK,
            )

        if payment_status == PaymentStatus.FAILED:
            update_purchase_status(
                purchase,
                PaymentStatus.FAILED,
            )
            return Response(
                {"detail": "Purchase marked as failed."},
                status=status.HTTP_200_OK,
            )

        if payment_status != PaymentStatus.SUCCESSFUL:
            return Response(
                {"detail": "Unsupported payment status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        wallet = PointWallet.objects.select_for_update().get(
            user=purchase.customer.user
        )

        update_purchase_status(
            purchase,
            PaymentStatus.SUCCESSFUL,
            purchased_at=purchased_at,
        )
        credit_available_points(
            wallet,
            purchase.points,
        )
        create_point_transaction(
            wallet=wallet,
            points=purchase.points,
            transaction_type=TransactionType.PURCHASE,
            purchase=purchase,
        )

        return Response(
            {
                "detail": "Point purchase verified successfully.",
                "purchase_reference": purchase.payment_reference,
                "points": purchase.points,
            },
            status=status.HTTP_200_OK,
        )


class WithdrawalRequestView(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    generics.GenericAPIView,
):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = WithdrawalRequestSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsVerifiedProvider()]

        return [(IsAdminUser | IsVerifiedProvider)()]

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if "pk" in kwargs:
            return self.retrieve(request, *args, **kwargs)

        return self.list(request, *args, **kwargs)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = request.user.provider_profile

        minimum_withdraw_points = 1000
        points_to_withdraw = serializer.validated_data["points"]

        if points_to_withdraw < minimum_withdraw_points:
            raise ValidationError({"points": "Minimum points to withdraw is 1000."})

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

    def get_queryset(self):
        if self.request.user.is_staff:
            return self.queryset.filter(status=WithdrawalStatus.PENDING)

        if self.request.user.role == UserRole.PROVIDER:
            return self.queryset.filter(
                provider=self.request.user.provider_profile
            ).order_by("-created_at")

        return self.queryset.none()


class WithdrawalApproveView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = WithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        withdrawal = (
            WithdrawalRequest.objects.select_for_update()
            .select_related("provider__user")
            .get(pk=kwargs["pk"])
        )

        if withdrawal.status != WithdrawalStatus.PENDING:
            return Response(
                {"detail": ("Only pending withdrawals can be approved.")},
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


class WithdrawalRejectView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = WithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        withdrawal = (
            WithdrawalRequest.objects.select_for_update()
            .select_related("provider__user")
            .get(pk=kwargs["pk"])
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
