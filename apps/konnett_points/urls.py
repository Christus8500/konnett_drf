from django.urls import path

from apps.konnett_points.views import (
    UserWalletView,
    UserTransactionView,
    PointPurchaseView,
    PointPurchaseVerificationView,
    WithdrawalRequestView,
    WithdrawalApproveView,
    WithdrawalRejectView,
)

urlpatterns = [
    path("wallet/", UserWalletView.as_view(), name="user-wallet"),
    path(
        "transactions/", UserTransactionView.as_view(), name="user-wallet-transactions"
    ),
    path("purchase/", PointPurchaseView.as_view(), name="purchase-konnett-points"),
    path(
        "verify/",
        PointPurchaseVerificationView.as_view(),
        name="verify-purchase-konnett-points",
    ),
    path(
        "withdrawals/",
        WithdrawalRequestView.as_view(),
        name="withdrawal-list-create",
    ),
    path(
        "withdrawals/<uuid:pk>/",
        WithdrawalRequestView.as_view(),
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
