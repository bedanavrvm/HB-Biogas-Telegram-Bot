"""Resumable, non-destructive amendments to historical Portal records."""
from collections import defaultdict
from decimal import Decimal
import re
import time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.models import IntegrationOperation, JawabuFarmerMaster
from core.services.identifiers import normalize_kenyan_phone, validate_kenyan_national_id
from core.services.jawabu_validation import parse_business_date
from .models import LegacyDraft, LegacyEvent, LegacyRow, LegacyUpload
from .registers import owns_case
from .workbook import ALIASES, DATES, MONEY, literal, propose, token

HB_FIELDS = {'installation_status', 'installation_date', 'serial_number', 'readiness_status',
    'installation_report_status', 'pending_installation_comment', 'commissioning_status',
    'commissioning_date', 'pending_commissioning_comment', 'cs_remarks'}


def current_value(case, key, baseline):
    action = getattr(case, 'homebiogas_action', None)
    if key in HB_FIELDS and action:
        if key == 'installation_date':
            return action.installation_date or action.planned_installation_date
        return getattr(action, key)
    return getattr(case, key, baseline.get(key, ''))


def bind_update_headers(headers):
    from .workbook import bind_headers
    if any(token(h) == 'sourcerow' for h in headers):
        return bind_headers(headers)
    aliases = {'name': 'customer_name', 'caseid': 'case_id', 'signdate': 'legacy_sign_date',
        'firstphonenumber': 'primary_phone', 'secondphonenumber': 'secondary_phone',
        'homebiogasvisitdate': 'hbg_visit_date', 'jawaburequsitiondate': 'requisition_date',
        'depositdatetohbg': 'hb_deposit_date', 'commsioningstatus': 'commissioning_status',
        'installationdatescheduleddateestimatedinstallationdate': 'installation_date',
        'csremarkssalescommissionstatus': 'cs_remarks',
        'decisionaction': 'legacy_outcome', 'depositpaidtojbl': 'legacy_deposit_paid_jbl',
        'constituency': 'legacy:Constituency', 'homebiogasaction': 'legacy:HomeBiogas Action',
        'total': 'legacy:Total', 'openbalance': 'legacy:Open Balance'}
    bindings = {}
    for index, header in enumerate(headers):
        name = token(header)
        if not name or name == 'ane':
            continue
        field = aliases.get(name) or ALIASES.get(name) or 'legacy:' + str(header).strip()
        if field in bindings.values():
            raise ValueError(f'Duplicate source header: {header}.')
        bindings[index] = field
    if 'customer_name' not in bindings.values():
        raise ValueError('The selected register requires a Name or Customer Name column.')
    return bindings


def equivalent(key, value):
    text = ' '.join(literal(value).split())
    if not text or text == '-':
        return ''
    if key in DATES:
        parsed = parse_business_date(text)
        return parsed.isoformat() if parsed else text.casefold()
    if key in MONEY or key in {'legacy:Total', 'legacy:Open Balance'}:
        try:
            return Decimal(re.sub(r'(?i)(kes|kshs?\.?|,|\s)', '', text)).normalize()
        except ArithmeticError:
            return text.casefold()
    if key in {'primary_phone', 'secondary_phone'}:
        return normalize_kenyan_phone(text) or text.casefold()
    if key == 'national_id':
        return validate_kenyan_national_id(text) or text.casefold()
    if key == 'hb_sales_person':
        return token(text)
    if key in {'installation_status', 'commissioning_status', 'readiness_status', 'installation_report_status'}:
        from .cleaning import status_value
        return token(status_value(key, text))
    return text.casefold()


def effective_values(row):
    """Keep original source bytes/facts while exposing explicitly accepted amendments."""
    values = dict(row.values)
    for event in sorted((e for e in row.events.all() if e.action == 'fields_updated'), key=lambda e: e.pk):
        values.update(event.payload.get('source_changes', {}))
    return values


def parsed_values(values):
    normalized = {key: str(equivalent(key, value)) if key in MONEY and value not in ('', '-', None) else value for key, value in values.items()}
    from .cleaning import STATUS_ALIASES, status_value
    normalized.update({key: status_value(key, value) for key, value in values.items() if key in STATUS_ALIASES})
    return propose(normalized)


