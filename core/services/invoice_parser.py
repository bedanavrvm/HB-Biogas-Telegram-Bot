import re
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pypdf import PdfReader
from django.db import transaction

from core.models import JawabuFarmerMaster
from core.services.jawabu_pipeline import sync_farmer_to_master_sheet

logger = logging.getLogger(__name__)


class InvoiceSheetSyncError(RuntimeError):
    pass


AMOUNT_RE = re.compile(r"^(?:KES\s*)?-?\d[\d,]*(?:\.\d{2})$")
PHONE_RE = re.compile(r"(?:\+254|0)\d{8,9}")

def clean_amount(val: str) -> Decimal | None:
    if not val:
        return None
    try:
        cleaned = re.sub(r'[^\d.-]', '', val.replace("KES", ""))
        if not cleaned:
            return None
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None

def parse_invoice_date(date_str: str) -> date | None:
    if not date_str:
        return None
    cleaned = date_str.strip().replace('/', '-').replace(' ', '-')
    for fmt in ('%d-%b-%Y', '%d-%B-%Y', '%d-%m-%Y', '%Y-%m-%d', '%m-%d-%Y'):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return None

def _non_empty_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]

def _index(lines, label):
    try:
        return lines.index(label)
    except ValueError:
        return -1

def _index_after(lines, label, start_index):
    if start_index < 0:
        return _index(lines, label)
    try:
        return lines.index(label, start_index + 1)
    except ValueError:
        return -1

def _line_after(lines, index, offset):
    target = index + offset
    if index < 0 or target >= len(lines):
        return ""
    return lines[target]

def _first_match(lines, pattern):
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(0)
    return ""

def _customer_id(bill_to_lines):
    for line in bill_to_lines[1:]:
        if re.fullmatch(r"\d{7,8}", line):
            return line
    return ""

def _amount_lines(lines, start, end=None):
    if start < 0:
        return []
    end = len(lines) if end is None or end < 0 else end
    return [line for line in lines[start:end] if AMOUNT_RE.match(line)]

def _line_amounts(lines, amount_index, subtotal_index, payment_index, balance_index):
    end_candidates = [index for index in [subtotal_index, payment_index, balance_index] if index > amount_index]
    end = min(end_candidates) if end_candidates else None
    values = _amount_lines(lines, amount_index + 1, end)
    rate = values[0] if len(values) >= 1 else ""
    line_amount = values[1] if len(values) >= 2 else rate
    return rate, line_amount

def _value_after_label(lines, label):
    """Return the first amount on the line immediately following *label*."""
    idx = _index(lines, label)
    if idx < 0:
        return ""
    # Look up to 3 lines ahead for the first amount value
    for offset in range(1, 4):
        target = idx + offset
        if target >= len(lines):
            break
        if AMOUNT_RE.match(lines[target]):
            return lines[target]
        # Stop early if we hit another known label
        if lines[target].isupper() and len(lines[target]) > 2:
            break
    return ""

def _summary_amounts(lines, payment_index, balance_index):
    """
    Extract subtotal, discount, total, and payment from invoice lines.
    Supports two layout styles:
      1. All 4 amounts packed consecutively between PAYMENT and BALANCE DUE.
      2. Each amount on the line after its own label keyword.
    """
    if payment_index < 0 or balance_index < 0 or payment_index >= balance_index:
        return "", "", "", ""
    values = _amount_lines(lines, payment_index + 1, balance_index)
    if len(values) >= 4:
        # Packed layout: subtotal, discount, total, payment
        return values[0], values[1], values[2], values[3]
    if len(values) == 1:
        # Only payment is between the two headings — read total/discount by label
        total = _value_after_label(lines, "TOTAL")
        discount = _value_after_label(lines, "DISCOUNT")
        subtotal = _value_after_label(lines, "SUBTOTAL")
        payment = values[0]
        return subtotal, discount, total, payment
    return "", "", "", ""


def _payment_near_balance(lines, payment_index, balance_index):
    if payment_index >= 0 and payment_index < balance_index:
        values = _amount_lines(lines, balance_index + 1, balance_index + 4)
        if len(values) >= 2 and not values[0].upper().startswith("KES"):
            return values[0]
    values = _amount_lines(lines, max(0, balance_index - 2), balance_index)
    return values[-1] if values else ""

