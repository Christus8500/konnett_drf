from django.urls import path, include

from rest_framework.routers import DefaultRouter

from apps.konnett_points.views import (
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

router = DefaultRouter()
router.register(
    "",
    ApprovedWithdrawalRequestViewset,
    basename="approved-withdrawals",
)

urlpatterns = [
    # User Wallet
    path("wallet/", UserWalletView.as_view(), name="user-wallet"),
    # User Transactions
    path(
        "transactions/", UserTransactionView.as_view(), name="user-wallet-transactions"
    ),
    # Point Purchase
    path("purchase/", PointPurchaseView.as_view(), name="purchase-konnett-points"),
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
    path("approved_withdrawals/", include(router.urls)),
    path(
        "approved_withdrawals/<uuid:pk>/paid/",
        ApprovedWithdrawalRequestPaidView.as_view(),
        name="approved-withdrawal-paid",
    ),
]
