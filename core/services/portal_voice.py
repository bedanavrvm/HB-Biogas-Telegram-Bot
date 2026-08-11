"""Bounded, auditable voice transcription for the two approved Portal fields."""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from core.models import PortalVoiceTranscriptionAttempt


logger = logging.getLogger(__name__)

ALLOWED_FIELDS = {
    PortalVoiceTranscriptionAttempt.FIELD_JBL_VISIT_COMMENT: 'portal.jbl_visit.write',
    PortalVoiceTranscriptionAttempt.FIELD_FINAL_DECISION_COMMENT: 'portal.final_review.write',
}
ALLOWED_MIME_TYPES = {
    'audio/webm': '.webm',
    'audio/ogg': '.ogg',
    'audio/mp4': '.m4a',
    'audio/mpeg': '.mp3',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
}
MAX_AUDIO_BYTES = 5 * 1024 * 1024
GROQ_TRANSCRIPTION_URL = 'https://api.groq.com/openai/v1/audio/transcriptions'
ALLOWED_LANGUAGE_MODES = {'auto', 'en', 'sw'}
LANGUAGE_PROMPTS = {
    'auto': 'JBL, HomeBiogas, IMAB.',
    'en': 'JBL HomeBiogas field visit comment. Terms: JBL, HomeBiogas, IMAB, farmer, installation, deposit, loan.',
    'sw': 'Maoni ya ziara ya JBL HomeBiogas. Istilahi: JBL, HomeBiogas, IMAB, mkulima, mtambo wa biogas, amana, mkopo.',
}


class VoiceInputError(ValueError):
    def __init__(self, message: str, *, code: str = 'invalid_request', status: int = 400, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after


def voice_enabled() -> bool:
    return bool(
        getattr(settings, 'PORTAL_VOICE_INPUT_ENABLED', False)
        and getattr(settings, 'PORTAL_VOICE_PROVIDER', '') == 'groq'
        and getattr(settings, 'GROQ_API_KEY', '')
    )


def _day_bounds():
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.get_current_timezone()), now


def _enforce_quota(user, duration_ms: int) -> None:
    start, _ = _day_bounds()
    attempts = PortalVoiceTranscriptionAttempt.objects.filter(created_at__gte=start)
    total_requests = attempts.count()
    total_ms = attempts.aggregate(total=Sum('duration_ms'))['total'] or 0
    user_requests = attempts.filter(user=user).count()
    if total_requests >= max(1, int(settings.PORTAL_VOICE_DAILY_REQUEST_LIMIT)):
        raise VoiceInputError('The voice pilot has reached today\'s request allowance. Please type this comment.', code='rate_limited', status=429)
    if total_ms + duration_ms > max(1, int(settings.PORTAL_VOICE_DAILY_AUDIO_SECONDS)) * 1000:
        raise VoiceInputError('The voice pilot has reached today\'s audio allowance. Please type this comment.', code='rate_limited', status=429)
    if user_requests >= max(1, int(settings.PORTAL_VOICE_USER_DAILY_REQUEST_LIMIT)):
        raise VoiceInputError('You have reached today\'s voice pilot allowance. Please type this comment.', code='rate_limited', status=429)


def _normal_mime(value: str) -> str:
    return str(value or '').split(';', 1)[0].strip().lower()


def _validate_audio(audio: bytes, mime_type: str, duration_ms: int) -> tuple[str, int]:
    mime = _normal_mime(mime_type)
    if mime not in ALLOWED_MIME_TYPES:
        raise VoiceInputError('This phone produced an unsupported audio format. Please use keyboard input.', code='unsupported_audio')
    if not audio:
        raise VoiceInputError('No recorded audio was received.', code='empty_audio')
    if len(audio) > MAX_AUDIO_BYTES:
        raise VoiceInputError('The recording is too large. Record a shorter comment.', code='audio_too_large', status=413)
    maximum = max(1, int(settings.PORTAL_VOICE_MAX_SECONDS)) * 1000
    if duration_ms <= 0 or duration_ms > maximum + 1000:
        raise VoiceInputError(f'Recordings are limited to {settings.PORTAL_VOICE_MAX_SECONDS} seconds.', code='audio_too_long')
    return mime, maximum


