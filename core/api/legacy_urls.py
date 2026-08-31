"""Individually reviewed root compatibility routes; no blanket API include."""

from django.urls import path

from .auth_views import telegram_session_login
from .legacy_routes import direct_legacy_alias
from .origination_views import (
    origination_africastalking_delivery_report,
    origination_signer_consent,
    origination_signer_otp,
    origination_signer_packet_preview,
    origination_signer_session,
    origination_signer_verify,
)
from .views import staff_telegram_activation_submit, tat_signature_webhook, telegram_webhook


def alias(route, view, canonical, name):
    return path(route, direct_legacy_alias(view, canonical_path=canonical), name=name)


urlpatterns = [
    # Cached activation/login clients may still POST these root paths.
    alias('staff/activate/submit/', staff_telegram_activation_submit, '/api/staff/activate/submit/', 'legacy_staff_activation_submit'),
    alias('auth/telegram/', telegram_session_login, '/api/auth/telegram/', 'legacy_telegram_session_login'),

    # Public signing links can outlive a frontend deployment. GET and POST
    # compatibility stays direct so bearer credentials are never rewritten.
    alias('origination/sign/api/session/', origination_signer_session, '/api/origination/sign/api/session/', 'legacy_origination_signer_session'),
    alias('origination/sign/api/packet/', origination_signer_packet_preview, '/api/origination/sign/api/packet/', 'legacy_origination_signer_packet'),
    alias('origination/sign/api/consent/', origination_signer_consent, '/api/origination/sign/api/consent/', 'legacy_origination_signer_consent'),
    alias('origination/sign/api/otp/', origination_signer_otp, '/api/origination/sign/api/otp/', 'legacy_origination_signer_otp'),
    alias('origination/sign/api/verify/', origination_signer_verify, '/api/origination/sign/api/verify/', 'legacy_origination_signer_verify'),

    # Provider endpoints remain direct aliases until their external dashboards
    # are confirmed on the canonical /api/ callbacks.
    alias('webhook/telegram/', telegram_webhook, '/api/webhook/telegram/', 'legacy_telegram_webhook'),
    alias('webhook/e-signatures/tat/', tat_signature_webhook, '/api/webhook/e-signatures/tat/', 'legacy_tat_signature_webhook'),
    alias('origination/webhooks/africastalking/delivery/', origination_africastalking_delivery_report, '/api/origination/webhooks/africastalking/delivery/', 'legacy_origination_africastalking_delivery'),
]
