"""IT-only bounded cutover; PostgreSQL is authoritative, Sheets is a projection."""
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
import hashlib,json,re,time,uuid
from django.core import signing
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.db.models import Count,Q
from django.utils import timezone
from core.models import GroupSheetConfiguration,JawabuFarmerMaster
from .models import LegacyBatch,LegacyUpload,LegacyChunk,LegacyDraft,LegacyRow
from . import services,streaming
from .workbook import propose
from .registers import partner_for_source,case_ids,owns_case

CHUNK=512*1024


def authorize(actor,access,group,*,branch=None,product=''):
    if (group.workflow or {}).get('type') not in {'jawabu','jawabu_homebiogas'}:
        raise PermissionDenied('Legacy Data requires a configured Portal owner.')
    services.authorize(actor,access,group,branch=branch,product=product)
    from core.services.portal_permissions import portal_access_decision
    if actor.is_superuser:return
    if branch is None:
        from core.models import AccessGrant
        grants=AccessGrant.objects.filter(user=actor,workflow='jawabu_portal',active=True,role='IT').filter(Q(group_configuration=group)|Q(group_configuration__isnull=True))
        for grant in grants:
            decision=portal_access_decision(actor,'portal.legacy.manage',access=access,branch=grant.branch,product=grant.product,group_configuration=group,enforce_group_scope=True)
            if decision.allowed and 'IT' in decision.roles:return
    else:
        resource=SimpleNamespace(branch=branch,payment_product=product,group_configuration_id=group.pk)
        decision=portal_access_decision(actor,'portal.legacy.manage',access=access,resource=resource,group_configuration=group,enforce_group_scope=True)
        if decision.allowed and 'IT' in decision.roles:return
    raise PermissionDenied('Scoped Portal IT authority is required for Legacy Data.')


def create(body,actor,access):
    group=GroupSheetConfiguration.objects.get(pk=body.get('group_id'),enabled=True)
    authorize(actor,access,group,branch='')
    namespace=str(body.get('namespace',''));size=int(body.get('size',0));digest=str(body.get('digest',''))
    source_sheet=str(body.get('source_sheet','Master Data'));partner_for_source(source_sheet)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',namespace):raise ValueError('Supply a stable cutover namespace.')
    if not 1<=size<=streaming.LIMIT or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Select an XLSX file up to 20 MiB with a SHA256 digest.')
    with transaction.atomic():
        GroupSheetConfiguration.objects.select_for_update().get(pk=group.pk)
        existing=LegacyUpload.objects.filter(batch__group=group,digest=digest,source_sheet=source_sheet).first()
        if existing:
            if existing.phase=='discarded':
                existing.phase='uploading';existing.state={};save(existing)
            return existing
        batch,_=LegacyBatch.objects.get_or_create(group=group,namespace=namespace,defaults={'source_hash':digest,'created_by':actor})
        return LegacyUpload.objects.create(batch=batch,actor=actor,filename=str(body.get('filename','source.xlsx'))[:200],digest=digest,size=size,source_sheet=source_sheet)


def receive(upload,position,content):
    position=int(position)
    if not 0<=position<(upload.size+CHUNK-1)//CHUNK:raise ValueError('Invalid chunk position.')
    if len(content)!=min(CHUNK,upload.size-position*CHUNK):raise ValueError('Chunk length does not match the declared source.')
    digest=hashlib.sha256(content).hexdigest()
    old=upload.chunks.filter(kind='source',position=position).first()
    if old:
        if old.digest!=digest:raise ValueError('This position already contains different bytes.')
        return
    if upload.phase!='uploading':raise ValueError('The source is sealed. Start a new version.')
    LegacyChunk.objects.create(upload=upload,position=position,content=content,digest=digest)


@contextmanager
def leased(upload):
    token=uuid.uuid4();now=timezone.now()
    count=LegacyUpload.objects.filter(pk=upload.pk).filter(Q(lease_until__isnull=True)|Q(lease_until__lt=now)).update(lease=token,lease_until=now+timedelta(seconds=60))
    if not count:raise ValueError('Another request is advancing this upload. Refresh saved progress.')
    try:
        upload.refresh_from_db();yield upload
    finally:LegacyUpload.objects.filter(pk=upload.pk,lease=token).update(lease=None,lease_until=None)


def save(upload):
    upload.revision+=1;upload.save(update_fields=['phase','state','revision','frozen'])


