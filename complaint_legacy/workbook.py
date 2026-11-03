"""The live Complaints register contract, with explicit historical header aliases."""
from datetime import date, datetime, time
from io import BytesIO
import hashlib
import json
import re

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation
from core.services.identifiers import normalize_kenyan_phone, validate_kenyan_national_id
from core.services.sheet_schema import COMPLAINT_REGISTER_FIELD_HEADERS


def token(value): return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


ALIASES = {token(label): key for key, label in COMPLAINT_REGISTER_FIELD_HEADERS.items()}
ALIASES.update({token(key): key for key in COMPLAINT_REGISTER_FIELD_HEADERS})
ALIASES.update({'sourcerow': 'source_row', 'casedate': 'date_reported', 'casereporteddate': 'date_reported',
    'casestatus': 'status', 'farmer': 'customer_name', 'mobile1': 'customer_phone', 'mobile2': 'secondary_phone',
    'casesubject': 'complaint_description', 'caseclosuredate': 'date_resolved',
    'jawabucommentsfeedback': 'historical_jbl_feedback', 'hbgcasestatusreconfirmation': 'historical_hb_reconfirmation',
    'hbcomments': 'historical_hb_comments', 'jblcomments': 'historical_jbl_comments'})
STATUSES = {'OPEN': 'Open', 'PENDING': 'Open', 'CLOSED': 'Closed', 'REOPENED': 'Reopened'}


def literal(value):
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, date): return value.isoformat()
    return '' if value is None else str(value).strip()


def mapping(cells):
    bindings = {}; seen = set(); headers = {}
    for cell in cells:
        if cell['value'] is None or not str(cell['value']).strip(): continue
        column = cell['column']; label = str(cell['value']).strip()
        if column > 256: raise ValueError('Named source columns must fit within the first 256 columns.')
        key = ALIASES.get(token(label), 'unmapped:'+str(column)+':'+label)
        if key in seen: raise ValueError(f'Duplicate column mapping for {label}. Retain one authoritative column.')
        seen.add(key); bindings[str(column)] = key; headers[str(column)] = label
    if not {'status', 'date_reported'} <= seen:
        raise ValueError('The workbook must contain Status and Date Reported (CASE STATUS and Case Date are also accepted).')
    return {'bindings': bindings, 'headers': headers}


def values_for(cells, bindings):
    values = {}
    for cell in cells:
        value = cell['value']
        if value in ('', None): continue
        column = str(cell['column'])
        if int(column) > 256: raise ValueError('A populated source cell lies beyond column 256; retain it in a reviewed source column.')
        key = bindings.get(column, 'unmapped:'+column)
        if cell['data_type'] == 'f':
            if key in {'status', 'date_reported', 'date_resolved'}:
                raise ValueError('Status and date formulas must be replaced with reviewed values before uploading.')
            key = 'formula:'+key
        values[key] = literal(value)
    return values


def reported_date(raw):
    if not raw: return None
    text = str(raw).strip()
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ].*)?', text):
            value = datetime.fromisoformat(text)
            return timezone.make_aware(value) if timezone.is_naive(value) else value
    except ValueError: return None
    for fmt in ('%d-%m-%y', '%d-%m-%Y', '%d/%m/%Y', '%d/%m/%y', '%d-%b-%Y', '%d-%B-%Y', '%d.%m.%Y', '%d.%m.%y'):
        try: return timezone.make_aware(datetime.combine(datetime.strptime(text, fmt).date(), time.min))
        except ValueError: pass
    return None


