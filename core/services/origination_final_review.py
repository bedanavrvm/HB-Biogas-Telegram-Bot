"""Independent post-sign review for governed conditional Origination packets."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationCorrectionItem,
    OriginationCorrectionRequest,
    OriginationSigningAction,
    OriginationSigningActionInvalidation,
    OriginationSigningPackage,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    _record_event,
    _require_request_id,
    _schema_fields,
    _slot_request_id,
)


def _correction_catalog(application, package) -> dict[tuple[str, str], str]:
    result = {
        (OriginationCorrectionItem.TARGET_FIELD, str(item.get('key') or '')):
            str(item.get('label') or item.get('key') or '')
        for item in _schema_fields(application.schema_snapshot)
        if item.get('key')
    }
    for item in (application.product_terms_snapshot or {}).get('requirements', []):
        if isinstance(item, dict) and item.get('key'):
            result[(OriginationCorrectionItem.TARGET_REQUIREMENT, str(item['key']))] = str(
                item.get('label') or item['key']
            )
    for document in application.packet_documents.filter(selected=True):
        for item in (document.schema_snapshot or {}).get('fields', []):
            if isinstance(item, dict) and item.get('key'):
                key = f'{document.document_key}.{item["key"]}'
                result[(OriginationCorrectionItem.TARGET_DOCUMENT_FIELD, key)] = (
                    f'{document.name}: {item.get("label") or item["key"]}'
                )
    from core.services.origination_esign import _slot_catalog
    for slot in _slot_catalog(package):
        key = f'{slot["document_key"]}.{slot["key"]}'
        if package.actions.filter(
            document_key=slot['document_key'], slot_key=slot['key'],
            mode=OriginationSigningAction.MODE_VERIFIED, invalidation__isnull=True,
        ).exists():
            result[(OriginationCorrectionItem.TARGET_SIGNATURE_SLOT, key)] = str(
                slot.get('label') or slot['key']
            )
    return result


def _normalized_items(application, package, items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list) or not items:
        raise OriginationError('Flag at least one correction item.')
    catalog = _correction_catalog(application, package)
    result = []
    seen = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise OriginationError('Every correction target must be an object.')
        identity = (str(raw.get('target_type') or ''), str(raw.get('target_key') or ''))
        if identity not in catalog or identity in seen:
            raise OriginationError('Choose each correction target once from the signed packet.')
        instruction = str(raw.get('instruction') or '').strip()[:1000]
        if not instruction:
            raise OriginationError('Give an instruction for every flagged correction.')
        seen.add(identity)
        result.append({
            'target_type': identity[0], 'target_key': identity[1][:240],
            'target_label': catalog[identity][:160], 'instruction': instruction,
        })
    return result


@transaction.atomic
def final_review_signed_packet(
    *, application_id, package_id, actor, expected_revision: int,
    expected_signed_hash: str, decision: str, reason: str,
    correction_items: Any, request_id: str,
) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    if application.events.filter(action__startswith='final_review_', request_id=request_id).exists():
        return application
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before final review.')
    if application.status != LoanOriginationApplication.STATUS_SIGNED_PENDING_APPROVAL:
        raise OriginationError('Only a signed conditional packet can receive final review.')
    if application.officer_id == actor.pk and not getattr(actor, 'is_superuser', False):
        raise OriginationError('The originating officer cannot approve their own application.')
    if (
        application.recheck_assigned_to_id
        and application.recheck_assigned_to_id != actor.pk
        and not getattr(actor, 'is_superuser', False)
    ):
        raise OriginationError(
            'This correction remains assigned to the original checker. '
            'Record a reasoned takeover before completing final review.'
        )
    package = application.signing_packages.select_for_update().filter(
        pk=package_id, conditional_approval=True,
        status=OriginationSigningPackage.STATUS_FULLY_SIGNED,
    ).first()
    if not package:
        raise OriginationError('The signed conditional packet was not found.')
    if not expected_signed_hash or expected_signed_hash != package.signed_document_hash:
        raise OriginationConflict('The signed packet hash changed. Open it again before deciding.')
    from core.services.origination_esign import signed_package_content
    _verified_package, signed_content = signed_package_content(package_id=package.pk)
    if _verified_package.signed_document_hash != expected_signed_hash or not signed_content:
        raise OriginationConflict('The signed packet bytes changed. Open them again before deciding.')
    if not application.events.filter(
        action='signed_packet_accessed', actor=actor,
        after_values__package_id=str(package.pk),
        after_values__signed_document_hash=package.signed_document_hash,
    ).exists():
        raise OriginationError('Open the complete signed packet before recording final review.')

    normalized = str(decision or '').strip().casefold()
    if normalized not in {'approve', 'request_correction', 'decline'}:
        raise OriginationError('Choose approve, request_correction, or decline.')
    reason = str(reason or '').strip()[:2000]
    if normalized in {'request_correction', 'decline'} and not reason:
        raise OriginationError('Give a reason for this final-review decision.')
    before = {'status': application.status, 'revision': application.revision}
    signed_at = package.finalized_at

    correction_kind = ''
    if normalized == 'approve':
        application.status = LoanOriginationApplication.STATUS_APPROVED
        application.recheck_assigned_to = None
        package.final_decision = 'approved'
        package.final_approved_signed_document_hash = package.signed_document_hash
        package.archive_status = 'pending'
    elif normalized == 'decline':
        application.status = LoanOriginationApplication.STATUS_DECLINED
        application.recheck_assigned_to = None
        package.status = OriginationSigningPackage.STATUS_DECLINED
        package.final_decision = 'declined'
    else:
        items = _normalized_items(application, package, correction_items)
        correction = OriginationCorrectionRequest.objects.create(
            application=application, application_revision=application.revision,
            reviewer=actor, summary=reason,
        )
        OriginationCorrectionItem.objects.bulk_create([
            OriginationCorrectionItem(correction_request=correction, **item) for item in items
        ])
        application.recheck_assigned_to = actor
        signature_only = all(
            item['target_type'] == OriginationCorrectionItem.TARGET_SIGNATURE_SLOT
            for item in items
        )
        correction_kind = 'signature_only' if signature_only else 'data_or_evidence'
        if signature_only:
            affected_role_instructions = {}
            for item in items:
                document_key, slot_key = item['target_key'].split('.', 1)
                action = package.actions.filter(
                    document_key=document_key, slot_key=slot_key,
                    mode=OriginationSigningAction.MODE_VERIFIED,
                    invalidation__isnull=True,
                ).order_by('-created_at').first()
                if not action:
                    raise OriginationConflict('A flagged signature changed. Refresh the final review.')
                affected_role_instructions.setdefault(action.signer_role, item['instruction'])
            for signer_role, instruction in affected_role_instructions.items():
                role_actions = package.actions.filter(
                    signer_role=signer_role,
                    action_type__in=[
                        OriginationSigningAction.TYPE_SIGNATURE,
                        OriginationSigningAction.TYPE_DATE_SIGNED,
                    ],
                    mode=OriginationSigningAction.MODE_VERIFIED,
                    invalidation__isnull=True,
                ).order_by('created_at', 'id')
                if not role_actions.exists():
                    raise OriginationConflict('A flagged signature changed. Refresh the final review.')
                for action in role_actions:
                    OriginationSigningActionInvalidation.objects.create(
                        action=action, reason=instruction, invalidated_by=actor,
                        request_id=_slot_request_id(request_id, 'invalidate', str(action.pk)),
                    )
            affected_roles = set(affected_role_instructions)
            if affected_roles:
                package.signer_sessions.filter(
                    signer_role__in=affected_roles, is_active=True,
                ).update(is_active=False, status='cancelled', invalidated_at=timezone.now())
            package.status = OriginationSigningPackage.STATUS_IN_PROGRESS
            package.signed_document_hash = ''
            package.pending_signed_document = bytes()
            package.finalized_at = None
            package.archive_status = 'not_ready'
            application.status = LoanOriginationApplication.STATUS_PARTIALLY_SIGNED
        else:
            package.status = OriginationSigningPackage.STATUS_CANCELLED
            package.signer_sessions.filter(is_active=True).update(
                is_active=False, status='cancelled', invalidated_at=timezone.now(),
            )
            application.status = LoanOriginationApplication.STATUS_CORRECTION_REQUIRED
        package.final_decision = 'correction_required'

    now = timezone.now()
    package.final_reviewed_by = actor
    package.final_reviewed_at = now
    package.final_review_reason = reason
    package.save()
    application.final_reviewed_by = actor
    application.final_reviewed_at = now
    application.revision += 1
    application.save(update_fields=[
        'status', 'recheck_assigned_to', 'final_reviewed_by',
        'final_reviewed_at', 'revision', 'updated_at',
    ])
    _record_event(
        application, f'final_review_{normalized}', actor=actor, request_id=request_id,
        before=before, after={
            'status': application.status, 'package_id': str(package.pk),
            'signed_document_hash': expected_signed_hash, 'reason': reason,
            'correction_kind': correction_kind,
            'external_resigning_required': correction_kind == 'data_or_evidence',
            'signed_to_review_seconds': (
                max(0, int((now - signed_at).total_seconds())) if signed_at else None
            ),
        },
    )
    if normalized == 'approve':
        from core.services.origination_esign import _archive_signed_package_after_commit
        transaction.on_commit(lambda: _archive_signed_package_after_commit(
            package_id=package.pk, signed_hash=package.signed_document_hash,
        ))
    return application
