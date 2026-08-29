import django_filters

from apps.konnett_points.models import PointTransaction, WithdrawalRequest


class PointTransactionFilter(django_filters.FilterSet):
    class Meta:
        model = PointTransaction
        fields = [
            "transaction_type",
        ]


class WithdrawalRequestFilter(django_filters.FilterSet):
    class Meta:
        model = WithdrawalRequest
        fields = [
            "status",
        ]