def _balance_due(lines, balance_index):
    values = _amount_lines(lines, balance_index + 1, balance_index + 4)
    return values[-1] if values else ""

def _bill_to_end_index(lines, bill_to_index, description_index, serial_index, due_date_index):
    candidates = [
        _index_after(lines, "INVOICE", bill_to_index),
        description_index,
        serial_index,
        _index_after(lines, "DATE", bill_to_index),
        due_date_index,
    ]
    candidates = [index for index in candidates if index > bill_to_index]
    return min(candidates) if candidates else description_index

def _index_startswith(lines, prefix):
    """Find the index of the first line that starts with *prefix* (case-insensitive)."""
    up = prefix.upper()
    for i, l in enumerate(lines):
        if l.upper().startswith(up):
            return i
    return -1


def _extract_inline(lines, prefix):
    """
    Find the first line starting with *prefix* and return the value
    portion after the prefix.  E.g. 'INVOICE 9505' → '9505'.
    Handles both 'LABEL value' (same line) and 'LABEL' followed by
    value-on-next-line formats.
    """
    idx = _index_startswith(lines, prefix)
    if idx < 0:
        return ''
    line = lines[idx]
    remainder = line[len(prefix):].strip().lstrip(':').strip()
    if remainder:
        return remainder
    # Value is on the next line
    if idx + 1 < len(lines):
        return lines[idx + 1]
    return ''


def _extract_amount_inline(lines, prefix):
    """
    Extract a numeric amount from a line that has the label and value
    on the same line, e.g. 'SUBTOTAL 54,000.00' -> '54,000.00'.
    Handles labels at the start or embedded in the line, plus optional KES.
    """
    val = _extract_inline(lines, prefix)
    val = re.sub(r'^KES\s*', '', val.strip(), flags=re.IGNORECASE).strip()
    if re.match(r'^-?\d[\d,]*(\.\d{2})?$', val):
        return val

    label = re.escape(prefix.strip())
    pattern = re.compile(
        rf'\b{label}\b\s*(?:KES\s*)?(-?\d[\d,]*(?:\.\d{{2}})?)',
        flags=re.IGNORECASE,
    )
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return ''


def _invoice_segments_from_text(text: str):
    """
    Split the full PDF text into per-invoice segments.
    Each invoice starts with 'Page 1 of 1' in the real format.
    """
    parts = re.split(r'Page\s+1\s+of\s+1', text, flags=re.IGNORECASE)
    return [p for p in parts if 'BILL TO' in p.upper() and 'BALANCE DUE' in p.upper()]


