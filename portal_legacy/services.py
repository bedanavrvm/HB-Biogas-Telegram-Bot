"""Reviewed, scoped import. No provider writes, approval fabrication or identity merges."""
import hashlib
import re
from types import SimpleNamespace
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from core.models import JawabuFarmerMaster
from .models import LegacyBatch, LegacyRow, LegacyEvent
from .workbook import read_workbook, propose


def authorize(actor, access, group, *, branch=None, product='', farmer=None):
    from core.services.portal_permissions import portal_access_decision
    from core.services.access_policies import OPERATIONS_ADMIN_ROLE
    def owns_legacy_authority(decision):
        return decision.allowed and (actor.is_superuser or bool(set(decision.roles) & {OPERATIONS_ADMIN_ROLE, 'IT'}))
    if not actor or not actor.is_active:
        raise PermissionDenied('Active Portal staff identity required.')
    if not group.enabled:
        raise PermissionDenied('This Portal owner is disabled.')
    if farmer is not None and farmer.group_configuration_id != group.pk:
        raise PermissionDenied('The case owner changed; reconcile its legacy ownership before writing.')
    if branch is None and farmer is None and not actor.is_superuser:
        from core.models import AccessGrant
        from django.db.models import Q
        grants = AccessGrant.objects.filter(user=actor, workflow='jawabu_portal', active=True).filter(Q(group_configuration=group) | Q(group_configuration__isnull=True))
        for grant in grants:
            if owns_legacy_authority(portal_access_decision(actor, 'portal.case.correct', access=access, branch=grant.branch,
                    product=grant.product, group_configuration=group, enforce_group_scope=True)):
                return
        raise PermissionDenied('No applicable Portal import/correction grant in this group.')
    resource = farmer or SimpleNamespace(branch=branch or '', payment_product=product, group_configuration_id=group.pk)
    decision = portal_access_decision(actor, 'portal.case.correct', access=access, resource=resource,
                                      group_configuration=group, enforce_group_scope=True)
    if not owns_legacy_authority(decision):
        raise PermissionDenied('Scoped Portal Operations/IT authority is required.')


@transaction.atomic
def stage(content, *, namespace, group, actor, access):
    authorize(actor, access, group)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', namespace or ''):
        raise ValueError('Supply a stable cutover namespace (letters, digits, dash or underscore).')
    records = read_workbook(content); digest = hashlib.sha256(content).hexdigest()
    # Group lock serializes initial namespace creation as well as corrected-file staging.
    type(group).objects.select_for_update(no_key=True).get(pk=group.pk)
    if LegacyBatch.objects.filter(group=group, source_hash=digest).exclude(namespace=namespace).exists():
        raise ValueError('This workbook is already staged. Resume its original namespace instead of creating another import.')
    batch, _ = LegacyBatch.objects.get_or_create(group=group, namespace=namespace,
        defaults={'source_hash': digest, 'created_by': actor})
    batch = LegacyBatch.objects.select_for_update().get(pk=batch.pk)
    found = set(); pending = []; checked_branches = set()
    existing = {(r.source_sheet, r.source_row): r for r in batch.rows.all()}
    for sheet, number, values in records:
        branch = values.get('branch', ''); product = values.get('payment_product', '')
        if (branch, product) not in checked_branches:
            authorize(actor, access, group, branch=branch, product=product); checked_branches.add((branch, product))
        candidate = propose(values)
        row = existing.get((sheet, number))
        created = row is None
        if created:
            row = LegacyRow(batch=batch, source_sheet=sheet, source_row=number, values=values, proposal=candidate, source_hash=digest)
            pending.append(row)
        found.add(row.pk)
        meaningful = lambda data: {key: value for key, value in data.items() if value not in ('', '-', None)}
        if not created and not row.committed_at and row.values == values and row.proposal.get('issues') == ['Row absent from latest reviewed workbook; restage it before commit.']:
            row.proposal = candidate; row.revision += 1; row.save(update_fields=['proposal', 'revision'])
        if not created and meaningful(row.values) != meaningful(values):
            authorize(actor, access, group, branch=row.values.get('branch', ''), product=row.values.get('payment_product', ''))
            if row.committed_at:
                raise ValueError(f'{sheet} row {number}: committed values changed; reconcile the existing case explicitly.')
            before = row.values; row.values = values; row.proposal = candidate; row.source_hash = digest; row.revision += 1; row.save()
            LegacyEvent.objects.create(row=row, actor=actor, request_key='source:'+digest,
                                       action='source_revised', payload={'before': before, 'after': values})
    LegacyRow.objects.bulk_create(pending, batch_size=500)
    for row in batch.rows.filter(committed_at__isnull=True).exclude(pk__in=found):
        authorize(actor, access, group, branch=row.values.get('branch', ''), product=row.values.get('payment_product', ''))
        row.proposal = {**row.proposal, 'issues': ['Row absent from latest reviewed workbook; restage it before commit.']}
        row.save(update_fields=['proposal'])
    batch.source_hash = digest; batch.save(update_fields=['source_hash'])
    return batch


