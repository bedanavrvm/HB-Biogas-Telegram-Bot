"""Source-bound review operations. No workflow or access-grant writes."""
from __future__ import annotations

import hashlib
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .catalog import PATTERNS, current_manifest, digest
from .models import ReviewDecision, ReviewRevision, StandardRelease


def require_actor(actor):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise ValidationError('An active Superuser must perform this review action.')


def require_current(revision):
    if revision.manifest['source_fingerprint'] != digest(current_manifest(revision.pattern)):
        raise ValidationError('The source changed. Capture a new revision before reviewing this one.')


def snapshot(pattern, fingerprint, actor):
    require_actor(actor)
    if pattern not in PATTERNS:
        raise ValidationError('Choose a catalogue pattern.')
    manifest = current_manifest(pattern)
    if fingerprint != digest(manifest):
        raise ValidationError('The source changed. Refresh the comparison first.')
    manifest['source_fingerprint'] = fingerprint
    revision, _ = ReviewRevision.objects.get_or_create(fingerprint=digest(manifest),
        defaults={'pattern': pattern, 'manifest': manifest, 'created_by': actor})
    return revision


@transaction.atomic
def attach_evidence(revision, actor, upload, *, variant, theme, state, kind, font_verified):
    """Upload on explicit reviewer request; retain a new immutable revision."""
    require_actor(actor)
    from qa_tracker.services import validate_screenshot
    from core.services.order_approval import GoogleDriveMediaStorage
    revision = ReviewRevision.objects.select_for_update().get(pk=revision.pk)
    require_current(revision)
    if variant not in {item['id'] for item in revision.manifest['variants']}:
        raise ValidationError('Choose an alternative in this comparison.')
    if theme not in ('light', 'dark') or state not in revision.manifest['states']:
        raise ValidationError('Choose the screenshot theme and state.')
    if kind not in ('browser', 'native'):
        raise ValidationError('Identify the capture as browser or real Telegram.')
    content, mime, checksum = validate_screenshot(upload)
    import io
    from PIL import Image
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
    item = {'variant': variant, 'theme': theme, 'state': state, 'kind': kind,
            'font_verified': font_verified is True, 'width': width, 'height': height,
            'sha256': checksum, 'mime': mime, 'source_fingerprint': revision.manifest['source_fingerprint']}
    for existing in revision.manifest['evidence']:
        if all(existing.get(key) == value for key, value in item.items()):
            return revision
    evidence_request = digest({'revision': str(revision.pk), 'evidence': item})
    previous = ReviewRevision.objects.filter(manifest__evidence_request=evidence_request).first()
    if previous:
        return previous
    filename = f'ui-{revision.pattern}-{checksum[:16]}.{ "png" if mime == "image/png" else "jpg" }'
    file_id, _ = GoogleDriveMediaStorage().upload(content, filename, mime, revision.pattern, timezone.now(),
        workflow_key='ui_review', record_type='synthetic_design', record_key=checksum)
    item.update(drive_file_id=file_id, filename=filename)
    manifest = {**revision.manifest, 'evidence': [*revision.manifest['evidence'], item],
                'evidence_request': evidence_request}
    result, _ = ReviewRevision.objects.get_or_create(fingerprint=digest(manifest),
        defaults={'pattern': revision.pattern, 'manifest': manifest, 'created_by': actor})
    return result


