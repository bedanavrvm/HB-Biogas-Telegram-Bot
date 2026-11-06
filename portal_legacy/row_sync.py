"""FIFO upserts of committed cases; unimported Sheet rows are preserved."""
import uuid,json,time
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone
from openpyxl.utils import get_column_letter
from core.services.identifiers import normalize_kenyan_phone, validate_kenyan_national_id
from .importer import authorize, save
from .models import LegacyRow
from .projection import destination, checksum, record_values
from .workbook import token


def begin(upload):
    if upload.mode=='updates':raise ValueError('Use the non-destructive update publisher for update uploads.')
    if upload.phase not in {'ready','committing'}:raise ValueError('Finish the current processing step before starting Sheet sync.')
    if not upload.frozen or not upload.state.get('cleanup_complete'):raise ValueError('The reviewed cutover hold is required.')
    committed=upload.drafts.filter(legacy__committed_at__isnull=False)
    if not committed.exists():raise ValueError('Import at least one case first.')
    if committed.values('legacy__farmer_id').annotate(n=Count('pk')).filter(n__gt=1).exists():raise ValueError('Multiple source rows link to one case. Reconcile duplicate bindings before syncing.')
    p=upload.state.setdefault('row_sync',{'stage':'prepare','case_rows':{},'scan_offset':0})
    p['return_phase']=upload.phase
    if p['stage']=='done':p['stage']='rows'
    upload.state.pop('sync_error',None);upload.phase='syncing_rows';save(upload)


def _value(values,headers,names):
    return next((str(values[i]).strip() for i,h in enumerate(headers) if token(h) in names and i<len(values) and str(values[i]).strip()),'')


def _check_identity(draft,values,headers):
    from core.services.jawabu_case_reference import display_case_reference
    identity=_value(values,headers,{'masterrecordid'}) or _value(values,headers,{'caseid'})
    if identity:
        if identity not in {str(draft.legacy.farmer_id),display_case_reference(draft.legacy.farmer)}:raise ValueError(f'Source row {draft.source_row}: Sheet Case ID {identity} belongs to another case. No row was overwritten.')
        return
    if not any(str(v).strip() for v in values):return
    original=draft.reconciliation.get('original_values',draft.values)
    name=_value(values,headers,{'customername','clientname','name'}).casefold()
    names={str(v.get('customer_name','')).strip().casefold() for v in (original,draft.values)}-{''}
    national_id=_value(values,headers,{'nationalid','customernationalid','idnumber'})
    phone=_value(values,headers,{'primaryphone','primaryphonenumber','phonenumber'})
    normalized_id=validate_kenyan_national_id(national_id)
    same_id=bool(normalized_id and normalized_id in {validate_kenyan_national_id(v.get('national_id','')) for v in (original,draft.values)})
    phone_key=lambda value:normalize_kenyan_phone(value) or str(value).strip()
    same_phone=bool(phone and phone_key(phone) in {phone_key(v.get('primary_phone','')) for v in (original,draft.values)})
    if not (same_id or name in names and same_phone):
        raise ValueError(f'Source row {draft.source_row}: Sheet name/ID/phone do not confirm the source. Expected {original.get("customer_name","")} / {original.get("national_id","")} / {original.get("primary_phone","")}; found {name} / {national_id} / {phone}. No row was overwritten.')


