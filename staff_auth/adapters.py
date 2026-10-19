"""Closed enrollment policy and encrypted maintained MFA implementation."""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.mfa.adapter import DefaultMFAAdapter

from .crypto import decrypt_secret, encrypt_secret


class StaffAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False


class StaffMFAAdapter(DefaultMFAAdapter):
    def encrypt(self, text):
        return encrypt_secret(text)

    def decrypt(self, encrypted_text):
        return decrypt_secret(encrypted_text)
