"""Provider transport only: Django, never an SMS receipt, verifies signing."""
from __future__ import annotations

import hashlib

import requests
from django.conf import settings

from core.services.external_resilience import ExternalOperationError, remaining_external_seconds
from core.services.identifiers import normalize_kenyan_phone

AFRICAS_TALKING = 'africas_talking'
ADVANTA = 'advanta'
PROVIDERS = (AFRICAS_TALKING, ADVANTA)
ADVANTA_BASE_URL = 'https://quicksms.advantasms.com/api/services'


class OriginationSmsSubmissionError(ExternalOperationError):
    """Only allowlisted categories may cross this interface; never raw responses."""

    def __init__(self, provider_status: str, *, rejected: bool = False):
        super().__init__('The SMS provider did not confirm sending the message.')
        self.provider_status = provider_status
        self.rejected = rejected
        self.status_code = 400 if rejected else 503


def selected_provider(config=settings) -> str:
    return str(getattr(config, 'ORIGINATION_SMS_PROVIDER', AFRICAS_TALKING) or '').strip().casefold()


def account_fingerprint(provider: str, config=settings) -> str:
    # Key rotation within the same account is harmless; account replacement is not.
    account = (getattr(config, 'AFRICASTALKING_USERNAME', '') if provider == AFRICAS_TALKING
               else getattr(config, 'ORIGINATION_ADVANTA_PARTNER_ID', ''))
    return hashlib.sha256(f'{provider}:{str(account).strip()}'.encode()).hexdigest()


def _advanta_post(endpoint: str, payload: dict) -> dict:
    try:
        budget = remaining_external_seconds(getattr(settings, 'API_REQUEST_TIMEOUT', 10))
        connect_timeout = min(3.0, budget / 3)
        response = requests.post(
            f'{ADVANTA_BASE_URL}/{endpoint}', json=payload,
            timeout=(connect_timeout, budget - connect_timeout),
            allow_redirects=False, verify=True,
        )
        if response.status_code != 200:
            raise OriginationSmsSubmissionError('send_unconfirmed')
        data = response.json()
    except OriginationSmsSubmissionError:
        raise
    except Exception:
        # HTTP exception objects may contain credential-bearing request bodies.
        raise OriginationSmsSubmissionError('send_unconfirmed') from None
    if not isinstance(data, dict):
        raise OriginationSmsSubmissionError('send_unconfirmed')
    return data


def _credentials() -> dict:
    return {'apikey': str(settings.ORIGINATION_ADVANTA_API_KEY),
            'partnerID': str(settings.ORIGINATION_ADVANTA_PARTNER_ID)}


def _response_code(data: dict) -> str:
    values = [str(data[key]).strip() for key in ('response-code', 'respose-code') if key in data]
    if not values or len(set(values)) != 1:
        return ''
    return values[0]


_REJECTIONS = {'1001': 'invalid_sender', '1002': 'network_not_allowed',
               '1003': 'invalid_recipient', '1004': 'account_unavailable',
               '1006': 'invalid_credentials', '4091': 'invalid_credentials',
               '4092': 'invalid_credentials'}


def _advanta_submit(message: str, phone: str) -> dict[str, str]:
    payload = {**_credentials(), 'mobile': phone, 'message': message,
               'shortcode': str(settings.ORIGINATION_ADVANTA_SENDER_ID)}
    data = _advanta_post('sendotp', payload)
    if not isinstance(data, dict):
        raise OriginationSmsSubmissionError('send_unconfirmed')
    if _response_code(data) in _REJECTIONS:
        raise OriginationSmsSubmissionError(_REJECTIONS[_response_code(data)], rejected=True)
    recipients = data.get('responses')
    if not isinstance(recipients, list) or len(recipients) != 1 or not isinstance(recipients[0], dict):
        raise OriginationSmsSubmissionError('send_unconfirmed')
    row = recipients[0]
    code = _response_code(row)
    if code in _REJECTIONS:
        raise OriginationSmsSubmissionError(_REJECTIONS[code], rejected=True)
    # A conflicting envelope or misleading success description is not acceptance.
    envelope = any(key in data for key in ('response-code', 'respose-code'))
    description = str(row.get('response-description') or '').strip().casefold()
    message_id = row.get('messageid')
    if (code != '200' or (envelope and _response_code(data) != '200')
            or description not in {'', 'success', 'successful'}
            or normalize_kenyan_phone(row.get('mobile')) != phone
            or not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 255):
        raise OriginationSmsSubmissionError('send_unconfirmed')
    return {'id': message_id.strip(), 'status': 'Accepted'}