class Matches:
    def __init__(self, upload):
        self.upload = upload
        self.cases = {str(c.pk): c for c in JawabuFarmerMaster.objects.filter(
            group_configuration=upload.batch.group).select_related('group_configuration', 'homebiogas_action') if owns_case(upload, c)}
        self.indices = {key: defaultdict(set) for key in ('id', 'phone', 'name', 'serial')}
        self.baselines = {}
        for row in LegacyRow.objects.filter(farmer_id__in=self.cases, committed_at__isnull=False).prefetch_related('events').order_by('committed_at', 'pk'):
            self.baselines.setdefault(str(row.farmer_id), row)
        self.originals = reviewed_originals(upload, self.baselines)
        for case_id, case in self.cases.items():
            for key, values in [('id', [case.national_id]), ('phone', [case.primary_phone, case.secondary_phone]),
                                ('name', [case.customer_name]), ('serial', [current_value(case, 'serial_number', {})])]:
                field = {'id': 'national_id', 'phone': 'primary_phone'}.get(key, key)
                for value in values:
                    norm = equivalent(field, value)
                    if norm:
                        self.indices[key][norm].add(case_id)
        for case_id, values in self.originals.items():
            for key, field in [('id','national_id'),('phone','primary_phone'),('phone','secondary_phone')]:
                norm=equivalent(field,values.get(field))
                if norm:self.indices[key][norm].add(case_id)

    def find(self, values, explicit=''):
        if explicit:
            if explicit not in self.cases:
                raise ValueError('Select a case in this owner and register.')
            return explicit, 'Selected case', [explicit]
        reference = str(values.get('case_id') or '').strip()
        if reference:
            candidates = {key for key, c in self.cases.items() if reference in {key, f'JBL-{c.case_reference_number}'}}
            return (next(iter(candidates)), 'Case ID', sorted(candidates)) if len(candidates) == 1 else ('', 'Case ID needs review', sorted(candidates))
        national_id = equivalent('national_id', values.get('national_id'))
        candidates = self.indices['id'].get(national_id, set()) if national_id else set()
        phones = set().union(*(self.indices['phone'].get(equivalent('primary_phone', values.get(k)), set()) for k in ('primary_phone', 'secondary_phone')))
        name = self.indices['name'].get(equivalent('name', values.get('customer_name')), set())
        serial = self.indices['serial'].get(equivalent('serial', values.get('serial_number')), set())
        if len(candidates) == 1:
            return next(iter(candidates)), 'National ID', sorted(candidates)
        if candidates:
            for support in (serial, phones & name, name):
                narrowed = candidates & support
                if len(narrowed) == 1:
                    return next(iter(narrowed)), 'National ID and unit/contact', sorted(candidates)
            return '', 'Multiple cases share this National ID', sorted(candidates)
        supported = phones & name
        if len(supported) == 1:
            case_id = next(iter(supported))
            old_id = equivalent('national_id', self.cases[case_id].national_id)
            if national_id and old_id and old_id != national_id:
                return '', 'Name/phone match has a different National ID', [case_id]
            return case_id, 'Phone and name', [case_id]
        suggestions = supported or serial or name or phones
        return '', 'Choose an existing case or confirm a new case' if suggestions else 'No matching case', sorted(suggestions)[:10]


