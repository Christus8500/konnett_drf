"""

Shared logic for changing a user's bank details:
  * password confirmation when a bank field really changes
  * a cooldown (User.bank_details_changed_at) that the withdrawal endpoint enforces
  * an audit log line and an alert email

Used by both CustomerProfileSerializer and ProviderProfileSerializer.
"""

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.mails.services import queue_email
from apps.mails.tasks import process_email_outbox

logger = logging.getLogger(__name__)

BANK_FIELDS = ("account_number", "account_name", "bank_name")


def _cooldown():
    return timedelta(hours=getattr(settings, "BANK_CHANGE_COOLDOWN_HOURS", 24))


def bank_cooldown_ends_at(user, now=None):
    """Return when the cooldown ends, or None if no cooldown is active."""
    changed_at = getattr(user, "bank_details_changed_at", None)
    if changed_at is None:
        return None
    ends_at = changed_at + _cooldown()
    return ends_at if ends_at > (now or timezone.now()) else None


def changed_bank_fields(user, user_data):
    """Bank fields in user_data whose value differs from what the user has now."""
    return [
        f for f in BANK_FIELDS if f in user_data and user_data[f] != getattr(user, f)
    ]


def apply_user_update(user, user_data):
    """
    Save user_data on the user. Must be called inside a transaction.

    - Starts the withdrawal cooldown when previously complete bank details change.
      Setting details for the first time (any field was empty) does not, unless
      settings.BANK_COOLDOWN_ON_FIRST_SETUP is True.
    - Re-sending unchanged values changes nothing and triggers nothing.
    - Logs and emails the account holder whenever a bank field really changes.

    Returns the list of bank fields that changed.
    """
    if not user_data:
        return []

    # Everything below is computed BEFORE the new values are applied.
    changed = changed_bank_fields(user, user_data)
    had_complete_details = all(getattr(user, f) for f in BANK_FIELDS)

    for attr, value in user_data.items():
        setattr(user, attr, value)
    update_fields = list(user_data)

    starts_cooldown = bool(changed) and (
        had_complete_details or getattr(settings, "BANK_COOLDOWN_ON_FIRST_SETUP", False)
    )
    if starts_cooldown:
        user.bank_details_changed_at = timezone.now()
        update_fields.append("bank_details_changed_at")

    user.save(update_fields=[*update_fields, "updated_at"])

    if changed:
        # Field names only, never values.
        logger.warning(
            "Bank details changed user_id=%s fields=%s cooldown_started=%s",
            user.pk,
            changed,
            starts_cooldown,
        )
        email, _ = queue_email(
            idempotency_key=f"bank-details-changed:{user.pk}:{uuid.uuid4().hex}",
            recipient=user.email,
            email_type="bank_details_changed",
            payload={"user_id": str(user.pk)},  # no account data in the payload
        )
        transaction.on_commit(
            lambda eid=email.pk: process_email_outbox.delay(eid), robust=True
        )

    return changed


class BankDetailsPasswordMixin:
    """
    Put this BEFORE serializers.ModelSerializer in the bases. The serializer must
    declare a write-only `current_password` field (and list it in Meta.fields).
    Requires the current password whenever a bank field would really change.
    """

    def validate(self, attrs):
        attrs = super().validate(attrs)
        password = attrs.pop("current_password", None)  # never reaches update()

        if self.instance is None:
            return attrs

        user = self.instance.user
        if changed_bank_fields(user, attrs.get("user", {})):
            if not password:
                raise serializers.ValidationError(
                    {"current_password": "Required to change bank details."}
                )
            if not user.check_password(password):
                raise serializers.ValidationError(
                    {"current_password": "Incorrect password."}
                )
        return attrs