def _africastalking_submit(message: str, phone: str) -> dict[str, str]:
    import africastalking
    sender = str(getattr(settings, 'AFRICASTALKING_SENDER_ID', '') or '').strip() or None
    try:
        africastalking.initialize(str(settings.AFRICASTALKING_USERNAME), str(settings.AFRICASTALKING_API_KEY))
        response = africastalking.SMS.send(message, [f'+{phone}'], sender_id=sender, enqueue=False)
    except Exception:
        raise OriginationSmsSubmissionError('send_unconfirmed') from None
    data = response.get('SMSMessageData') if isinstance(response, dict) else None
    recipients = data.get('Recipients') if isinstance(data, dict) else None
    if not isinstance(recipients, list) or len(recipients) != 1 or not isinstance(recipients[0], dict):
        raise OriginationSmsSubmissionError('send_unconfirmed')
    recipient = recipients[0]
    code = str(recipient.get('statusCode') or '').strip()
    status = str(recipient.get('status') or '').strip()
    accepted = {'success', 'accepted', 'processed', 'sent', 'queued'}
    rejection_codes = {'401': 'RiskHold', '402': 'InvalidSenderId', '403': 'InvalidPhoneNumber',
                       '404': 'UnsupportedNumberType', '405': 'InsufficientBalance',
                       '406': 'UserInBlacklist', '407': 'CouldNotRoute', '500': 'InternalServerError',
                       '501': 'GatewayError', '502': 'RejectedByGateway'}
    normalized = status.casefold().replace(' ', '')
    rejected = rejection_codes.get(code) or {
        **{value.casefold(): value for value in rejection_codes.values()},
        'failed': 'Failed', 'rejected': 'Rejected',
    }.get(normalized)
    if rejected:
        raise OriginationSmsSubmissionError(rejected, rejected=True)
    if ((code and code not in {'100', '101', '102'}) or (normalized and normalized not in accepted)
            or (not code and normalized not in accepted)):
        raise OriginationSmsSubmissionError('send_unconfirmed')
    message_id = recipient.get('messageId') or recipient.get('message_id')
    if not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 255:
        raise OriginationSmsSubmissionError('send_unconfirmed')
    return {'id': message_id.strip(), 'status': status or {'100': 'Processed', '101': 'Sent', '102': 'Queued'}[code]}


def submit(message: str, phone: str, *, provider: str) -> dict[str, str]:
    from origination.services.origination_signing_configuration import provider_configuration_issues
    if provider_configuration_issues(settings, provider=provider):
        raise OriginationSmsSubmissionError('configuration_required', rejected=True)
    normalized = normalize_kenyan_phone(phone)
    if not normalized:
        raise OriginationSmsSubmissionError('invalid_recipient', rejected=True)
    if provider == ADVANTA:
        return _advanta_submit(message, normalized)
    if provider == AFRICAS_TALKING:
        return _africastalking_submit(message, normalized)
    raise OriginationSmsSubmissionError('configuration_required', rejected=True)


def delivery_state(provider: str, status: str) -> str:
    normalized = str(status).casefold().replace(' ', '')
    if provider == ADVANTA:
        if normalized == 'deliveredtoterminal':
            return 'delivered'
        if normalized in {'senttonetwork', 'scheduled'}:
            return 'accepted'
        if normalized in {'deliveryimpossible', 'absentsubscriber', 'sendernameblacklisted'}:
            return 'failed'
        return 'unknown'
    if normalized in {'success', 'delivered'}:
        return 'delivered'
    if normalized in {'accepted', 'processed', 'sent', 'submitted', 'buffered', 'queued'}:
        return 'accepted'
    if normalized in {'failed', 'rejected', 'expired', 'undeliverable', 'insufficientbalance'}:
        return 'failed'
    return 'unknown'


def lookup_delivery(message_id: str, *, provider: str) -> dict[str, str]:
    if provider != ADVANTA:
        raise OriginationSmsSubmissionError('lookup_unsupported')
    from origination.services.origination_signing_configuration import provider_configuration_issues
    if provider_configuration_issues(settings, provider=provider):
        raise OriginationSmsSubmissionError('configuration_required')
    data = _advanta_post('getdlr', {**_credentials(), 'messageID': message_id})
    if _response_code(data) != '200':
        # Published numeric meanings conflict: no report is not failed delivery.
        return {'state': 'unknown', 'status': 'report_unavailable'}
    if str(data.get('message-id') or '') != message_id:
        raise OriginationSmsSubmissionError('lookup_mismatch')
    description = str(data.get('delivery-description') or '')
    state = delivery_state(provider, description)
    allowed = {'DeliveredToTerminal', 'SentToNetwork', 'Scheduled', 'DeliveryImpossible',
               'AbsentSubscriber', 'SenderName Blacklisted', 'Unknown'}
    return {'state': state, 'status': description if description in allowed else 'Unknown'}


def gsm7_units(message: str) -> int | None:
    """Count septets, including escape-table characters; None means Unicode."""
    basic = set('@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?¡'
                'ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà')
    extended = set('^{}\\[~]|€\f')
    if any(character not in basic | extended for character in message):
        return None
    return sum(2 if character in extended else 1 for character in message)
