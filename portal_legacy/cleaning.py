"""Value-only historical workbook cleaning; never workflow authority.

The original cells belong in the retained upload. Unknown values are reported,
not guessed from totals, the current year, or another customer's identity.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

from core.services.identifiers import normalize_kenyan_phone, validate_kenyan_national_id
from core.services.jawabu_validation import parse_business_date
from .workbook import DATES, MONEY, literal, token

PROFILE = 'reviewed-v5-amendments-1'
STATUS_ALIASES = {
    'installation_status': {'open': 'Open', 'notinstalled': 'Open', 'pendinginstallation': 'Open',
                            'installed': 'Installed', 'closed': 'Closed'},
    'commissioning_status': {'done': 'Commissioned', 'commissioned': 'Commissioned',
                             'pending': 'Not commissioned', 'notcommissioned': 'Not commissioned',
                             'unknown': '', 'notrecordedlegacy': ''},
    'readiness_status': {'ready': 'Ready', 'notready': 'Not ready', 'notconfirmed': 'Not confirmed'},
    'installation_report_status': {'yes': 'Yes', 'no': 'No', 'notapplicable': 'Not applicable'},
}
REFERENCE = re.compile(r'(?:(HB|ECO)[\s-]*|ORDER(?:\s*(?:NO\.?|NUMBER))?\s*[-:#]?\s*|#)?(\d+)', re.I)
MONTHS = {name: number for number, names in enumerate((
    ('jan', 'january'), ('feb', 'february'), ('mar', 'march'), ('apr', 'april'), ('may',),
    ('jun', 'june'), ('jul', 'july'), ('aug', 'august'), ('sep', 'sept', 'september'),
    ('oct', 'october'), ('nov', 'november'), ('dec', 'december')), 1) for name in names}


def status_value(key, value):
    return STATUS_ALIASES.get(key, {}).get(token(value), literal(value))


def reference_value(key, value, source_sheet=''):
    text = literal(value).strip()
    if not text or text == '-':
        return ''
    matched = REFERENCE.fullmatch(text)
    if not matched or int(matched[2]) < 1:
        raise ValueError('Confirm the historical reference format.')
    prefix = (matched[1] or '').upper()
    if key == 'payment_number':
        if prefix:
            raise ValueError('Payment references cannot use an order partner prefix.')
        return str(int(matched[2]))
    partner = 'ECO' if source_sheet == 'Eco-conserve' else 'HB' if source_sheet == 'Master Data' else ''
    if partner and prefix and prefix != partner:
        raise ValueError('The order prefix belongs to the other register.')
    return f'{prefix or partner}-{int(matched[2])}' if prefix or partner else str(int(matched[2]))


def money_value(value):
    text = literal(value).strip()
    if not text or text == '-':
        return '0'
    if re.search(r'\bnot\s+on\s+sf\b', text, re.I):
        return 'Not on SF'
    text = re.sub(r'^(?:KES|KSHS?)\.?\s*', '', text, flags=re.I)
    text = re.sub(r'\s*/[-=]$', '', text).strip()
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', text):
        raise ValueError('Confirm the amount; dates, prose and calculated differences are not receipts.')
    try:
        amount = Decimal(text.replace(',', ''))
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation()
    except InvalidOperation as exc:
        raise ValueError('Confirm the historical amount.') from exc
    return format(amount, 'f')


def outcome_value(value):
    text = ' '.join(literal(value).split())
    upper = text.upper()
    if not upper or upper == '-':
        return ''
    if upper.startswith('APPROVED') and not re.search(r'CANCEL|WITHDR|REJECT|DEFER|\b(?:HOLD|NOT|NEVER)\b', upper):
        return 'Approved'
    if re.fullmatch(r'(?:OPTED\s+(?:FOR\s+)?|PAID\s+)?CASH(?:\s+TO\s+HB)?\.?', upper):
        return 'Opted for Cash'
    if upper in {'OPTED FOR OTHER PARTNER', 'OPTED FOR OTHER'}:
        return 'Opted for Other Partner'
    categories = set()
    for result, pattern in (
        ('Rejected', r'\b(?:REJECTED|REJACTED|REUJECTED)\b'),
        ('Deferred / On Hold', r'\b(?:DEFERRED|DEFERED|DEFFERED|DIFFERED|DIFFERRED|DEFFFERED|RESCHEDULED)\b'),
        ('Withdrawn', r'\b(?:WITHDREW|WITHDRAWN)\b'), ('Cancelled', r'\bCANCELLED\b')):
        if re.search(pattern, upper):
            categories.add(result)
    if len(categories) == 1 and not re.search(r'\b(?:APPROVED|NOT|NEVER|PENDING)\b', upper):
        return next(iter(categories))
    return text


def merge_source_notes(current, incoming='', november=''):
    """Retain earlier history and append new source wording once, without fake actors."""
    result = literal(current)
    for label, text in (('Updated source comments', incoming), ('November source note', november)):
        text = literal(text)
        normalize = lambda value: ' '.join(value.split()).casefold()
        entries = {normalize(result)} | {normalize(part) for part in result.split('\n\n')}
        entries |= {normalize(part.split(':\n', 1)[-1]) for part in result.split('\n\n')}
        if text and normalize(text) not in entries:
            result = (result + '\n\n' if result else '') + label + ':\n' + text
    return result


@dataclass
class CleanedReview:
    values: dict
    issues: dict = field(default_factory=dict)
    retained: set = field(default_factory=set)
    raw_blanks: set = field(default_factory=set)
    pending_reason: str = ''


def clean_review_values(values, *, source_sheet, baseline=None, originals=None, county_aliases=None):
    """Clean against reviewed context; preserve unresolved existing values.

    County aliases must come from the retained reviewed reference. A proposed
    geographic change without that evidence stays in the exception report.
    """
    baseline, originals, county_aliases = baseline or {}, originals or {}, county_aliases or {}
    result = CleanedReview(dict(values))
    def retain(key, reason):
        result.issues[key] = reason
        result.retained.add(key)
        result.values[key] = baseline.get(key, '')
    for key, raw in values.items():
        text = literal(raw)
        if key in originals and text == literal(originals[key]) and key in baseline:
            result.values[key] = baseline[key]
            result.retained.add(key)
            continue
        if text in ('', '-'):
            result.raw_blanks.add(key)
            if key in baseline:
                result.values[key] = baseline[key]
                result.retained.add(key)
            elif key in MONEY:
                result.values[key] = '0'
            else:
                result.values[key] = ''
            continue
        if text.startswith('#') and text in {'#REF!', '#VALUE!', '#N/A', '#DIV/0!', '#NAME?', '#NUM!', '#NULL!'}:
            retain(key, 'The workbook contains an Excel formula error; retain the reviewed value.')
        elif key == 'national_id':
            result.values[key] = validate_kenyan_national_id(text)
            if not result.values[key]:
                result.issues[key] = 'Pending: missing or invalid National ID.'
        elif key in {'primary_phone', 'secondary_phone'}:
            normalized = normalize_kenyan_phone(text)
            if normalized:
                result.values[key] = normalized
            else:
                retain(key, 'Historical contact requires confirmation.')
        elif key in MONEY:
            try:
                result.values[key] = money_value(text)
                if result.values[key] == 'Not on SF' and key != 'deposit_paid_hbg':
                    raise ValueError('Not on SF is only an HB-deposit exception.')
            except ValueError as exc:
                retain(key, str(exc))
        elif key in {'order_number', 'payment_number'}:
            try:
                result.values[key] = reference_value(key, text, source_sheet)
            except ValueError as exc:
                retain(key, str(exc))
        elif key in DATES:
            parsed = parse_business_date(text)
            if parsed:
                result.values[key] = parsed.isoformat()
            else:
                # An unchanged partial old date cannot choose a new year.
                old = parse_business_date(baseline.get(key))
                parts = re.fullmatch(r'(\d{1,2})[\s/.-]+([A-Za-z]+)', text)
                if old and parts and int(parts[1]) == old.day and MONTHS.get(parts[2].casefold()) == old.month:
                    result.values[key] = old.isoformat()
                    result.retained.add(key)
                else:
                    retain(key, 'A complete historical date is not established; no year was inferred.')
        elif key in STATUS_ALIASES:
            if token(text) not in STATUS_ALIASES[key]:
                retain(key, 'Confirm this historical status before applying it.')
            else:
                result.values[key] = status_value(key, text)
        elif key == 'hb_sales_person':
            # Separator spacing does not change the historical staff label.
            reviewed = literal(baseline.get(key))
            unannotated = re.sub(r'\[[^\]]+\]', '', text)
            words = set(re.findall(r'[A-Z0-9]+', unannotated.upper()))
            reviewed_words = set(re.findall(r'[A-Z0-9]+', reviewed.upper()))
            if reviewed and words and words < reviewed_words:
                retain(key, 'Updated source shortens the reviewed staff label; retain the complete reviewed label.')
            else:
                result.values[key] = reviewed if token(text) == token(reviewed) or (reviewed and token(unannotated) == token(reviewed)) else ' '.join(text.split()).upper()
        elif key == 'customer_name':
            result.values[key] = ' '.join(text.split()).upper()
        elif key == 'county':
            normalized = ' '.join(text.split()).upper()
            reviewed = ' '.join(literal(baseline.get(key)).split()).upper()
            mapped = county_aliases.get(token(normalized))
            if normalized == reviewed or mapped:
                result.values[key] = mapped or reviewed
            else:
                retain(key, 'County differs from the reviewed value without a confirmed reference mapping.')
        elif key == 'village' and token(text) == token(baseline.get('legacy:Location detail')):
            result.values[key] = baseline.get('village', '')
            result.retained.add(key)
        elif key == 'legacy_outcome':
            result.values[key] = outcome_value(text)
    if not validate_kenyan_national_id(result.values.get('national_id')):
        result.pending_reason = 'Pending: missing or invalid National ID.'
    elif not literal(result.values.get('customer_name')):
        result.pending_reason = 'Pending: customer name is not established.'
    if {'deposit_paid_hbg', 'legacy_deposit_paid_jbl'} <= values.keys():
        if result.values.get('deposit_paid_hbg') == 'Not on SF':
            result.values['legacy:Total'] = ''
        elif not {'deposit_paid_hbg', 'legacy_deposit_paid_jbl'} & result.issues.keys():
            try:
                total = Decimal(money_value(result.values.get('deposit_paid_hbg'))) + Decimal(money_value(result.values.get('legacy_deposit_paid_jbl')))
                result.values['legacy:Total'] = format(total, 'f')
            except (ValueError, InvalidOperation):
                retain('legacy:Total', 'Unresolved receipt amount; no total or balancing receipt inferred.')
    if 'case_comment_history' in values or any(token(key) == 'legacynovcommments' for key in values):
        november = next((literal(value) for key, value in result.values.items() if token(key) == 'legacynovcommments'), '')
        result.values['case_comment_history'] = merge_source_notes(
            baseline.get('case_comment_history', ''), result.values.get('case_comment_history', ''), november)
    return result