def reviewed_originals(upload, baselines):
    """Recover retained Original identity cells so an unchanged old typo is not reimported."""
    private=upload.state.setdefault('update_private', {})
    if 'originals' in private:return private['originals']
    from . import streaming
    rows={str(row.pk):case_id for case_id,row in baselines.items()}
    drafts=LegacyDraft.objects.filter(legacy_id__in=rows,upload__mode='initial').values('legacy_id','upload_id','source_row')
    lookup=defaultdict(dict)
    for draft in drafts:lookup[draft['upload_id']][draft['source_row']]=rows[str(draft['legacy_id'])]
    originals={}
    for original in LegacyUpload.objects.filter(pk__in=lookup):
        with streaming.rows(original) as records:
            _,(_,cells)=next(records)
            source_column=next((c['column'] for c in cells if token(c['value'])=='sourcerow'),None)
            columns={}
            for cell in cells:
                parts=[p.strip() for p in str(cell['value'] or '').split('|')]
                if len(parts)>1 and parts[-1]=='Original':
                    name=token(parts[-2])
                    field={'firstphonenumber':'primary_phone','primaryphone':'primary_phone','secondphonenumber':'secondary_phone','secondaryphone':'secondary_phone','idnumber':'national_id','nationalid':'national_id'}.get(name)
                    if field:columns[cell['column']]=field
            if not source_column or not columns:continue
            for _,(_,cells) in records:
                by_column={c['column']:c['value'] for c in cells}
                try:source_row=int(by_column.get(source_column,0))
                except (ValueError,TypeError):continue
                case_id=lookup[original.pk].get(source_row)
                if case_id:originals[case_id]={field:literal(by_column.get(column)) for column,field in columns.items()}
    private['originals']=originals
    return originals


def compare(draft, matches, explicit=''):
    case_id, method, candidates = matches.find(draft.values, explicit)
    candidate = parsed_values(draft.values)
    proposal = {'fields': candidate['fields'], 'state': '', 'issues': [], 'review_status': 'ready',
                'kind': 'ambiguous' if candidates and not case_id else 'new' if not case_id else 'unchanged',
                'match_method': method, 'case_id': case_id, 'candidates': candidates, 'changes': {}}
    if case_id:
        case = matches.cases[case_id]
        row = matches.baselines.get(case_id)
        baseline = effective_values(row) if row else {}
        # Original reviewed source is a baseline, not permission to undo a later app correction.
        for key, raw in draft.values.items():
            if key in {'case_id', 'source_row', 'decision_stage', 'reviewer_notes', 'legacy_progress_notes', 'legacy_reason', 'legacy_reason_code'}:
                continue
            # Previously unmapped reference columns remain upload evidence, not new case fields.
            if (key.startswith('legacy:') or key == 'legacy_sign_date') and key not in baseline:
                continue
            current = current_value(case, key, baseline)
            reviewed=matches.originals.get(case_id,{})
            if key in reviewed and equivalent(key,raw)==equivalent(key,reviewed[key]) and equivalent(key,current)==equivalent(key,baseline.get(key)):
                continue
            if key == 'village' and equivalent(key, raw) == equivalent(key, baseline.get('legacy:Location detail')):
                continue
            if key in {'order_number', 'payment_number'}:
                from .cleaning import reference_value
                try:
                    if reference_value(key, raw, matches.upload.source_sheet) == reference_value(key, current, matches.upload.source_sheet):
                        continue
                except ValueError:
                    pass
            if equivalent(key, raw) == equivalent(key, current):
                continue
            error = next((i for i in candidate['issues'] if i.startswith(key + ':')), '')
            if raw not in ('', '-', None) and key not in candidate['fields'] and not error:
                error = 'This value needs correction before it can be applied.'
            if row is None and key not in {f.name for f in case._meta.fields if not f.is_relation}:
                error = 'This is an app-created case. Use its owning workflow for this field.'
            proposal['changes'][key] = {'before': literal(current), 'after': literal(raw), 'error': error,
                'app_conflict': key in baseline and equivalent(key, current) != equivalent(key, baseline[key])}
        proposal['kind'] = 'changed' if proposal['changes'] else 'unchanged'
        proposal['state'] = case.workflow_state
        proposal['case_revision'] = case.workflow_revision
    else:
        proposal['issues'] = [method] if candidates else []
    draft.proposal = proposal
    draft.approved = False
    previous = draft.reconciliation
    draft.reconciliation = {**previous, 'applied': False, 'selected_fields': [key for key, change in proposal['changes'].items()
        if change['after'] not in ('', '-') and not change['error'] and not change.get('app_conflict')]}
    draft.save(update_fields=['proposal', 'approved', 'reconciliation'])