def advance(upload,actor,access):
    authorize(actor,access,upload.batch.group,branch='')
    if not upload.frozen:raise ValueError('The cutover hold was released. Refresh before syncing.')
    p=upload.state['row_sync'];sheet=destination(upload);book=sheet.spreadsheet
    # Finish an uncertain saved write before upgrading its allocation checkpoint.
    if p['stage']!='prepare' and not p.get('allocation') and not p.get('plans'):
        p['stage']='prepare'
    if p['stage']=='prepare':
        header_row=int((upload.batch.group.workflow or {}).get('master_header_row') or 1)
        headers=sheet.row_values(header_row)
        if not any(token(h) in {'customername','clientname','name'} for h in headers):raise ValueError('The selected register needs a Customer Name header.')
        new_headers=list(headers)
        if 'caseid' not in {token(h) for h in headers}:new_headers.append('Case ID')
        if 'masterrecordid' not in {token(h) for h in headers}:new_headers.append('Master Record ID')
        p.update(spreadsheet=str(book.id),sheet=sheet.id,header_row=header_row,headers=headers,new_headers=new_headers,scan_rows=sheet.row_count,
            stage='scan',scan_offset=0,case_rows={},empty_rows=[],allocation='first_empty',next_append=sheet.row_count+1)
        save(upload);return
    if str(book.id)!=p['spreadsheet'] or sheet.id!=p['sheet']:raise ValueError('Sheet destination changed. Restore the reviewed destination before resuming.')
    headers=sheet.row_values(p['header_row'])
    if headers not in (p['headers'],p['new_headers']):raise ValueError('Sheet headers changed. Restore the reviewed headers before resuming.')
    width=len(p['new_headers'])
    if p['stage']=='scan':
        start=p['header_row']+1+p['scan_offset'];end=min(start+249,p['scan_rows'])
        if start<=end:
            page=sheet.get(f'A{start}:{get_column_letter(sheet.col_count)}{end}',value_render_option='FORMULA')
            identities=[];references=[];capacity=upload.drafts.count()
            for number in range(start,end+1):
                values=page[number-start] if number-start<len(page) else []
                if not any(str(v).strip() for v in values) and len(p['empty_rows'])<capacity:p['empty_rows'].append(number)
                identity=_value(values,headers,{'masterrecordid'}) or _value(values,headers,{'caseid'})
                try:identities.append((number,str(uuid.UUID(identity))))
                except ValueError:
                    if identity.startswith('JBL-') and identity[4:].isdigit():references.append((number,int(identity[4:])))
            owned={str(pk) for pk in upload.drafts.filter(legacy__farmer_id__in=[value for _,value in identities]).values_list('legacy__farmer_id',flat=True)}
            reference_ids=dict(upload.drafts.filter(legacy__farmer__case_reference_number__in=[value for _,value in references]).values_list('legacy__farmer__case_reference_number','legacy__farmer_id'))
            identities.extend((number,str(reference_ids[ref])) for number,ref in references if ref in reference_ids)
            owned.update(str(value) for value in reference_ids.values())
            for number,identity in identities:
                if identity not in owned:continue
                if identity in p['case_rows'] and p['case_rows'][identity]!=number:raise ValueError(f'Duplicate Case ID on Sheet rows {p["case_rows"][identity]} and {number}; resolve it before syncing.')
                p['case_rows'][identity]=number
            p['scan_offset']+=250
        else:p['stage']='rows'
        save(upload);return
    plans=p.get('plans',[])
    if not plans:
        drafts=list(upload.drafts.filter(legacy__committed_at__isnull=False).filter(
            Q(reconciliation__sheet_receipt__isnull=True)|Q(reconciliation__sheet_receipt__verified=False)|Q(reconciliation__sheet_receipt__reference_format__isnull=True)
        ).select_related('legacy__farmer').order_by('legacy__committed_at','pk')[:50])
        if not drafts:
            p['stage']='done';upload.state.pop('sync_error',None);upload.phase=p['return_phase']
            if not upload.drafts.filter(legacy__isnull=True).exists():upload.phase='complete';upload.frozen=False
            save(upload);return
        targets=[p['case_rows'].get(str(d.legacy.farmer_id),d.source_row) for d in drafts]
        if any(row<=p['header_row'] for row in targets):raise ValueError('Source Row points at the Sheet header; no row was overwritten.')
        column=get_column_letter(sheet.col_count)
        valid=[(i,row) for i,row in enumerate(targets) if row<=sheet.row_count]
        pages=sheet.batch_get([f'A{row}:{column}{row}' for _,row in valid],value_render_option='FORMULA') if valid else []
        existing={index:list(page[0]) if page else [] for (index,_),page in zip(valid,pages)}
        started=time.monotonic()
        for index,(draft,row) in enumerate(zip(drafts,targets)):
            authorize(actor,access,upload.batch.group,branch=draft.values.get('branch',''),product=draft.values.get('payment_product',''))
            old=existing.get(index,[])
            if str(draft.legacy.farmer_id) not in p['case_rows']:
                # Source Row is provenance; a newly projected case may already occupy it.
                if row in p['case_rows'].values():old=[]
                if not any(str(v).strip() for v in old):
                    row=p['empty_rows'].pop(0) if p['empty_rows'] else p['next_append']
                    if row==p['next_append']:p['next_append']+=1
            _check_identity(draft,old,headers)
            values=record_values(draft.legacy,p['new_headers'],row-p['header_row'],existing=old)
            plans.append({'draft':draft.pk,'legacy':str(draft.legacy_id),'case':str(draft.legacy.farmer_id),'row':row,'before':checksum([old]),'values':values,'revision':draft.legacy.farmer.workflow_revision})
            if len(json.dumps(plans).encode())>512*1024 or time.monotonic()-started>=3:break
        p['plans']=plans;save(upload)
    # Keep durable write plans even when Google loses an acknowledgement.
    from gspread.exceptions import APIError
    from requests.exceptions import RequestException
    from core.services.miniapp_deletion_sheets import lock_sheet_mutations
    failure=None
    with transaction.atomic():
        lock_sheet_mutations()
        try:
            _write_plans(upload, p, sheet, book, headers, width, plans)
        except (APIError, RequestException, TimeoutError, ValueError) as exc:
            failure=exc
    if failure: raise failure


