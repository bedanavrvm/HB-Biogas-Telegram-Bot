"""Guarded Origination signing simulation and controlled stamp rendering."""

from __future__ import annotations

import hashlib
import json
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


def _validated_signature_capture(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OriginationError('Draw or type the TEST signature before confirming this slot.')
    method = str(value.get('method') or '').strip().casefold()
    if method == 'typed':
        name = ' '.join(str(value.get('name') or '').split())
        if len(name) < 2 or len(name) > 120:
            raise OriginationError('Enter the signer name using 2 to 120 characters.')
        return {'method': 'typed', 'name': name}
    if method != 'drawn':
        raise OriginationError('Choose Draw signature or Type signature.')
    raw_strokes = value.get('strokes')
    if not isinstance(raw_strokes, list) or not raw_strokes or len(raw_strokes) > 40:
        raise OriginationError('Draw the TEST signature before confirming this slot.')
    strokes = []
    total_points = 0
    for raw_stroke in raw_strokes:
        if not isinstance(raw_stroke, list) or len(raw_stroke) < 2 or len(raw_stroke) > 500:
            raise OriginationError('The drawn TEST signature contains an invalid stroke.')
        stroke = []
        for raw_point in raw_stroke:
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
                raise OriginationError('The drawn TEST signature contains an invalid point.')
            try:
                x, y = float(raw_point[0]), float(raw_point[1])
            except (TypeError, ValueError) as exc:
                raise OriginationError('The drawn TEST signature contains an invalid point.') from exc
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise OriginationError('The drawn TEST signature must stay inside the signature pad.')
            stroke.append([round(x, 4), round(y, 4)])
        strokes.append(stroke)
        total_points += len(stroke)
    if total_points > 2000:
        raise OriginationError('The drawn TEST signature is too detailed. Clear it and try again.')
    return {'method': 'drawn', 'strokes': strokes}


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
            capture = (action.metadata or {}).get('signature_capture') or {}
            if capture.get('method') == 'drawn':
                pdf.saveState()
                pdf.setLineCap(1)
                pdf.setLineJoin(1)
                pdf.setLineWidth(max(1, min(box_width, box_height) * .025))
                inset = max(2, min(box_width, box_height) * .08)
                draw_width = max(1, box_width - inset * 2)
                draw_height = max(1, box_height - inset * 2)
                for stroke in capture.get('strokes') or []:
                    if len(stroke) < 2:
                        continue
                    path = pdf.beginPath()
                    path.moveTo(x + inset + stroke[0][0] * draw_width, y + inset + (1 - stroke[0][1]) * draw_height)
                    for point in stroke[1:]:
                        path.lineTo(x + inset + point[0] * draw_width, y + inset + (1 - point[1]) * draw_height)
                    pdf.drawPath(path, stroke=1, fill=0)
                pdf.restoreState()
            else:
                name = str(capture.get('name') or 'TEST SIGNATURE')
                font_name = 'Helvetica-BoldOblique'
                font_size = min(15, max(7, box_height * .38))
                name = name[:120]
                text_width = max(1, pdf.stringWidth(name, font_name, font_size))
                horizontal_scale = min(1, max(0.1, (box_width - 6) / text_width))
                pdf.saveState()
                pdf.translate(x + box_width / 2, y + max(5, box_height * .38))
                pdf.scale(horizontal_scale, 1)
                pdf.setFont(font_name, font_size)
                pdf.drawCentredString(0, 0, name)
                pdf.restoreState()
            pdf.setFillColorRGB(.78, .08, .08)
            pdf.setFont('Helvetica-Bold', min(6, max(4, box_height * .16)))
            pdf.drawRightString(x + box_width - 2, y + 2, 'TEST')
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
