"""Explicit replacement of one selected register, preserving its counterpart."""
from decimal import Decimal
import hashlib,json,zlib
import uuid
from django.db import transaction
from django.utils import timezone
from openpyxl.utils import get_column_letter
from core.services.external_resilience import external_call_budget
from .models import LegacyChunk,LegacyRow
from .importer import save,authorize
from .registers import case_ids,owns_case


def checksum(rows):
    def canonical(row):
        row=[str(v) if v is not None else '' for v in row]
        while row and row[-1]=='':row.pop()
        return row
    return hashlib.sha256(json.dumps([canonical(r) for r in rows],separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def destination(upload):
    from core.services.sheets import GoogleSheetsService
    config=upload.batch.group;workflow=config.workflow or {}
    master=str(workflow.get('master_sheet_name') or 'Master Data').strip()
    eco=str(workflow.get('eco_conserve_sheet_name') or 'Eco-conserve').strip()
    if master.casefold()==eco.casefold():raise ValueError('Master Data and Eco-conserve destinations must be different.')
    name=eco if upload.source_sheet=='Eco-conserve' else master
    service=GoogleSheetsService.get_instance(sheet_id=workflow.get('master_sheet_id') or config.sheet_id,sheet_name=name)
    if not service.is_available():raise ValueError(f'{upload.source_sheet} is unavailable. Local imported records remain saved.')
    # The gateway caches worksheets; grid dimensions may have changed since opening it.
    return service._sheet.spreadsheet.get_worksheet_by_id(service._sheet.id)


def preview(upload,actor,access):
    authorize(actor,access,upload.batch.group,branch='')
    if not upload.state.get('cleanup_complete'):raise ValueError('Complete test cleanup first.')
    if upload.drafts.filter(legacy__isnull=True).exists():raise ValueError('Account for every source row before replacing the selected register.')
    imported_ids={str(pk) for pk in upload.drafts.values_list('legacy__farmer_id',flat=True)}
    if upload.drafts.values('legacy__farmer_id').distinct().count()!=upload.drafts.count():
        raise ValueError('Multiple source rows link to one case. Reconcile the duplicate bindings before complete replacement.')
    if set(case_ids(upload))!=imported_ids:
        raise ValueError('The selected register contains cases outside this import, or a case is linked to the other register. Reconcile before replacement.')
    sheet=destination(upload)
    workflow=upload.batch.group.workflow or {};header_row=int(workflow.get('master_header_row') or 1)
    headers=sheet.row_values(header_row)
    if not headers:raise ValueError('The selected register requires an existing header row.')
    from .workbook import token
    if not any(token(h) in {'customername','clientname','name'} for h in headers):raise ValueError('The selected register must have a named customer column before replacement.')
    new_headers=list(headers)
    if 'caseid' not in {token(h) for h in headers}:new_headers.append('Case ID')
    upload.state.pop('sync_error',None)
    upload.state['projection']={'spreadsheet':sheet.spreadsheet.id,'sheet':sheet.id,'name':sheet.title,'source_sheet':upload.source_sheet,
        'header_row':header_row,'headers':headers,'new_headers':new_headers,'old_rows':sheet.row_count,'old_cols':sheet.col_count,
        'count':upload.drafts.count(),'offset':0,'snapshot_hashes':[],'snapshot_kind':'backup_'+str(upload.revision)}
    save(upload)
    return {'spreadsheet':sheet.spreadsheet.id,'tab':sheet.title,'data_start_row':header_row+1,'clear_through_row':sheet.row_count,
            'clear_columns':sheet.col_count,'rows':upload.drafts.count(),'headers':new_headers,'source_sheet':upload.source_sheet,'preserved_register':'Master Data' if upload.source_sheet=='Eco-conserve' else 'Eco-conserve'}


def confirm(upload,body):
    if not body.get('manual_edits_paused'):raise ValueError('Pause manual edits to the selected register before confirming replacement.')
    if not upload.state.get('projection'):raise ValueError('Preview the exact destination first.')
    upload.frozen=True;upload.phase='backup';save(upload)


def record_values(legacy,headers,ordinal,existing=None):
    from core.services.jawabu_pipeline import master_projection_fields
    from core.services.jawabu_validation import parse_business_date
    from .workbook import token
    fields=master_projection_fields(legacy.farmer);result={}
    for name,(aliases,value) in fields.items():
        if value is None:value=''
        if name in {'county','sub_county','village','ward','branch','system_branch','landmark'}:value=str(value).upper()
        if name.endswith('_date') and value:
            parsed=parse_business_date(value)
            if parsed:value=parsed.strftime('%d-%b-%Y')
        for alias in aliases:result[token(alias)]=str(value)
    for name in ('invoice_amount','discount','payment','balance_due'):
        value=getattr(legacy.farmer,name,None)
        if value is not None:
            for alias in fields.get(name,([],None))[0]:result[token(alias)]=format(Decimal(str(value)),'.2f')
    for name in ('primary_phone','secondary_phone'):
        if legacy.values.get(name):
            for alias in fields.get(name,([],None))[0]:result[token(alias)]=legacy.values[name]
    hb=legacy.values.get('deposit_paid_hbg','0');jbl=legacy.values.get('legacy_deposit_paid_jbl','0')
    from .workbook import propose
    parsed=propose(legacy.values)['fields']
    total='' if 'not on sf' in hb.lower() else format(Decimal(parsed.get('deposit_paid_hbg','0'))+Decimal(parsed.get('legacy_deposit_paid_jbl','0')),'.2f')
    result.update({'caseid':str(legacy.farmer_id),'masterrecordid':str(legacy.farmer_id),'no':str(ordinal),
        'total':total,'depositpaidtojbl':str(jbl),'depositpaidtohbg':str(hb)})
    # Historical-only fields are projected only if that explicit column already exists.
    for name,value in legacy.values.items():
        if name.startswith('legacy:'):result[token('LEGACY | '+name[7:]+' | Cleaned')]=str(value)
    return [result.get(token(h),existing[i] if existing and i<len(existing) else '') for i,h in enumerate(headers)]


def advance(upload,actor,access):
    authorize(actor,access,upload.batch.group,branch='')
    p=upload.state['projection']
    if p.get('source_sheet','Master Data')!=upload.source_sheet:raise ValueError('The saved projection belongs to another register. Re-preview the destination.')
    sheet=destination(upload)
    if str(sheet.spreadsheet.id)!=str(p['spreadsheet']) or sheet.id!=p['sheet']:raise ValueError('Destination changed. Re-preview the selected register.')
    allowed_headers=[p['headers'],p['new_headers']] if upload.phase in {'replacing','readback','complete'} else [p['headers']]
    if sheet.row_values(p['header_row']) not in allowed_headers:raise ValueError('Selected register headers changed after preview.')
    book=sheet.spreadsheet;offset=p['offset'];width=len(p['new_headers']);column=get_column_letter(max(width,p['old_cols']))
    if upload.phase in {'backup','projecting','verifying'} and (sheet.row_count!=p['old_rows'] or sheet.col_count!=p['old_cols']):
        raise ValueError('Selected register grid changed after preview. Review replacement again before continuing.')
    with external_call_budget(8):
        if upload.phase=='backup':
            start=p['header_row']+1+offset;end=min(start+249,p['old_rows'])
            if start<=p['old_rows']:
                rows=sheet.get(f'A{start}:{column}{end}',value_render_option='FORMULA')
                from .workbook import token
                from core.models import JawabuFarmerMaster
                identity_columns=[i for i,h in enumerate(p['headers']) if token(h) in {'caseid','masterrecordid'}]
                identities=[]
                for row in rows:
                    for i in identity_columns:
                        if i<len(row) and row[i]:
                            try:identities.append(uuid.UUID(str(row[i])))
                            except ValueError:pass
                if any(not owns_case(upload,case) for case in JawabuFarmerMaster.objects.filter(pk__in=identities).only('pk','group_configuration_id','legacy_fulfillment_partner','county','hb_sales_person')):
                    raise ValueError('The destination contains live Case IDs from another owner or register. No replacement performed.')
                data=zlib.compress(json.dumps(rows,ensure_ascii=False).encode());digest=checksum(rows)
                chunk,_=LegacyChunk.objects.get_or_create(upload=upload,kind=p.get('snapshot_kind','backup'),position=offset,defaults={'content':data,'digest':digest})
                if chunk.digest!=digest:raise ValueError('Selected register changed during snapshot. Re-preview the destination.')
                p['snapshot_hashes'].append([start,end,digest]);p['offset']+=250
            else:
                if p['count']==0:raise ValueError('An empty import cannot replace the selected register.')
                # Capacity check includes the temporary copy, not a second full backup worksheet.
                title='_legacy_'+str(upload.pk).replace('-','')[:20]
                worksheets=book.worksheets();staging=next((w for w in worksheets if w.title==title),None)
                capacity=sum(w.row_count*w.col_count for w in worksheets)
                added=(0 if staging else (p['count']+1)*width)+max(0,p['count']+p['header_row']-sheet.row_count)*max(width,sheet.col_count)+max(0,width-sheet.col_count)*sheet.row_count
                if capacity+added>10_000_000:raise ValueError('Insufficient spreadsheet cell capacity for safe staging and replacement.')
                staging=staging or book.add_worksheet(title=title,rows=max(p['count']+1,2),cols=width)
                staging.hide()
                staging.update(range_name=f'A1:{get_column_letter(width)}1',values=[p['new_headers']],value_input_option='RAW')
                p['staging_id']=staging.id;p['offset']=0;upload.phase='projecting'
        elif upload.phase=='projecting':
            drafts=list(upload.drafts.select_related('legacy__farmer').order_by('source_row')[offset:offset+100])
            if drafts:
                rows=[]
                for i,draft in enumerate(drafts):
                    services_group=upload.batch.group
                    authorize(actor,access,services_group,branch=draft.values.get('branch',''),product=draft.values.get('payment_product',''))
                    rows.append(record_values(draft.legacy,p['new_headers'],offset+i+1))
                staging=book.get_worksheet_by_id(p['staging_id'])
                staging.update(range_name=f'A{offset+2}:{get_column_letter(width)}{offset+1+len(rows)}',values=rows,value_input_option='RAW')
                actual=staging.get(f'A{offset+2}:{get_column_letter(width)}{offset+1+len(rows)}',value_render_option='FORMULA')
                if checksum(actual)!=checksum(rows):raise ValueError('Staging readback differs. Retry the same saved offset.')
                p['offset']+=len(rows)
            else:p['offset']=0;upload.phase='verifying'
        elif upload.phase=='verifying':
            if offset<len(p['snapshot_hashes']):
                start,end,digest=p['snapshot_hashes'][offset]
                if checksum(sheet.get(f'A{start}:{column}{end}',value_render_option='FORMULA'))!=digest:raise ValueError('Selected register changed since preview. Pause edits and prepare a fresh snapshot.')
                p['offset']+=1
            else:upload.phase='replacing'
        elif upload.phase=='replacing':
            # Snapshot/staging are retained until target readback; no destructive blind retry.
            metadata=book.fetch_sheet_metadata()
            markers=metadata.get('developerMetadata',[])+[m for s in metadata.get('sheets',[]) if s.get('properties',{}).get('sheetId')==sheet.id for m in s.get('developerMetadata',[])]
            marker=next((m for m in markers if m.get('metadataKey')=='legacy_cutover' and m.get('metadataValue')==str(upload.pk) and m.get('location',{}).get('sheetId')==sheet.id),None)
            if not marker:
                if sheet.row_count!=p['old_rows'] or sheet.col_count!=p['old_cols']:raise ValueError('Selected register grid changed before replacement. IT must inspect the destination; no replacement was sent.')
                requests=[]
                if sheet.row_count<p['count']+p['header_row']:requests.append({'appendDimension':{'sheetId':sheet.id,'dimension':'ROWS','length':p['count']+p['header_row']-sheet.row_count}})
                if sheet.col_count<width:requests.append({'appendDimension':{'sheetId':sheet.id,'dimension':'COLUMNS','length':width-sheet.col_count}})
                requests.extend([
                    {'updateCells':{'range':{'sheetId':sheet.id,'startRowIndex':p['header_row'],'endRowIndex':max(p['old_rows'],p['count']+p['header_row']),'startColumnIndex':0,'endColumnIndex':max(p['old_cols'],width)},'fields':'userEnteredValue'}},
                    {'copyPaste':{'source':{'sheetId':p['staging_id'],'startRowIndex':1,'endRowIndex':p['count']+1,'startColumnIndex':0,'endColumnIndex':width},'destination':{'sheetId':sheet.id,'startRowIndex':p['header_row'],'startColumnIndex':0},'pasteType':'PASTE_VALUES'}},
                    {'createDeveloperMetadata':{'developerMetadata':{'metadataKey':'legacy_cutover','metadataValue':str(upload.pk),'visibility':'DOCUMENT','location':{'sheetId':sheet.id}}}}])
                if width>len(p['headers']):requests.append({'updateCells':{'range':{'sheetId':sheet.id,'startRowIndex':p['header_row']-1,'endRowIndex':p['header_row'],'startColumnIndex':len(p['headers']),'endColumnIndex':width},'rows':[{'values':[{'userEnteredValue':{'stringValue':v}} for v in p['new_headers'][len(p['headers']):]]}],'fields':'userEnteredValue'}})
                book.batch_update({'requests':requests})
            upload.phase='readback';p['offset']=0
        elif upload.phase=='readback':
            drafts=list(upload.drafts.select_related('legacy__farmer').order_by('source_row')[offset:offset+100])
            if drafts:
                expected=[record_values(d.legacy,p['new_headers'],offset+i+1) for i,d in enumerate(drafts)]
                start=p['header_row']+offset+1;end=start+len(drafts)-1
                if checksum(sheet.get(f'A{start}:{get_column_letter(width)}{end}',value_render_option='FORMULA'))!=checksum(expected):raise ValueError('Selected register readback mismatch. Group remains held; inspect saved snapshot.')
                with transaction.atomic():
                    LegacyRow.objects.filter(pk__in=[d.legacy_id for d in drafts]).update(publication_ready=True)
                    p['offset']+=len(drafts);save(upload)
            else:
                upload.phase='complete';upload.frozen=False;p['completed_at']=timezone.now().isoformat()
        save(upload)
