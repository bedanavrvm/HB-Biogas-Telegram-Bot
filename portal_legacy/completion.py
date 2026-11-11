"""Close verified initial loading while retaining explicitly reviewed source holds."""
import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from . import importer
from .models import LegacyUpload
from .registers import owns_case


def values_digest(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()


def _exceptions(entries: list) -> list[dict]:
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise ValueError('Explicitly account for 1–500 retained source exceptions.')
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'id', 'reason', 'values_sha256'}:
            raise ValueError('Each retained exception needs its draft ID, review reason and source fingerprint.')
        identity, reason, digest = str(entry['id']), entry['reason'], entry['values_sha256']
        if (not identity.isdigit() or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
                or not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('Invalid retained source exception.')
        result.append({'id': identity, 'reason': reason.strip(), 'values_sha256': digest})
    if len({row['id'] for row in result}) != len(result):
        raise ValueError('Retained exceptions must name distinct source drafts.')
    return sorted(result, key=lambda row: int(row['id']))


@transaction.atomic
def complete_review(upload, *, actor, access, expected_revision, request_key: str, exceptions: list):
    """Release only this verified register's hold; no case or Google writes.

    The caller holds the existing upload lease. The shared Sheet mutex serializes
    closure with destructive replacement/admission. Exact exceptions remain in
    their original drafts and sealed workbook, with one immutable review audit.
    """
    from core.services.compliance_audit import record_event
    from core.services.miniapp_deletion_sheets import lock_sheet_mutations

    importer.authorize(actor, access, upload.batch.group, branch='')
    if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 120:
        raise ValueError('A request key of 1–120 characters is required.')
    entries = _exceptions(exceptions)
    lock_sheet_mutations()
    saved = LegacyUpload.objects.select_for_update(of=('self',)).select_related('batch__group').get(pk=upload.pk)
    importer.authorize(actor, access, saved.batch.group, branch='')
    if not upload.lease or saved.lease != upload.lease or not saved.lease_until or saved.lease_until <= timezone.now():
        raise ValueError('Acquire the current upload lease before completing review.')
    prior = saved.state.get('review_completion')
    if prior:
        if (prior['request_key'] != request_key or prior['exceptions'] != entries
                or saved.phase != 'complete' or saved.frozen):
            raise ValueError('This completion request belongs to different review facts.')
        upload.refresh_from_db()
        return prior
    if saved.revision != expected_revision:
        raise ValueError('This workspace changed. Refresh and review the retained exceptions again.')
    if saved.mode != 'initial' or saved.phase != 'ready' or not saved.frozen or not saved.state.get('cleanup_complete'):
        raise ValueError('Only a held, ready initial import can complete with reviewed exceptions.')
    sync = saved.state.get('row_sync', {})
    if sync.get('stage') != 'done' or sync.get('plans') or saved.state.get('sync_error'):
        raise ValueError('Finish and verify every saved Sheet write before completing review.')
    drafts = list(saved.drafts.select_for_update(of=('self',)).select_related('legacy__farmer').order_by('pk'))
    pending = [draft for draft in drafts if draft.legacy_id is None]
    if {str(draft.pk) for draft in pending} != {row['id'] for row in entries}:
        raise ValueError('Account for every unimported source row, and only those rows.')
    facts = {row['id']: row for row in entries}
    for draft in pending:
        if draft.approved:
            raise ValueError('Apply or explicitly deselect outstanding approved rows before completing review.')
        if values_digest(draft.values) != facts[str(draft.pk)]['values_sha256']:
            raise ValueError('A retained source row changed. Review its current facts.')
    imported = [draft for draft in drafts if draft.legacy_id is not None]
    if not imported:
        raise ValueError('Import and verify at least one case before completing review.')
    case_ids = set()
    for draft in imported:
        row = draft.legacy
        receipt = draft.reconciliation.get('sheet_receipt') or {}
        receipt_revision = receipt.get('revision')
        if (not row.committed_at or not row.farmer_id or not row.publication_ready
                or receipt.get('verified') is not True or receipt.get('reference_format') != 'staff'):
            raise ValueError('Every imported row needs a verified staff-reference Sheet receipt.')
        if (receipt.get('spreadsheet') != sync.get('spreadsheet') or receipt.get('sheet') != sync.get('sheet')
                or receipt.get('row') != sync.get('case_rows', {}).get(str(row.farmer_id))
                or not isinstance(receipt.get('digest'), str) or len(receipt['digest']) != 64
                or receipt_revision is not None and (type(receipt_revision) is not int
                    or receipt_revision < 0 or receipt_revision > row.farmer.workflow_revision)):
            raise ValueError('An imported Sheet receipt does not match its saved case/register binding.')
        if (row.batch_id != saved.batch_id or row.source_sheet != saved.source_sheet
                or not owns_case(saved, row.farmer) or row.farmer_id in case_ids):
            raise ValueError('Reconcile duplicate or cross-register case bindings before completing review.')
        case_ids.add(row.farmer_id)
    completed_at = timezone.now().isoformat()
    completion = {'request_key': request_key, 'actor_id': str(actor.pk), 'completed_at': completed_at,
        'source_sheet': saved.source_sheet, 'imported': len(imported), 'synced': len(imported),
        'retained_exceptions': len(entries), 'exceptions': entries,
        'source_rows': {str(draft.pk): draft.source_row for draft in pending}}
    saved.state = {**saved.state, 'review_completion': completion}
    saved.phase, saved.frozen = 'complete', False
    importer.save(saved)
    record_event(workflow='jawabu_portal', action='legacy_review_completed_with_exceptions',
        subject_type='LegacyUpload', subject_id=str(saved.pk),
        deduplication_key=f'portal-legacy-review-completion:{saved.pk}:{request_key}',
        actor=actor, request_id=request_key, source_model='portal_legacy.LegacyUpload',
        before_values={'phase': 'ready', 'frozen': True},
        after_values={'phase': 'complete', 'frozen': False},
        metadata={'source_sheet': saved.source_sheet, 'group_id': str(saved.batch.group_id),
            'imported': len(imported), 'verified_receipts': len(imported), 'retained_exceptions': entries,
            'no_case_or_external_writes': True}, sensitive=True)
    upload.refresh_from_db()
    return completion
