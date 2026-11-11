from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import signing


class PasswordResetOnlyTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "apps.accounts.tokens.PasswordResetOnlyTokenGenerator"


password_reset_token_generator = PasswordResetOnlyTokenGenerator()


EMAIL_CHANGE_SALT = "apps.accounts.email-change"


def make_email_change_token(user, new_email):
    return signing.dumps(
        {"uid": str(user.pk), "old": user.email, "new": new_email},
        salt=EMAIL_CHANGE_SALT,
    )


def read_email_change_token(token):
    # Raises signing.BadSignature (SignatureExpired is a subclass)
    return signing.loads(
        token, salt=EMAIL_CHANGE_SALT, max_age=settings.EMAIL_CHANGE_TIMEOUT
    )