def compare_step(upload, actor, access):
    from . import importer
    matches = Matches(upload)
    started = time.monotonic()
    drafts = upload.drafts.filter(proposal__kind__isnull=True).order_by('source_row')[:100]
    for draft in drafts:
        compare(draft, matches)
        if time.monotonic() - started > 4:
            break
    if not upload.drafts.filter(proposal__kind__isnull=True).exists():
        # Two source rows must never silently amend the same case twice.
        duplicate_ids = upload.drafts.exclude(proposal__case_id='').values('proposal__case_id').annotate(n=Count('pk')).filter(n__gt=1)
        for item in duplicate_ids:
            for draft in upload.drafts.filter(proposal__case_id=item['proposal__case_id']):
                draft.proposal.update(kind='ambiguous', issues=['More than one uploaded row matches this case. Select one row to apply.'])
                draft.save(update_fields=['proposal'])
        upload.phase = 'ready'
    importer.save(upload)


def payload(upload):
    from core.services.portal_publication import MASTER_OPERATION
    counts = dict(upload.drafts.values('proposal__kind').annotate(n=Count('pk')).values_list('proposal__kind', 'n'))
    applied = upload.drafts.filter(reconciliation__applied=True)
    operation_ids = [operation for r in applied.values_list('reconciliation', flat=True) for operation in r.get('operations', [])]
    synced_ids = set(str(pk) for pk in IntegrationOperation.objects.filter(pk__in=operation_ids,
        operation_type=MASTER_OPERATION, status=IntegrationOperation.STATUS_SUCCEEDED,
        metadata__result__action=MASTER_OPERATION).values_list('pk', flat=True))
    synced = sum(bool(r.get('operations')) and set(r['operations']) <= synced_ids for r in applied.values_list('reconciliation', flat=True))
    total = upload.drafts.count()
    return {'id': str(upload.pk), 'namespace': upload.batch.namespace, 'mode': upload.mode,
        'group_id': str(upload.batch.group_id), 'group_label': upload.batch.group.display_name,
        'filename': upload.filename, 'source_sheet': upload.source_sheet, 'phase': upload.phase,
        'revision': upload.revision, 'frozen': False, 'chunks': list(upload.chunks.filter(kind='source').values_list('position', flat=True)),
        'size': upload.size, 'total': total, 'committed': applied.count(), 'selected': upload.drafts.filter(approved=True).count(),
        'counts': counts, 'state': {k: v for k, v in upload.state.items() if k != 'update_private'},
        'sheet_sync': {'state': 'needs_attention' if upload.state.get('sync_error') else 'awaiting_sync' if applied.count() > synced else 'complete',
            'synced': synced, 'pending': applied.count() - synced, 'not_imported': total - applied.count() - counts.get('unchanged', 0), 'error': upload.state.get('sync_error', '')}}


def inspect_rows(upload, offset, filter_by):
    qs = upload.drafts.order_by('source_row')
    if filter_by in {'changed', 'new', 'ambiguous', 'unchanged'}:
        qs = qs.filter(proposal__kind=filter_by)
    elif filter_by == 'selected':
        qs = qs.filter(approved=True)
    elif filter_by == 'committed':
        qs = qs.filter(reconciliation__applied=True)
    elif filter_by != 'all':
        qs = qs.exclude(proposal__kind='unchanged').exclude(reconciliation__applied=True)
    offset = max(0, int(offset))
    rows = []
    case_ids = {pk for p in qs[offset:offset+50].values_list('proposal', flat=True) for pk in p.get('candidates', [])}
    cases = {str(c.pk): c for c in JawabuFarmerMaster.objects.filter(pk__in=case_ids, group_configuration=upload.batch.group)}
    for draft in qs[offset:offset+50]:
        p = draft.proposal
        rows.append({'id': str(draft.pk), 'source_row': draft.source_row, 'name': draft.values.get('customer_name', ''),
            'source_values': draft.values, 'original_values': draft.values, 'proposal': p, 'field_issues': {},
            'committed': bool(draft.reconciliation.get('applied')), 'approved': draft.approved,
            'reconciliation': draft.reconciliation, 'identity_collision': False, 'duplicate_rows': [],
            'existing_cases': [{'id': key, 'reference': f'JBL-{cases[key].case_reference_number}', 'name': cases[key].customer_name}
                for key in p.get('candidates', []) if key in cases]})
    return {'rows': rows, 'total': qs.count(), 'offset': offset}


