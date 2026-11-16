"""Guarded Origination signing simulation and controlled stamp rendering."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from io import BytesIO
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from origination.models import OriginationSigningAction, OriginationSigningPackage, OriginationStampAsset
from origination.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    _record_event,
    _require_request_id,
    _slot_request_id,
    frozen_unsigned_package_content,
)


def test_signing_enabled() -> bool:
    environment = str(getattr(settings, 'SENTRY_ENVIRONMENT', '') or '').strip().casefold()
    return bool(
        getattr(settings, 'ORIGINATION_TEST_SIGNING_ENABLED', False)
        and environment in {'development', 'dev', 'local', 'test', 'testing', 'staging'}
    )


def _slot_catalog(package: OriginationSigningPackage) -> list[dict[str, Any]]:
    slots = []
    for participant in package.participants_snapshot or []:
        if not isinstance(participant, dict):
            continue
        role = str(participant.get('role') or '').strip()
        for raw in participant.get('slots') or []:
            slot = {'key': raw} if isinstance(raw, str) else dict(raw or {})
            key = str(slot.get('key') or '').strip()
            document_key = str(slot.get('document_key') or 'primary').strip()
            if role and key:
                slots.append({
                    **slot, 'role': role, 'participant_id': participant.get('participant_id', ''), 'key': key, 'document_key': document_key,
                    'type': str(slot.get('type') or slot.get('slot_type') or 'signature'),
                    'required': bool(slot.get('required', participant.get('required', True))),
                })
    return slots


def _validated_signature_capture(value):
    from document_signing.appearance import _validated_signature_capture as validate
    return validate(value)


def serialize_test_signing(package: OriginationSigningPackage) -> dict[str, Any]:
    if not package.test_mode:
        # Verified external signatures deliberately have no Django actor; they
        # belong to a signer session and are serialized by the verified-signing
        # service. Keep the compatibility object without inspecting them.
        return {
            'enabled': test_signing_enabled(),
            'test_mode': False,
            'completed': False,
            'completed_at': '',
            'slots': [],
        }
    actions = {
        (item.document_key, item.slot_key): item
        for item in package.actions.select_related('stamp_asset', 'actor').all()
    }
    slots = []
    for slot in _slot_catalog(package):
        action = actions.get((slot['document_key'], slot['key']))
        slots.append({
            **slot,
            'completed': bool(action),
            'completed_at': action.created_at.isoformat() if action else '',
            'actor_name': (
                (action.actor.get_full_name() or action.actor.get_username())
                if action and action.actor_id
                else 'External signer' if action and action.signer_session_id
                else 'System' if action else ''
            ),
            'stamp_asset': str(action.stamp_asset_id or '') if action else '',
            'capture_method': str((action.metadata or {}).get('signature_capture', {}).get('method') or '') if action else '',
        })
    return {
        'enabled': test_signing_enabled(),
        'test_mode': package.test_mode,
        'completed': bool(package.test_completed_at),
        'completed_at': package.test_completed_at.isoformat() if package.test_completed_at else '',
        'slots': slots,
    }


@transaction.atomic
def simulate_slot(
    *, package_id, actor, document_key: str, slot_key: str, signer_role: str,
    expected_revision: int, request_id: str, stamp_asset_id: str = '',
    signature_capture: Any = None,
) -> tuple[OriginationSigningPackage, bool]:
    request_id = _require_request_id(request_id)
    if not test_signing_enabled():
        raise OriginationError('Test signing is disabled or forbidden in the production environment.')
    # Do not join the nullable application.branch_ref while acquiring this
    # lock. PostgreSQL rejects FOR UPDATE on the nullable side of an outer
    # join. Lock the package and its required application relation explicitly;
    # the branch comparison below needs only application.branch_ref_id.
    package = OriginationSigningPackage.objects.select_for_update(
        of=('self', 'application'),
    ).select_related('application').get(pk=package_id)
    replay = package.actions.filter(request_id=request_id).first()
    if replay:
        replay_capture = (
            _validated_signature_capture(signature_capture)
            if replay.action_type == OriginationSigningAction.TYPE_SIGNATURE else None
        )
        if (
            replay.document_key != document_key
            or replay.slot_key != slot_key
            or replay.signer_role != signer_role
            or str(replay.stamp_asset_id or '') != str(stamp_asset_id or '')
            or (replay_capture or {}) != ((replay.metadata or {}).get('signature_capture') or {})
        ):
            raise OriginationError('This request key was already used for a different test signing action.')
        return package, True
    if not package.test_mode:
        raise OriginationError('This is not a test signing package.')
    if package.application.revision != int(expected_revision):
        raise OriginationConflict('This application changed. Refresh before simulating signing.')
    if package.status not in {package.STATUS_PENDING, package.STATUS_IN_PROGRESS}:
        raise OriginationError('This signing package no longer accepts test actions.')
    selected = next((
        item for item in _slot_catalog(package)
        if item['document_key'] == document_key
        and item['key'] == slot_key
        and item['role'] == signer_role
    ), None)
    if not selected:
        raise OriginationError('Choose a configured signing slot from this package.')
    if package.actions.filter(document_key=document_key, slot_key=slot_key).exists():
        # Package row locking serializes concurrent taps. A different retry
        # key cannot produce a second action for an already completed slot.
        return package, True
    action_type = selected['type']
    if action_type not in {'signature', 'stamp'}:
        raise OriginationError('Only signature and stamp slots can be simulated.')
    stamp = None
    if action_type == 'stamp':
        stamp = OriginationStampAsset.objects.filter(
            pk=stamp_asset_id, active=True,
            environment=OriginationStampAsset.ENV_TEST,
        ).select_related('branch').first()
        if not stamp:
            raise OriginationError('Choose an active test stamp.')
        if stamp.branch_id and stamp.branch_id != package.application.branch_ref_id:
            raise OriginationError('This stamp is not approved for the application branch.')
    elif stamp_asset_id:
        raise OriginationError('A stamp asset can only be used in a stamp slot.')
    capture = _validated_signature_capture(signature_capture) if action_type == 'signature' else None
    capture_hash = (
        hashlib.sha256(json.dumps(capture, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if capture else ''
    )
    OriginationSigningAction.objects.create(
        package=package, document_key=document_key, slot_key=slot_key,
        signer_role=signer_role, action_type=action_type,
        mode=OriginationSigningAction.MODE_TEST, stamp_asset=stamp, actor=actor,
        request_id=request_id,
        metadata={
            'warning': 'TEST ONLY - no OTP or legal signature verification',
            'signature_capture': capture or {},
            'capture_sha256': capture_hash,
        },
    )
    if action_type == OriginationSigningAction.TYPE_SIGNATURE:
        # One signer gives one holistic signature for the complete packet. Reuse
        # that immutable capture at every placement owned by the same role.
        for signature_slot in _slot_catalog(package):
            if (
                signature_slot['role'] != signer_role
                or signature_slot['type'] != OriginationSigningAction.TYPE_SIGNATURE
            ):
                continue
            OriginationSigningAction.objects.get_or_create(
                package=package,
                document_key=signature_slot['document_key'],
                slot_key=signature_slot['key'],
                defaults={
                    'signer_role': signer_role,
                    'action_type': OriginationSigningAction.TYPE_SIGNATURE,
                    'mode': OriginationSigningAction.MODE_TEST,
                    'actor': actor,
                    'request_id': _slot_request_id(
                        request_id, signature_slot['document_key'], signature_slot['key'],
                    ),
                    'metadata': {
                        'warning': 'TEST ONLY - no OTP or legal signature verification',
                        'signature_capture': capture or {},
                        'capture_sha256': capture_hash,
                        'reused_for_packet': True,
                    },
                },
            )
        signed_date = timezone.localdate().isoformat()
        for date_slot in _slot_catalog(package):
            if (
                date_slot['role'] != signer_role
                or date_slot['type'] != OriginationSigningAction.TYPE_DATE_SIGNED
            ):
                continue
            OriginationSigningAction.objects.get_or_create(
                package=package, document_key=date_slot['document_key'], slot_key=date_slot['key'],
                defaults={
                    'signer_role': signer_role,
                    'action_type': OriginationSigningAction.TYPE_DATE_SIGNED,
                    'mode': OriginationSigningAction.MODE_TEST, 'actor': actor,
                    'request_id': _slot_request_id(
                        request_id, date_slot['document_key'], date_slot['key'],
                    ),
                    'metadata': {
                        'warning': 'TEST ONLY - no OTP or legal signature verification',
                        'signed_date': signed_date,
                    },
                },
            )
    package.status = package.STATUS_IN_PROGRESS
    completed = {
        (item.document_key, item.slot_key)
        for item in package.actions.all()
    }
    required = {
        (item['document_key'], item['key'])
        for item in _slot_catalog(package) if item['required']
    }
    if required and required <= completed:
        package.test_completed_at = timezone.now()
    package.save(update_fields=['status', 'test_completed_at', 'updated_at'])
    _record_event(
        package.application, 'test_signing_slot_completed', actor=actor,
        request_id=request_id,
        after={
            'package_id': str(package.pk), 'document_key': document_key,
            'slot_key': slot_key, 'signer_role': signer_role,
            'action_type': action_type, 'test_only': True,
        },
    )
    return package, False


def active_test_stamps(application) -> list[dict[str, Any]]:
    rows = OriginationStampAsset.objects.filter(
        active=True, environment=OriginationStampAsset.ENV_TEST,
    ).filter(branch__isnull=True) | OriginationStampAsset.objects.filter(
        active=True, environment=OriginationStampAsset.ENV_TEST,
        branch=application.branch_ref,
    )
    return [
        {'id': str(item.pk), 'name': item.name, 'version': item.version,
         'scope': item.branch.name if item.branch_id else 'Organization'}
        for item in rows.distinct().order_by('name', '-version')
    ]


def _slot_overlay(width, height, items, *, test_mode):
    from document_signing.appearance import _slot_overlay as overlay
    return overlay(width, height, items, test_mode=test_mode)


def _test_overlay(width: float, height: float, items: list[tuple[dict, OriginationSigningAction]]) -> bytes:
    """Backward-compatible test-only overlay entry point."""
    return _slot_overlay(width, height, items, test_mode=True)


def render_test_package(package: OriginationSigningPackage) -> bytes:
    if not package.test_mode or not test_signing_enabled():
        raise OriginationError('A test signing preview is not available for this package.')
    content = frozen_unsigned_package_content(package)
    manifest = package.document_manifest_snapshot or []
    actions = list(package.actions.select_related('stamp_asset').all())
    placement_keys = {(slot['document_key'], slot['key']): slot.get('placement_key') or slot['role'] + '.' + slot['key']
                      for slot in _slot_catalog(package)}
    actions_by_document: dict[str, list[OriginationSigningAction]] = {}
    for action in actions:
        actions_by_document.setdefault(action.document_key, []).append(action)
    page_specs: dict[int, list[tuple[dict, OriginationSigningAction]]] = {}
    offset = 0
    for document in manifest:
        config = ((document.get('template') or {}).get('configuration') or {})
        slots = ((config.get('signature_overlay_manifest') or {}).get('slots') or {})
        for action in actions_by_document.get(str(document.get('key') or ''), []):
            spec = slots.get(placement_keys.get((action.document_key, action.slot_key), f'{action.signer_role}.{action.slot_key}'))
            if isinstance(spec, dict):
                page_specs.setdefault(offset + int(spec.get('page_number') or 1), []).append((spec, action))
        offset += int(document.get('page_count') or 0)
    reader = PdfReader(BytesIO(content))
    writer = PdfWriter()
    for page_number, page in enumerate(reader.pages, start=1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _slot_overlay(width, height, page_specs.get(page_number, []), test_mode=True)
        page.merge_page(PdfReader(BytesIO(overlay)).pages[0], over=True)
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def render_verified_package(package: OriginationSigningPackage) -> bytes:
    """Render verified actions over the exact frozen packet configuration."""
    if package.test_mode:
        raise OriginationError('A test package cannot produce a verified signed document.')
    content = frozen_unsigned_package_content(package)
    manifest = package.document_manifest_snapshot or []
    actions = list(package.actions.filter(
        mode=OriginationSigningAction.MODE_VERIFIED, invalidation__isnull=True,
    ).select_related('stamp_asset'))
    placement_keys = {(slot['document_key'], slot['key']): slot.get('placement_key') or slot['role'] + '.' + slot['key']
                      for slot in _slot_catalog(package)}
    actions_by_document: dict[str, list[OriginationSigningAction]] = {}
    for action in actions:
        actions_by_document.setdefault(action.document_key, []).append(action)
    page_specs: dict[int, list[tuple[dict, OriginationSigningAction]]] = {}
    offset = 0
    for document in manifest:
        config = ((document.get('template') or {}).get('configuration') or {})
        slots = ((config.get('signature_overlay_manifest') or {}).get('slots') or {})
        for action in actions_by_document.get(str(document.get('key') or ''), []):
            spec = slots.get(placement_keys.get((action.document_key, action.slot_key), f'{action.signer_role}.{action.slot_key}'))
            if isinstance(spec, dict):
                page_specs.setdefault(offset + int(spec.get('page_number') or 1), []).append((spec, action))
        offset += int(document.get('page_count') or 0)
    reader = PdfReader(BytesIO(content))
    writer = PdfWriter()
    for page_number, page in enumerate(reader.pages, start=1):
        overlay = _slot_overlay(
            float(page.mediabox.width), float(page.mediabox.height),
            page_specs.get(page_number, []), test_mode=False,
        )
        page.merge_page(PdfReader(BytesIO(overlay)).pages[0], over=True)
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def verified_packet_version(package: OriginationSigningPackage) -> str:
    """Derive a stable display version from the frozen bytes and active actions.

    The value is presentation/concurrency metadata only. A predecessor signing
    action changing this version never invalidates another signer's consent or
    active OTP challenge.
    """
    actions = package.actions.filter(
        mode=OriginationSigningAction.MODE_VERIFIED,
        invalidation__isnull=True,
    ).order_by('document_key', 'slot_key', 'signer_role', 'created_at', 'id')
    payload = {
        'unsigned_document_hash': package.unsigned_document_hash,
        'actions': [
            {
                'id': str(item.pk),
                'document_key': item.document_key,
                'slot_key': item.slot_key,
                'signer_role': item.signer_role,
                'action_type': item.action_type,
            }
            for item in actions
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