@transaction.atomic
def decide(revision, actor, *, decision, payload, request_key):
    require_actor(actor)
    # Lock only this non-null root, never nullable actor joins.
    revision = ReviewRevision.objects.select_for_update().get(pk=revision.pk)
    require_current(revision)
    if decision not in dict(ReviewDecision.CHOICES):
        raise ValidationError('Choose a review action.')
    if not isinstance(payload, dict) or not isinstance(payload.get('reason'), str) or not payload['reason'].strip():
        raise ValidationError('Add a short reason for this decision.')
    selected = str(payload.get('variant', ''))
    variants = {item['id']: item for item in revision.manifest['variants']}
    if decision in ('adopt', 'changes', 'approve') and selected not in variants:
        raise ValidationError('Choose the alternative you reviewed.')
    if decision in ('adopt', 'approve'):
        evidence = [item for item in revision.manifest['evidence'] if item['variant'] == selected]
        if not evidence:
            raise ValidationError('Attach a screenshot of this alternative before approving it.')
        if payload.get('reviewed') is not True:
            raise ValidationError('Confirm that you reviewed the layout, states and behaviour.')
        if not any(item.get('font_verified') for item in evidence):
            raise ValidationError('Verify the rendered font on the attached evidence before approving.')
        if decision == 'adopt' and variants[selected].get('proposal'):
            raise ValidationError('Use Approve proposal for a candidate foundation.')
    allowed = ('variant', 'reason', 'use_when', 'avoid_when', 'intentional', 'reviewed', 'device_result')
    cleaned = {key: payload[key] for key in allowed if key in payload}
    if len(str(cleaned)) > 8000:
        raise ValidationError('Keep review notes under 8,000 characters.')
    key = uuid.UUID(str(request_key))
    event, created = ReviewDecision.objects.get_or_create(request_key=key, defaults={
        'revision': revision, 'actor': actor, 'decision': decision, 'payload': cleaned})
    if not created and (event.revision_id != revision.pk or event.actor_id != actor.pk
                        or event.decision != decision or event.payload != cleaned):
        raise ValidationError('This request key belongs to a different review. Refresh and retry.')
    return event


def latest_design_decision(revision):
    return revision.decisions.exclude(decision='device').first()


@transaction.atomic
def prepare_release(actor, request_key):
    require_actor(actor)
    key = uuid.UUID(str(request_key))
    existing = StandardRelease.objects.filter(request_key=key).first()
    if existing:
        if existing.actor_id != actor.pk:
            raise ValidationError('This request belongs to a different reviewer.')
        return existing
    # One stable row serializes version allocation on PostgreSQL as well.
    roots = list(ReviewRevision.objects.select_for_update().filter(pattern='foundations').order_by('id'))
    if not roots:
        raise ValidationError('Review foundations first. No standard is approved yet.')
    selections = []
    for pattern in PATTERNS:
        revision = ReviewRevision.objects.filter(pattern=pattern).first()
        event = latest_design_decision(revision) if revision else None
        if not event or event.decision not in ('adopt', 'approve', 'defer'):
            raise ValidationError(f'{PATTERNS[pattern]["title"]}: record an approval or explicit deferral first.')
        require_current(revision)
        if pattern == 'foundations' and event.decision == 'defer':
            raise ValidationError('Approve foundations before preparing a standard.')
        selections.append({'pattern': pattern, 'revision': str(revision.pk), 'fingerprint': revision.fingerprint,
                           'decision': str(event.pk), 'action': event.decision, 'variant': event.payload.get('variant', ''),
                           'source_fingerprint': revision.manifest['source_fingerprint'],
                           'sources': next((item['sources'] for item in revision.manifest['variants'] if item['id'] == event.payload.get('variant')), [])})
    manifest = {'format': 1, 'selections': selections, 'themes': ['telegram', 'jbl'],
                'default_theme': 'telegram', 'default_appearance': 'auto',
                'migration_authorized': False, 'phase_6': 'Requires separate explicit user approval.'}
    same = StandardRelease.objects.filter(fingerprint=digest(manifest)).first()
    if same:
        return same
    version = (StandardRelease.objects.aggregate(value=Max('version'))['value'] or 0) + 1
    return StandardRelease.objects.create(version=version, manifest=manifest, fingerprint=digest(manifest), actor=actor, request_key=key)


def read_evidence(revision, index):
    from core.services.order_approval import GoogleDriveMediaStorage
    try:
        evidence = revision.manifest['evidence'][index]
    except (IndexError, TypeError):
        raise ValidationError('This evidence is not available.')
    content = GoogleDriveMediaStorage().download(evidence['drive_file_id'])
    if hashlib.sha256(content).hexdigest() != evidence['sha256']:
        raise ValidationError('The evidence integrity check failed. Capture it again.')
    return content, evidence
