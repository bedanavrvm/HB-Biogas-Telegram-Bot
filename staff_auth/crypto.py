"""Versioned, fail-closed MFA encryption using dedicated deployment keys."""
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


PREFIX = 'staff-mfa:v1:'


class MFASecretUnavailable(ValueError):
    """Safe error; never include a key, credential or encrypted input."""


def keyring():
    keys = getattr(settings, 'STAFF_MFA_ENCRYPTION_KEYS', ())
    if not isinstance(keys, (list, tuple)) or not keys:
        raise ImproperlyConfigured('Dedicated staff MFA encryption keys are required.')
    try:
        if len(set(keys)) != len(keys) or any(key == settings.SECRET_KEY for key in keys):
            raise ValueError
        return MultiFernet([Fernet(key.encode('ascii')) for key in keys])
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise ImproperlyConfigured('Staff MFA encryption keys are not configured safely.') from None


def encrypt_secret(text):
    if not isinstance(text, str) or not text:
        raise MFASecretUnavailable('MFA secret material is unavailable.')
    return PREFIX + keyring().encrypt(text.encode('utf-8')).decode('ascii')


def decrypt_secret(encrypted_text):
    if not isinstance(encrypted_text, str) or not encrypted_text.startswith(PREFIX):
        raise MFASecretUnavailable('MFA secret material cannot be read safely.')
    try:
        return keyring().decrypt(encrypted_text[len(PREFIX):].encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError, ValueError):
        raise MFASecretUnavailable('MFA secret material cannot be read safely.') from None
