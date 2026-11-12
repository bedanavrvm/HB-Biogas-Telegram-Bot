"""Reviewed external facts amend a case without changing its intake origin."""
import re

from django.db import transaction
from django.utils import timezone

from core.services.jawabu_validation import parse_business_date
from .workbook import literal, token

POLICY = 'reconcile-v1'
GUIDANCE_FIELDS = {'guidance_decision', 'guidance_comment', 'guidance_hb_action', 'guidance_november_comment'}
POSITION_LABELS = {'credit': 'Credit Analysis', 'deferred': 'Deferred / On Hold', 'rejected': 'Rejected',
    'withdrawn': 'Withdrawn', 'cash': 'Opted for Cash', 'other': 'Opted for Other Partner',
    'rescheduled': 'Rescheduled', 'jbl_visit': 'Awaiting JBL Visit'}
OUTCOMES = {'credit': 'APPROVED', 'deferred': 'DEFERRED / ON HOLD', 'rejected': 'REJECTED',
    'withdrawn': 'WITHDRAWN', 'cash': 'OPTED FOR CASH', 'other': 'OPTED FOR OTHER PARTNER',
    'rescheduled': 'RESCHEDULED', 'jbl_visit': 'JBL TO SCHEDULE VISIT'}
NOTE_FIELDS = ('case_comment_history', 'guidance_comment', 'guidance_hb_action', 'guidance_november_comment')
FINANCIAL_FIELDS = {'order_number', 'payment_number', 'invoice_number', 'invoice_amount', 'discount',
    'requisition_date', 'invoice_date', 'legacy_deposit_paid_jbl'}


def enabled(upload):
    return upload.mode == 'updates' and upload.state.get('update_policy') == POLICY


def decision(value):
    text = token(value)
    if re.match(r'def+er', text) or text in {'hold', 'onhold'}: return 'deferred'
    if text.startswith(('reject', 'rejcet')): return 'rejected'
    if text.startswith(('optedcash', 'optedforcash', 'paidcashtohb')): return 'cash'
    if 'otherfinancier' in text or 'otherpartner' in text: return 'other'
    if text.startswith(('withdr', 'cancel')): return 'withdrawn'
    if text.startswith('approved'):
        return '' if 'pendingminimumdeposit' in text else 'credit'
    if text == 'rescheduled': return 'rescheduled'
    if text in {'jawabutoschedulevisit', 'jbltoschedulevisit', 'awaitingjblvisit'}: return 'jbl_visit'
    return ''


def suggested_position(values, override=''):
    if override == 'keep': return '', ''
    if override:
        if override not in POSITION_LABELS: raise ValueError('Choose a supported reconciliation position.')
        return override, 'Explicit reviewed position; retained source guidance remains in the audit.'
    guidance = values.get('guidance_decision', '')
    latest = str(values.get('guidance_comment') or '')
    if str(guidance).strip() and token(guidance) != 'opted' and not decision(guidance):
        return '', 'Decision guidance requires its owning workflow or an explicit reviewed position.'
    result = decision(guidance) or decision(values.get('legacy_outcome', ''))
    if token(guidance) == 'opted' and re.search(r'\bopted\s+(?:for\s+)?cash\b', latest, re.I): result = 'cash'
    # A stated current follow-up overrides a contradictory short guide cell.
    if re.search(r'\b(?:requested|needs?)\b.{0,60}\b(?:more time|discuss|decide)\b', latest, re.I): result = 'deferred'
    if re.search(r'\bin (?:process (?:for|of)|progress).*?credit analys', latest, re.I): result = 'credit'
    return result, 'Reviewed spreadsheet outcome; no historical approval actor or timestamp inferred.'