def payload(upload):
    counts=upload.drafts.aggregate(total=Count('pk'),committed=Count('pk',filter=Q(legacy__committed_at__isnull=False)),selected=Count('pk',filter=Q(approved=True)))
    total,committed=counts['total'],counts['committed']
    # Publication permission (including an explicit case link) is not a remote receipt.
    synced=min(committed,upload.state.get('projection',{}).get('offset',0)) if upload.phase in {'readback','complete'} else 0
    error=upload.state.get('sync_error','')
    state=('needs_attention' if error else 'complete' if upload.phase=='complete' else
           'in_progress' if upload.phase in {'backup','projecting','verifying','replacing','readback'} else
           'awaiting_confirmation' if committed==total and total else 'awaiting_import')
    return {'id':str(upload.pk),'namespace':upload.batch.namespace,'group_id':str(upload.batch.group_id),'group_label':upload.batch.group.display_name or upload.batch.group.sheet_name,
        'filename':upload.filename,'source_sheet':upload.source_sheet,'phase':upload.phase,'revision':upload.revision,'frozen':upload.frozen,
        'chunks':list(upload.chunks.filter(kind='source').values_list('position',flat=True)),
        'size':upload.size,'total':total,'committed':committed,
        'sheet_sync':{'state':state,'synced':synced,'pending':committed-synced,'not_imported':total-committed,'error':error},
        'selected':counts['selected'],'state':{k:v for k,v in upload.state.items() if k not in {'cleanup_ids','cleanup_plans','cleanup_facts','cleanup_remaining','snapshot_hashes'}}}


def prepare(upload):
    if upload.phase!='uploading':return
    upload.state=streaming.mapping(upload);upload.phase='mapping';save(upload)


def stage_step(upload,actor,access):
    started=time.monotonic();offset=upload.state['offset'];pending=[];exhausted=True
    previous_count=upload.drafts.count()
    with streaming.rows(upload,offset) as records:
        for next_offset,(physical,cells) in records:
            values=streaming.values_for(cells,upload.state['bindings'])
            if values.get('customer_name') or any(v not in ('','-','0',None) for k,v in values.items() if k not in {'source_row'} and not k.startswith('legacy:')):
                try:source_row=int(values.pop('source_row'))
                except (KeyError,ValueError,TypeError):raise ValueError(f'Worksheet row {physical}: retain its original Source Row.')
                if source_row<2:raise ValueError('Source Row must be at least 2.')
                authorize(actor,access,upload.batch.group,branch=values.get('branch',''),product=values.get('payment_product',''))
                candidate=propose(values)
                blocking=[issue for issue in candidate['issues'] if 'invalid amount' in issue]
                model_fields={f.name:f for f in JawabuFarmerMaster._meta.fields if not f.is_relation}
                for key,value in candidate['fields'].items():
                    if key in model_fields and value not in ('',None):
                        try:model_fields[key].run_validators(model_fields[key].to_python(value))
                        except ValidationError:blocking.append(f'{key}: value exceeds the supported field format, length or precision.')
                candidate['issues']+= [issue for issue in blocking if issue not in candidate['issues']]
                candidate['review_status']='blocked' if blocking else 'warning' if candidate['issues'] else 'ready'
                pending.append(LegacyDraft(upload=upload,source_row=source_row,values=values,proposal=candidate))
                if previous_count+len(pending)>50000:raise ValueError('The selected register exceeds the 50,000-record limit.')
            offset=next_offset
            if len(pending)>=250 or time.monotonic()-started>=5:exhausted=False;break
    with transaction.atomic():
        LegacyDraft.objects.bulk_create(pending,batch_size=100)
        upload.state['offset']=offset
        if exhausted:upload.phase='ready'
        save(upload)


def inspect_rows(upload,offset=0,filter_by='all'):
    qs=upload.drafts.order_by('source_row');offset=max(0,int(offset))
    if filter_by=='committed':qs=qs.filter(legacy__committed_at__isnull=False)
    elif filter_by=='pending':qs=qs.filter(legacy__committed_at__isnull=True)
    elif filter_by=='selected':qs=qs.filter(approved=True)
    elif filter_by in {'ready','warning','blocked'}:qs=qs.filter(proposal__review_status=filter_by)
    total=qs.count();rows=[]
    for draft in qs.select_related('legacy')[offset:offset+50]:
        row=services.row_payload(draft.legacy) if draft.legacy_id else {'id':str(draft.pk),'name':draft.values.get('customer_name',''),
            'source_row':draft.source_row,'sheet':upload.source_sheet,'proposal':draft.proposal,'source_values':draft.values,'committed':False,'existing_cases':[],'identity_collision':False}
        row.update(id=str(draft.pk),approved=draft.approved,reconciliation=draft.reconciliation)
        if not draft.legacy_id and draft.proposal.get('fields',{}).get('national_id'):
            matches=JawabuFarmerMaster.objects.filter(group_configuration=upload.batch.group,national_id=draft.proposal['fields']['national_id']).values('pk','case_reference_number')[:10]
            row['existing_cases']=[{'id':str(m['pk']),'reference':f"JBL-{m['case_reference_number']}"} for m in matches]
            row['identity_collision']=bool(row['existing_cases'])
        rows.append(row)
    return {'rows':rows,'total':total,'offset':offset}


