"""Privacy-safe diagnostics for staff Telegram Mini Apps.

The client contract is intentionally an allowlist. It can correlate a lifecycle
signal with an existing request UUID, but it cannot submit arbitrary text,
customer fields, Telegram identifiers, URLs, or request/response bodies.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
import logging
import uuid

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from core.models import (
    MiniAppDiagnosticDailyAggregate,
    MiniAppDiagnosticEvent,
    MiniAppDiagnosticSession,
)
from core.services.miniapp_requests import validate_request_key


SURFACE_WORKFLOWS = {
    'portal': 'jawabu_portal',
    'loan_origination': 'jawabu_portal',
    'order_approval': 'jawabu_portal',
    'jawabu_farmers': 'jawabu_portal',
    'fca_review': 'jawabu_portal',
    'complaint_cases': 'complaint_cases',
    'tat_tracker': 'tat_tracker',
    'spin': 'spin_credit_analysis',
}
PLATFORMS = frozenset({'android', 'ios', 'desktop', 'other'})
NETWORK_BUCKETS = frozenset({'offline', 'slow', 'cellular', 'wifi', 'unknown'})
MEMORY_BUCKETS = frozenset({'low', 'medium', 'high', 'unknown'})
VISIBILITIES = frozenset({'visible', 'hidden'})
EVENT_TYPES = frozenset({
    'session_started', 'heartbeat', 'backgrounded', 'resumed',
    'page_hidden', 'page_restored', 'intentional_close', 'client_error',
    'startup_failure', 'navigation_or_native_dismissal', 'api_request',
    'recovery_complete', 'client_capability', 'carousel_gesture',
})
ACTIONS = frozenset({
    '', 'boot', 'periodic', 'visibility_change', 'page_lifecycle',
    'submit_success', 'completed_batch', 'empty_queue', 'user_back',
    'native_close', 'unknown', 'api_request', 'recovery',
    'gesture_policy', 'gesture_started', 'gesture_completed',
})
STATUS_BUCKETS = frozenset({
    '', 'ok', 'client_error', 'server_error', 'offline', 'timeout',
    'cancelled', 'unknown',
})
TERMINAL_CLASSIFICATIONS = frozenset({
    MiniAppDiagnosticSession.CLASSIFICATION_INTENTIONAL_CLOSE,
    MiniAppDiagnosticSession.CLASSIFICATION_STARTUP_FAILURE,
    MiniAppDiagnosticSession.CLASSIFICATION_NAVIGATION,
    MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT,
    MiniAppDiagnosticSession.CLASSIFICATION_BACKGROUND_NOT_RESUMED,
})
TOKEN_SALT = 'core.miniapp-diagnostics.signal-token.v1'
logger = logging.getLogger(__name__)


class DiagnosticPayloadError(ValueError):
    pass


def _bounded_choice(value, choices, default):
    normalized = str(value or '').strip().lower()
    return normalized if normalized in choices else default


def parse_client_uuid(value, *, field_name='identifier') -> uuid.UUID:
    try:
        return uuid.UUID(str(value or '').strip())
    except (TypeError, ValueError, AttributeError) as exc:
        raise DiagnosticPayloadError(f'{field_name} must be a valid UUID.') from exc


def workflow_for_surface(surface: str) -> str:
    normalized = str(surface or '').strip().lower()
    if normalized not in SURFACE_WORKFLOWS:
        raise DiagnosticPayloadError('The Mini App surface is not supported.')
    return SURFACE_WORKFLOWS[normalized]


def issue_signal_token(session: MiniAppDiagnosticSession) -> str:
    return signing.dumps(
        {'sid': str(session.client_session_uuid), 'uid': session.actor_id, 'workflow': session.workflow},
        salt=TOKEN_SALT,
        compress=True,
    )


def actor_id_from_signal_token(token: str, client_session_uuid: uuid.UUID) -> int | None:
    try:
        payload = signing.loads(
            str(token or ''), salt=TOKEN_SALT,
            max_age=int(getattr(settings, 'MINIAPP_DIAGNOSTICS_TOKEN_MAX_AGE_SECONDS', 172800)),
        )
    except signing.BadSignature:
        return None
    if str(payload.get('sid') or '') != str(client_session_uuid):
        return None
    try:
        return int(payload.get('uid'))
    except (TypeError, ValueError):
        return None


@transaction.atomic
def start_session(*, actor, payload: dict) -> tuple[MiniAppDiagnosticSession, bool]:
    client_uuid = parse_client_uuid(payload.get('session_uuid'), field_name='session_uuid')
    surface = str(payload.get('surface') or '').strip().lower()
    workflow = workflow_for_surface(surface)
    release = str(payload.get('release') or '').strip()[:80]
    platform = _bounded_choice(payload.get('platform'), PLATFORMS, 'other')
    network = _bounded_choice(payload.get('network_bucket'), NETWORK_BUCKETS, 'unknown')
    memory = _bounded_choice(payload.get('device_memory_bucket'), MEMORY_BUCKETS, 'unknown')
    defaults = {
        'actor': actor,
        'workflow': workflow,
        'surface': surface,
        'release': release,
        'platform': platform,
        'network_bucket': network,
        'device_memory_bucket': memory,
    }
    session, created = MiniAppDiagnosticSession.objects.get_or_create(
        client_session_uuid=client_uuid, defaults=defaults,
    )
    if session.actor_id != actor.pk or session.workflow != workflow or session.surface != surface:
        raise DiagnosticPayloadError('This diagnostic session belongs to a different actor or workflow.')
    # A later authenticated launch proves only that an older visible session
    # stopped reporting; it does not prove why. Recovery events from durable
    # client storage may subsequently promote this honest intermediate state
    # to abrupt_unknown_confirmed.
    MiniAppDiagnosticSession.objects.filter(
        actor=actor,
        workflow=workflow,
        classification=MiniAppDiagnosticSession.CLASSIFICATION_ACTIVE,
        ended_at__isnull=True,
    ).exclude(pk=session.pk).update(classification=MiniAppDiagnosticSession.CLASSIFICATION_STALE)
    return session, created


def _clean_event(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise DiagnosticPayloadError('Each diagnostic event must be an object.')
    event_type = str(raw.get('event_type') or '').strip().lower()
    if event_type not in EVENT_TYPES:
        raise DiagnosticPayloadError('A diagnostic event type is invalid.')
    event_uuid = parse_client_uuid(raw.get('event_uuid'), field_name='event_uuid')
    try:
        elapsed_ms = max(0, min(int(raw.get('elapsed_ms') or 0), 604_800_000))
    except (TypeError, ValueError) as exc:
        raise DiagnosticPayloadError('elapsed_ms must be a whole number.') from exc
    action = str(raw.get('action') or '').strip().lower()
    if action not in ACTIONS:
        action = 'unknown'
    status = str(raw.get('status_bucket') or '').strip().lower()
    if status not in STATUS_BUCKETS:
        status = 'unknown'
    try:
        request_id = validate_request_key(raw.get('request_id'))
    except ValueError:
        request_id = ''
    return {
        'client_event_uuid': event_uuid,
        'event_type': event_type,
        'elapsed_ms': elapsed_ms,
        # The route is server-owned from the session surface. Client URLs,
        # query strings, case IDs, and fragments are never retained.
        'route': '',
        'action': action,
        'visibility': _bounded_choice(raw.get('visibility'), VISIBILITIES, 'visible'),
        'online': bool(raw.get('online', True)),
        'network_bucket': _bounded_choice(raw.get('network_bucket'), NETWORK_BUCKETS, 'unknown'),
        'status_bucket': status,
        'request_id': request_id,
    }


def _classification_after(session, event_type: str, visibility: str) -> tuple[str, bool]:
    classification = session.classification
    terminal = False
    if event_type in {'backgrounded', 'page_hidden'}:
        classification = MiniAppDiagnosticSession.CLASSIFICATION_BACKGROUNDED
    elif event_type in {'resumed', 'page_restored', 'heartbeat', 'session_started'}:
        classification = MiniAppDiagnosticSession.CLASSIFICATION_ACTIVE
    elif event_type == 'intentional_close':
        classification = MiniAppDiagnosticSession.CLASSIFICATION_INTENTIONAL_CLOSE
        terminal = True
    elif event_type == 'startup_failure':
        classification = MiniAppDiagnosticSession.CLASSIFICATION_STARTUP_FAILURE
        terminal = True
    elif event_type == 'navigation_or_native_dismissal':
        classification = MiniAppDiagnosticSession.CLASSIFICATION_NAVIGATION
        terminal = True
    elif event_type == 'client_error' and classification not in TERMINAL_CLASSIFICATIONS:
        classification = MiniAppDiagnosticSession.CLASSIFICATION_CLIENT_ERROR
    elif event_type == 'recovery_complete' and classification not in TERMINAL_CLASSIFICATIONS:
        classification = (
            MiniAppDiagnosticSession.CLASSIFICATION_BACKGROUND_NOT_RESUMED
            if visibility == 'hidden'
            else MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT
        )
        terminal = True
    return classification, terminal


@transaction.atomic
def record_signals(*, session: MiniAppDiagnosticSession, payload: dict) -> list[str]:
    raw_events = payload.get('events')
    if not isinstance(raw_events, list) or not raw_events:
        raise DiagnosticPayloadError('Provide at least one diagnostic event.')
    if len(raw_events) > 20:
        raise DiagnosticPayloadError('A maximum of 20 diagnostic events is allowed per request.')
    locked = MiniAppDiagnosticSession.objects.select_for_update().get(pk=session.pk)
    acknowledged: list[str] = []
    now = timezone.now()
    became_abrupt = False
    last_elapsed_ms = locked.events.order_by('-elapsed_ms').values_list('elapsed_ms', flat=True).first() or 0
    for raw in raw_events:
        cleaned = _clean_event(raw)
        event_uuid = cleaned.pop('client_event_uuid')
        acknowledged.append(str(event_uuid))
        if (
            cleaned['event_type'] == 'heartbeat'
            and cleaned['elapsed_ms'] < last_elapsed_ms
            and not locked.events.filter(client_event_uuid=event_uuid).exists()
        ):
            # A delayed retry must not make an older heartbeat look like new
            # evidence after later lifecycle milestones have been recorded.
            continue
        event, _created = MiniAppDiagnosticEvent.objects.get_or_create(
            session=locked,
            client_event_uuid=event_uuid,
            defaults=cleaned,
        )
        if _created:
            last_elapsed_ms = max(last_elapsed_ms, event.elapsed_ms)
            locked.last_signal_at = now
            locked.last_visibility = event.visibility
            classification, terminal = _classification_after(
                locked, event.event_type, event.visibility,
            )
            locked.classification = classification
            became_abrupt = became_abrupt or classification == MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT
            if event.event_type == 'recovery_complete':
                locked.recovered_on_later_launch = True
            if terminal:
                locked.ended_at = now
    locked.save(update_fields=[
        'last_signal_at', 'last_visibility', 'classification',
        'recovered_on_later_launch', 'ended_at',
    ])
    if became_abrupt:
        transaction.on_commit(lambda: log_abrupt_rate_alert_if_needed(locked.pk))
    return acknowledged


def abrupt_rate_alert_snapshot(session: MiniAppDiagnosticSession, *, now=None) -> dict | None:
    """Return a privacy-safe platform/workflow/release alert when its baseline regresses."""
    if str(getattr(settings, 'SENTRY_ENVIRONMENT', '')).lower() != 'production':
        return None
    now = now or timezone.now()
    segment = MiniAppDiagnosticSession.objects.filter(
        platform=session.platform, workflow=session.workflow, release=session.release,
    )
    # Do not establish a baseline from a partial first week.
    if not segment.filter(started_at__lte=now - timedelta(days=7)).exists():
        return None
    current = segment.filter(started_at__gte=now - timedelta(hours=1))
    current_total = current.count()
    current_abrupt = current.filter(
        classification=MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT,
    ).count()
    if current_total < 20 or current_abrupt < 5:
        return None
    baseline = segment.filter(
        started_at__gte=now - timedelta(days=7),
        started_at__lt=now - timedelta(hours=1),
    )
    baseline_total = baseline.count()
    if baseline_total < 20:
        return None
    baseline_abrupt = baseline.filter(
        classification=MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT,
    ).count()
    current_rate = current_abrupt / current_total
    baseline_rate = baseline_abrupt / baseline_total
    if current_rate <= baseline_rate * 2 or current_rate <= baseline_rate + 0.05:
        return None
    return {
        'platform': session.platform,
        'workflow': session.workflow,
        'release': session.release,
        'window_sessions': current_total,
        'window_abrupt': current_abrupt,
        'window_rate': round(current_rate, 4),
        'baseline_sessions': baseline_total,
        'baseline_abrupt': baseline_abrupt,
        'baseline_rate': round(baseline_rate, 4),
    }


def log_abrupt_rate_alert_if_needed(session_id) -> dict | None:
    """Rate-limit one structured warning per segment/hour without external writes."""
    try:
        session = MiniAppDiagnosticSession.objects.get(pk=session_id)
        snapshot = abrupt_rate_alert_snapshot(session)
        if not snapshot:
            return None
        from django.core.cache import cache
        hour = timezone.now().strftime('%Y%m%d%H')
        cache_key = (
            f"miniapp-diagnostic-alert:{session.workflow}:{session.platform}:"
            f"{session.release}:{hour}"
        )
        if cache.add(cache_key, True, timeout=3700):
            logger.warning('Mini App confirmed-abrupt rate threshold exceeded: %s', snapshot)
        return snapshot
    except Exception:
        # Monitoring must not make signal ingestion or host workflows fail.
        return None


def aggregate_and_prune(*, apply: bool, raw_days: int | None = None, aggregate_days: int | None = None) -> dict:
    raw_days = int(raw_days or getattr(settings, 'MINIAPP_DIAGNOSTICS_RAW_RETENTION_DAYS', 14))
    aggregate_days = int(
        aggregate_days or getattr(settings, 'MINIAPP_DIAGNOSTICS_AGGREGATE_RETENTION_DAYS', 180)
    )
    raw_cutoff = timezone.now() - timedelta(days=max(1, raw_days))
    aggregate_cutoff = timezone.localdate() - timedelta(days=max(1, aggregate_days))
    raw = MiniAppDiagnosticSession.objects.filter(started_at__lt=raw_cutoff)
    aggregate_groups = Counter(
        (
            timezone.localtime(item.started_at).date(), item.workflow, item.surface,
            item.platform, item.release, item.classification, item.network_bucket,
        )
        for item in raw.iterator()
    )
    result = {
        'raw_sessions': raw.count(),
        'raw_events': MiniAppDiagnosticEvent.objects.filter(session__started_at__lt=raw_cutoff).count(),
        'aggregate_rows': len(aggregate_groups),
        'expired_aggregate_rows': MiniAppDiagnosticDailyAggregate.objects.filter(date__lt=aggregate_cutoff).count(),
    }
    if not apply:
        return result
    with transaction.atomic():
        for key, count in aggregate_groups.items():
            MiniAppDiagnosticDailyAggregate.objects.update_or_create(
                date=key[0], workflow=key[1], surface=key[2], platform=key[3],
                release=key[4], classification=key[5], network_bucket=key[6],
                defaults={'session_count': count},
            )
        raw.delete()
        MiniAppDiagnosticDailyAggregate.objects.filter(date__lt=aggregate_cutoff).delete()
    return result
