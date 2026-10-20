"""Closed enrollment policy and encrypted maintained MFA implementation."""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.mfa.adapter import DefaultMFAAdapter

from .crypto import decrypt_secret, encrypt_secret


class StaffAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False

    def add_message(self, request, *args, **kwargs):
        if getattr(request, '_staff_browser_json_feedback', False):
            return
        return super().add_message(request, *args, **kwargs)


class StaffMFAAdapter(DefaultMFAAdapter):
    def encrypt(self, text):
        return encrypt_secret(text)

    def decrypt(self, encrypted_text):
        return decrypt_secret(encrypted_text)