def _write_plans(upload, p, sheet, book, headers, width, plans):
    def read():
        valid=[plan for plan in plans if plan['row']<=sheet.row_count]
        column=get_column_letter(min(width,sheet.col_count))
        ranges=[f'A{plan["row"]}:{column}{plan["row"]}' for plan in valid]
        values=sheet.batch_get(ranges,value_render_option='FORMULA') if valid else []
        found={plan['draft']:list(rows[0]) if rows else [] for plan,rows in zip(valid,values)}
        return [found.get(plan['draft'],[]) for plan in plans]
    from core.models import JawabuFarmerMaster
    cases={str(farmer.pk):farmer for farmer in JawabuFarmerMaster.objects.filter(pk__in=[plan['case'] for plan in plans]).order_by('pk').select_for_update()}
    observed=read()
    for plan,values in zip(plans,observed):
        farmer=cases[plan['case']]
        if plan.get('revision')!=farmer.workflow_revision:
            legacy=LegacyRow.objects.get(pk=plan['legacy']);legacy.farmer=farmer
            fresh=record_values(legacy,p['new_headers'],plan['row']-p['header_row'],existing=values)
            if checksum([values]) not in {plan['before'],checksum([plan['values']]),checksum([fresh])}:
                raise ValueError('A pending import row changed outside its saved checkpoint. Review it before retrying.')
            plan.update(values=fresh,before=checksum([values]),revision=farmer.workflow_revision)
    save(upload)
    requests=[]
    for plan,values in zip(plans,observed):
        if checksum([values])==checksum([plan['values']]):continue
        if checksum([values])!=plan['before']:raise ValueError(f'Sheet row {plan["row"]} changed after preparation; no stale value was overwritten.')
        for index,value in enumerate(plan['values']):
            old=values[index] if index<len(values) else ''
            if str(value)==str(old):continue
            requests.append({'updateCells':{'range':{'sheetId':sheet.id,'startRowIndex':plan['row']-1,'endRowIndex':plan['row'],'startColumnIndex':index,'endColumnIndex':index+1},
                'rows':[{'values':[{'userEnteredValue':{'stringValue':str(value)}}]}],'fields':'userEnteredValue'}})
    if requests:
        last=max(plan['row'] for plan in plans)
        if sum(s.row_count*s.col_count for s in book.worksheets())+max(0,last-sheet.row_count)*max(width,sheet.col_count)+max(0,width-sheet.col_count)*sheet.row_count>10_000_000:raise ValueError('Insufficient Sheet capacity.')
        dimensions=[]
        if sheet.row_count<last:dimensions.append({'appendDimension':{'sheetId':sheet.id,'dimension':'ROWS','length':last-sheet.row_count}})
        if sheet.col_count<width:dimensions.append({'appendDimension':{'sheetId':sheet.id,'dimension':'COLUMNS','length':width-sheet.col_count}})
        if headers!=p['new_headers']:
            dimensions.append({'updateCells':{'range':{'sheetId':sheet.id,'startRowIndex':p['header_row']-1,'endRowIndex':p['header_row'],'startColumnIndex':0,'endColumnIndex':width},'rows':[{'values':[{'userEnteredValue':{'stringValue':str(v)}} for v in p['new_headers']]}],'fields':'userEnteredValue'}})
        book.batch_update({'requests':dimensions+requests})
        sheet=book.get_worksheet_by_id(p['sheet'])
    from core.services.jawabu_master import hide_master_system_columns
    for index,header in enumerate(p['new_headers'],1):
        if token(header)=='masterrecordid':hide_master_system_columns(sheet,index,index)
    for plan,values in zip(plans,read()):
        if checksum([values])!=checksum([plan['values']]):raise ValueError(f'Sheet row {plan["row"]} did not verify. Resume to check the saved write before retrying.')
    with transaction.atomic():
        for plan in plans:
            draft=upload.drafts.select_for_update(of=('self',)).select_related('legacy__farmer').get(pk=plan['draft'])
            draft.reconciliation['sheet_receipt']={'verified':True,'spreadsheet':p['spreadsheet'],'sheet':sheet.id,'row':plan['row'],'digest':checksum([plan['values']]),'revision':plan['revision'],'at':timezone.now().isoformat()}
            from core.services.jawabu_case_reference import display_case_reference
            case_column=next(i for i,header in enumerate(p['new_headers']) if token(header)=='caseid')
            if plan['values'][case_column]==display_case_reference(draft.legacy.farmer):draft.reconciliation['sheet_receipt']['reference_format']='staff'
            draft.save(update_fields=['reconciliation']);p['case_rows'][plan['case']]=plan['row']
        LegacyRow.objects.filter(pk__in=[plan['legacy'] for plan in plans]).update(publication_ready=True)
        p.pop('plans');save(upload)