def parse_invoice_text(text: str, page_number: int) -> dict | None:
    """
    Parse a single invoice page text.

    Supports two layout styles:
      1. **Inline** (real PDF): label and value on the same line
         e.g. 'INVOICE 9505', 'DATE 16/03/2026', 'SUBTOTAL 54,000.00'
      2. **Stacked** (mock/test format): label on one line, value on the next
         e.g. 'DUE DATE\\nINV-2026-999\\n15-Jun-2026'
    """
    upper_text = text.upper()
    if 'HOMEBIOGAS VENTURES LIMITED' not in upper_text or 'BILL TO' not in upper_text:
        return None

    lines = _non_empty_lines(text)

    # ── Customer block ────────────────────────────────────────────────────────
    bill_to_index = _index(lines, 'BILL TO')
    if bill_to_index < 0:
        return None

    # End of customer block: first line that starts with INVOICE, DATE, TERMS,
    # DUE DATE, DESCRIPTION, or SERIAL NUMBER (whichever comes first after BILL TO)
    STOP_PREFIXES = ('INVOICE ', 'DATE ', 'TERMS', 'DUE DATE', 'DESCRIPTION', 'SERIAL NUMBER')
    bill_to_end = len(lines)
    for i in range(bill_to_index + 1, len(lines)):
        if any(lines[i].upper().startswith(p) for p in STOP_PREFIXES):
            bill_to_end = i
            break
    bill_to_lines = lines[bill_to_index + 1: bill_to_end]

    customer_name = bill_to_lines[0].strip() if bill_to_lines else ''
    customer_phone = _first_match(bill_to_lines, PHONE_RE)
    customer_id = _customer_id(bill_to_lines)

    # ── Invoice metadata ──────────────────────────────────────────────────────
    # Real format:  'INVOICE 9505'  and  'DATE 16/03/2026'
    # Stacked fmt:  standalone 'DUE DATE', then 'INV-2026-999', then '15-Jun-2026'
    invoice_no = _extract_inline(lines, 'INVOICE ')   # 'INVOICE 9505' → '9505'
    invoice_date_raw = _extract_inline(lines, 'DATE ') # 'DATE 16/03/2026' → '16/03/2026'

    if not invoice_no or not invoice_date_raw:
        # Stacked layout fallback
        due_date_index = _index(lines, 'DUE DATE')
        if due_date_index >= 0:
            invoice_no = invoice_no or _line_after(lines, due_date_index, 1)
            invoice_date_raw = invoice_date_raw or _line_after(lines, due_date_index, 2)

    # ── Monetary fields ───────────────────────────────────────────────────────
    # Real format:  'SUBTOTAL 54,000.00'  /  'DISCOUNT -3,000.00'  etc. (inline)
    # Stacked fmt:  standalone 'SUBTOTAL', value on next line

    subtotal  = _extract_amount_inline(lines, 'SUBTOTAL')
    discount  = _extract_amount_inline(lines, 'DISCOUNT')
    total     = _extract_amount_inline(lines, 'TOTAL')
    payment   = _extract_amount_inline(lines, 'PAYMENT')
    balance_due = _extract_amount_inline(lines, 'BALANCE DUE')

    amount_index = _index(lines, 'AMOUNT')
    subtotal_index = _index_startswith(lines, 'SUBTOTAL')
    payment_index = _index_startswith(lines, 'PAYMENT')
    balance_index = _index_startswith(lines, 'BALANCE DUE')
    _, line_amount = _line_amounts(lines, amount_index, subtotal_index, payment_index, balance_index)

    if not balance_due:
        # Stacked fallback
        balance_due_raw = _balance_due(lines, balance_index)
        balance_due = balance_due_raw

    invoice_amount = subtotal or line_amount or total

    # Validate: we need at least a customer name and an invoice number
    if not customer_name or not invoice_no:
        return None

    balance_verification = verify_balance_due(
        invoice_amount=invoice_amount,
        discount=discount,
        total_after_discount=total,
        payment=payment,
        balance_due=balance_due,
    )

    return {
        'page': page_number,
        'invoice_no': invoice_no,
        'invoice_date': invoice_date_raw,
        'customer_name': customer_name,
        'customer_phone': customer_phone,
        'customer_id': customer_id,
        'invoice_amount': invoice_amount,
        'total_after_discount': total,
        'discount': discount,
        'payment': payment,
        'balance_due': balance_due,
        **balance_verification,
    }



def verify_balance_due(invoice_amount: str, discount: str, total_after_discount: str, payment: str, balance_due: str) -> dict:
    """Compare printed BALANCE DUE with calculated balance without replacing it."""
    printed = clean_amount(balance_due)
    total = clean_amount(total_after_discount)
    paid = clean_amount(payment)
    gross = clean_amount(invoice_amount)
    disc = clean_amount(discount)

    calculated = None
    basis = ''
    if total is not None and paid is not None:
        calculated = total - paid
        basis = 'total_after_discount_minus_payment'
    elif gross is not None and disc is not None and paid is not None:
        adjusted_total = gross + disc if disc < 0 else gross - disc
        calculated = adjusted_total - paid
        basis = 'gross_minus_discount_minus_payment'

    if printed is None:
        return {
            'balance_due_check': 'Missing printed balance due',
            'calculated_balance_due': str(calculated) if calculated is not None else '',
            'balance_due_difference': '',
            'balance_due_check_basis': basis,
        }
    if calculated is None:
        return {
            'balance_due_check': 'Cannot verify',
            'calculated_balance_due': '',
            'balance_due_difference': '',
            'balance_due_check_basis': '',
        }

    difference = printed - calculated
    return {
        'balance_due_check': 'OK' if difference == 0 else 'Mismatch',
        'calculated_balance_due': str(calculated),
        'balance_due_difference': str(difference),
        'balance_due_check_basis': basis,
    }

