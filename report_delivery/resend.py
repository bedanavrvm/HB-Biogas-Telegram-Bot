"""Small fixed-endpoint Resend adapter; never expose raw provider responses."""
import base64
import hashlib
import hmac
import json

import requests
from django.conf import settings
from django.utils import timezone


class SubmissionError(Exception):
    def __init__(self, code, *, retryable=False, ambiguous=False, retry_after=0):
        self.code, self.retryable, self.ambiguous, self.retry_after = code, retryable, ambiguous, retry_after
        super().__init__(code)


def send_email(payload, *, key):
    if not settings.REPORT_EMAIL_DELIVERY_ENABLED or not settings.RESEND_API_KEY or not settings.REPORT_EMAIL_FROM:
        raise SubmissionError('delivery_not_configured')
    try:
        response = requests.post(
            'https://api.resend.com/emails', json=payload,
            headers={'Authorization': 'Bearer ' + settings.RESEND_API_KEY, 'Idempotency-Key': key},
            timeout=(5, 20), allow_redirects=False,
        )
    except requests.RequestException:
        raise SubmissionError('submission_network_error', retryable=True, ambiguous=True) from None
    if response.status_code in {408, 409, 429} or response.status_code >= 500:
        # A payload conflict is permanent; an in-flight same-key conflict may
        # be retried. Interpret only provider categories, never log the body.
        try:
            category = response.json().get('name', '')
        except (ValueError, AttributeError):
            category = ''
        if response.status_code == 409 and category == 'invalid_idempotent_request':
            raise SubmissionError('idempotency_payload_conflict')
        try:
            retry_after = min(3600, max(0, int(response.headers.get('Retry-After', '0'))))
        except ValueError:
            retry_after = 0
        raise SubmissionError('provider_temporarily_unavailable', retryable=True, ambiguous=response.status_code != 429, retry_after=retry_after)
    if not 200 <= response.status_code < 300:
        raise SubmissionError('provider_rejected_request')
    try:
        provider_id = response.json()['id']
        if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 100:
            raise ValueError
        return provider_id
    except (ValueError, KeyError, TypeError):
        raise SubmissionError('provider_response_unreadable', retryable=True, ambiguous=True) from None


def verify_webhook(body, headers, *, now=None):
    """Svix raw-body HMAC protocol with five-minute replay tolerance."""
    secret = settings.RESEND_WEBHOOK_SECRET
    event_id = headers.get('svix-id', '')
    timestamp = headers.get('svix-timestamp', '')
    signatures = headers.get('svix-signature', '')
    try:
        if not secret.startswith('whsec_') or not 1 <= len(event_id) <= 100 or len(signatures) > 4096:
            raise ValueError
        if abs(int(timestamp) - int((now or timezone.now()).timestamp())) > 300:
            raise ValueError
        encoded = secret.removeprefix('whsec_')
        key = base64.b64decode(encoded + '=' * (-len(encoded) % 4), validate=True)
        if not key:
            raise ValueError
        signed = event_id.encode() + b'.' + timestamp.encode() + b'.' + body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        if not any(hmac.compare_digest(value[3:], expected) for value in signatures.split() if value.startswith('v1,')):
            raise ValueError
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
        return event_id, payload
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('Webhook signature is invalid.') from None
