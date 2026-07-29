"""Server-side recovery drafts for sensitive Telegram Mini App forms."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import MiniAppDraft


DRAFT_TTL = timedelta(days=7)
MAX_DRAFT_BYTES = 250_000
ATTACHMENT_FIELD_NAMES = frozenset({
    'attachment', 'attachments', 'credit_analysis', 'crb_report', 'evidence',
    'file', 'files', 'media', 'spin_report', 'upload', 'uploads',
})


class MiniAppDraftError(ValueError):
    """A stable, user-safe draft validation failure."""


class MiniAppDraftConflict(MiniAppDraftError):
    """Another device saved this draft after the caller loaded it."""


def _contains_attachment_payload(value: Any) -> bool:
    """Keep recovery drafts to form fields; upload bytes stay client-side."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace('-', '_').replace(' ', '_')
            if normalized in ATTACHMENT_FIELD_NAMES or _contains_attachment_payload(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_attachment_payload(item) for item in value)
    return isinstance(value, str) and value.lstrip().lower().startswith('data:')


def _validated_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise MiniAppDraftError('Draft data must be an object.')
    if _contains_attachment_payload(payload):
        raise MiniAppDraftError('Attachments are not saved in drafts. Select files again when submitting.')
    # JSON serialization both enforces the wire contract and prevents opaque
    # Python values from reaching the JSON column.
    import json

    encoded = json.dumps(payload, ensure_ascii=True, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_DRAFT_BYTES:
        raise MiniAppDraftError('Draft is too large. Remove unnecessary text and try again.')
    return json.loads(encoded)


def get_draft(*, user, workflow: str, context_key: str) -> MiniAppDraft | None:
    """Return the caller's unexpired draft, cleaning an expired copy safely."""
    draft = MiniAppDraft.objects.filter(
        user=user,
        workflow=workflow,
        context_key=context_key,
    ).first()
    if draft and draft.expired:
        draft.delete()
        return None
    return draft


@transaction.atomic
def save_draft(
    *, user, workflow: str, context_key: str, payload: Any, expected_revision: int | None,
) -> MiniAppDraft:
    """Save one recovery draft with optimistic locking between devices."""
    cleaned = _validated_payload(payload)
    now = timezone.now()
    draft = MiniAppDraft.objects.select_for_update().filter(
        user=user,
        workflow=workflow,
        context_key=context_key,
    ).first()
    if draft and draft.expired:
        draft.delete()
        draft = None

    if draft:
        if expected_revision is not None and expected_revision != draft.revision:
            raise MiniAppDraftConflict('This draft changed on another device. Refresh before saving again.')
        draft.payload = cleaned
        draft.revision += 1
        draft.expires_at = now + DRAFT_TTL
        draft.save(update_fields=['payload', 'revision', 'expires_at', 'updated_at'])
        return draft

    if expected_revision not in (None, 0):
        raise MiniAppDraftConflict('This draft is no longer available. Refresh before saving again.')
    try:
        return MiniAppDraft.objects.create(
            user=user,
            workflow=workflow,
            context_key=context_key,
            payload=cleaned,
            expires_at=now + DRAFT_TTL,
        )
    except IntegrityError as exc:
        # A parallel initial save won the unique constraint race.  Ask the
        # caller to reload rather than replacing data they have not seen.
        raise MiniAppDraftConflict('This draft changed on another device. Refresh before saving again.') from exc


def delete_draft(*, user, workflow: str, context_key: str) -> None:
    MiniAppDraft.objects.filter(
        user=user,
        workflow=workflow,
        context_key=context_key,
    ).delete()