def clean_phone(phone: str) -> str:
    cleaned = re.sub(r'\D', '', str(phone or ''))
    if cleaned.startswith('254'):
        return cleaned[3:]
    if cleaned.startswith('0'):
        return cleaned[1:]
    return cleaned


def _resolve_unique_match(matches, label: str):
    if len(matches) == 1:
        return matches[0], ''
    if len(matches) > 1:
        return None, f"Multiple farmers matched by {label}. Review manually."
    return None, ''


def _match_invoice_to_farmer(inv: dict, farmers: list[JawabuFarmerMaster]):
    inv_id = str(inv.get("customer_id") or '').strip()
    inv_name = str(inv.get("customer_name") or '').strip().upper()
    inv_phone = clean_phone(inv.get("customer_phone") or '')

    if inv_id:
        id_matches = [f for f in farmers if str(f.national_id).strip() == inv_id]
        if len(id_matches) > 1 and inv_phone:
            phone_filtered = [f for f in id_matches if clean_phone(f.primary_phone) == inv_phone]
            if len(phone_filtered) == 1:
                return phone_filtered[0], ''
        matched, reason = _resolve_unique_match(id_matches, 'National ID')
        if matched or reason:
            return matched, reason

    if inv_phone:
        phone_matches = [f for f in farmers if clean_phone(f.primary_phone) == inv_phone]
        matched, reason = _resolve_unique_match(phone_matches, 'Primary Phone')
        if matched or reason:
            return matched, reason

    if inv_name:
        name_matches = [f for f in farmers if str(f.customer_name).strip().upper() == inv_name]
        matched, reason = _resolve_unique_match(name_matches, 'Customer Name')
        if matched or reason:
            return matched, reason

    return None, ''


def match_and_update_invoices(order_number: str, pdf_bytes: bytes) -> dict:
    reader = PdfReader(BytesIO(pdf_bytes))
    invoices = []
    
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        parsed = parse_invoice_text(text, i)
        if parsed:
            invoices.append(parsed)

    if not invoices:
        return {"ok": False, "error": "No valid HomeBiogas invoices found in the PDF."}

    # Fetch active farmers in the batch
    farmers = list(JawabuFarmerMaster.objects.filter(
        order_number=order_number,
        status='active'
    ))

    results = []
    matched_count = 0

    for inv in invoices:
        matched_farmer, match_error = _match_invoice_to_farmer(inv, farmers)

        if matched_farmer:
            try:
                with transaction.atomic():
                    matched_farmer.invoice_number = inv["invoice_no"]
                    matched_farmer.invoice_date = parse_invoice_date(inv["invoice_date"])
                    matched_farmer.invoice_amount = clean_amount(inv["invoice_amount"])
                    matched_farmer.discount = clean_amount(inv["discount"])
                    matched_farmer.payment = clean_amount(inv["payment"])
                    matched_farmer.balance_due = clean_amount(inv["balance_due"])
                    matched_farmer.save()

                    if not sync_farmer_to_master_sheet(matched_farmer):
                        raise InvoiceSheetSyncError(
                            "Google Sheet sync failed for "
                            f"{matched_farmer.customer_name or 'matched farmer'} "
                            f"({matched_farmer.national_id or matched_farmer.primary_phone or matched_farmer.id}). "
                            "The invoice was not committed to the database."
                        )
            except InvoiceSheetSyncError as exc:
                logger.error("Invoice upload failed during sheet sync: %s", exc)
                results.append({
                    "customer_name": matched_farmer.customer_name,
                    "status": "Sync failed",
                    "invoice_no": inv["invoice_no"],
                    "reason": str(exc),
                })
                return {
                    "ok": False,
                    "error": str(exc),
                    "total_parsed": len(invoices),
                    "matched_count": matched_count,
                    "results": results,
                }

            results.append({
                "customer_name": matched_farmer.customer_name,
                "status": "Matched",
                "invoice_no": inv["invoice_no"]
            })
            matched_count += 1
        else:
            results.append({
                "customer_name": inv["customer_name"],
                "status": "Ambiguous" if match_error else "Unmatched",
                "invoice_no": inv["invoice_no"],
                "reason": match_error,
            })

    return {
        "ok": True,
        "total_parsed": len(invoices),
        "matched_count": matched_count,
        "results": results
    }
