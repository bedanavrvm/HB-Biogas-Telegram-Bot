"""Idempotent Gmail intake for forwarded M-PESA statements."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from email.utils import parseaddr, parsedate_to_datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import MailboxCursor, StatementMailReceipt
from .services import MASKED_PHONE_RE, AssessmentError, parse_statement_filename

logger = logging.getLogger(__name__)
ORIGINAL_DATE_RE = re.compile(r'^Date:\s*(.+)$', re.IGNORECASE | re.MULTILINE)
GMAIL_READONLY_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'


def _header(payload: dict, name: str) -> str:
    target = name.casefold()
    for item in payload.get('headers') or []:
        if str(item.get('name') or '').casefold() == target:
            return str(item.get('value') or '').strip()
    return ''


def _sender_email(payload: dict) -> str:
    return parseaddr(_header(payload, 'From'))[1].strip().casefold()


def _received_at(message: dict) -> datetime:
    try:
        return datetime.fromtimestamp(int(message.get('internalDate')) / 1000, tz=datetime_timezone.utc)
    except (TypeError, ValueError, OSError):
        return timezone.now()


def _decoded_body(part: dict) -> str:
    encoded = str((part.get('body') or {}).get('data') or '')
    if not encoded:
        return ''
    try:
        return base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8', errors='replace')
    except (ValueError, TypeError):
        return ''


def _message_text(payload: dict) -> str:
    chunks = []
    stack = [payload]
    while stack:
        part = stack.pop()
        if str(part.get('mimeType') or '').casefold() == 'text/plain':
            chunks.append(_decoded_body(part))
        stack.extend(reversed(part.get('parts') or []))
    return '\n'.join(chunks)


def _original_sent_at(payload: dict) -> tuple[datetime | None, str]:
    body = _message_text(payload)
    match = ORIGINAL_DATE_RE.search(body)
    if match:
        try:
            value = parsedate_to_datetime(match.group(1).strip())
            if value.tzinfo is None:
                value = value.replace(tzinfo=datetime_timezone.utc)
            return value, 'forwarded_header'
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        value = parsedate_to_datetime(_header(payload, 'Date'))
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime_timezone.utc)
        return value, 'forward_received_header'
    except (TypeError, ValueError, OverflowError):
        return None, ''


def _pdf_attachments(payload: dict):
    stack = [payload]
    while stack:
        part = stack.pop()
        filename = str(part.get('filename') or '').strip()
        attachment_id = str((part.get('body') or {}).get('attachmentId') or '').strip()
        if filename and attachment_id and filename.casefold().endswith('.pdf'):
            yield attachment_id, filename
        stack.extend(reversed(part.get('parts') or []))


def _gmail_credentials():
    """Build refreshable credentials for one consented personal Gmail inbox."""
    from google.oauth2.credentials import Credentials

    raw = str(getattr(settings, 'CREDIT_ASSESSMENT_GMAIL_OAUTH_JSON', '') or '').strip()
    if not raw:
        raise RuntimeError('credit_mailbox_oauth_missing')
    try:
        info = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError('credit_mailbox_oauth_invalid') from exc
    if not isinstance(info, dict):
        raise RuntimeError('credit_mailbox_oauth_invalid')
    required = ('client_id', 'client_secret', 'refresh_token')
    if any(not str(info.get(key) or '').strip() for key in required):
        raise RuntimeError('credit_mailbox_oauth_incomplete')
    normalized = {
        'client_id': str(info['client_id']).strip(),
        'client_secret': str(info['client_secret']).strip(),
        'refresh_token': str(info['refresh_token']).strip(),
        'type': 'authorized_user',
    }
    return Credentials.from_authorized_user_info(normalized, scopes=[GMAIL_READONLY_SCOPE])


def _gmail_service():
    from googleapiclient.discovery import build

    mailbox_user = str(getattr(settings, 'CREDIT_ASSESSMENT_GMAIL_USER', '') or '').strip()
    if not mailbox_user:
        raise RuntimeError('credit_mailbox_user_missing')
    return build('gmail', 'v1', credentials=_gmail_credentials(), cache_discovery=False)


def _attachment_bytes(service, message_id: str, attachment_id: str) -> bytes:
    response = service.users().messages().attachments().get(
        userId='me', messageId=message_id, id=attachment_id,
    ).execute()
    encoded = str(response.get('data') or '')
    return base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))


def ingest_message(service, message_id: str, *, commit: bool) -> dict:
    message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
    payload = message.get('payload') or {}
    subject = _header(payload, 'Subject')
    sender = _sender_email(payload)
    received_at = _received_at(message)
    original_sent_at, time_source = _original_sent_at(payload)
    ingested = 0
    skipped = 0
    for attachment_id, filename in _pdf_attachments(payload):
        try:
            parsed = parse_statement_filename(filename)
        except AssessmentError:
            skipped += 1
            continue
        if StatementMailReceipt.objects.filter(gmail_message_id=message_id, gmail_attachment_id=attachment_id).exists():
            skipped += 1
            continue
        data = _attachment_bytes(service, message_id, attachment_id)
        if not data.startswith(b'%PDF-'):
            skipped += 1
            continue
        content_hash = hashlib.sha256(data).hexdigest()
        drive_file_id = ''
        if commit:
            from core.services.order_approval import GoogleDriveMediaStorage
            storage = GoogleDriveMediaStorage()
            drive_file_id, _url = storage.upload(
                data, filename, 'application/pdf', parsed.masked_phone, received_at,
                workflow_key='credit_assessment', record_type='mpesa_statement', record_key=content_hash,
            )
            StatementMailReceipt.objects.create(
                gmail_message_id=message_id,
                gmail_attachment_id=attachment_id,
                gmail_thread_id=str(message.get('threadId') or ''),
                forwarding_sender=sender,
                subject=subject[:998],
                original_sent_at=original_sent_at,
                inbox_received_at=received_at,
                original_time_source=time_source,
                attachment_name=filename[:255],
                attachment_hash=content_hash,
                attachment_size=len(data),
                masked_phone_pattern=parsed.masked_phone,
                statement_period_start=parsed.period_start,
                statement_period_end=parsed.period_end,
                statement_full_year=parsed.full_year,
                drive_file_id=drive_file_id,
            )
        ingested += 1
    return {'message_id': message_id, 'ingested': ingested, 'skipped': skipped}


@transaction.atomic
def _claim_cursor(now, owner):
    cursor, _ = MailboxCursor.objects.select_for_update().get_or_create(singleton_key='statement_inbox')
    if cursor.lease_expires_at and cursor.lease_expires_at > now:
        raise RuntimeError('credit_mailbox_busy')
    cursor.lease_owner = owner
    cursor.lease_expires_at = now + timedelta(minutes=5)
    cursor.last_polled_at = now
    cursor.last_error_code = ''
    cursor.save(update_fields=['lease_owner', 'lease_expires_at', 'last_polled_at', 'last_error_code', 'updated_at'])
    return cursor


def poll_mailbox(*, commit: bool = False, limit: int = 50) -> dict:
    if not str(getattr(settings, 'CREDIT_ASSESSMENT_GMAIL_USER', '') or '').strip():
        raise RuntimeError('credit_mailbox_disabled')
    now = timezone.now()
    owner = uuid.uuid4().hex
    cursor = _claim_cursor(now, owner)

    try:
        service = _gmail_service()
        profile = service.users().getProfile(userId='me').execute()
        configured_user = str(getattr(settings, 'CREDIT_ASSESSMENT_GMAIL_USER', '') or '').strip().casefold()
        if str(profile.get('emailAddress') or '').strip().casefold() != configured_user:
            raise RuntimeError('credit_mailbox_account_mismatch')
        query = 'has:attachment filename:MPESA_Statement_ newer_than:180d'
        response = service.users().messages().list(userId='me', q=query, maxResults=max(1, min(limit, 500))).execute()
        results = [ingest_message(service, str(item['id']), commit=commit) for item in response.get('messages') or []]
        cursor.history_id = str(response.get('historyId') or cursor.history_id)
        cursor.last_succeeded_at = timezone.now()
        return {
            'commit': commit,
            'messages': len(results),
            'ingested': sum(item['ingested'] for item in results),
            'skipped': sum(item['skipped'] for item in results),
        }
    except Exception as exc:
        cursor.last_error_code = type(exc).__name__[:80] or 'credit_mailbox_failed'
        logger.warning('Credit statement mailbox poll failed: code=%s', cursor.last_error_code)
        raise
    finally:
        MailboxCursor.objects.filter(singleton_key='statement_inbox', lease_owner=owner).update(
            history_id=cursor.history_id,
            last_succeeded_at=cursor.last_succeeded_at,
            last_error_code=cursor.last_error_code,
            lease_owner='', lease_expires_at=None,
        )