def row_payload(row):
    fields = row.proposal.get('fields', {})
    identity_collision = bool(fields.get('national_id') and JawabuFarmerMaster.objects.filter(national_id=fields['national_id']).exists())
    matches = JawabuFarmerMaster.objects.filter(group_configuration=row.batch.group,
        national_id=fields.get('national_id'), branch=row.values.get('branch', '')).values('id', 'case_reference_number') if fields.get('national_id') else []
    return {'id': str(row.pk), 'sheet': row.source_sheet, 'source_row': row.source_row,
            'name': row.values.get('customer_name', ''), 'revision': row.revision,
            'proposal': row.proposal, 'farmer_id': str(row.farmer_id or ''),
            'committed': bool(row.committed_at), 'continuation_confirmed': row.continuation_confirmed,
            'source_values': row.values,
            'identity_collision': identity_collision,
            'existing_cases': [{'id': str(m['id']), 'reference': f"JBL-{m['case_reference_number']}"} for m in matches]}


def case_payload(farmer):
    row = LegacyRow.objects.filter(farmer=farmer, committed_at__isnull=False).order_by('committed_at', 'pk').first()
    if row is None: return None
    return {'row_id': str(row.pk), 'source_sheet': row.source_sheet, 'source_row': row.source_row,
            'reported_outcome': row.proposal.get('outcome', ''), 'stage': row.proposal.get('stage', ''),
            'reason': row.values.get('legacy_reason', ''), 'comment': row.values.get('case_comment_history', ''),
            'issues': row.proposal.get('issues', []), 'revision': row.revision,
            'source_notes': {key.replace('_', ' '): row.values[key] for key in ('pending_installation_comment', 'pending_commissioning_comment', 'cs_remarks') if row.values.get(key)},
            'reported_references': {key.replace('_', ' '): row.values[key] for key in ('order_number', 'invoice_number', 'payment_number') if row.values.get(key)},
            'missing_fields': [key.replace('_', ' ') for key in ('national_id', 'primary_phone', 'hbg_visit_date', 'invoice_number', 'invoice_date', 'installation_date', 'commissioning_date') if not row.values.get(key) or row.values.get(key) == '-'],
            'continuation_confirmed': row.continuation_confirmed,
            'needs_hb_handover': bool(farmer.legacy_fulfillment_partner) and farmer.workflow_state == 'ordered' and not hasattr(farmer, 'homebiogas_action'),
            'evidence': row.proposal.get('evidence', []), 'publication_ready': row.publication_ready}


def _existing_collision(row, fields):
    query = JawabuFarmerMaster.objects.filter(group_configuration=row.batch.group)
    if fields.get('national_id') and query.filter(national_id=fields['national_id']).exists(): return True
    return False


def _retain_numbers(row, actor, *, allow_occupied=False):
    from requisitions.models import OrderSequenceState, OrderNumberClaim
    from payments.models import PaymentSequenceState, PaymentNumberClaim
    for field, sequence_model, claim_model in [('order_number', OrderSequenceState, OrderNumberClaim),
                                               ('payment_number', PaymentSequenceState, PaymentNumberClaim)]:
        raw = str(row.proposal['fields'].get(field, '')).strip()
        if not raw: continue
        match = re.fullmatch(r'(?:(HB|ECO)-|#)?(\d+)', raw, re.I)
        if not match: raise ValueError(f'{field}: confirm the allocator reference format before commit.')
        kwargs = {'group_configuration': row.batch.group}
        if field == 'order_number':
            kwargs['partner'] = 'ECOCONSERVE' if match[1] and match[1].upper() == 'ECO' or 'eco' in row.source_sheet.lower() else 'HB'
        sequence, _ = sequence_model.objects.get_or_create(**kwargs, defaults={'next_number': 1, 'updated_by': actor})
        sequence = sequence_model.objects.select_for_update().get(pk=sequence.pk)
        before = sequence.next_number
        claim, _ = claim_model.objects.get_or_create(sequence=sequence, number=int(match[2]), defaults={'retired': True})
        if claim.batch_id or not claim.retired:
            if allow_occupied: continue  # The current governed allocation/release wins over older source evidence.
            raise ValueError(f'{field}: number is bound to an existing/released workspace; reconcile it before import.')
        sequence.next_number = max(sequence.next_number, int(match[2])+1)
        sequence.revision += 1; sequence.updated_by = actor
        sequence.adjustment_reason = f'Legacy cutover {row.batch.namespace}; retained reference, no signed document inferred.'
        sequence.save()
        from requisitions.models import OrderSequenceEvent
        from payments.models import PaymentSequenceEvent
        event_model = OrderSequenceEvent if field == 'order_number' else PaymentSequenceEvent
        event_model.objects.create(sequence=sequence, action='legacy_import', number_before=before,
            number_after=sequence.next_number, revision_after=sequence.revision, actor=actor,
            reason=sequence.adjustment_reason, request_id='legacy:'+str(row.pk))