def _drive_upload(attempt, audio: bytes) -> str:
    from googleapiclient.http import MediaIoBaseUpload
    from core.services.order_approval import GoogleDriveMediaStorage

    storage = GoogleDriveMediaStorage()
    local_day = timezone.localtime(attempt.created_at or timezone.now()).date().isoformat()
    parent = storage.parent_folder_id
    for part in ('Temporary Voice Input', local_day, str(attempt.id)):
        parent = storage.ensure_child_folder(parent, part)
    extension = ALLOWED_MIME_TYPES.get(attempt.audio_mime_type, '.webm')
    created = storage.service.files().create(
        body={'name': f'recording{extension}', 'parents': [parent]},
        media_body=MediaIoBaseUpload(io.BytesIO(audio), mimetype=attempt.audio_mime_type, resumable=False),
        fields='id', supportsAllDrives=True,
    ).execute()
    return str(created['id'])


def _drive_download(file_id: str) -> bytes:
    from core.services.order_approval import GoogleDriveMediaStorage
    return GoogleDriveMediaStorage().download(file_id)


def _trash_drive_file(file_id: str) -> None:
    from core.services.order_approval import GoogleDriveMediaStorage
    GoogleDriveMediaStorage().service.files().update(
        fileId=file_id, body={'trashed': True}, fields='id', supportsAllDrives=True,
    ).execute()


def _call_groq(audio: bytes, mime_type: str, language_mode: str) -> tuple[str, int, str, str, float | None]:
    extension = ALLOWED_MIME_TYPES[mime_type]
    request_data = {
        'model': settings.PORTAL_VOICE_MODEL,
        'response_format': 'verbose_json',
        'temperature': '0',
        'prompt': LANGUAGE_PROMPTS[language_mode],
    }
    if language_mode != 'auto':
        request_data['language'] = language_mode
    try:
        response = requests.post(
            GROQ_TRANSCRIPTION_URL,
            headers={'Authorization': f'Bearer {settings.GROQ_API_KEY}'},
            files={'file': (f'recording{extension}', audio, mime_type)},
            data=request_data,
            timeout=max(10, int(getattr(settings, 'API_REQUEST_TIMEOUT', 10) or 10) * 3),
        )
    except requests.RequestException as exc:
        raise VoiceInputError('Voice transcription is temporarily unavailable. Your typed text is unchanged.', code='unavailable', status=503) from exc
    if response.status_code == 429:
        try:
            retry_after = max(1, int(float(response.headers.get('retry-after', '1'))))
        except (TypeError, ValueError):
            retry_after = 1
        raise VoiceInputError('Voice transcription is busy. Retry shortly or type the comment.', code='rate_limited', status=429, retry_after=retry_after)
    if response.status_code >= 400:
        logger.warning('Groq transcription failed status=%s request_id=%s', response.status_code, response.headers.get('x-request-id', '-'))
        raise VoiceInputError('Voice transcription is temporarily unavailable. Your typed text is unchanged.', code='unavailable', status=503)
    try:
        payload = response.json()
        transcript = str(payload.get('text') or '').strip()
        provider_duration_ms = max(0, int(float(payload.get('duration') or 0) * 1000))
        detected_language = str(payload.get('language') or '')[:16].lower()
        log_probabilities = [
            float(segment['avg_logprob'])
            for segment in (payload.get('segments') or [])
            if isinstance(segment, dict) and segment.get('avg_logprob') is not None
        ]
        average_log_probability = (
            sum(log_probabilities) / len(log_probabilities) if log_probabilities else None
        )
    except (TypeError, ValueError, requests.JSONDecodeError) as exc:
        raise VoiceInputError('The transcription service returned an invalid response. Please retry.', code='invalid_provider_response', status=502) from exc
    if not transcript:
        raise VoiceInputError('No speech was detected. Retry or type the comment.', code='no_speech', status=422)
    if provider_duration_ms > (max(1, int(settings.PORTAL_VOICE_MAX_SECONDS)) + 1) * 1000:
        raise VoiceInputError(f'Recordings are limited to {settings.PORTAL_VOICE_MAX_SECONDS} seconds.', code='audio_too_long')
    provider_id = str((payload.get('x_groq') or {}).get('id') or response.headers.get('x-request-id') or '')[:128]
    return transcript, provider_duration_ms, provider_id, detected_language, average_log_probability