def select(upload,body):
    if upload.phase not in {'ready','committing'}:raise ValueError('Finish staging before selecting rows.')
    if body.get('all') is True:
        upload.drafts.filter(legacy__isnull=True).exclude(proposal__review_status='blocked').update(approved=bool(body.get('approved')))
    else:
        for item in body.get('rows',[])[:50]:
            upload.drafts.filter(pk=item['id'],legacy__isnull=True).exclude(proposal__review_status='blocked').update(approved=bool(item.get('approved')),reconciliation={
                'existing_case_id':str(item.get('existing_case_id','')),'note':str(item.get('note',''))[:2000]})


def cleanup_preview(upload,actor):
    from core.services.miniapp_deletion import authorize as deletion_authorize,preview_selection,CASCADE
    deletion_authorize(actor)
    group=upload.batch.group
    if not upload.drafts.exists():
        raise ValueError('Stage at least one source record before starting a cutover.')
    if upload.drafts.filter(proposal__review_status='blocked').exists():
        raise ValueError('Correct blocked source rows in the workbook and stage a new version before deleting test data.')
    if LegacyUpload.objects.filter(batch__group=group,source_sheet=upload.source_sheet,phase='complete').exclude(pk=upload.pk).exists():
        raise ValueError('This register already completed its legacy cutover. Use audited customer updates; imported live cases are not test data.')
    # Deletion/publication needs whole-owner authority, not an amalgam of narrow branch grants.
    if 'cleanup_ids' not in upload.state or upload.state.get('cleanup_source_sheet')!=upload.source_sheet:
        with transaction.atomic():
            GroupSheetConfiguration.objects.select_for_update().get(pk=group.pk)
            if LegacyUpload.objects.filter(batch__group=group,frozen=True).exclude(pk=upload.pk).exists():raise ValueError('Another cutover owns this group.')
            upload.frozen=True
            upload.state['cleanup_ids']=case_ids(upload)
            upload.state['cleanup_source_sheet']=upload.source_sheet
            upload.state['cleanup_plans']=[];upload.state['cleanup_facts']={};upload.state['cleanup_preview_offset']=0;save(upload)
    ids=upload.state['cleanup_ids'];offset=upload.state['cleanup_preview_offset'];chunk=ids[offset:offset+10]
    if chunk:
        plan=preview_selection(model_label='core.JawabuFarmerMaster',ids=chunk,actor=actor,mode=CASCADE,sheet_policy='legacy_cutover_db_only')
        if plan['blockers']:raise ValueError(' '.join(plan['blockers']))
        from core.services.miniapp_deletion import _row_fingerprint
        for key in plan['deleted']:upload.state['cleanup_facts']['|'.join(key)]=_row_fingerprint(plan['rows'][key])
        for (label,pk),record in plan['rows'].items():
            if label=='core.JawabuFarmerMaster' and not owns_case(upload,record):raise ValueError('A linked case belongs to another owner or register; reconcile it first.')
            owner=getattr(record,'group_configuration_id',None)
            if owner is not None and owner!=group.pk:raise ValueError('Linked operational records belong to another Portal owner. Reconcile ownership before deletion.')
        upload.state['cleanup_plans'].append({'ids':chunk,'fingerprint':plan['fingerprint'],'groups':plan['groups']})
        upload.state['cleanup_preview_offset']+=len(chunk);save(upload)
    if upload.state['cleanup_preview_offset']>=len(ids):
        manifest=hashlib.sha256(json.dumps(upload.state['cleanup_plans'],sort_keys=True).encode()).hexdigest()
        upload.state['cleanup_manifest']=manifest;save(upload)
        disclosed={}
        for plan in upload.state['cleanup_plans']:
            for category in ('deleted','retained','unlinked'):
                for group in plan['groups'][category]:
                    key=(category,group['model']);disclosed.setdefault(key,set()).update(group['references'])
        return {'count':len(ids),'complete':True,'impact':[{'category':k[0],'model':k[1],'count':len(v)} for k,v in sorted(disclosed.items())],
                'source_sheet':upload.source_sheet,'token':signing.dumps({'upload':str(upload.pk),'actor':actor.pk,'manifest':manifest,'source_sheet':upload.source_sheet},salt='legacy-test-cleanup')}
    return {'count':len(ids),'reviewed':upload.state['cleanup_preview_offset'],'complete':False}


