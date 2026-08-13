from django.urls import path

from apps.konnett_points.views import (
    UserWalletView,
    UserTransactionView,
    PointPurchaseView,
    PointPurchaseVerificationView,
    WithdrawalRequestListCreateView,
    WithdrawalRequestRetrieveView,
    WithdrawalApproveView,
    WithdrawalRejectView,
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
        "verify/",
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
]