def position_error(case, target, values):
    if not target: return ''
    if case.status != 'active': return 'Only active cases can be reconciled.'
    from payments.models import PaymentBatchCase
    from core.models import ParsedInvoice, RequisitionBatch
    if RequisitionBatch.objects.filter(farmer_ids__contains=[str(case.pk)]).exists() or PaymentBatchCase.objects.filter(farmer=case).exists() or ParsedInvoice.objects.filter(matched_farmer=case).exists():
        return 'Live order/invoice/payment evidence requires its owning workflow correction.'
    if case.order_number or case.requisition_batch_id or case.invoice_number or hasattr(case, 'homebiogas_action'):
        return 'Keep the later order/HB workflow. Use its owning correction process to change it.'
    source_order = str(values.get('order_number') or '').strip()
    if source_order not in {'', '-'}:
        return 'Verify and link the existing source order through its owning workflow; do not allocate another number.'
    if case.final_decided_at or case.final_decided_by:
        return 'A recorded final decision requires its owning workflow correction.'
    if case.workflow_state not in {'legacy_review', 'jbl_visit', 'credit', 'deferred', 'rejected', 'withdrawn'}:
        return 'This position cannot be reconciled from the current workflow.'
    if target in {'credit', 'jbl_visit', 'rescheduled'} and case.workflow_state in {'rejected', 'withdrawn'} and case.pipeline_events.filter(action__in=['case_withdrawn', 'credit_decision_recorded', 'final_decision_recorded']).exists():
        return 'Resume a natively closed case through its owning workflow before reconciling source progress.'
    if case.deferred_until and case.deferred_until < timezone.now() and target in {'credit', 'jbl_visit', 'rescheduled'}:
        return 'This deferral expired. Complete the existing reappraisal workflow before resuming.'
    if target == 'rescheduled':
        planned = parse_business_date(values.get('reconciliation_next_visit_date', ''))
        if not planned: return 'Choose an exact next visit date; vague source scheduling remains held.'
        if planned < timezone.localdate(): return 'Next visit date cannot be earlier than today.'
    return ''


def current_position(case):
    if case.workflow_state == 'withdrawn':
        return {'Opted for Cash': 'cash', 'Opted for Other Partner': 'other'}.get(case.jbl_visit_status, 'withdrawn')
    if case.workflow_state == 'jbl_visit' and case.jbl_visit_status == 'Rescheduled': return 'rescheduled'
    return case.workflow_state


def changes(case, values, baseline, review):
    from core.services.jawabu_comments import master_comment_history
    result = {}
    existing = master_comment_history(case)
    seen = token(existing + ' ' + str(case.comments or ''))
    notes = []
    for key in NOTE_FIELDS:
        raw = str(values.get(key) or '').strip()
        normalized = token(raw)
        if normalized and normalized not in {'nocomments', 'nocomment'} and normalized not in seen:
            notes.append(raw); seen += normalized
    if notes:
        result['reported_notes'] = {'before': existing, 'after': '\n\n'.join(notes), 'error': '', 'app_conflict': False}
    target, reason = suggested_position(values, review.get('position_override', ''))
    if not target and reason and review.get('position_override') != 'keep':
        result['reconciled_position'] = {'before': POSITION_LABELS.get(current_position(case), current_position(case)),
            'after': str(values.get('guidance_decision', '')), 'target': '', 'reason': reason,
            'error': reason, 'app_conflict': False}
    reviewed = bool(review.get('position_override')) or any(token(values.get(k)) != token(baseline.get(k)) for k in GUIDANCE_FIELDS)
    source_changed = decision(values.get('legacy_outcome')) != decision(baseline.get('legacy_outcome'))
    if target and (reviewed or source_changed) and current_position(case) != target:
        conflict = case.pipeline_events.filter(action__in=['jbl_visit_completed', 'credit_decision_recorded',
            'final_decision_recorded', 'case_withdrawn', 'withdrawal_resumed']).exists()
        result['reconciled_position'] = {'before': POSITION_LABELS.get(current_position(case), current_position(case)),
            'after': POSITION_LABELS[target], 'target': target, 'reason': reason,
            'error': position_error(case, target, {**values, 'reconciliation_next_visit_date': review.get('next_visit_date', '')}),
            'app_conflict': conflict}
    return result