def create_transcription(*, user, farmer, field_name: str, request_id: str, duration_ms: int, audio: bytes | None = None, mime_type: str = '', source_attempt=None, language_mode: str = 'auto'):
    if not voice_enabled():
        raise VoiceInputError('Voice input is not available. Please type the comment.', code='disabled', status=503)
    if field_name not in ALLOWED_FIELDS:
        raise VoiceInputError('Voice input is not enabled for this field.', code='unsupported_field')
    language_mode = str(language_mode or '').strip().lower()
    if not language_mode and source_attempt is not None:
        language_mode = source_attempt.requested_language
    language_mode = language_mode or 'auto'
    if language_mode not in ALLOWED_LANGUAGE_MODES:
        raise VoiceInputError('Select Auto, English, or Swahili for voice input.', code='unsupported_language')
    request_id = str(request_id or '').strip()
    if not request_id:
        raise VoiceInputError('A retry key is required.', code='idempotency_key_required', status=428)
    existing = PortalVoiceTranscriptionAttempt.objects.filter(user=user, request_id=request_id).first()
    if existing:
        return existing, True
    if source_attempt is not None:
        if source_attempt.user_id != user.pk or source_attempt.farmer_id != farmer.pk or source_attempt.field_name != field_name:
            raise VoiceInputError('That recording is not available for this field.', code='not_found', status=404)
        if source_attempt.expires_at <= timezone.now() or not source_attempt.drive_file_id:
            raise VoiceInputError('That retry recording has expired. Record again.', code='expired', status=410)
        audio = _drive_download(source_attempt.drive_file_id)
        mime_type = source_attempt.audio_mime_type
        duration_ms = source_attempt.duration_ms
    audio = bytes(audio or b'')
    mime, _ = _validate_audio(audio, mime_type, duration_ms)
    _enforce_quota(user, duration_ms)
    attempt = PortalVoiceTranscriptionAttempt.objects.create(
        user=user, farmer=farmer, field_name=field_name, request_id=request_id,
        audio_hash=hashlib.sha256(audio).hexdigest(), audio_size=len(audio),
        audio_mime_type=mime, duration_ms=duration_ms,
        provider=settings.PORTAL_VOICE_PROVIDER, model_name=settings.PORTAL_VOICE_MODEL,
        requested_language=language_mode,
        expires_at=timezone.now() + timedelta(minutes=max(1, int(settings.PORTAL_VOICE_RETRY_RETENTION_MINUTES))),
        source_attempt=source_attempt,
    )
    if source_attempt is not None:
        attempt.drive_file_id = source_attempt.drive_file_id
        attempt.deletion_status = source_attempt.deletion_status
    else:
        try:
            attempt.drive_file_id = _drive_upload(attempt, audio)
            attempt.deletion_status = 'pending'
        except Exception:
            logger.exception('Temporary voice upload failed attempt_id=%s', attempt.id)
            attempt.deletion_status = 'not_stored'
    try:
        transcript, provider_duration_ms, provider_id, detected_language, average_log_probability = _call_groq(
            audio, mime, language_mode,
        )
    except VoiceInputError as exc:
        attempt.status = PortalVoiceTranscriptionAttempt.STATUS_FAILED
        attempt.error_code = exc.code
        attempt.save(update_fields=['drive_file_id', 'deletion_status', 'status', 'error_code', 'updated_at'])
        raise
    attempt.transcript = transcript[:2000]
    attempt.provider_request_id = provider_id
    attempt.detected_language = detected_language
    attempt.average_log_probability = average_log_probability
    attempt.duration_ms = provider_duration_ms or duration_ms
    attempt.status = PortalVoiceTranscriptionAttempt.STATUS_TRANSCRIBED
    attempt.save(update_fields=['drive_file_id', 'deletion_status', 'transcript', 'provider_request_id', 'detected_language', 'average_log_probability', 'duration_ms', 'status', 'updated_at'])
    return attempt, False


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left_char != right_char)))
        previous = current
    return previous[-1]