def select(upload, body):
    if upload.phase != 'ready':
        raise ValueError('Finish comparison before selecting changes.')
    if body.get('all') is True:
        # New records and unresolved matches always require their own explicit selection.
        upload.drafts.filter(proposal__kind='changed').exclude(reconciliation__applied=True).update(approved=bool(body.get('approved')))
        if not body.get('approved'):
            upload.drafts.all().update(approved=False)
        return
    matches = None
    for item in body.get('rows', [])[:50]:
        draft = upload.drafts.get(pk=item['id'])
        if draft.reconciliation.get('applied'):
            continue
        explicit = str(item.get('existing_case_id') or '')
        if explicit and (explicit != draft.proposal.get('case_id') or draft.proposal.get('kind')=='ambiguous'):
            matches = matches or Matches(upload)
            compare(draft, matches, explicit)
        fields = draft.reconciliation.get('selected_fields', []) if explicit else item.get('selected_fields', draft.reconciliation.get('selected_fields', []))
        if not isinstance(fields, list) or not set(fields) <= set(draft.proposal.get('changes', {})):
            raise ValueError('Select only fields in this saved comparison.')
        draft.reconciliation.update(selected_fields=fields, create_new=item.get('create_new') is True)
        draft.approved = bool(item.get('approved')) and draft.proposal.get('kind') != 'unchanged'
        if draft.approved and draft.proposal.get('kind') == 'ambiguous':
            raise ValueError('Choose an exact existing case before approving this row.')
        draft.save(update_fields=['approved', 'reconciliation'])


@transaction.atomic
def apply_row(draft_id, actor, access):
    from . import importer, services
    from core.services.portal_publication import MASTER_OPERATION, reserve_farmer_publication
    draft = LegacyDraft.objects.select_for_update().select_related('upload__batch__group').get(pk=draft_id)
    if draft.reconciliation.get('applied'):
        return
    upload = draft.upload
    p = draft.proposal
    key = f'legacy-update:{draft.pk}'
    if p['kind'] == 'new' and draft.reconciliation.get('create_new'):
        # Recheck identity at commit, including cases added after the comparison.
        current_match = Matches(upload).find(draft.values)
        if current_match[0] or current_match[2]:
            raise ValueError('A matching case now exists. Refresh this row before creating a case.')
        row = LegacyRow.objects.create(batch=upload.batch, source_sheet=upload.source_sheet,
            source_row=draft.source_row, source_hash=upload.digest, values=draft.values, proposal=parsed_values(draft.values))
        row = services.commit_row(row.pk, expected_revision=row.revision, request_key=key, actor=actor, access=access)
        farmer = row.farmer
        from .fence import case_blocked
        if case_blocked(farmer):raise ValueError('Finish the active initial import before adding another case to this register.')
        row.publication_ready=True
        row.save(update_fields=['publication_ready'])
    else:
        if p['kind'] != 'changed' or not p.get('case_id'):
            raise ValueError('Choose a matched changed case or explicitly confirm a new case.')
        farmer = JawabuFarmerMaster.objects.select_for_update(of=('self',)).select_related('group_configuration').get(pk=p['case_id'])
        if upload.drafts.filter(approved=True,proposal__case_id=str(farmer.pk)).exclude(pk=draft.pk).exists() or upload.drafts.filter(reconciliation__applied=True,proposal__case_id=str(farmer.pk)).exists():
            raise ValueError('Only one source row can update a case in this upload. Clear the duplicate selection.')
        importer.authorize(actor, access, upload.batch.group, branch=farmer.branch, product=farmer.payment_product)
        if not owns_case(upload, farmer):
            raise ValueError('The case owner/register changed. Compare it again.')
        from .fence import case_blocked
        if case_blocked(farmer):
            raise ValueError('Finish this case\'s initial import verification before applying updates.')
        if int(farmer.workflow_revision) != int(p['case_revision']):
            raise ValueError('This case changed since comparison. Refresh its comparison before applying changes.')
        row = farmer.legacy_records.filter(committed_at__isnull=False).order_by('committed_at', 'pk').first()
        fields = draft.reconciliation.get('selected_fields', [])
        if not fields:
            raise ValueError('Select at least one changed field.')
        selected = {field: p['changes'][field]['after'] for field in fields}
        for field in fields:
            if p['changes'][field]['error']:
                raise ValueError(p['changes'][field]['error'])
        apply_fields(farmer, row, selected, actor, key)
        farmer.refresh_from_db()
        if row:
            normalized=parsed_values(selected)['fields']
            LegacyEvent.objects.create(row=row, actor=actor, request_key=key, action='fields_updated', payload={
                'upload_id': str(upload.pk), 'source_row': draft.source_row, 'source_hash': upload.digest,
                'source_changes': {k:literal(normalized.get(k,value)) for k,value in selected.items()},
                'before': {k: p['changes'][k]['before'] for k in fields}, 'after': selected})
            row.revision += 1
            row.save(update_fields=['revision'])
    operations = reserve_farmer_publication(farmer, request_id=key, requested_by=actor)
    draft.legacy = row
    draft.reconciliation.update(applied=True, operations=[str(o.pk) for o in operations if o.operation_type == MASTER_OPERATION])
    draft.approved = False
    draft.save(update_fields=['legacy', 'reconciliation', 'approved'])


