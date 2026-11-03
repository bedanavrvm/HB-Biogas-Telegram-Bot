"""Review-first historical intake; current Complaints owns cases and publication."""
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from tempfile import gettempdir
import hashlib
import json
import re
import time
import uuid

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from core.models import AccessGrant, ComplaintCaseControl, ComplaintCaseEvent, GroupSheetConfiguration, ParsedMessage, ProcessedMessage, RawMessage
from core.services import complaint_cases as cases, legacy_xlsx
from .models import ImportUpload, ImportChunk, ImportRow
from . import workbook

CHUNK = 512*1024


def authorize(group, actor):
    user = actor.user
    if not user or not user.is_active or not cases.is_complaint_workflow(group): raise PermissionDenied('Active Complaints IT authority is required.')
    row = GroupSheetConfiguration.objects.get(group_id=group.group_id, enabled=True)
    if not user.is_superuser:
        grants = AccessGrant.objects.filter(user=user, workflow='complaint_cases', role='IT', active=True, branch='', product='')
        if not grants.filter(Q(group_configuration=row)|Q(group_configuration__isnull=True)).exists():
            raise PermissionDenied('A whole-workspace Complaints IT grant is required. Other Mini App roles do not grant import access.')
    if not cases.actor_can(group, actor, 'complaint.legacy.manage'): raise PermissionDenied('Complaints legacy import is outside your access scope.')
    return row


def can_manage(group, actor):
    try: authorize(group, actor); return True
    except (PermissionDenied, GroupSheetConfiguration.DoesNotExist): return False


def save(upload):
    upload.revision += 1
    upload.save(update_fields=['phase','state','revision'])


def payload(upload):
    return {'id': str(upload.pk), 'filename': upload.filename, 'namespace': upload.namespace,
        'source_sheet': upload.source_sheet, 'phase': upload.phase, 'revision': upload.revision,
        'size': upload.size, 'chunks': list(upload.chunks.values_list('position',flat=True)),
        'total': upload.rows.count(), 'selected': upload.rows.filter(approved=True,case__isnull=True).count(),
        'committed': upload.rows.filter(committed_at__isnull=False).count(), 'queued': upload.rows.filter(published=True).count(),
        'state': upload.state}


