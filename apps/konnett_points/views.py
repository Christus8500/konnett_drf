import logging
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
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
from rest_framework.throttling import BaseThrottle, UserRateThrottle, ScopedRateThrottle
from rest_framework.decorators import action

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view

from apps.core.utils import (
    generate_reference,
    get_cache,
    set_cache,
    versioned_cache_key,
    FORBIDDEN,
    THROTTLED,
    UNAUTHORIZED,
    VALIDATION_ERROR,
)
from apps.core.constants import WITHDRAWAL_REFERENCE_PREFIX
from apps.core.choices import PlatformFeeSource, UserRole, PaymentStatus, TransactionType, WithdrawalStatus
from apps.core.permissions import IsCustomer, IsVerifiedProvider

from apps.accounts.bank_details import bank_cooldown_ends_at

from apps.konnett_points.models import (
    PlatformFeeEntry,
    PointWallet,
    PointPurchase,
    PointTransaction,
    WithdrawalRequest,
    ApprovedWithdrawalRequest,
)
from apps.konnett_points.serializers import (
    AdminWithdrawalRequestSerializer,
    ApprovedWithdrawalRequestSerializer,
    PaymentWebhookSerializer,
    PlatformFeeEntrySerializer,
    PlatformFeeTotalSerializer,
    PointPurchaseSerializer,
    PointTransactionSerializer,
    PointsDetailResponseSerializer,
    PurchaseVerifiedResponseSerializer,
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
    record_platform_fee,
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

logger = logging.getLogger(__name__)


def _client_ip(request):
    # INFO
    # Honours REST_FRAMEWORK["NUM_PROXIES"]; set it to 1 behind Railway's proxy.
    return BaseThrottle().get_ident(request)

def _detail_response(description):
    return OpenApiResponse(response=PointsDetailResponseSerializer, description=description)


INVALID_PAGE = OpenApiResponse(description="Invalid page.")
WITHDRAWAL_NOT_FOUND = OpenApiResponse(description="Withdrawal request not found.")

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
        else:
            logger.debug("List served from cache scope=%s owner=%s", scope, owner_id)

        return Response(data)


# UserWalletView retrieves the authenticated user's PointWallet information.
@extend_schema(
    tags=["Points"],
    summary="Get my point wallet",
    responses={
        200: UserPointWalletSerializer,
        401: UNAUTHORIZED,
        404: OpenApiResponse(description="Wallet not found."),
    },
)
class UserWalletView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPointWalletSerializer

    def get_object(self):
        # 404 instead of a 500 when the user has no wallet
        return get_object_or_404(
            PointWallet.objects.select_related("user"), user=self.request.user
        )


# UserTransactionView retrieves the authenticated user's PointTransaction history.
@extend_schema(
    tags=["Points"],
    summary="List my point transactions",
    description=(
        "Paginated and cached. Supports the filter query parameters and "
        "`ordering` (`created_at`, `points`); newest first by default."
    ),
    responses={
        200: PointTransactionSerializer,
        401: UNAUTHORIZED,
        404: INVALID_PAGE,
        429: THROTTLED,
    },
)
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
@extend_schema(
    tags=["Points"],
    summary="Start a point purchase (customers)",
    description="Creates a pending purchase; points are credited when the payment webhook confirms it.",
    request=PointPurchaseSerializer,
    responses={
        201: PointPurchaseSerializer,
        400: VALIDATION_ERROR,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        429: THROTTLED,
    },
)
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

        logger.info(
            "Point purchase initiated user_id=%s purchase_id=%s reference=%s",
            request.user.pk,
            purchase.pk,
            purchase.payment_reference,
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
        tags=["Payments"],
        summary="Payment provider webhook",
        description=(
            "Called by the payment provider, not by app users. Authenticated by the "
            "provider's webhook signature (checked before the body is read), not by "
            "user credentials. Idempotent: repeated deliveries never credit twice."
        ),
        request=PaymentWebhookSerializer,
        responses={
            200: PurchaseVerifiedResponseSerializer,
            400: _detail_response(
                "Missing reference, unsupported status, or missing/invalid/mismatched amount."
            ),
            401: _detail_response("Invalid webhook signature."),
            404: _detail_response("Point purchase not found."),
        },
    )
    @transaction.atomic
    def post(self, request):
        # Must run BEFORE request.data is read: parsing the body consumes the
        # stream, and request.body then raises.
        if not verify_webhook_signature(request):
            logger.warning(
                "Payment webhook rejected: invalid signature ip=%s", _client_ip(request)
            )
            return Response(
                {"detail": "Invalid webhook signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        data = request.data
        payment_reference = data.get("txRef")
        payment_status = PROVIDER_STATUS_MAP.get(
            str(data.get("status", "")).lower())
        payment_amount = data.get("amount")

        # %r below: values from the payload are logged escaped, so they can't forge log lines.
        if not payment_reference:
            logger.warning("Payment webhook without a payment reference")
            return Response(
                {"detail": "Payment reference is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if payment_status is None:
            logger.warning(
                "Payment webhook with unsupported status reference=%.100r status=%.50r",
                payment_reference,
                data.get("status"),
            )
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
            logger.warning(
                "Payment webhook for unknown purchase reference=%.100r", payment_reference
            )
            return Response(
                {"detail": "Point purchase not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # A successful purchase must never be credited twice.
        if purchase.status == PaymentStatus.SUCCESSFUL:
            logger.info(
                "Duplicate payment webhook ignored: already successful purchase_id=%s",
                purchase.pk,
            )
            return Response(
                {"detail": "Purchase has already been processed."},
                status=status.HTTP_200_OK,
            )

        # Handle failed payments.
        if payment_status == PaymentStatus.FAILED:
            if purchase.status == PaymentStatus.FAILED:
                logger.info(
                    "Duplicate payment webhook ignored: already failed purchase_id=%s",
                    purchase.pk,
                )
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
            logger.warning(
                "Successful payment webhook without amount purchase_id=%s", purchase.pk
            )
            return Response(
                {"detail": "Payment amount is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payment_amount = Decimal(str(payment_amount))
        except (InvalidOperation, TypeError):
            logger.warning(
                "Successful payment webhook with invalid amount purchase_id=%s",
                purchase.pk,
            )
            return Response(
                {"detail": "Invalid payment amount."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if purchase.money_amount != payment_amount:
            # Money-related: this should be rare, so make it loud.
            logger.error(
                "Payment amount mismatch purchase_id=%s expected=%s received=%s",
                purchase.pk,
                purchase.money_amount,
                payment_amount,
            )
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

        record_platform_fee(
            purchase.admin_fee_points,
            PlatformFeeSource.PURCHASE_FEE,
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

        logger.info(
            "Purchase credited purchase_id=%s user_id=%s points=%s",
            purchase.pk,
            purchase.customer.user_id,
            purchase.credited_points,
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

    @extend_schema(
        tags=["Withdrawals"],
        summary="List withdrawal requests",
        description=(
            "Customers and providers see their own requests (account number masked). "
            "Staff see all PENDING requests with full bank details "
            "(`AdminWithdrawalRequest` shape). Paginated and cached."
        ),
        responses={
            200: WithdrawalRequestSerializer,
            401: UNAUTHORIZED,
            404: INVALID_PAGE,
            429: THROTTLED,
        },
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @extend_schema(
        tags=["Withdrawals"],
        summary="Request a withdrawal",
        description="Locks the points and snapshots the account's bank details.",
        request=WithdrawalRequestSerializer,
        responses={
            201: WithdrawalRequestSerializer,
            400: OpenApiResponse(description=(
                "Validation error: below minimum points, missing/invalid bank details, "
                "bank details changed within the cooldown window, a request already "
                "pending, or insufficient available points."
            )),
            401: UNAUTHORIZED, 403: FORBIDDEN, 429: THROTTLED,
        },
    )
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        # also enforces the minimum points
        serializer.is_valid(raise_exception=True)

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

        ends_at = bank_cooldown_ends_at(user)
        if ends_at is not None:
            logger.warning(
                "Withdrawal blocked by bank-change cooldown user_id=%s ends_at=%s",
                user.pk, ends_at.isoformat(),
            )
            raise ValidationError(
                {"bank_details": (
                    "You changed your bank details recently. Withdrawals are available "
                    f"again after {ends_at:%d %b %Y, %H:%M} UTC."
                )},
                code="bank_cooldown",
            )

        # Locking the wallet also serialises this user's requests, so the
        # pending check below can't race.
        wallet = get_object_or_404(
            PointWallet.objects.select_for_update(), user=user)

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
            withdrawal_reference=generate_reference(
                WITHDRAWAL_REFERENCE_PREFIX),
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

        logger.info(
            "Withdrawal requested user_id=%s withdrawal_id=%s points=%s reference=%s",
            user.pk,
            withdrawal.pk,
            points_to_withdraw,
            withdrawal.withdrawal_reference,
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

    @extend_schema(
        tags=["Withdrawals"],
        summary="Get a withdrawal request",
        description=(
            "Users can only retrieve their own requests (account number masked). "
            "Staff can retrieve any request, with full bank details."
        ),
        responses={
            200: WithdrawalRequestSerializer,
            401: UNAUTHORIZED,
            404: WITHDRAWAL_NOT_FOUND,
        },
    )
    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)


# WithdrawalApproveView handles the approval of pending withdrawal requests by admins.
class WithdrawalApproveView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = AdminWithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @extend_schema(
        tags=["Withdrawals (admin)"],
        summary="Approve a pending withdrawal",
        description=(
            "No request body. Deducts the locked points, records the transaction, "
            "queues the payout list entry and emails the user."
        ),
        request=None,
        responses={
            200: AdminWithdrawalRequestSerializer,
            400: _detail_response(
                "Not pending, or the user does not have enough locked points."
            ),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: WITHDRAWAL_NOT_FOUND,
        },
    )
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
            logger.error(
                "Withdrawal approval blocked: locked points below request "
                "withdrawal_id=%s user_id=%s locked=%s requested=%s",
                withdrawal.pk,
                withdrawal.user_id,
                wallet.locked_points,
                withdrawal.points,
            )
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
            update_fields=["status", "processed_by",
                           "processed_at", "updated_at"]
        )

        # Explicit now, instead of a post_save signal. The OneToOne guards against duplicates.
        ApprovedWithdrawalRequest.objects.create(withdrawal=withdrawal)

        queue_withdrawal_email(withdrawal, WithdrawalStatus.APPROVED)

        logger.info(
            "Withdrawal approved admin_id=%s withdrawal_id=%s user_id=%s points=%s",
            request.user.pk,
            withdrawal.pk,
            withdrawal.user_id,
            withdrawal.points,
        )

        return Response(self.get_serializer(withdrawal).data, status=status.HTTP_200_OK)


# WithdrawalRejectView handles the rejection of pending withdrawal requests by admins.
class WithdrawalRejectView(generics.UpdateAPIView):
    queryset = WithdrawalRequest.objects.all()
    serializer_class = AdminWithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]

    @extend_schema(
        tags=["Withdrawals (admin)"],
        summary="Reject a pending withdrawal",
        description="Unlocks the user's points and emails them the reason.",
        request=WithdrawalRejectSerializer,
        responses={
            200: AdminWithdrawalRequestSerializer,
            400: OpenApiResponse(
                description=(
                    "Validation error (missing `reject_reason`), not pending, or "
                    "the user does not have enough locked points."
                )
            ),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: WITHDRAWAL_NOT_FOUND,
        },
    )
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
            logger.error(
                "Withdrawal rejection blocked: locked points below request "
                "withdrawal_id=%s user_id=%s locked=%s requested=%s",
                withdrawal.pk,
                withdrawal.user_id,
                wallet.locked_points,
                withdrawal.points,
            )
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

        # The reject reason text is intentionally not logged.
        logger.info(
            "Withdrawal rejected admin_id=%s withdrawal_id=%s user_id=%s points=%s",
            request.user.pk,
            withdrawal.pk,
            withdrawal.user_id,
            withdrawal.points,
        )

        return Response(self.get_serializer(withdrawal).data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Withdrawals (admin)"],
        summary="List approved withdrawals awaiting payout",
        description="Approved withdrawals not yet marked as paid, oldest first. Paginated.",
        responses={200: ApprovedWithdrawalRequestSerializer, 401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=["Withdrawals (admin)"],
        summary="Get an approved withdrawal awaiting payout",
        description="Only unpaid entries are found; a paid one returns 404.",
        responses={
            200: ApprovedWithdrawalRequestSerializer,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: OpenApiResponse(description="Approved withdrawal not found (or already paid)."),
        },
    ),
)
class ApprovedWithdrawalRequestViewset(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApprovedWithdrawalRequestSerializer
    permission_classes = [IsAdminUser]
    queryset = (
        ApprovedWithdrawalRequest.objects.filter(paid=False)
        .select_related("withdrawal__user", "withdrawal__processed_by")
        .order_by("created_at")  # oldest first, so payouts go in order
    )


@extend_schema(
        tags=["Withdrawals (admin)"],
        summary="Mark an approved withdrawal as paid",
        description="No request body. Sets the paid flag and timestamp and emails the user.",
        request=None,
        responses={
            200: ApprovedWithdrawalRequestSerializer,
            400: _detail_response("Already paid, or the withdrawal is not approved."),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: OpenApiResponse(description="Approved withdrawal not found."),
        },
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

        logger.info(
            "Withdrawal marked paid admin_id=%s withdrawal_id=%s user_id=%s points=%s",
            request.user.pk,
            withdrawal.pk,
            withdrawal.user_id,
            withdrawal.points,
        )

        return Response(self.get_serializer(approved_withdrawal).data)


@extend_schema_view(
    list=extend_schema(
        tags=["Platform fees (admin)"],
        summary="List platform fee entries",
        description="Paginated. Filter by `source`; order by `created_at` or `points`.",
        responses={200: PlatformFeeEntrySerializer, 401: UNAUTHORIZED, 403: FORBIDDEN},
    ),
    retrieve=extend_schema(
        tags=["Platform fees (admin)"],
        summary="Get a platform fee entry",
        responses={
            200: PlatformFeeEntrySerializer,
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: OpenApiResponse(description="Fee entry not found."),
        },
    ),
)
class PlatformFeeEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PlatformFeeEntrySerializer
    permission_classes = [IsAdminUser]
    queryset = PlatformFeeEntry.objects.all()
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["source"]
    ordering_fields = ["created_at", "points"]

    @extend_schema(
        tags=["Platform fees (admin)"],
        summary="Total platform fees",
        description="Sum of fee points, overall and per source. Respects the `source` filter.",
        responses={200: PlatformFeeTotalSerializer, 401: UNAUTHORIZED, 403: FORBIDDEN},
    )
    @action(detail=False, methods=["get"])
    def total(self, request):
        qs = self.filter_queryset(self.get_queryset())
        # order_by() clears any ordering (e.g. ?ordering=created_at), which would
        # otherwise be added to the GROUP BY and split every source into many rows.
        by_source = qs.order_by().values("source").annotate(total=Sum("points"))
        return Response(
            {
                "total_points": sum(row["total"] for row in by_source),
                "by_source": {row["source"]: row["total"] for row in by_source},
            }
        )