def apply_fields(farmer, row, selected, actor, request_id):
    """One historical correction boundary; live workflow evidence stays with its owner."""
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.jawabu_customer_quality import record_field_provenance
    from core.services.portal_case_corrections import CASE_CORRECTION_FIELDS, correct_case_fields
    from . import services
    reason = 'Historical workbook update'
    ordinary = {key: value for key, value in selected.items() if key in CASE_CORRECTION_FIELDS}
    if ordinary:
        # The existing correction boundary owns identity, locations and post-visit deposits.
        if 'deposit_paid_hbg' in ordinary and not farmer.jbl_visit_date:
            from hb_operations.deposits import update_deposit
            from core.services.telegram_identity import user_access
            update_deposit(farmer, amount=ordinary.pop('deposit_paid_hbg'), reason=reason,
                request_id=request_id + ':deposit', expected_revision=farmer.workflow_revision, actor=actor, access=user_access(actor, 'jawabu_portal'))
            farmer.refresh_from_db()
        if ordinary:
            farmer = correct_case_fields(farmer, values=ordinary, expected_revision=farmer.workflow_revision,
                reason=reason, request_id=request_id + ':fields', actor=actor)
    rest = {key: value for key, value in selected.items() if key not in CASE_CORRECTION_FIELDS}
    parsed = parsed_values(rest)
    protected = {'credit_decision', 'final_decision', 'workflow_state', 'jbl_officer', 'credit_decided_at', 'final_decided_at',
        'credit_decided_by', 'final_decided_by', 'branch', 'payment_product', 'actual_receipts'}
    if protected & rest.keys():
        raise ValueError('Use the owning workflow to change approval, assignment or product fields.')
    if {'order_number', 'payment_number', 'invoice_number', 'invoice_amount', 'discount', 'requisition_date', 'invoice_date'} & rest.keys():
        from core.models import RequisitionBatch, ParsedInvoice
        from payments.models import PaymentBatchCase
        if RequisitionBatch.objects.filter(farmer_ids__contains=[str(farmer.pk)]).exists() or ParsedInvoice.objects.filter(matched_farmer=farmer).exists() or PaymentBatchCase.objects.filter(farmer=farmer).exists():
            raise ValueError('This case has live order/invoice/payment evidence. Use its owning workflow for financial corrections.')
        from copy import copy
        if row is None:raise ValueError('Use the owning workflow to change financial references on an app-created case.')
        snapshot = copy(row)
        snapshot.proposal = parsed
        services._retain_numbers(snapshot, actor, allow_occupied=False, request_key=request_id + ':references')
    model_fields = {f.name: f for f in farmer._meta.fields if not f.is_relation}
    allowed = set(model_fields) & set(ALIASES.values()) - protected - {'id', 'case_reference_number', 'created_at', 'updated_at'}
    before = {}; after = {}
    for key, raw in rest.items():
        if key not in allowed:
            continue
        field = model_fields[key]
        value = parsed['fields'].get(key, None if field.null else '')
        value = field.clean(value, farmer)
        before[key] = literal(getattr(farmer, key)); after[key] = literal(value)
        setattr(farmer, key, value)
    changed_model_fields=list(before)
    baseline=effective_values(row) if row else {}
    for key, value in rest.items():
        if key not in before:
            before[key]=literal(current_value(farmer,key,baseline));after[key]=literal(value)
    if before:
        revision = farmer.workflow_revision
        farmer.workflow_revision += 1
        farmer.save(update_fields=[*changed_model_fields, 'workflow_revision', 'updated_at'])
        label = actor.get_full_name() or actor.get_username()
        record_field_provenance(farmer, old_values=before, new_values=after, source='legacy_update', source_reference=request_id, actor=label)
        record_pipeline_event(farmer, action='legacy_fields_updated', stage_key='case_history', source='legacy_update',
            actor=label, actor_user=actor, request_id=request_id, reason=reason, old_values=before, new_values=after,
            revision_before=revision, revision_after=farmer.workflow_revision)
    if HB_FIELDS & rest.keys():
        if row is None:raise ValueError('Use HB Actions to change an app-created case.')
        apply_hb_fields(farmer, row, rest, actor, request_id)


