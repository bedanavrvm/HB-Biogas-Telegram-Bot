"""Shared one-use admission after native TOTP validation; never a verifier."""
from datetime import timedelta
import hashlib
import hmac

from allauth.core.internal.cryptokit import _strip_punctuation
from allauth.headless.mfa.inputs import AuthenticateInput
from allauth.headless.mfa.views import AuthenticateView
from allauth.mfa import app_settings
from allauth.mfa.adapter import get_adapter
from allauth.mfa.models import Authenticator
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .crypto import decrypt_secret
from .models import StaffTOTPReplayState


class ReplayStoreUnavailable(Exception):
    """Safe failure; never include a credential or backend exception text."""


@sensitive_variables()
def reserve_totp_use(authenticator, code):
    """Reserve a native-validated code. Return false on any still-live claim.

    Use the pinned native comparison's normalization: punctuation/whitespace
    variants must not mint independent replay keys. This function does not
    validate a code and must only follow successful native validation.
    """
    if authenticator.type != Authenticator.Type.TOTP or authenticator.pk is None:
        raise ValueError('A saved native TOTP factor is required.')
    secret = decrypt_secret(authenticator.data['secret'])
    canonical = _strip_punctuation(code).lower()
    digest = hmac.new(
        secret.encode('ascii'),
        f'staff-browser-totp-use-v1\0{authenticator.pk}\0{canonical}'.encode('ascii'),
        hashlib.sha256,
    ).hexdigest()
    now = timezone.now()
    expires_at = now + timedelta(seconds=app_settings.TOTP_PERIOD * (2 * app_settings.TOTP_TOLERANCE + 1))
    # PostgreSQL rechecks this condition after a competing update releases its
    # row lock. Only one renewal can replace an expired claim.
    if StaffTOTPReplayState.objects.filter(pk=digest, expires_at__lte=now).update(expires_at=expires_at):
        return True
    try:
        # Savepoint keeps a duplicate insert from poisoning a caller transaction.
        with transaction.atomic():
            StaffTOTPReplayState.objects.create(key_digest=digest, expires_at=expires_at)
    except IntegrityError:
        if StaffTOTPReplayState.objects.filter(pk=digest).exists():
            return False
        raise
    return True


class BrowserAuthenticateInput(AuthenticateInput):
    @sensitive_variables()
    def clean_code(self):
        code = super().clean_code()
        if self.authenticator.type == Authenticator.Type.TOTP:
            try:
                accepted = reserve_totp_use(self.authenticator, code)
            except DatabaseError:
                raise ReplayStoreUnavailable('Browser authentication is temporarily unavailable.') from None
            if not accepted:
                raise get_adapter().validation_error('incorrect_code')
        return code


class BrowserAuthenticateView(AuthenticateView):
    input_class = BrowserAuthenticateInput
