import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import generics, mixins, status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated, AllowAny
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.throttling import UserRateThrottle, ScopedRateThrottle

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from apps.core.utils import (
    generate_reference,
    get_cache,
    set_cache,
    versioned_cache_key,
)
from apps.core.constants import WITHDRAWAL_REFERENCE_PREFIX
from apps.core.choices import UserRole, PaymentStatus, TransactionType, WithdrawalStatus
from apps.core.permissions import IsCustomer, IsVerifiedProvider

from apps.konnett_points.models import (
    PointWallet,
    PointPurchase,
    PointTransaction,
    WithdrawalRequest,
    ApprovedWithdrawalRequest,
)
from apps.konnett_points.serializers import (
    AdminWithdrawalRequestSerializer,
    ApprovedWithdrawalRequestSerializer,
    PointPurchaseSerializer,
    PointTransactionSerializer,
    UserPointWalletSerializer,
    WithdrawalRejectSerializer,
    WithdrawalRequestSerializer,
)
from apps.konnett_points.utils import (
    create_point_purchase_record,
    create_point_transaction,
    credit_available_points,
    deduct_locked_points,
    lock_points,
    unlock_points,
    update_purchase_status,
    verify_webhook_signature,
)
from apps.konnett_points.filters import PointTransactionFilter, WithdrawalRequestFilter
from apps.konnett_points.notifications import (
    create_point_purchase_initiated_notification,
    create_point_purchase_successful_notification,
    create_point_purchase_failed_notification,
    create_withdrawal_request_received_notification,
    queue_withdrawal_email,
)
from apps.konnett_points.cache import (
    TRANSACTIONS_SCOPE,
    WITHDRAWALS_ADMIN_OWNER,
    WITHDRAWALS_ADMIN_SCOPE,
    WITHDRAWALS_USER_SCOPE,
)

from apps.mails.services import queue_email
from apps.mails.tasks import process_email_outbox

# Create your views here.


class CachedListMixin:
    """
    Caches list responses (paginated or not) under a per-owner version key.
    Changing the owner's data bumps the version, which makes every old page
    unreachable at once. Move this to apps/core if you want to reuse it.
    """

    cache_timeout = None

    def get_cache_scope(self, request):
        raise NotImplementedError

    def list(self, request, *args, **kwargs):
        scope, owner_id = self.get_cache_scope(request)
        key = versioned_cache_key(scope, owner_id, request.query_params)

        data = get_cache(key)
        if data is None:
            queryset = self.filter_queryset(self.get_queryset())
            page = self.paginate_queryset(queryset)  # 404 for an invalid page
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                data = self.get_paginated_response(serializer.data).data
            else:
                data = self.get_serializer(queryset, many=True).data
            set_cache(key, data, timeout=self.cache_timeout)

        return Response(data)


# UserWalletView retrieves the authenticated user's PointWallet information.
class UserWalletView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPointWalletSerializer

    def get_object(self):
        # 404 instead of a 500 when the user has no wallet
        return get_object_or_404(
            PointWallet.objects.select_related("user"), user=self.request.user
        )


# UserTransactionView retrieves the authenticated user's PointTransaction history.
class UserTransactionView(CachedListMixin, generics.ListAPIView):
    serializer_class = PointTransactionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PointTransactionFilter
    ordering_fields = [
        "created_at",
        "points",
    ]  # was "processed_at", which doesn't exist
    ordering = ["-created_at"]
    throttle_classes = [UserRateThrottle]
    cache_timeout = settings.MEDIUM_CACHE_TIMEOUT

    def get_cache_scope(self, request):
        return TRANSACTIONS_SCOPE, request.user.id

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PointTransaction.objects.none()

        return PointTransaction.objects.filter(
            wallet__user=self.request.user
        ).select_related("wallet__user")