@transaction.atomic
def create(group, actor, body):
    owner = authorize(group, actor)
    size = int(body.get('size',0)); digest = str(body.get('digest','')); namespace = str(body.get('namespace',''))
    sheet = str(body.get('source_sheet','Case Management')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',namespace): raise ValueError('Supply a stable import namespace (letters, numbers, underscore or hyphen).')
    if not 0 < size <= legacy_xlsx.LIMIT or not re.fullmatch('[a-f0-9]{64}',digest): raise ValueError('Choose one XLSX up to 20 MiB with its SHA256 checksum.')
    if not sheet or len(sheet)>128: raise ValueError('Choose the exact worksheet name.')
    GroupSheetConfiguration.objects.select_for_update().get(pk=owner.pk)
    upload = ImportUpload.objects.filter(group=owner,digest=digest).first()
    if upload:
        if upload.source_sheet != sheet: raise ValueError('This workbook is already bound to another selected worksheet.')
        if upload.phase == 'discarded': upload.phase='uploading'; upload.state={}; save(upload)
        return upload
    return ImportUpload.objects.create(group=owner,actor=actor.user,namespace=namespace,filename=str(body.get('filename','source.xlsx'))[:200],
                                      digest=digest,size=size,source_sheet=sheet)


@contextmanager
def leased(upload):
    lease = uuid.uuid4(); now = timezone.now()
    claimed = ImportUpload.objects.filter(pk=upload.pk).filter(Q(lease_until__isnull=True)|Q(lease_until__lt=now)).update(lease=lease,lease_until=now+timedelta(seconds=60))
    if not claimed: raise ValueError('Another request is advancing this import. Refresh saved progress.')
    try: upload.refresh_from_db(); yield upload
    finally: ImportUpload.objects.filter(pk=upload.pk,lease=lease).update(lease=None,lease_until=None)


def receive(upload, position, content):
    position = int(position)
    if not 0 <= position < (upload.size+CHUNK-1)//CHUNK: raise ValueError('Invalid chunk position.')
    if len(content) != min(CHUNK,upload.size-position*CHUNK): raise ValueError('Chunk length does not match the declared workbook.')
    digest = hashlib.sha256(content).hexdigest(); old = upload.chunks.filter(position=position).first()
    if old:
        if old.digest != digest: raise ValueError('This source chunk already contains different bytes.')
        return
    if upload.phase != 'uploading': raise ValueError('The workbook is sealed. Stage a new source version.')
    ImportChunk.objects.create(upload=upload,position=position,content=content,digest=digest)


def cache_root(upload): return Path(gettempdir())/'complaint-legacy-private'/str(upload.pk)


def prepare(upload):
    if upload.phase != 'uploading': return
    with legacy_xlsx.rows(upload,cache_root(upload)) as rows:
        offset, (_physical,cells) = next(rows)
    upload.state = {**workbook.mapping(cells),'offset': offset}; upload.phase='mapping'; save(upload)


def message_key(upload, source_row):
    return 'legacy:'+hashlib.sha256(f'{upload.group_id}/{upload.namespace}/{upload.source_sheet}/{source_row}'.encode()).hexdigest()


def existing(upload, row):
    case = ParsedMessage.objects.filter(group_id=upload.group.group_id,message_id=message_key(upload,row.source_row)).first()
    if case:
        previous = case.complaint_legacy_rows.filter(committed_at__isnull=False).order_by('committed_at','pk').first()
        if not previous or previous.values != row.values: raise ValueError('This original source row already has different imported facts. Use audited case correction; no existing case was overwritten.')
    return case


def stage_step(upload):
    started=time.monotonic(); pending=[]; offset=upload.state['offset']; exhausted=True; count=upload.rows.count()
    fingerprints=set(upload.rows.values_list('proposal__fingerprint',flat=True))
    with legacy_xlsx.rows(upload,cache_root(upload),offset) as records:
        for next_offset,(physical,cells) in records:
            values=workbook.values_for(cells,upload.state['bindings'])
            if values:
                try: source_row=int(values.pop('source_row',physical))
                except (TypeError,ValueError): raise ValueError(f'Worksheet row {physical}: retain its original integer Source Row.')
                if source_row<2: raise ValueError('Source Row must be 2 or greater.')
                candidate=workbook.propose(values)
                duplicate=candidate['fingerprint'] in fingerprints
                fingerprints.add(candidate['fingerprint'])
                if duplicate:
                    candidate['issues'].append('Identical source facts repeat in this worksheet. Review the duplicate before importing.');candidate['status']='blocked'
                draft=ImportRow(upload=upload,source_row=source_row,values=values,proposal=candidate)
                try:
                    if existing(upload,draft): candidate['warnings'].append('This exact source row was already imported; approval will reuse its case.')
                except ValueError as exc: candidate['issues'].append(str(exc)); candidate['status']='blocked'
                if values.get('complaint_id') and ComplaintCaseControl.objects.filter(parsed_message__group_id=upload.group.group_id,reference_number=values['complaint_id']).exists() and not ParsedMessage.objects.filter(group_id=upload.group.group_id,message_id=message_key(upload,source_row)).exists():
                    candidate['issues'].append('Complaint ID already exists. Reconcile this source instead of creating another case.'); candidate['status']='blocked'
                pending.append(draft)
                if count+len(pending)>50000: raise ValueError('The selected worksheet exceeds 50,000 source records.')
            offset=next_offset
            if len(pending)>=250 or time.monotonic()-started>=5: exhausted=False; break
    with transaction.atomic():
        ImportRow.objects.bulk_create(pending,batch_size=100)
        upload.state['offset']=offset
        if exhausted: upload.phase='ready'
        save(upload)


def inspect(upload, offset=0, status='all'):
    offset=max(0,int(offset)); rows=upload.rows.select_related('case__complaint_control').order_by('source_row')
    if status in {'ready','warning','blocked'}: rows=rows.filter(proposal__status=status)
    elif status=='pending': rows=rows.filter(committed_at__isnull=True)
    elif status=='committed': rows=rows.filter(committed_at__isnull=False)
    return {'total': rows.count(), 'offset': offset, 'rows': [{'id':r.pk,'source_row':r.source_row,'values':r.values,
        'proposal':r.proposal,'approved':r.approved,'committed':bool(r.committed_at),
        'reference':r.case.complaint_control.reference_number if r.case_id else ''} for r in rows[offset:offset+50]]}


def select(upload, body):
    if upload.phase!='ready': raise ValueError('Finish staging/processing before changing approval.')
    rows=upload.rows.filter(case__isnull=True).exclude(proposal__status='blocked')
    if body.get('all') is True: rows.update(approved=body.get('approved') is True)
    else:
        for item in body.get('rows',[])[:50]: rows.filter(pk=item['id']).update(approved=item.get('approved') is True)
    save(upload)


@transaction.atomic
def commit_row(upload,row_id,group,actor):
    row=ImportRow.objects.select_for_update().get(pk=row_id,upload=upload)
    if row.committed_at: return
    candidate=workbook.propose(row.values)
    if candidate['issues']: raise ValueError('Correct blocked status/date/field issues before import.')
    GroupSheetConfiguration.objects.select_for_update(no_key=True).get(pk=upload.group_id)
    case=existing(upload,row)
    if case:
        row.case=case; row.committed_at=timezone.now(); row.save(update_fields=['case','committed_at']); return
    fields=candidate['fields']; reference=message_key(upload,row.source_row)
    original=json.dumps(row.values,ensure_ascii=False,sort_keys=True)
    raw=RawMessage.objects.create(telegram_message_id=reference,sender='',content=original,received_at=timezone.now())
    processed=ProcessedMessage.objects.create(raw_message=raw,message_hash=reference,status='success')
    category=next((c for c in cases.available_categories(group) if c.label.casefold()==fields['complaint_category'].casefold()),None)
    case=ParsedMessage.objects.create(processed_message=processed,message_id=reference,group_id=group.group_id,
        raw_message=original,source='complaint_legacy',timestamp=workbook.reported_date(fields['date_reported']),
        complaint_status=fields['status'],date_resolved=workbook.reported_date(fields['date_resolved']),
        sender=fields['reported_by'],customer_name=fields['customer_name'],customer_phone=fields['customer_phone'],
        secondary_phone=fields['secondary_phone'],customer_id=fields['customer_id'],county=fields['county'],
        sub_county=fields['sub_county'],village=fields['village'],branch_region=fields['branch_region'],
        complaint_category=fields['complaint_category'],complaint_description=fields['complaint_description'],
        resolution_details=fields['resolution_details'],gps_link=fields['gps_link'])
    priority=category.default_priority if category else 'normal'; target={'high':24,'normal':72,'low':120}[priority]
    control=ComplaintCaseControl.objects.create(parsed_message=case,category=category,customer=None,customer_match_status='unmatched',
        priority=priority,sla_target_hours=target,sla_started_at=case.timestamp,sla_due_at=case.timestamp+timedelta(hours=target),sync_status='not_required')
    cases.ensure_control_reference(control)
    row.case=case; row.committed_at=timezone.now(); row.save(update_fields=['case','committed_at'])
    event=ComplaintCaseEvent.objects.create(case=control,revision=control.revision,action='legacy_imported',actor=actor.user,
        actor_label=actor.name,request_id='legacy:'+str(upload.pk)+':'+str(row.pk),
        after_values={'status':case.complaint_status,'reported_at':case.timestamp.isoformat(),'source_row':row.source_row},
        reason='Imported historical workbook snapshot. Historical authors and unknown closure dates were not inferred.')
    from core.services.compliance_audit import record_event
    record_event(workflow='complaint_cases',action='complaint.legacy.imported',subject_type='complaint_case',subject_id=str(case.pk),
        actor=actor.user,source_model='ComplaintCaseEvent',source_event_id=str(event.pk),
        deduplication_key='complaint-legacy:'+str(row.pk),metadata={'upload':str(upload.pk),'source_row':row.source_row})


def commit_step(upload,group,actor):
    started=time.monotonic()
    for row in upload.rows.filter(approved=True,case__isnull=True).order_by('source_row')[:50]:
        try: commit_row(upload,row.pk,group,actor)
        except ValueError as exc:
            proposal={**row.proposal,'status':'blocked','commit_error':str(exc)}
            upload.rows.filter(pk=row.pk).update(approved=False,proposal=proposal)
        if time.monotonic()-started>=5: break
    upload.phase='committing' if upload.rows.filter(approved=True,case__isnull=True).exists() else 'ready'; save(upload)


def publish_step(upload,group):
    from complaint_publications.services import queue_sheet
    started=time.monotonic()
    for row in upload.rows.filter(case__isnull=False,published=False).select_related('case')[:50]:
        with transaction.atomic():
            row=ImportRow.objects.select_for_update(of=('self',)).select_related('case').get(pk=row.pk)
            if not row.published: queue_sheet(group,row.case); row.published=True; row.save(update_fields=['published'])
        if time.monotonic()-started>=5: break
    upload.phase='publishing' if upload.rows.filter(case__isnull=False,published=False).exists() else 'ready'; save(upload)


def historical_notes(case, field):
    if case.source!='complaint_legacy': return ''
    row=case.complaint_legacy_rows.filter(committed_at__isnull=False).order_by('committed_at','pk').first()
    if not row: return ''
    keys={'resolution_comments':('resolution_comments','historical_hb_comments','historical_hb_reconfirmation'),
          'jbl_verification_comments':('jbl_verification_comments',),
          'resolution_history':('resolution_history','historical_jbl_feedback','historical_jbl_comments')}[field]
    labels=COMPLAINT_LABELS
    return '\n'.join(f'[Historical source: {labels.get(k,k)}; author/time not recorded]\n{row.values[k]}' for k in keys if row.values.get(k))


COMPLAINT_LABELS={'resolution_comments':'Resolution Comments','historical_hb_comments':'HB Comments',
    'historical_hb_reconfirmation':'HBG Case Status Re-Confirmation','historical_jbl_feedback':'Jawabu Comments (Feedback)',
    'historical_jbl_comments':'JBL Comments','jbl_verification_comments':'JBL Verification Comments','resolution_history':'Resolution History'}
