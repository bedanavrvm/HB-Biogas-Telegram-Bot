"""Explicit, source-preserving SysUp review atop the existing canonical importer."""
import hashlib
import json
from uuid import UUID
from django.db import transaction
from core.models import JawabuFarmerMaster, JawabuFarmerUploadBatch
from core.services.system_export import commit_system_export_review_batch

FIELDS = ('ID NO', 'Customer ID', 'Mobile No', 'Name', 'Branch', 'Loan Officer', 'Product Name', 'LGF Balance')


@transaction.atomic
def commit_review(batch_id, submitted, *, revision, request_id, actor, authorize):
    if not request_id or not isinstance(submitted, list):
        raise ValueError('Refresh SysUp before committing this review.')
    if not isinstance(revision, (str, int)):
        raise ValueError('Refresh SysUp before committing this review.')
    digest = hashlib.sha256(json.dumps(submitted, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    batch = JawabuFarmerUploadBatch.objects.select_for_update().get(pk=batch_id)
    for replay in batch.portal_commit_replays or []:
        if replay.get('request_id') == request_id:
            if replay.get('payload_hash') != digest or replay.get('actor') != actor.pk:
                raise ValueError('This request was already used for another SysUp change.')
            return batch, replay['result']
    if int(revision) != batch.portal_revision:
        raise ValueError('This upload changed. Refresh SysUp and review it again.')
    if not all(isinstance(item, dict) for item in submitted):
        raise ValueError('Refresh SysUp before committing this review.')
    if not all(isinstance(item.get('approved'), bool) for item in submitted):
        raise ValueError('Select the SysUp rows to commit, then retry.')
    if not any(item.get('approved') for item in submitted) and not (
            batch.parsed_rows and all(row.get('Import Status') == 'already_current' for row in batch.parsed_rows)):
        raise ValueError('Select at least one matched SysUp row to commit.')
    # Stable lock order protects two imports reviewing overlapping cases.
    selected_ids = sorted({str(item.get('Matched Farmer ID') or '') for item in submitted if item.get('approved')})
    try:
        for selected_id in selected_ids:
            UUID(selected_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Choose an available Portal case for each selected row.') from exc
    locked = {str(farmer.pk): farmer for farmer in JawabuFarmerMaster.objects.select_for_update().filter(pk__in=selected_ids).order_by('pk')}
    source = {str(row.get('row_fingerprint')): row for row in batch.parsed_rows or []}
    seen = set()
    edits = {}
    for item in submitted:
        fingerprint = str(item.get('row_fingerprint') or '')
        if fingerprint not in source or fingerprint in seen:
            raise ValueError('The source rows changed. Refresh SysUp.')
        seen.add(fingerprint)
        row = dict(source[fingerprint])
        row['approved'] = bool(item.get('approved'))
        if row['approved']:
            farmer = locked.get(str(item.get('Matched Farmer ID')))
            if farmer is None:
                raise ValueError('A selected case is no longer available. Refresh SysUp.')
            authorize(farmer)
            if int(item.get('case_revision') or 0) != farmer.workflow_revision:
                raise ValueError('A selected case changed. Refresh its values before importing.')
            row['Matched Farmer ID'] = str(farmer.pk)
            row['case_revision'] = farmer.workflow_revision
            choices = item.get('field_choices') or {}
            corrections = item.get('source_corrections') or {}
            if not isinstance(choices, dict) or not isinstance(corrections, dict) or set(choices) - set(FIELDS) or set(corrections) - set(FIELDS):
                raise ValueError('Unsupported SysUp field. Refresh the review.')
            for field, choice in choices.items():
                if choice not in ('portal', 'sysup'):
                    raise ValueError('Choose Keep Portal or Use SysUp.')
                if choice == 'portal':
                    row[field] = ''  # The importer preserves empty source values.
            for field, value in corrections.items():
                if choices.get(field) != 'portal':
                    row[field] = str('' if value is None else value).strip()
            row['field_choices'] = choices
            row['source_corrections'] = {field: {'before': source[fingerprint].get(field), 'after': value}
                                         for field, value in corrections.items()}
        edits[fingerprint] = row
    rows = [edits.get(str(row.get('row_fingerprint')), {**row, 'approved': False}) for row in batch.parsed_rows or []]
    result = commit_system_export_review_batch(batch, rows, actor=actor.get_full_name() or actor.get_username())
    batch.portal_revision += 1
    batch.portal_commit_replays = [*(batch.portal_commit_replays or []),
        {'request_id': request_id, 'payload_hash': digest, 'actor': actor.pk, 'result': result}][-100:]
    batch.save(update_fields=['portal_revision', 'portal_commit_replays', 'updated_at'])
    return batch, result