def apply_hb_fields(farmer, row, fields, actor, request_id):
    from copy import copy
    from hb_operations.models import HomeBiogasAction
    from hb_operations.services import correct_action, update_commissioning_notes
    from . import services
    from .cleaning import STATUS_ALIASES, status_value
    fields = {key: status_value(key, value) if key in STATUS_ALIASES else value for key, value in fields.items()}
    action = HomeBiogasAction.objects.select_for_update().filter(farmer=farmer).first()
    if action and not action.legacy_origin_id:
        raise ValueError('Use HB Actions to correct a case released by a signed order.')
    if action is None:
        snapshot = copy(row)
        snapshot.proposal = propose({**effective_values(row), **fields})
        if any('predates installation' in issue or 'in the future' in issue for issue in snapshot.proposal['issues']):
            raise ValueError('Confirm the installation and commissioning dates before applying changes.')
        services._hb_baseline(snapshot, farmer, actor)
        if not HomeBiogasAction.objects.filter(farmer=farmer).exists():
            raise ValueError('Supply confirmed historical installation/order facts before changing HB progress.')
        return
    installation = HB_FIELDS - {'commissioning_status', 'commissioning_date', 'pending_commissioning_comment', 'cs_remarks'}
    values = {key: (token(value) if key in {'installation_status', 'readiness_status', 'installation_report_status'} else literal(equivalent(key,value)) if key in DATES else value)
        for key, value in fields.items() if key in HB_FIELDS}
    for key in {'readiness_status', 'installation_report_status'} & values.keys():
        values[key] = {'notready': 'not_ready', 'notconfirmed': 'not_confirmed', 'notapplicable': 'not_applicable'}.get(values[key], values[key])
    if installation & values.keys():
        action, _, _ = correct_action(action.pk, payload={'workstream': 'installation', **{k:v for k,v in values.items() if k in installation}},
            actor=actor, request_id=request_id + ':installation', expected_revision=action.revision)
    if {'commissioning_status', 'commissioning_date'} & values.keys():
        if 'commissioning_status' in values:
            values['commissioning_status'] = values['commissioning_status'].lower().replace(' ', '_')
        action, _, _ = correct_action(action.pk, payload={'workstream': 'commissioning', **{k:v for k,v in values.items() if k in {'commissioning_status', 'commissioning_date'}}},
            actor=actor, request_id=request_id + ':commissioning', expected_revision=action.revision)
    if {'pending_commissioning_comment', 'cs_remarks'} & values.keys():
        update_commissioning_notes(action.pk, payload={'pending_commissioning_comment': values.get('pending_commissioning_comment',action.pending_commissioning_comment), 'additional_remarks': values.get('cs_remarks',action.cs_remarks)},
            actor=actor, request_id=request_id + ':notes', expected_revision=action.revision)