@transaction.atomic
def apply(draft, farmer, selected, actor, access, request_id):
    from .importer import authorize
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.jawabu_comments import record_case_comment, master_comment_history
    from core.services.jawabu_customer_quality import record_field_provenance
    from core.services.workflow_transitions import next_workflow_revision
    authorize(actor, access, draft.upload.batch.group, branch=farmer.branch, product=farmer.payment_product)
    # The caller locks the case and checks the staged revision before any facts change.
    source_values = {key: literal(value) for key, value in draft.values.items()
        if key in selected or 'reported_notes' in selected and key in NOTE_FIELDS
        or 'reconciled_position' in selected and key in {'legacy_outcome', *GUIDANCE_FIELDS}}
    replay = farmer.pipeline_events.filter(request_id=request_id + ':reconciled').first()
    if replay: return replay
    before = {}; after = {}; fields = []
    target = ''
    if 'reconciled_position' in selected:
        target = draft.proposal['changes']['reconciled_position']['target']
        if target not in POSITION_LABELS: raise ValueError('Choose a supported reconciliation position.')
        error = position_error(farmer, target, {**draft.values, 'reconciliation_next_visit_date': draft.reconciliation.get('next_visit_date', '')})
        if error: raise ValueError(error)
        before = {key: literal(getattr(farmer, key)) for key in ['workflow_state', 'jbl_visit_status', 'jbl_next_visit_date',
            'deferred_at', 'deferred_stage', 'deferred_until', 'withdrawn_stage', 'credit_decision', 'final_decision']}
        farmer.workflow_state = {'cash': 'withdrawn', 'other': 'withdrawn', 'rescheduled': 'jbl_visit'}.get(target, target)
        farmer.jbl_next_visit_date = parse_business_date(draft.reconciliation.get('next_visit_date')) if target == 'rescheduled' else None
        if target in {'cash', 'other', 'rescheduled'}:
            farmer.jbl_visit_status = POSITION_LABELS[target]
        elif target == 'credit' and farmer.jbl_visit_date:
            farmer.jbl_visit_status = 'Visited, Awaiting Credit Analysis'
        if target == 'credit':
            if not farmer.credit_decided_at and not farmer.credit_decided_by: farmer.credit_decision = ''
            if not farmer.final_decided_at and not farmer.final_decided_by: farmer.final_decision = ''
        # Unknown external hold dates do not acquire a fictitious 60-day deadline.
        farmer.deferred_at = None; farmer.deferred_until = None
        if target != 'deferred': farmer.deferred_stage = ''
        farmer.withdrawn_stage = ''
        if farmer.workflow_state != before['workflow_state']:
            before['workflow_state_entered_at'] = literal(farmer.workflow_state_entered_at)
            farmer.workflow_state_entered_at = timezone.now()
        after = {key: literal(getattr(farmer, key)) for key in before}
        fields = list(after)
    revision_before, revision_after = next_workflow_revision(farmer)
    farmer.save(update_fields=[*fields, 'workflow_revision', 'updated_at'])
    record_field_provenance(farmer, old_values=before, new_values=after, source='spreadsheet_reconciliation',
        source_reference=str(draft.upload.pk), source_row_number=draft.source_row, actor=actor.get_username())
    external_fields = [key for key in selected if key.endswith('_date') or key == 'reconciled_position']
    event = record_pipeline_event(farmer, action='source_reconciled', stage_key='case_history',
        actor=actor.get_username(), actor_user=actor, source='spreadsheet_reconciliation', request_id=request_id + ':reconciled',
        old_values=before, new_values=after, from_state=before.get('workflow_state', farmer.workflow_state),
        to_state=farmer.workflow_state, revision_before=revision_before, revision_after=revision_after,
        reason='Reviewed external workbook amendment; original intake origin retained.',
        metadata={'upload_id': str(draft.upload.pk), 'source_hash': draft.upload.digest, 'source_row': draft.source_row,
            'source_sheet': draft.upload.source_sheet, 'source_values': source_values,
            'externally_reported_fields': external_fields, 'precision': 'date' if 'jbl_visit_date' in selected else 'unknown',
            'position_override': draft.reconciliation.get('position_override', '')})
    if 'reported_notes' in selected:
        existing = token(master_comment_history(farmer))
        for index, note in enumerate(selected['reported_notes'].split('\n\n')):
            if token(note) and token(note) not in existing:
                record_case_comment(farmer=farmer, stage_key='correction', comment=note, actor=actor.get_username(),
                    actor_user=actor, request_id=f'{request_id}:note:{index}', pipeline_event=event)
                existing += token(note)
    return event