def require_finance_reconciled(group_id):
    from django.db.models import Q
    rows = LegacyRow.objects.filter(batch__group_id=group_id)
    if rows.filter(committed_at__isnull=False).exists() and rows.filter(committed_at__isnull=True).filter(
        Q(proposal__fields__order_number__gt='') | Q(proposal__fields__payment_number__gt='')).exists():
        raise ValueError('Legacy cutover finance references remain uncommitted. Reconcile those rows before generating new numbered documents.')


def _hb_baseline(row, farmer, actor):
    from hb_operations.models import HomeBiogasAction
    data = row.proposal['fields']; status = data.get('installation_status', '').upper()
    commissioned = data.get('commissioning_status', '').lower() == 'commissioned'
    if not row.proposal.get('hb_known'): return
    installed_on = data.get('installation_date') or None
    commissioned_on = data.get('commissioning_date') or None
    disputed = any('completion is in the future' in issue or 'Commissioning predates installation' in issue for issue in row.proposal.get('issues', []))
    if disputed:
        # A confirmed physical milestone does not establish which conflicting old date was correct.
        installed_on = commissioned_on = None
        row.proposal['hb_dates_unconfirmed'] = True; row.save(update_fields=['proposal'])
    HomeBiogasAction.objects.create(farmer=farmer, legacy_origin=row,
        source_order_number=data.get('order_number', ''), source_requisition_version=0,
        installation_status='installed' if commissioned or status == 'INSTALLED' else 'closed' if status == 'CLOSED' else 'open',
        installation_date=installed_on if commissioned or status == 'INSTALLED' else None,
        planned_installation_date=(data.get('installation_date') or None) if not commissioned and status != 'INSTALLED' else None,
        commissioning_status='commissioned' if commissioned else 'not_commissioned' if str(data.get('commissioning_status', '')).lower() == 'not commissioned' else 'unknown',
        commissioning_date=commissioned_on,
        serial_number=data.get('serial_number', ''),
        readiness_status={'Ready':'ready','Not ready':'not_ready','Not confirmed':'not_confirmed'}.get(data.get('readiness_status'), '') if status != 'INSTALLED' and not commissioned else '',
        installation_report_status={'Yes':'yes','No':'no','Not applicable':'not_applicable'}.get(data.get('installation_report_status'), ''),
        pending_installation_comment=data.get('pending_installation_comment', ''),
        pending_commissioning_comment=data.get('pending_commissioning_comment', ''),
        cs_remarks=data.get('cs_remarks', ''), created_by=None)


