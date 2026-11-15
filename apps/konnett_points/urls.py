from django.urls import path, include

from rest_framework.routers import SimpleRouter

from apps.konnett_points.views import (
    PlatformFeeEntryViewSet,
    UserWalletView,
    UserTransactionView,
    PointPurchaseView,
    PointPurchaseVerificationView,
    WithdrawalRequestListCreateView,
    WithdrawalRequestRetrieveView,
    WithdrawalApproveView,
    WithdrawalRejectView,
    ApprovedWithdrawalRequestViewset,
    ApprovedWithdrawalRequestPaidView,
)

# Existing behaviour: list/retrieve at /approved_withdrawals/
approved_router = SimpleRouter()
approved_router.register(
    "",
    ApprovedWithdrawalRequestViewset,
    basename="approved-withdrawals",
)

# New: /platform-fees/
fees_router = SimpleRouter()
fees_router.register(
    "",
    PlatformFeeEntryViewSet,
    basename="platform-fee",
)

urlpatterns = [
    # User Wallet
    path("wallet/", UserWalletView.as_view(), name="user-wallet"),
    # User Transactions
    path(
        "transactions/", UserTransactionView.as_view(), name="user-wallet-transactions"
    ),
    # Point Purchase
    path("purchase/", PointPurchaseView.as_view(),
         name="purchase-konnett-points"),
    # Point Purchase Verification
    path(
        "purchase/verify/",
        PointPurchaseVerificationView.as_view(),
        name="verify-purchase-konnett-points",
    ),
    # Withdrawal Requests
    path(
        "withdrawals/",
        WithdrawalRequestListCreateView.as_view(),
        name="withdrawal-list-create",
    ),
    path(
        "withdrawals/<uuid:pk>/",
        WithdrawalRequestRetrieveView.as_view(),
        name="withdrawal-retrieve",
    ),
    path(
        "withdrawals/<uuid:pk>/approve/",
        WithdrawalApproveView.as_view(),
        name="withdrawal-approve",
    ),
    path(
        "withdrawals/<uuid:pk>/reject/",
        WithdrawalRejectView.as_view(),
        name="withdrawal-reject",
    ),
    # Approved withdrawals: the specific "paid" route goes BEFORE the router include
    path(
        "approved_withdrawals/<uuid:pk>/paid/",
        ApprovedWithdrawalRequestPaidView.as_view(),
        name="approved-withdrawal-paid",
    ),
    path("approved_withdrawals/", include(approved_router.urls)),
    # Platform fees (admin only)
    path("platform-fees/", include(fees_router.urls)),
]