def validate_transcription_reference(*, attempt_id, user, farmer, field_name: str):
    try:
        attempt = PortalVoiceTranscriptionAttempt.objects.get(
            pk=attempt_id, user=user, farmer=farmer, field_name=field_name,
        )
    except (PortalVoiceTranscriptionAttempt.DoesNotExist, ValueError) as exc:
        raise VoiceInputError('The voice transcription could not be verified.', code='not_found', status=404) from exc
    if attempt.status != attempt.STATUS_TRANSCRIBED or attempt.expires_at <= timezone.now():
        raise VoiceInputError('That voice transcription has expired or was already resolved.', code='expired', status=410)
    return attempt


def resolve_transcription(*, attempt_id, user, farmer, field_name: str, accepted_text: str = '', accepted: bool = True):
    try:
        attempt = PortalVoiceTranscriptionAttempt.objects.get(pk=attempt_id, user=user, farmer=farmer, field_name=field_name)
    except (PortalVoiceTranscriptionAttempt.DoesNotExist, ValueError) as exc:
        raise VoiceInputError('The voice transcription could not be verified.', code='not_found', status=404) from exc
    if attempt.status in {attempt.STATUS_ACCEPTED, attempt.STATUS_CANCELLED}:
        return attempt
    if accepted:
        attempt.edit_distance = _edit_distance(attempt.transcript, str(accepted_text or ''))
        attempt.status = attempt.STATUS_ACCEPTED
    else:
        attempt.status = attempt.STATUS_CANCELLED
    attempt.transcript = ''
    attempt.resolved_at = timezone.now()
    file_id = attempt.drive_file_id
    if file_id:
        try:
            _trash_drive_file(file_id)
            related = PortalVoiceTranscriptionAttempt.objects.filter(drive_file_id=file_id)
            related.exclude(pk=attempt.pk).exclude(
                status__in=[attempt.STATUS_ACCEPTED, attempt.STATUS_CANCELLED],
            ).update(
                status=attempt.STATUS_CANCELLED, transcript='', resolved_at=timezone.now(),
                deletion_status='deleted', deletion_error='',
            )
            related.update(deletion_status='deleted', deletion_error='')
            attempt.deletion_status = 'deleted'
            attempt.deletion_error = ''
        except Exception:
            logger.exception('Temporary voice deletion failed attempt_id=%s', attempt.id)
            attempt.deletion_status = 'retry'
            attempt.deletion_error = 'Temporary audio cleanup failed.'
    attempt.save(update_fields=['status', 'transcript', 'resolved_at', 'edit_distance', 'deletion_status', 'deletion_error', 'updated_at'])
    return attempt


def cleanup_expired_transcriptions(*, limit: int = 100) -> dict:
    now = timezone.now()
    attempts = list(PortalVoiceTranscriptionAttempt.objects.filter(
        expires_at__lte=now,
    ).exclude(deletion_status='deleted').order_by('expires_at')[:max(1, limit)])
    deleted = failed = 0
    handled_files = set()
    for attempt in attempts:
        file_id = attempt.drive_file_id
        if file_id and file_id not in handled_files:
            try:
                _trash_drive_file(file_id)
                PortalVoiceTranscriptionAttempt.objects.filter(drive_file_id=file_id).update(deletion_status='deleted', deletion_error='')
                deleted += 1
                handled_files.add(file_id)
            except Exception:
                logger.exception('Expired voice cleanup failed attempt_id=%s', attempt.id)
                attempt.deletion_status = 'retry'
                attempt.deletion_error = 'Temporary audio cleanup failed.'
                attempt.save(update_fields=['deletion_status', 'deletion_error', 'updated_at'])
                failed += 1
        if attempt.status not in {attempt.STATUS_ACCEPTED, attempt.STATUS_CANCELLED}:
            attempt.status = attempt.STATUS_EXPIRED
            attempt.transcript = ''
            attempt.resolved_at = now
            attempt.save(update_fields=['status', 'transcript', 'resolved_at', 'updated_at'])
        if not file_id and attempt.deletion_status != 'deleted':
            attempt.deletion_status = 'deleted'
            attempt.save(update_fields=['deletion_status', 'updated_at'])
    return {'examined': len(attempts), 'deleted': deleted, 'failed': failed}