@transaction.atomic
def commit_row(row_id, *, expected_revision, request_key, actor, access, existing_case_id='', separate_unit_note=''):
    owner = LegacyRow.objects.select_related('batch__group').get(pk=row_id)
    authorize(actor, access, owner.batch.group, branch=owner.values.get('branch', ''), product=owner.values.get('payment_product', ''))
    # Serialize imports without blocking unrelated case FK inserts into the same group.
    type(owner.batch.group).objects.select_for_update(no_key=True).get(pk=owner.batch.group_id)
    row = LegacyRow.objects.select_for_update(of=('self',)).select_related('batch__group').get(pk=row_id)
    authorize(actor, access, row.batch.group, branch=row.values.get('branch', ''), product=row.values.get('payment_product', ''))
    if not request_key or len(request_key) > 120: raise ValueError('A request key of 1–120 characters is required.')
    if row.committed_at:
        authorize(actor, access, row.batch.group, farmer=row.farmer)
        return row
    if row.revision != expected_revision: raise ValueError('The import row changed. Refresh before committing.')
    proposal = propose(row.values)
    if row.proposal.get('issues') == ['Row absent from latest reviewed workbook; restage it before commit.']:
        raise ValueError(row.proposal['issues'][0])
    if any('invalid amount' in issue for issue in proposal['issues']):
        raise ValueError('Resolve invalid monetary values before committing this row.')
    fields = proposal['fields']
    if existing_case_id:
        farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=existing_case_id, group_configuration=row.batch.group)
        authorize(actor, access, row.batch.group, farmer=farmer)
        if fields.get('national_id') and farmer.national_id and fields['national_id'] != farmer.national_id:
            raise ValueError('Existing case has a different National ID. Resolve identity through the owning identity workflow.')
        if not str(separate_unit_note or '').strip(): raise ValueError('Explain the explicit existing-case reconciliation.')
        _retain_numbers(row, actor, allow_occupied=True)
        # Link evidence only; a historical file cannot overwrite newer operational facts.
        row.farmer = farmer; row.committed_at = timezone.now(); row.continuation_confirmed = True; row.publication_ready = True; row.revision += 1; row.save()
        LegacyEvent.objects.create(row=row, actor=actor, request_key=request_key, action='linked',
            payload={'case_id': str(farmer.pk), 'note': separate_unit_note, 'historical_fields_not_overwritten': True})
        return row
    if _existing_collision(row, fields) and not str(separate_unit_note or '').strip():
        raise ValueError('Existing identity/order collision: explicitly link the exact existing case or confirm a separate unit before import.')
    if row.values.get('case_id'):
        raise ValueError('An existing Case ID requires explicit reconciliation; it cannot create a second case.')
    model_names = {f.name for f in JawabuFarmerMaster._meta.fields}
    # Projection remarks and document references are not operational approval/scanning evidence.
    excluded = {'id', 'customer', 'group_configuration', 'source', 'source_name', 'workflow_state',
                'credit_decided_by', 'credit_decided_at', 'final_decided_by', 'final_decided_at',
                'jbl_officer', 'updated_at', 'created_at', 'workflow_revision', 'workflow_state_entered_at',
                'case_reference_number', 'deferred_stage', 'deferred_at', 'deferred_until'}
    model_values = {k: v for k, v in fields.items() if k in model_names and k not in excluded}
    model_values['legacy_fulfillment_partner'] = 'ECOCONSERVE' if row.source_sheet == 'Eco-conserve' else 'HB'
    if fields.get('deposit_paid_hbg'): model_values['actual_receipts'] = fields['deposit_paid_hbg']
    outcome = proposal['outcome']; stage_key = proposal['stage']
    if stage_key and outcome in {'APPROVED', 'REJECTED', 'DEFERRED / ON HOLD'}:
        label = {'APPROVED': 'Approved', 'REJECTED': 'Rejected', 'DEFERRED / ON HOLD': 'Deferred / On Hold'}[outcome]
        if stage_key == 'jbl_visit': model_values['jbl_visit_status'] = {'APPROVED': 'Visited, Awaiting Credit Analysis', 'REJECTED': 'Rejected by JBL'}.get(outcome, label)
        else: model_values['credit_decision' if stage_key == 'credit' else 'final_decision'] = label
    if proposal['state'] == 'deferred': model_values['deferred_stage'] = stage_key
    for field, value in list(model_values.items()):
        if value not in ('', None):
            try: model_values[field] = JawabuFarmerMaster._meta.get_field(field).clean(value, None)
            except Exception as exc:
                from django.core.exceptions import ValidationError
                if not isinstance(exc, ValidationError): raise
                raise ValueError(f'{field}: value does not meet the canonical field format/length.') from exc
    if fields.get('national_id'):
        from core.models import JawabuCustomer
        from django.db.models import Max
        matches = list(JawabuCustomer.objects.select_for_update().filter(national_id=fields['national_id']))
        if len(matches) > 1: raise ValueError('Multiple historical identity records require explicit identity reconciliation.')
        if matches:
            customer = matches[0]
        else:
            phone = fields.get('primary_phone', '')
            if phone and JawabuCustomer.objects.filter(primary_phone=phone).exists(): phone = ''
            customer, _ = JawabuCustomer.objects.get_or_create(national_id=fields['national_id'], identity_enforced=True, defaults={'primary_phone': phone})
        customer = JawabuCustomer.objects.select_for_update().get(pk=customer.pk)
        if customer.applications.exists() and not separate_unit_note:
            raise ValueError('Existing customer: confirm a separate unit or explicitly link its existing case.')
        model_values['customer'] = customer
        model_values['unit_number'] = (customer.applications.aggregate(n=Max('unit_number'))['n'] or 0)+1
    _retain_numbers(row, actor)
    farmer = JawabuFarmerMaster.objects.create(**model_values, group_configuration=row.batch.group,
        source='portal_legacy', source_name=row.source_sheet, source_row_number=row.source_row,
        workflow_state=proposal['state'], raw_data={'legacy_row_id': str(row.pk)})
    row.farmer = farmer; row.proposal = proposal; row.committed_at = timezone.now()
    row.continuation_confirmed = proposal['state'] != 'legacy_review'; row.revision += 1; row.save()
    _hb_baseline(row, farmer, actor)
    LegacyEvent.objects.create(row=row, actor=actor, request_key=request_key, action='imported',
                              payload={'state': proposal['state'], 'evidence': proposal['evidence'], 'source_hash': row.source_hash, 'separate_unit_note': separate_unit_note})
    return row