# PointPurchaseView allows customers to create a new PointPurchase record.
class PointPurchaseView(generics.CreateAPIView):
    serializer_class = PointPurchaseSerializer
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "point_purchase"

    @transaction.atomic
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

        # Notify user of initiated purchase
        transaction.on_commit(
            lambda: create_point_purchase_initiated_notification(
                user=purchase.customer.user, purchase=purchase
            )
        )

        return Response(
            response_serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


# Maps the provider's status strings to your PaymentStatus values.
# Check the provider's docs for the exact strings they send.
PROVIDER_STATUS_MAP = {
    "successful": PaymentStatus.SUCCESSFUL,
    "success": PaymentStatus.SUCCESSFUL,
    "failed": PaymentStatus.FAILED,
}


# PointPurchaseVerificationView handles the verification of point purchases via a webhook from the payment provider.
class PointPurchaseVerificationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # a webhook is never a logged-in session
    http_method_names = ["post"]

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiTypes.OBJECT,
            401: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @transaction.atomic
    def post(self, request):
        # Must run BEFORE request.data is read: parsing the body consumes the
        # stream, and request.body then raises.
        if not verify_webhook_signature(request):
            return Response(
                {"detail": "Invalid webhook signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        data = request.data
        payment_reference = data.get("txRef")
        payment_status = PROVIDER_STATUS_MAP.get(str(data.get("status", "")).lower())
        payment_amount = data.get("amount")

        if not payment_reference:
            return Response(
                {"detail": "Payment reference is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if payment_status is None:
            return Response(
                {"detail": "Unsupported payment status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            purchased_at = parse_datetime(str(data.get("createdAt") or ""))
        except ValueError:
            purchased_at = None
        if purchased_at is not None and timezone.is_naive(purchased_at):
            purchased_at = timezone.make_aware(purchased_at)
        purchased_at = purchased_at or timezone.now()

        # Lock the purchase so concurrent webhook deliveries can't both process it.
        purchase = (
            PointPurchase.objects.select_for_update(of=("self",))
            .select_related("customer__user")
            .filter(payment_reference=payment_reference)
            .first()
        )
        if purchase is None:
            return Response(
                {"detail": "Point purchase not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # A successful purchase must never be credited twice.
        if purchase.status == PaymentStatus.SUCCESSFUL:
            return Response(
                {"detail": "Purchase has already been processed."},
                status=status.HTTP_200_OK,
            )

        # Handle failed payments.
        if payment_status == PaymentStatus.FAILED:
            if purchase.status == PaymentStatus.FAILED:
                return Response(
                    {"detail": "Purchase already marked as failed."},
                    status=status.HTTP_200_OK,
                )

            update_purchase_status(purchase, PaymentStatus.FAILED)

            email, _ = queue_email(
                idempotency_key=f"point-purchase-failed:{purchase.pk}",
                recipient=purchase.customer.user.email,
                email_type="point_purchase_failed",
                payload={"purchase_pk": str(purchase.pk)},
            )
            transaction.on_commit(
                lambda: create_point_purchase_failed_notification(
                    user=purchase.customer.user, purchase=purchase
                ),
                robust=True,
            )
            transaction.on_commit(
                lambda email_id=email.pk: process_email_outbox.delay(email_id),
                robust=True,
            )
            return Response(
                {"detail": "Purchase marked as failed."},
                status=status.HTTP_200_OK,
            )

        # ---- successful payment ----
        if payment_amount is None:
            return Response(
                {"detail": "Payment amount is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        wallet = get_object_or_404(
            PointWallet.objects.select_for_update(), user_id=purchase.customer.user_id
        )

        update_purchase_status(
            purchase, PaymentStatus.SUCCESSFUL, purchased_at=purchased_at
        )
        credit_available_points(wallet, purchase.credited_points)
        create_point_transaction(
            wallet=wallet,
            points=purchase.credited_points,
            transaction_type=TransactionType.PURCHASE,
            purchase=purchase,
        )

        # Same DB transaction as the credit, so both succeed or fail together.
        email, _ = queue_email(
            idempotency_key=f"point-purchase-success:{purchase.pk}",
            recipient=purchase.customer.user.email,
            email_type="point_purchase_successful",
            payload={"purchase_pk": str(purchase.pk)},
        )
        transaction.on_commit(
            lambda: create_point_purchase_successful_notification(
                user=purchase.customer.user, purchase=purchase
            ),
            robust=True,
        )
        # The periodic task is the backup if Celery can't be reached here.
        transaction.on_commit(
            lambda email_id=email.pk: process_email_outbox.delay(email_id),
            robust=True,
        )

        return Response(
            {
                "detail": "Point purchase verified successfully.",
                "purchase_reference": purchase.payment_reference,
                "points": purchase.credited_points,
            },
            status=status.HTTP_200_OK,
        )


def visible_withdrawals(user):
    """Withdrawal requests this user is allowed to see."""
    if user.is_staff:
        return WithdrawalRequest.objects.select_related("user", "processed_by")
    if user.role in (UserRole.PROVIDER, UserRole.CUSTOMER):
        return WithdrawalRequest.objects.filter(user=user)
    return WithdrawalRequest.objects.none()


# WithdrawalRequestListCreateView handles the creation and listing of withdrawal requests for providers.
class WithdrawalRequestListCreateView(
    CachedListMixin,
    mixins.CreateModelMixin,
    generics.GenericAPIView,
):
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = WithdrawalRequestFilter
    ordering_fields = ["created_at", "points"]
    ordering = ["-created_at"]
    throttle_scope = "withdrawals"
    cache_timeout = settings.SMALL_CACHE_TIMEOUT

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsVerifiedProvider() | IsCustomer()]
        return [IsAuthenticated()]

    def get_throttles(self):
        if self.request.method == "GET":
            return [UserRateThrottle()]
        return [ScopedRateThrottle()]

    def get_serializer_class(self):
        if self.request.method == "GET" and self.request.user.is_staff:
            return AdminWithdrawalRequestSerializer
        return WithdrawalRequestSerializer

    def get_cache_scope(self, request):
        if request.user.is_staff:
            return WITHDRAWALS_ADMIN_SCOPE, WITHDRAWALS_ADMIN_OWNER
        return WITHDRAWALS_USER_SCOPE, request.user.id

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WithdrawalRequest.objects.none()

        queryset = visible_withdrawals(self.request.user)
        if self.request.user.is_staff:
            return queryset.filter(status=WithdrawalStatus.PENDING)
        return queryset

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)  # also enforces the minimum points

        user = request.user
        points_to_withdraw = serializer.validated_data["points"]

        bank_details = {
            "account_number": user.account_number,
            "account_name": user.account_name,
            "bank_name": user.bank_name,
        }
        if not (
            re.fullmatch(r"\d{10}", user.account_number or "")
            and user.account_name
            and user.bank_name
        ):
            raise ValidationError(
                {
                    "bank_details": "Add valid bank details to your profile before requesting a withdrawal."
                }
            )

        # Locking the wallet also serialises this user's requests, so the
        # pending check below can't race.
        wallet = get_object_or_404(PointWallet.objects.select_for_update(), user=user)

        # Matches the one_pending_withdrawal_per_user constraint. Remove this
        # check if you dropped that constraint.
        if WithdrawalRequest.objects.filter(
            user=user, status=WithdrawalStatus.PENDING
        ).exists():
            raise ValidationError(
                {"detail": "You already have a pending withdrawal request."}
            )

        if wallet.available_points < points_to_withdraw:
            raise ValidationError({"points": "Insufficient available points."})

        lock_points(wallet, points_to_withdraw)

        # Snapshot the bank details: later edits to the User can't redirect this payout
        withdrawal = serializer.save(
            user=user,
            withdrawal_reference=generate_reference(WITHDRAWAL_REFERENCE_PREFIX),
            **bank_details,
        )

        create_point_transaction(
            wallet=wallet,
            points=points_to_withdraw,
            transaction_type=TransactionType.LOCK,
            withdrawal_request=withdrawal,
        )

        transaction.on_commit(
            lambda: create_withdrawal_request_received_notification(
                user=user, withdrawal=withdrawal
            ),
            robust=True,
        )

        return Response(
            self.get_serializer(withdrawal).data,
            status=status.HTTP_201_CREATED,
        )


# WithdrawalRequestRetrieveView retrieves a specific withdrawal request based on the user ID.
# Admins can retrieve any withdrawal request, while providers can only retrieve their own requests.
class WithdrawalRequestRetrieveView(
    mixins.RetrieveModelMixin,
    generics.GenericAPIView,
):
    # Access is enforced by the queryset: admins see everything, providers and
    # customers only their own requests, so IsAuthenticated is enough.
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.user.is_staff:
            return AdminWithdrawalRequestSerializer
        return WithdrawalRequestSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WithdrawalRequest.objects.none()
        return visible_withdrawals(self.request.user)

    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)


# WithdrawalApproveView handles the approval of pending withdrawal requests by admins.
class WithdrawalApproveView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = AdminWithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        withdrawal = get_object_or_404(
            WithdrawalRequest.objects.select_for_update(of=("self",)).select_related(
                "user"
            ),
            pk=kwargs["pk"],
        )

        if withdrawal.status != WithdrawalStatus.PENDING:
            return Response(
                {"detail": "Only pending withdrawals can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wallet = get_object_or_404(
            PointWallet.objects.select_for_update(), user_id=withdrawal.user_id
        )

        if wallet.locked_points < withdrawal.points:
            return Response(
                {
                    "detail": "The user does not have enough locked points for this withdrawal."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # locked_points -> deducted
        deduct_locked_points(wallet, withdrawal.points)

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
            update_fields=["status", "processed_by", "processed_at", "updated_at"]
        )

        # Explicit now, instead of a post_save signal. The OneToOne guards against duplicates.
        ApprovedWithdrawalRequest.objects.create(withdrawal=withdrawal)

        queue_withdrawal_email(withdrawal, WithdrawalStatus.APPROVED)

        return Response(self.get_serializer(withdrawal).data, status=status.HTTP_200_OK)


# WithdrawalRejectView handles the rejection of pending withdrawal requests by admins.
class WithdrawalRejectView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = AdminWithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        input_serializer = WithdrawalRejectSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        reject_reason = input_serializer.validated_data["reject_reason"]

        withdrawal = get_object_or_404(
            WithdrawalRequest.objects.select_for_update(of=("self",)).select_related(
                "user"
            ),
            pk=kwargs["pk"],
        )

        if withdrawal.status != WithdrawalStatus.PENDING:
            return Response(
                {"detail": "Only pending withdrawals can be rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wallet = get_object_or_404(
            PointWallet.objects.select_for_update(), user_id=withdrawal.user_id
        )

        if wallet.locked_points < withdrawal.points:
            return Response(
                {
                    "detail": "The user does not have enough locked points for this withdrawal."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # locked_points -> available_points
        unlock_points(wallet, withdrawal.points)

        create_point_transaction(
            wallet=wallet,
            points=withdrawal.points,
            transaction_type=TransactionType.UNLOCK,
            withdrawal_request=withdrawal,
        )

        withdrawal.status = WithdrawalStatus.REJECTED
        withdrawal.reject_reason = reject_reason
        withdrawal.processed_by = request.user
        withdrawal.processed_at = timezone.now()
        withdrawal.save(
            update_fields=[
                "status",
                "reject_reason",
                "processed_by",
                "processed_at",
                "updated_at",
            ]
        )

        queue_withdrawal_email(
            withdrawal, WithdrawalStatus.REJECTED, reject_reason=reject_reason
        )

        return Response(self.get_serializer(withdrawal).data, status=status.HTTP_200_OK)


class ApprovedWithdrawalRequestViewset(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApprovedWithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    queryset = (
        ApprovedWithdrawalRequest.objects.filter(paid=False)
        .select_related("withdrawal__user", "withdrawal__processed_by")
        .order_by("created_at")  # oldest first, so payouts go in order
    )


class ApprovedWithdrawalRequestPaidView(generics.UpdateAPIView):
    queryset = ApprovedWithdrawalRequest.objects.all()
    serializer_class = ApprovedWithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        approved_withdrawal = get_object_or_404(
            ApprovedWithdrawalRequest.objects.select_for_update(
                of=("self", "withdrawal")
            ).select_related("withdrawal__user"),
            pk=kwargs["pk"],
        )

        if approved_withdrawal.paid:
            return Response(
                {"detail": "This withdrawal has already been marked as paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        withdrawal = approved_withdrawal.withdrawal
        if withdrawal.status != WithdrawalStatus.APPROVED:
            return Response(
                {"detail": "Only approved withdrawals can be marked as paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        approved_withdrawal.paid = True
        approved_withdrawal.save(
            update_fields=["paid", "updated_at"]
        )  # model save() adds paid_on

        withdrawal.status = WithdrawalStatus.PAID
        withdrawal.save(update_fields=["status", "updated_at"])

        queue_withdrawal_email(withdrawal, WithdrawalStatus.PAID)

        return Response(self.get_serializer(approved_withdrawal).data)
