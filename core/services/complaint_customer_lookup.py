"""Complaints' explicitly authorized, biodata-only Portal customer directory."""
import re
from uuid import UUID

from django.db.models import Q
from core.models import JawabuFarmerMaster
from core.services.identifiers import normalize_kenyan_phone


def source(key):
    from .complaint_cases import ComplaintCaseError
    try:
        record = JawabuFarmerMaster.objects.select_related('customer').get(pk=UUID(str(key)))
    except (ValueError, TypeError, JawabuFarmerMaster.DoesNotExist):
        raise ComplaintCaseError('This Portal customer is no longer available. Choose another suggestion or continue manually.') from None
    return record


def name(record):
    return record.imab_customer_name or record.customer_name


def phone(record):
    value = record.primary_phone or (record.customer.primary_phone if record.customer else '')
    return normalize_kenyan_phone(value) or value


def national_id(record):
    return record.national_id or (record.customer.national_id if record.customer else '')


def reference(record):
    return f'JBL-{record.case_reference_number}'


def prefill(record, actor):
    from .location_catalog import location_options, resolve_location
    from .complaint_cases import numeric_customer_id
    fields = {'client_name': name(record), 'customer_id': national_id(record), 'customer_phone': phone(record),
              'secondary_phone': normalize_kenyan_phone(record.secondary_phone) or record.secondary_phone,
              'village': record.village, 'branch_region': '', 'county': '', 'sub_county': ''}
    warnings = []
    issues = {}
    branch = resolve_location(record.branch, location_type='branch')
    options = location_options(user=actor.user, access=actor.access)
    if branch and any(item['code']==branch.code for item in options['branches']):
        fields['branch_region'] = branch.code
    elif record.branch:
        warnings.append(f'Portal branch: {record.branch}. Choose an active branch within your Complaints permissions.')
    county = resolve_location(record.county, location_type='county')
    options = location_options(user=actor.user, access=actor.access, branch_value=fields['branch_region'])
    if county and any(item['code']==county.code for item in options['counties']): fields['county'] = county.code
    elif record.county: warnings.append(f'Portal county: {record.county}. Choose a supported county.')
    sub = resolve_location(record.sub_county, location_type='sub_county', parent=county) if county else None
    options = location_options(user=actor.user, access=actor.access, branch_value=fields['branch_region'], county_value=fields['county'])
    if sub and any(item['code']==sub.code for item in options['sub_counties']): fields['sub_county'] = sub.code
    elif record.sub_county: warnings.append(f'Portal constituency: {record.sub_county}. Choose a supported constituency.')
    for field, label in [('customer_phone','Primary phone'),('secondary_phone','Secondary phone')]:
        if fields[field] and not normalize_kenyan_phone(fields[field]): warnings.append(f'{label} is invalid in this Portal record. Review it before submitting.')
    if not re.fullmatch(r'[0-9]{1,9}', fields['customer_id'] or ''):
        warnings.append('National ID is missing or invalid in this Portal record. Complete it before submitting.')
    # Reuse the intake format without inventing missing historical identifiers.
    if fields['customer_id'] and re.fullmatch(r'[0-9]{1,9}', fields['customer_id']):
        fields['customer_id'] = numeric_customer_id(fields['customer_id'])
    for message in warnings:
        field = ('branch_region' if message.startswith('Portal branch:') else 'county' if message.startswith('Portal county:')
                 else 'sub_county' if message.startswith('Portal constituency:') else 'customer_phone' if message.startswith('Primary phone')
                 else 'secondary_phone' if message.startswith('Secondary phone') else 'customer_id')
        issues[field] = message
    return {'fields': {**fields, 'portal_source_key': str(record.pk), 'portal_source_label': reference(record)},
            'warnings': warnings, 'field_issues': issues, 'source_label': reference(record), 'location_options': options}


def lookup(group, actor, body):
    from .complaint_cases import actor_can, ComplaintCaseError
    if not actor_can(group, actor, 'complaint.case.create'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Complaints creation authority is required to look up customer biodata.')
    keys = {'customer_id', 'customer_phone', 'client_name', 'source_key'}
    if not isinstance(body, dict) or set(body)-keys or any(not isinstance(v,str) or len(v)>255 for v in body.values()):
        raise ComplaintCaseError('Use a name, National ID or primary phone to find a customer.')
    if body.get('source_key'): return {'selection': prefill(source(body['source_key']), actor)}
    identifier = str(body.get('customer_id','')).strip()
    digits = re.sub(r'\D','',body.get('customer_phone',''))
    tokens = body.get('client_name','').split()[:8]
    rows = JawabuFarmerMaster.objects.select_related('customer')
    queries = []
    if len(identifier)>=3 and identifier.isascii() and identifier.isdigit():
        queries += [('National ID', Q(national_id=identifier)|Q(national_id='',customer__national_id=identifier)),
                    ('ID starts with', Q(national_id__startswith=identifier)|Q(national_id='',customer__national_id__startswith=identifier))]
    if len(digits)>=4:
        prefix = '254'+digits[1:] if digits.startswith('0') else '254'+digits if digits.startswith(('7','1')) else digits
        variants = {prefix}
        if prefix.startswith('254'): variants.update({'0'+prefix[3:],prefix[3:]})
        exact = normalize_kenyan_phone(digits)
        if exact:
            equivalent = {exact, '0'+exact[3:], exact[3:]}
            queries.append(('Primary phone', Q(primary_phone__in=equivalent)|Q(customer__primary_phone__in=equivalent)|Q(customer__phone_history__phone=exact)))
        starts = Q()
        for value in variants: starts |= Q(primary_phone__startswith=value)|Q(primary_phone='',customer__primary_phone__startswith=value)
        queries.append(('Phone starts with', starts))
    if len(' '.join(tokens))>=3:
        queries.append(('Name',Q(customer_name__iexact=' '.join(tokens))|Q(imab_customer_name__iexact=' '.join(tokens))))
        words=Q()
        for token in tokens: words &= Q(customer_name__icontains=token)|Q(imab_customer_name__icontains=token)
        queries.append(('Name contains', words))
    matches=[]; seen=set()
    for reason, query in queries:
        for record in rows.filter(query).distinct().order_by('-updated_at','case_reference_number')[:10]:
            if record.pk in seen: continue
            seen.add(record.pk)
            conflicts=[]
            if identifier and national_id(record) and not national_id(record).startswith(identifier): conflicts.append('Different entered ID')
            if normalize_kenyan_phone(digits) and phone(record) and normalize_kenyan_phone(digits)!=phone(record): conflicts.append('Different primary phone')
            matches.append({'key':str(record.pk), 'reference':reference(record), 'name':name(record), 'national_id':national_id(record),
                'primary_phone':phone(record), 'branch':record.branch, 'location':', '.join(filter(None,[record.county,record.sub_county,record.village])),
                'matched_on':reason, 'conflicts':conflicts, 'historical':record.source=='portal_legacy'})
            if len(matches)==10: return {'matches':matches}
    return {'matches':matches}