def propose(values):
    issues = []; warnings = []; fields = {}
    status = STATUSES.get(str(values.get('status', '')).strip().upper())
    if not status: issues.append('Clean Status to OPEN, CLOSED or REOPENED. It cannot be inferred from comments.')
    start = reported_date(values.get('date_reported'))
    if not start: issues.append('A valid original Date Reported is required.')
    elif start > timezone.now(): issues.append('Date Reported cannot be in the future.')
    end = reported_date(values.get('date_resolved')) if values.get('date_resolved') else None
    if values.get('date_resolved') and not end: issues.append('Date Resolved is not a valid single date.')
    if end and (not start or end < start or end > timezone.now()): issues.append('Date Resolved must follow Date Reported and cannot be in the future.')
    if end and status != 'Closed': issues.append('An open/reopened case cannot have a final Date Resolved.')
    if status == 'Closed' and not end: warnings.append('Closure date unknown; elapsed days and SLA outcome remain unknown.')
    text_fields = ('customer_name', 'customer_id', 'county', 'sub_county', 'village', 'branch_region',
                   'complaint_category', 'complaint_description', 'resolution_details', 'reported_by', 'gps_link')
    for key in text_fields:
        fields[key] = str(values.get(key, '')).strip()
        limit = 500 if key == 'gps_link' else 128 if key in {'county','sub_county'} else 50000 if key in {'complaint_description','resolution_details'} else 255
        if limit and len(fields[key]) > limit: issues.append(f'{COMPLAINT_REGISTER_FIELD_HEADERS.get(key, key)} exceeds {limit} characters; original retained.')
    if fields['customer_id'] and not validate_kenyan_national_id(fields['customer_id']):
        warnings.append('National ID format needs review; original retained and no customer identity assigned.')
        fields['customer_id'] = ''
    if fields['gps_link'] and not re.match(r'^https?://', fields['gps_link'], re.I):
        warnings.append('GPS Link is not an HTTP(S) link; original retained.'); fields['gps_link'] = ''
    for key in ('customer_phone', 'secondary_phone'):
        raw = str(values.get(key, '')).strip(); valid = normalize_kenyan_phone(raw)
        parts = [p.strip() for p in re.split(r'[/,;\n]+', raw) if p.strip()]
        if not valid and len(parts) > 1 and all(normalize_kenyan_phone(p) for p in parts):
            valid = normalize_kenyan_phone(parts[0]); warnings.append(f'{key}: extra contacts retained in the historical source.')
        fields[key] = valid or raw
        if raw and not valid: warnings.append(f'{key}: historical phone format needs review; original retained.')
        if len(fields[key]) > 255: issues.append(f'{key} exceeds 255 characters; original retained.')
    for key in ('customer_name', 'customer_phone', 'customer_id', 'county', 'sub_county', 'village', 'branch_region', 'complaint_category', 'complaint_description'):
        if not fields.get(key): warnings.append(f'{COMPLAINT_REGISTER_FIELD_HEADERS.get(key,key)} is missing in this historical record.')
    if any(key.startswith(('unmapped:', 'formula:')) for key in values): warnings.append('Unmapped cells/formulas are retained in the historical source.')
    if values.get('complaint_id'): warnings.append('Original Complaint ID retained as source evidence; current CMP references are allocated by Complaints.')
    fields.update(status=status or '', date_reported=start.isoformat() if start else '', date_resolved=end.isoformat() if end else '')
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'fields': fields, 'issues': issues, 'warnings': warnings, 'status': 'blocked' if issues else 'warning' if warnings else 'ready', 'fingerprint': fingerprint}


def template():
    book = Workbook(); sheet = book.active; sheet.title = 'Case Management'
    sheet.append(list(COMPLAINT_REGISTER_FIELD_HEADERS.values())+['Source Row'])
    sheet.freeze_panes = 'A2'; sheet.auto_filter.ref = 'A1:W1'
    statuses = DataValidation(type='list', formula1='"OPEN,CLOSED,REOPENED"', allow_blank=False)
    statuses.errorTitle = 'Choose a status'; statuses.error = 'Choose OPEN, CLOSED or REOPENED.'; statuses.showErrorMessage = True
    sheet.add_data_validation(statuses); statuses.add('D2:D50001')
    sheet.column_dimensions['C'].number_format = 'dd-mmm-yyyy'
    sheet.column_dimensions['T'].number_format = 'dd-mmm-yyyy'
    notes = book.create_sheet('Import notes')
    for line in ['Status and Date Reported are mandatory. Other missing historical fields remain warnings.',
                 'Leave unknown Date Resolved blank; do not invent closure dates or elapsed days.',
                 'Retain Source Row when correcting/reordering a previously staged workbook.',
                 'Blank Complaint ID allocates a normal CMP reference. Existing cases are never overwritten.',
                 'Dates accept the normal projection format and 24-May-2026. Comments remain separate.',
                 'The importer saves approved rows first. Sheet publication is a separate explicit action.']:
        notes.append([line])
    out = BytesIO(); book.save(out); book.close(); return out.getvalue()
