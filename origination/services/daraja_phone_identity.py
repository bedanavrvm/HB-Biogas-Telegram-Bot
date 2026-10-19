"""Server-only Mobile Number Validation adapter; deliberately no paid retries."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from core.services.external_resilience import remaining_external_seconds

HOSTS = {'sandbox': 'https://sandbox.safaricom.co.ke', 'production': 'https://api.safaricom.co.ke'}
SAFE_CODES = {'4000', '4001', '400', '401.001', '403.001', '500'}


class ProviderFailure(Exception):
    """Safe classification only; never retain request/response objects or bodies."""

    def __init__(self, code='provider_unavailable', *, uncertain=False, provider_code='', status_code=None):
        self.code = code
        self.uncertain = uncertain
        self.provider_code = provider_code if provider_code in SAFE_CODES else ''
        self.status_code = status_code or (503 if uncertain or code == 'provider_transport_unavailable' else None)
        super().__init__(code)


@dataclass(frozen=True)
class Outcome:
    state: str
    provider_code: str
    response_ref: str = ''


def configuration_error() -> str:
    if not getattr(settings, 'ORIGINATION_PHONE_ID_CHECK_ENABLED', False):
        return 'disabled'
    if getattr(settings, 'DARAJA_ENVIRONMENT', '') not in HOSTS:
        return 'configuration_required'
    if not all(str(getattr(settings, key, '')).strip() for key in (
        'DARAJA_CONSUMER_KEY', 'DARAJA_CONSUMER_SECRET', 'DARAJA_SHORTCODE',
    )) or not str(settings.DARAJA_SHORTCODE).isascii() or not str(settings.DARAJA_SHORTCODE).isdigit():
        return 'configuration_required'
    if len(str(getattr(settings, 'DARAJA_PHONE_ID_HMAC_KEY', ''))) < 32:
        return 'configuration_required'
    try:
        limit = int(settings.ORIGINATION_PHONE_ID_CHECK_DAILY_LIMIT)
    except (TypeError, ValueError, AttributeError):
        return 'configuration_required'
    # The approved pilot can be reduced but cannot silently become unlimited.
    return '' if 1 <= limit <= 50 else 'configuration_required'


def provider_context() -> str:
    identity = [getattr(settings, key, '') for key in (
        'DARAJA_ENVIRONMENT', 'DARAJA_CONSUMER_KEY', 'DARAJA_SHORTCODE',
    )]
    identity += ['mobile-number-validation:national-id:hmac-v1', hashlib.sha256(
        str(getattr(settings, 'DARAJA_PHONE_ID_HMAC_KEY', '')).encode()).hexdigest()]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def subject_digest(phone: str, national_id: str) -> str:
    return hmac.new(str(settings.DARAJA_PHONE_ID_HMAC_KEY).encode(),
                    json.dumps(['01', phone, national_id], separators=(',', ':')).encode(), hashlib.sha256).hexdigest()


def parse_outcome(data: dict) -> Outcome:
    code = str(data.get('responseCode', ''))
    raw = data.get('status')
    value = raw if isinstance(raw, bool) else (
        {'true': True, 'false': False}.get(raw.strip().casefold()) if isinstance(raw, str) else None
    )
    if not ((code == '4000' and value is True) or (code == '4001' and value is False)):
        error = str(data.get('errorCode', ''))
        raise ProviderFailure('provider_response_invalid', provider_code=error)
    ref = str(data.get('responseRefID', ''))
    ref = ref if re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', ref) else ''
    return Outcome('matched' if value else 'not_matched', code, ref)


def _json_request(method: str, url: str, **kwargs) -> tuple[int, dict]:
    remaining = remaining_external_seconds(10)
    try:
        # requests' default adapter does not retry. Redirects could disclose PII
        # or credentials to a different endpoint, so they are never followed.
        with requests.request(method, url, timeout=(min(3, remaining), min(7, remaining)),
                              allow_redirects=False, stream=True, **kwargs) as response:
            body = bytearray()
            # Tiny bounded JSON replies: check the composed deadline between
            # bytes so a slowly trickling peer cannot hide inside a large chunk.
            for chunk in response.iter_content(1):
                remaining_external_seconds(10)
                body.extend(chunk)
                if len(body) > 8192:
                    raise ProviderFailure('provider_response_invalid', uncertain=method == 'POST')
            try:
                data = json.loads(body)
            except (ValueError, UnicodeError):
                raise ProviderFailure('provider_response_invalid', uncertain=method == 'POST') from None
            if not isinstance(data, dict):
                raise ProviderFailure('provider_response_invalid', uncertain=method == 'POST')
            return response.status_code, data
    except (requests.RequestException, TimeoutError):
        raise ProviderFailure('provider_transport_unavailable', uncertain=method == 'POST') from None


def _token_key() -> str:
    # Secret rotation invalidates tokens, but does not reset the daily allowance.
    digest = hmac.new(str(settings.DARAJA_PHONE_ID_HMAC_KEY).encode(),
                      str(settings.DARAJA_CONSUMER_SECRET).encode(), hashlib.sha256).hexdigest()
    return f'origination:daraja-token:{provider_context()}:{digest}'


def access_token() -> str:
    key = _token_key()
    token = cache.get(key)
    if token:
        return token
    status, data = _json_request('GET', HOSTS[settings.DARAJA_ENVIRONMENT] + '/oauth/v1/generate',
                                params={'grant_type': 'client_credentials'},
                                auth=(settings.DARAJA_CONSUMER_KEY, settings.DARAJA_CONSUMER_SECRET))
    token = data.get('access_token')
    if status != 200 or not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{1,4096}', token):
        raise ProviderFailure('provider_auth_unavailable', status_code=status)
    try:
        ttl = max(0, min(3600, int(data.get('expires_in', 0))) - 60)
    except (TypeError, ValueError):
        ttl = 0
    if ttl:
        cache.set(key, token, timeout=ttl)
    return token


def validate(*, phone: str, national_id: str, request_ref: str, before_dispatch) -> Outcome:
    error = configuration_error()
    if error:
        raise ProviderFailure(error)
    token = access_token()
    remaining_external_seconds(10)
    # This callback reauthorizes and atomically counts exactly this dispatch.
    before_dispatch()
    status, data = _json_request('POST', HOSTS[settings.DARAJA_ENVIRONMENT] + '/v1/KYC-validation/validateID',
                                headers={'Authorization': f'Bearer {token}'}, json={
                                    'requestRefID': request_ref, 'shortCode': settings.DARAJA_SHORTCODE,
                                    'msisdn': phone, 'idType': '01', 'idNumber': national_id,
                                })
    code = str(data.get('errorCode', ''))
    if status != 200 or code:
        if status == 401 or code == '401.001':
            cache.delete(_token_key())
        raise ProviderFailure('provider_unavailable', uncertain=status >= 500, provider_code=code, status_code=status)
    return parse_outcome(data)
