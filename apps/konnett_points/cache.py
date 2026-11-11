from apps.core.utils import bump_cache_version

TRANSACTIONS_SCOPE = "wallet-transactions"
WITHDRAWALS_USER_SCOPE = "withdrawals-user"
WITHDRAWALS_ADMIN_SCOPE = "withdrawals-admin"
WITHDRAWALS_ADMIN_OWNER = "pending"


def invalidate_transactions(user_id):
    bump_cache_version(TRANSACTIONS_SCOPE, user_id)


def invalidate_withdrawals(user_id):
    bump_cache_version(WITHDRAWALS_USER_SCOPE, user_id)
    bump_cache_version(WITHDRAWALS_ADMIN_SCOPE, WITHDRAWALS_ADMIN_OWNER)