def commit_step(upload, actor, access):
    from . import importer
    started = time.monotonic(); results = []
    for draft in upload.drafts.filter(approved=True).order_by('source_row')[:50]:
        try:
            apply_row(draft.pk, actor, access)
            results.append({'id': str(draft.pk), 'ok': True})
        except (ValueError, ValidationError) as exc:
            draft.refresh_from_db()
            draft.proposal['commit_error'] = str(exc)
            draft.approved = False
            draft.save(update_fields=['proposal', 'approved'])
            results.append({'id': str(draft.pk), 'ok': False, 'error': str(exc)})
        if time.monotonic() - started > 4:
            break
    upload.phase = 'committing' if upload.drafts.filter(approved=True).exists() else 'ready'
    importer.save(upload)
    return results


def sync_step(upload, actor, access):
    from . import importer
    from core.services.portal_publication import MASTER_OPERATION, attempt_publication, publication_deferral, reserve_farmer_publication
    missing=upload.drafts.filter(reconciliation__applied=True,reconciliation__operations=[]).select_related('legacy__farmer').first()
    if missing:
        farmer=missing.legacy.farmer if missing.legacy_id else JawabuFarmerMaster.objects.get(pk=missing.proposal['case_id'])
        if not owns_case(upload,farmer):raise ValueError('The case owner/register changed. Review its current publication.')
        operations=reserve_farmer_publication(farmer,request_id='legacy-update-configured:'+str(missing.pk),requested_by=actor)
        missing.reconciliation['operations']=[str(o.pk) for o in operations if o.operation_type==MASTER_OPERATION]
        missing.save(update_fields=['reconciliation'])
        if not missing.reconciliation['operations']:
            upload.phase='ready';upload.state['sync_error']='Sheet publication is not enabled for this register. Check its configuration before retrying.';importer.save(upload)
        return {}
    operation_ids = [pk for r in upload.drafts.filter(reconciliation__applied=True).values_list('reconciliation', flat=True) for pk in r.get('operations', [])]
    operation = IntegrationOperation.objects.filter(pk__in=operation_ids).exclude(
        status=IntegrationOperation.STATUS_SUCCEEDED,metadata__result__action=MASTER_OPERATION).order_by('created_at', 'pk').first()
    if operation is None:
        upload.phase = 'committing' if upload.state.pop('resume_commit', False) else 'ready'
        upload.state.pop('sync_error', None); importer.save(upload)
        return {}
    if operation.status==IntegrationOperation.STATUS_SUCCEEDED:
        # Later app edits may supersede this revision; follow their canonical publication.
        farmer=JawabuFarmerMaster.objects.get(pk=operation.source_id)
        if not owns_case(upload,farmer):raise ValueError('The case owner/register changed. Review its current publication.')
        replacements=reserve_farmer_publication(farmer,request_id='legacy-update-followup:'+str(upload.pk),requested_by=actor)
        replacement=next((o for o in replacements if o.operation_type==MASTER_OPERATION),None)
        if replacement is None or replacement.pk==operation.pk:
            upload.phase='ready';upload.state['sync_error']='Check the configured Sheet destination in Settings > App status.';importer.save(upload);return {}
        for draft in upload.drafts.filter(reconciliation__applied=True):
            if str(operation.pk) in draft.reconciliation.get('operations',[]):
                draft.reconciliation.setdefault('superseded_operations',[]).append(str(operation.pk))
                draft.reconciliation['operations']=[str(replacement.pk) if pk==str(operation.pk) else pk for pk in draft.reconciliation['operations']]
                draft.save(update_fields=['reconciliation'])
        return {}
    if operation.status == IntegrationOperation.STATUS_DEAD_LETTER:
        upload.phase = 'ready'; upload.state['sync_error'] = 'A saved update needs attention. Review it in Settings > App status.'; importer.save(upload)
        return {}
    result = attempt_publication(operation, max_seconds=8)
    wait = publication_deferral(result['operation'])
    if result.get('error'):
        upload.phase = 'ready'; upload.state['sync_error'] = 'The update remains saved. Review the publication failure in Settings > App status.'; importer.save(upload)
    return {'wait_seconds': min(wait.get('retry_after_seconds', 1), 5)} if wait.get('deferred') else {}