@transaction.atomic
def confirm_stage(row_id, *, state, note, expected_revision, request_key, actor, access):
    row = LegacyRow.objects.select_for_update(of=('self',)).select_related('batch__group').get(pk=row_id)
    if not row.farmer_id: raise ValueError('Import this row before confirming its continuation.')
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=row.farmer_id)
    authorize(actor, access, row.batch.group, farmer=farmer)
    payload = {'state': state, 'note': str(note or '').strip()}
    replay = row.events.filter(request_key=request_key).first()
    if replay:
        if replay.action != 'stage_confirmed' or replay.payload != payload: raise ValueError('Request key belongs to different facts.')
        return row
    if not request_key or len(request_key) > 120 or not payload['note']: raise ValueError('A request key and confirmation explanation are required.')
    if row.revision != expected_revision: raise ValueError('The legacy record changed. Refresh and review it again.')
    handover_only = bool(farmer.legacy_fulfillment_partner) and farmer.workflow_state == 'ordered' and not hasattr(farmer, 'homebiogas_action')
    if farmer.workflow_state != 'legacy_review' and not handover_only: raise ValueError('This case already has a continuation stage. Use its owning workflow action.')
    if handover_only and state != 'ordered': raise ValueError('Only the outstanding legacy HB handover can be confirmed here.')
    chosen = state
    if ':' in str(state):
        state, stage = state.split(':', 1)
        if state not in {'rejected', 'deferred'} or stage not in {'jbl_visit', 'credit', 'final'}: raise ValueError('Invalid historical decision stage.')
        expected_outcome = 'REJECTED' if state == 'rejected' else 'DEFERRED / ON HOLD'
        if row.proposal.get('outcome') != expected_outcome: raise ValueError('Stage confirmation cannot invent a different historical decision.')
        row.proposal['stage'] = stage
        farmer.deferred_stage = stage if state == 'deferred' else ''
        label = 'Rejected' if state == 'rejected' else 'Deferred / On Hold'
        if stage == 'jbl_visit': farmer.jbl_visit_status = 'Rejected by JBL' if state == 'rejected' else label
        elif stage == 'credit': farmer.credit_decision = label
        else: farmer.final_decision = label
    elif state not in {'jbl_visit', 'credit', 'final_review', 'order', 'ordered', 'withdrawn'}:
        raise ValueError('Choose a supported continuation stage.')
    if chosen == 'order':
        if row.proposal.get('outcome') != 'APPROVED': raise ValueError('Confirm the historical approval through its owning workflow before creating an order.')
        farmer.final_decision = 'Approved'
    if chosen == 'final_review' and row.proposal.get('outcome') == 'APPROVED': farmer.credit_decision = 'Approved'
    farmer.workflow_state = state; farmer.workflow_revision += 1
    farmer.save(update_fields=['workflow_state', 'workflow_revision', 'updated_at', 'deferred_stage', 'jbl_visit_status', 'credit_decision', 'final_decision'])
    row.continuation_confirmed = True; row.revision += 1; row.save()
    if state == 'ordered' and not hasattr(farmer, 'homebiogas_action'):
        row.proposal['hb_known'] = True; row.save(update_fields=['proposal'])
        _hb_baseline(row, farmer, actor)
    LegacyEvent.objects.create(row=row, actor=actor, request_key=request_key, action='stage_confirmed', payload=payload)
    return row