def cleanup_confirm(upload,actor,token):
    from core.services.miniapp_deletion import authorize as deletion_authorize
    deletion_authorize(actor)
    if upload.phase!='ready' or not upload.frozen or upload.state.get('cleanup_complete') or upload.drafts.filter(legacy__isnull=False).exists():
        raise ValueError('Test deletion requires a held, reviewed selection before canonical import.')
    signed=signing.loads(token,salt='legacy-test-cleanup',max_age=1800)
    if upload.state.get('cleanup_source_sheet')!=upload.source_sheet or signed!={'upload':str(upload.pk),'actor':actor.pk,'manifest':upload.state.get('cleanup_manifest'),'source_sheet':upload.source_sheet}:raise ValueError('Deletion selection changed. Preview again.')
    upload.phase='deleting';upload.state['cleanup_started']=True;upload.state['cleanup_remaining']=upload.state['cleanup_ids'];save(upload)


def deletion_step(upload,actor):
    from core.services.miniapp_deletion import preview_selection,delete_selection,CASCADE
    remaining=upload.state.get('cleanup_remaining',[])
    if upload.state.get('cleanup_source_sheet')!=upload.source_sheet:raise ValueError('Review the remaining cleanup selection for this register again.')
    live=[str(v) for v in JawabuFarmerMaster.objects.filter(pk__in=remaining,group_configuration=upload.batch.group).order_by('pk').values_list('pk',flat=True)[:10]]
    if live:
        if any(not owns_case(upload,case) for case in JawabuFarmerMaster.objects.filter(pk__in=live)):raise ValueError('Cleanup selection includes another register. Review the remaining selection again.')
        plan=preview_selection(model_label='core.JawabuFarmerMaster',ids=live,actor=actor,mode=CASCADE,sheet_policy='legacy_cutover_db_only')
        approved=set(upload.state['cleanup_ids'])
        if any(label=='core.JawabuFarmerMaster' and pk not in approved for label,pk in plan['deleted']):raise ValueError('New case appeared after deletion preview; review impact again.')
        from core.services.miniapp_deletion import _row_fingerprint
        for key in plan['deleted']:
            if upload.state['cleanup_facts'].get('|'.join(key))!=_row_fingerprint(plan['rows'][key]):raise ValueError('Deletion impact changed after confirmation. Re-review the remaining test selection.')
        delete_selection(model_label='core.JawabuFarmerMaster',ids=live,actor=actor,mode=CASCADE,fingerprint=plan['fingerprint'],
            request_id='legacy-'+str(upload.pk)+'-'+hashlib.sha256(','.join(live).encode()).hexdigest()[:20],sheet_policy='legacy_cutover_db_only')
    else:
        if case_ids(upload):raise ValueError('A new case exists outside the confirmed register selection. Re-preview cleanup.')
        upload.state['cleanup_complete']=True;upload.phase='ready'
    save(upload)


def commit_step(upload,actor,access):
    if not upload.state.get('cleanup_complete'):raise ValueError('Complete the Superuser-confirmed test cleanup first.')
    started=time.monotonic();results=[]
    for draft in upload.drafts.filter(approved=True,legacy__isnull=True).order_by('source_row')[:50]:
        try:
            with transaction.atomic():
                draft=LegacyDraft.objects.select_for_update().get(pk=draft.pk)
                if draft.legacy_id:continue
                authorize(actor,access,upload.batch.group,branch=draft.values.get('branch',''),product=draft.values.get('payment_product',''))
                row,created=LegacyRow.objects.get_or_create(batch=upload.batch,source_sheet=upload.source_sheet,source_row=draft.source_row,
                    defaults={'source_hash':upload.digest,'values':draft.values,'proposal':draft.proposal})
                if row.values!=draft.values:raise ValueError('This source row already has different facts. Reconcile its existing provenance.')
                saved=services.commit_row(row.pk,expected_revision=row.revision,request_key='legacy:'+str(upload.pk)+':'+str(draft.pk),actor=actor,access=access,
                    existing_case_id=draft.reconciliation.get('existing_case_id',''),separate_unit_note=draft.reconciliation.get('note',''))
                draft.legacy=saved;draft.save(update_fields=['legacy'])
                results.append({'id':draft.pk,'ok':True})
        except ValueError as exc:
            # Hold this row so a single bad case does not stall the entire approved selection.
            candidate={**draft.proposal,'commit_error':str(exc)}
            LegacyDraft.objects.filter(pk=draft.pk).update(approved=False,proposal=candidate)
            results.append({'id':draft.pk,'ok':False,'error':str(exc)})
        if time.monotonic()-started>=5:break
    upload.phase='committing' if upload.drafts.filter(approved=True,legacy__isnull=True).exists() else 'ready'
    save(upload);return results
