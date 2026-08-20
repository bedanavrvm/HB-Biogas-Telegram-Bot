"""Guarded Origination signing simulation and controlled stamp rendering."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from core.models import (
    OriginationSigningAction,
    OriginationSigningPackage,
    OriginationStampAsset,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    _record_event,
    _require_request_id,
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
                    **slot, 'role': role, 'key': key, 'document_key': document_key,
                    'type': str(slot.get('type') or slot.get('slot_type') or 'signature'),
                    'required': bool(slot.get('required', participant.get('required', True))),
                })
    return slots


def serialize_test_signing(package: OriginationSigningPackage) -> dict[str, Any]:
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
                action.actor.get_full_name() or action.actor.get_username()
                if action else ''
            ),
            'stamp_asset': str(action.stamp_asset_id or '') if action else '',
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
) -> tuple[OriginationSigningPackage, bool]:
    request_id = _require_request_id(request_id)
    if not test_signing_enabled():
        raise OriginationError('Test signing is disabled or forbidden in the production environment.')
    package = OriginationSigningPackage.objects.select_for_update().select_related(
        'application__branch_ref',
    ).get(pk=package_id)
    replay = package.actions.filter(request_id=request_id).first()
    if replay:
        if (
            replay.document_key != document_key
            or replay.slot_key != slot_key
            or replay.signer_role != signer_role
            or str(replay.stamp_asset_id or '') != str(stamp_asset_id or '')
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
    OriginationSigningAction.objects.create(
        package=package, document_key=document_key, slot_key=slot_key,
        signer_role=signer_role, action_type=action_type,
        mode=OriginationSigningAction.MODE_TEST, stamp_asset=stamp, actor=actor,
        request_id=request_id,
        metadata={'warning': 'TEST ONLY - no OTP or legal signature verification'},
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


def _test_overlay(width: float, height: float, items: list[tuple[dict, OriginationSigningAction]]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.saveState()
    pdf.setFillColorRGB(.78, .08, .08, alpha=.18)
    pdf.setFont('Helvetica-Bold', 34)
    pdf.translate(width / 2, height / 2)
    pdf.rotate(35)
    pdf.drawCentredString(0, 0, 'TEST ONLY - NOT LEGALLY SIGNED')
    pdf.restoreState()
    for spec, action in items:
        box = spec.get('allowed_area') or spec.get('box') or {}
        scale = 72 / 25.4 if spec.get('units', 'pt') == 'mm' else 1
        try:
            x, y = float(box['x']) * scale, float(box['y']) * scale
            box_width, box_height = float(box['width']) * scale, float(box['height']) * scale
        except (KeyError, TypeError, ValueError):
            continue
        if action.action_type == OriginationSigningAction.TYPE_STAMP and action.stamp_asset_id:
            pdf.drawImage(
                ImageReader(BytesIO(bytes(action.stamp_asset.image_png))), x, y,
                width=box_width, height=box_height, preserveAspectRatio=True,
                anchor='c', mask='auto',
            )
        else:
            pdf.setStrokeColorRGB(.48, .23, .93)
            pdf.setFillColorRGB(.34, .12, .65)
            pdf.rect(x, y, box_width, box_height, stroke=1, fill=0)
            pdf.setFont('Helvetica-BoldOblique', min(13, max(7, box_height * .38)))
            pdf.drawCentredString(x + box_width / 2, y + max(3, box_height * .35), 'TEST SIGNATURE')
    pdf.save()
    return output.getvalue()


def render_test_package(package: OriginationSigningPackage) -> bytes:
    if not package.test_mode or not test_signing_enabled():
        raise OriginationError('A test signing preview is not available for this package.')
    from core.services.origination_documents import render_packet
    content, manifest = render_packet(package.application)
    actions = list(package.actions.select_related('stamp_asset').all())
    actions_by_document: dict[str, list[OriginationSigningAction]] = {}
    for action in actions:
        actions_by_document.setdefault(action.document_key, []).append(action)
    page_specs: dict[int, list[tuple[dict, OriginationSigningAction]]] = {}
    offset = 0
    for document in manifest:
        config = ((document.get('template') or {}).get('configuration') or {})
        slots = ((config.get('signature_overlay_manifest') or {}).get('slots') or {})
        for action in actions_by_document.get(str(document.get('key') or ''), []):
            spec = slots.get(f'{action.signer_role}.{action.slot_key}')
            if isinstance(spec, dict):
                page_specs.setdefault(offset + int(spec.get('page_number') or 1), []).append((spec, action))
        offset += int(document.get('page_count') or 0)
    reader = PdfReader(BytesIO(content))
    writer = PdfWriter()
    for page_number, page in enumerate(reader.pages, start=1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _test_overlay(width, height, page_specs.get(page_number, []))
        page.merge_page(PdfReader(BytesIO(overlay)).pages[0], over=True)
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
