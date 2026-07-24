"""Payment document generation using the HB payment workbook template."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
from django.db import transaction
from django.utils import timezone
from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter

from core.models import JawabuFarmerMaster, ParsedInvoice, PaymentDocument, PaymentDocumentTemplate
from core.services.invoice_parser import clean_amount
from core.services.requisition import copy_row_formatting
from core.services.template_storage import TemplateStorageError, workbook_source_from_template


PAYMENT_TEMPLATE_FILENAME = 'HB_PAYMENT__89__7__machine_ready (1).xlsx'
PAYMENT_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class PaymentTemplateError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaymentTemplateLayout:
    sheet_name: str
    header_row: int
    data_start_row: int
    totals_row: int
    signature_block_start_row: int
    columns: dict[str, int]
    sum_columns: tuple[int, ...]
    config_warnings: tuple[str, ...] = ()


def _template_source():
    active_template = PaymentDocumentTemplate.objects.filter(is_active=True).first()
    fallback_path = Path('requisition') / PAYMENT_TEMPLATE_FILENAME
    try:
        return workbook_source_from_template(active_template, fallback_path=fallback_path)
    except TemplateStorageError as exc:
        raise PaymentTemplateError(
            'No payment document template is available. Upload one in '
            'Django Admin > Payment document templates and confirm it was stored in Google Drive.'
        ) from exc


def _read_config_sheet(wb) -> dict[str, str]:
    if '_TEMPLATE_CONFIG' not in wb.sheetnames:
        return {}
    ws = wb['_TEMPLATE_CONFIG']
    config = {}
    for row in range(2, ws.max_row + 1):
        key = str(ws.cell(row=row, column=1).value or '').strip()
        value = ws.cell(row=row, column=2).value
        if key:
            config[key] = '' if value is None else str(value).strip()
    return config


def _words(value: Any) -> set[str]:
    return set(re.findall(r'\b\w+\b', str(value or '').upper()))


def _detect_header_row(ws) -> int:
    for row in range(1, min(ws.max_row, 50) + 1):
        row_words = set()
        for col in range(1, ws.max_column + 1):
            row_words |= _words(ws.cell(row=row, column=col).value)
        if {'CUST', 'NO', 'NAME', 'BRANCH'} <= row_words and ('INVOICE' in row_words or 'AMOUNT' in row_words):
            return row
    raise PaymentTemplateError('Could not detect payment workbook header row.')


def _column_mapping_from_headers(ws, header_row: int) -> dict[str, int]:
    mapping = {}
    for col in range(1, ws.max_column + 1):
        header_text = str(ws.cell(row=header_row, column=col).value or '')
        text = ' '.join(
            str(ws.cell(row=row, column=col).value or '')
            for row in (header_row, header_row + 1)
        )
        words = _words(text)
        header_words = _words(header_text)
        header_upper = header_text.upper().strip()
        if 'REQUISITION' in words and 'DATE' in words:
            mapping['requisition_date'] = col
        elif 'ORDER' in words:
            mapping['order_no'] = col
        elif 'CUST' in words and 'NO' in words:
            mapping['cust_no'] = col
        elif header_upper in {'NO:', 'NO', 'NO.'} or header_words == {'NO'}:
            mapping['no'] = col
        elif 'NAME' in words and 'IMAB' in words:
            mapping['name_imab'] = col
        elif words == {'NAME'} or ('NAME' in words and 'IMAB' not in words):
            mapping.setdefault('name', col)
        elif 'PRIMARY' in words and 'MOBILE' in words:
            mapping['mobile_no'] = col
        elif 'SECONDARY' in words and 'MOBILE' in words:
            mapping['secondary_mobile'] = col
        elif 'BRANCH' in words:
            mapping['branch'] = col
        elif 'LOAN' in words and 'OFFICER' in words:
            mapping['loan_officer'] = col
        elif 'HB' in words and 'INVOICE' in words and 'AMOUNT' in words:
            mapping['hb_invoice_amount'] = col
        elif 'EXPECTED' in words and 'INVOICE' in words:
            mapping['expected_invoice_amount'] = col
        elif 'DISCOUNT' in words:
            mapping['discount'] = col
        elif 'DEPOSIT' in words and 'HBG' in words:
            mapping['deposit_paid_hbg'] = col
        elif 'DEPOSIT' in words and 'JBL' in words:
            mapping['deposit_paid_jbl'] = col
        elif 'LOAN' in words and 'AMOUNT' in words:
            mapping['loan_amount'] = col
        elif 'REPAYMENT' in words:
            mapping['repayment_dates'] = col
        elif 'TENOR' in words:
            mapping['tenor'] = col
        elif 'PRODUCT' in words:
            mapping['product'] = col
        elif 'CALL' in words and 'COMMENTS' in words:
            mapping['call_up_comments'] = col
    required = {
        'requisition_date', 'order_no', 'cust_no', 'no', 'name_imab', 'name',
        'mobile_no', 'branch', 'hb_invoice_amount', 'discount',
        'deposit_paid_hbg', 'deposit_paid_jbl', 'loan_amount',
    }
    missing = sorted(required - set(mapping))
    if missing:
        raise PaymentTemplateError(f"Payment workbook is missing required columns: {', '.join(missing)}")
    return mapping


def _first_numeric_row(ws, start_row: int, serial_col: int) -> int:
    for row in range(start_row, min(ws.max_row, 80) + 1):
        value = ws.cell(row=row, column=serial_col).value
        if value is None:
            continue
        try:
            int(str(value).strip())
            return row
        except ValueError:
            continue
    raise PaymentTemplateError('Could not detect payment workbook first data row.')


def _detect_totals_row(ws, start_row: int, sum_columns: tuple[int, ...]) -> int:
    candidate_columns = sum_columns or tuple(range(1, ws.max_column + 1))
    for row in range(start_row, min(ws.max_row, 160) + 1):
        formula_count = 0
        for col in candidate_columns:
            value = ws.cell(row=row, column=col).value
            if isinstance(value, str) and value.strip().upper().startswith('=SUM('):
                formula_count += 1
        if formula_count >= 2:
            return row
    raise PaymentTemplateError('Could not detect payment workbook totals row.')


def _last_numeric_row(ws, start_row: int, serial_col: int) -> int:
    last = start_row
    for row in range(start_row, min(ws.max_row, 120) + 1):
        value = ws.cell(row=row, column=serial_col).value
        try:
            int(str(value).strip())
            last = row
        except (TypeError, ValueError):
            if row > start_row:
                break
    return last


def _sum_columns_from_config(config: dict[str, str], columns: dict[str, int]) -> tuple[int, ...]:
    value = config.get('sum_cols') or ''
    result = []
    for item in value.split(','):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(column_index_from_string(item))
        except ValueError:
            pass
    if result:
        return tuple(result)
    return tuple(
        columns[key]
        for key in (
            'hb_invoice_amount', 'expected_invoice_amount', 'discount',
            'deposit_paid_hbg', 'deposit_paid_jbl', 'loan_amount',
        )
        if key in columns
    )


def payment_template_layout(wb) -> PaymentTemplateLayout:
    config = _read_config_sheet(wb)
    sheet_name = config.get('sheet_name') or wb.sheetnames[0]
    if sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]
    header_row = _detect_header_row(ws)
    columns = _column_mapping_from_headers(ws, header_row)
    sum_columns = _sum_columns_from_config(config, columns)
    try:
        data_start_row = _first_numeric_row(ws, header_row + 1, columns['no'])
        last_data_row = _last_numeric_row(ws, data_start_row, columns['no'])
        totals_row = last_data_row + 1
    except PaymentTemplateError:
        totals_row = _detect_totals_row(ws, header_row + 1, sum_columns)
        data_start_row = header_row + 1
    signature_block_start_row = totals_row + 3
    warnings = []
    expected = {
        'header_row': header_row,
        'data_start_row': data_start_row,
        'totals_row': totals_row,
        'signature_block_start_row': signature_block_start_row,
    }
    for key, detected in expected.items():
        configured = config.get(key)
        if configured and str(configured) != str(detected):
            warnings.append(f'{key} config={configured} visible={detected}')
    return PaymentTemplateLayout(
        sheet_name=sheet_name,
        header_row=header_row,
        data_start_row=data_start_row,
        totals_row=totals_row,
        signature_block_start_row=signature_block_start_row,
        columns=columns,
        sum_columns=sum_columns,
        config_warnings=tuple(warnings),
    )


def _amount(value) -> Decimal | None:
    if value is None or value == '':
        return None
    if isinstance(value, Decimal):
        return value
    return clean_amount(str(value))


def _xlsx_number(value):
    amount = _amount(value)
    if amount is None:
        return ''
    if amount == amount.to_integral_value():
        return int(amount)
    return float(amount)


def _invoice_for_farmer(farmer: JawabuFarmerMaster) -> ParsedInvoice | None:
    if not farmer.invoice_number:
        return None
    return (
        ParsedInvoice.objects
        .filter(invoice_no=farmer.invoice_number)
        .filter(
            matched_farmer=farmer,
        )
        .order_by('-updated_at')
        .first()
    )


def _row_payload(farmer: JawabuFarmerMaster) -> tuple[dict[str, Any], list[str], ParsedInvoice | None]:
    invoice = _invoice_for_farmer(farmer)
    missing = []
    if not farmer.customer_no:
        missing.append('Cust No')
    if not farmer.invoice_number:
        missing.append('Matched invoice')
    if not farmer.repayment_date:
        missing.append('Repayment Dates')
    if not farmer.repayment_tenor:
        missing.append('Tenor')

    hbg_deposit = _amount(farmer.actual_receipts) if not (farmer.lead_source and 'jbl' in farmer.lead_source.lower()) else None
    jbl_deposit = farmer.system_deposit_paid_jbl
    if jbl_deposit is None and farmer.lead_source and 'jbl' in farmer.lead_source.lower():
        jbl_deposit = _amount(farmer.actual_receipts)

    row = {
        'requisition_date': farmer.requisition_date,
        'order_no': farmer.order_number,
        'cust_no': farmer.customer_no,
        'name_imab': farmer.imab_customer_name,
        'name': farmer.customer_name,
        'mobile_no': farmer.primary_phone,
        'secondary_mobile': farmer.secondary_phone,
        'branch': farmer.system_branch or farmer.branch,
        'loan_officer': farmer.system_loan_officer or farmer.jbl_officer,
        'hb_invoice_amount': farmer.invoice_amount,
        'expected_invoice_amount': None,
        'discount': farmer.discount,
        'deposit_paid_hbg': hbg_deposit,
        'deposit_paid_jbl': jbl_deposit,
        'loan_amount': None,
        'repayment_dates': farmer.repayment_date,
        'tenor': farmer.repayment_tenor,
        'product': farmer.payment_product,
        'call_up_comments': '',
    }
    return row, missing, invoice


def payment_readiness(order_number: str) -> dict[str, Any]:
    farmers = list(
        JawabuFarmerMaster.objects
        .filter(order_number=order_number, status='active')
        .order_by('customer_name')
    )
    ready = []
    blocked = []
    invoice_batch_ids = set()
    for farmer in farmers:
        row, missing, invoice = _row_payload(farmer)
        item = {
            'farmer_id': str(farmer.id),
            'customer_name': farmer.customer_name,
            'national_id': farmer.national_id,
            'primary_phone': farmer.primary_phone,
            'missing': missing,
            'row': row,
        }
        if invoice:
            invoice_batch_ids.add(str(invoice.batch_id))
            item['invoice_id'] = str(invoice.id)
            item['invoice_batch_id'] = str(invoice.batch_id)
        if missing:
            blocked.append(item)
        else:
            ready.append(item)
    return {
        'order_number': order_number,
        'total_clients': len(farmers),
        'ready_count': len(ready),
        'blocked_count': len(blocked),
        'invoice_batch_ids': sorted(invoice_batch_ids),
        'ready': ready,
        'blocked': blocked,
    }


def _set_cell(ws, row: int, col: int | None, value):
    if not col:
        return
    cell = ws.cell(row=row, column=col)
    if value is None:
        cell.value = ''
        return
    if isinstance(value, (date, datetime)):
        cell.value = value
        cell.number_format = 'dd-mmm-yyyy'
    elif isinstance(value, Decimal):
        cell.value = _xlsx_number(value)
    else:
        cell.value = value or ''


def _copy_payment_template_row(ws, src_row: int, dst_row: int) -> None:
    copy_row_formatting(ws, src_row, dst_row)
    ws.row_dimensions[dst_row].height = ws.row_dimensions[src_row].height
    for col in range(1, ws.max_column + 1):
        src_cell = ws.cell(row=src_row, column=col)
        if isinstance(src_cell.value, str) and src_cell.value.startswith('='):
            dst_cell = ws.cell(row=dst_row, column=col)
            dst_cell.value = Translator(src_cell.value, origin=src_cell.coordinate).translate_formula(dst_cell.coordinate)


def _write_payment_rows(ws, layout: PaymentTemplateLayout, rows: list[dict[str, Any]]) -> int:
    first_data_row = layout.data_start_row
    template_rows = max(1, layout.totals_row - layout.data_start_row)
    count = len(rows)
    if count > template_rows:
        insert_at = layout.totals_row
        ws.insert_rows(insert_at, count - template_rows)
        for row in range(insert_at, insert_at + (count - template_rows)):
            _copy_payment_template_row(ws, first_data_row, row)
    elif count < template_rows:
        ws.delete_rows(first_data_row + count, template_rows - count)

    for index, payload in enumerate(rows, start=1):
        row = first_data_row + index - 1
        _set_cell(ws, row, layout.columns.get('no'), index)
        for key, value in payload.items():
            if key == 'expected_invoice_amount' and value is None:
                expected_col = layout.columns.get('expected_invoice_amount')
                hb_col = layout.columns.get('hb_invoice_amount')
                discount_col = layout.columns.get('discount')
                hbg_deposit_col = layout.columns.get('deposit_paid_hbg')
                if expected_col and hb_col and discount_col and hbg_deposit_col:
                    ws.cell(row=row, column=expected_col, value=(
                        f'={get_column_letter(hb_col)}{row}-'
                        f'({get_column_letter(discount_col)}{row}+{get_column_letter(hbg_deposit_col)}{row})'
                    ))
                continue
            _set_cell(ws, row, layout.columns.get(key), value)

    totals_row = first_data_row + count
    for col in layout.sum_columns:
        letter = get_column_letter(col)
        if count:
            ws.cell(row=totals_row, column=col, value=f'=SUM({letter}{first_data_row}:{letter}{first_data_row + count - 1})')
        else:
            ws.cell(row=totals_row, column=col, value=0)
    return totals_row


def generate_payment_workbook(order_number: str) -> tuple[bytes, dict[str, Any]]:
    readiness = payment_readiness(order_number)
    if readiness['blocked_count']:
        raise PaymentTemplateError('Payment document has blocked rows. Resolve missing fields before generating.')
    from core.services.template_validation import template_source_bytes, validate_template_bytes, UnsafeTemplateError
    template_bytes = template_source_bytes(_template_source())
    try:
        validate_template_bytes(template_bytes, 'payment')
    except UnsafeTemplateError as exc:
        raise PaymentTemplateError(str(exc)) from exc
    wb = openpyxl.load_workbook(io.BytesIO(template_bytes))
    layout = payment_template_layout(wb)
    ws = wb[layout.sheet_name]
    rows = [item['row'] for item in readiness['ready']]
    totals_row = _write_payment_rows(ws, layout, rows)
    out = io.BytesIO()
    wb.save(out)
    summary = {
        **{key: value for key, value in readiness.items() if key not in {'ready', 'blocked'}},
        'template_sheet': layout.sheet_name,
        'header_row': layout.header_row,
        'data_start_row': layout.data_start_row,
        'totals_row': totals_row,
        'config_warnings': list(layout.config_warnings),
    }
    return out.getvalue(), summary


def _upload_payment_workbook(data: bytes, filename: str, actor: str, order_number: str) -> tuple[str, str]:
    from core.services.order_approval import GoogleDriveMediaStorage

    return GoogleDriveMediaStorage().upload(
        data,
        filename=filename,
        mime_type=PAYMENT_CONTENT_TYPE,
        id_number='payment_documents',
        received_at=timezone.now(),
        group_config=None,
        workflow_key='Jawabu/Payment Documents',
        record_type='Order',
        record_key=order_number,
    )


@transaction.atomic
def create_payment_document(order_number: str, actor: str = '', final: bool = False) -> PaymentDocument:
    xlsx, summary = generate_payment_workbook(order_number)
    status = 'final' if final else 'preview'
    version = 1
    if final:
        latest = PaymentDocument.objects.filter(order_number=order_number, status='final').order_by('-version').first()
        version = (latest.version + 1) if latest else 1
    filename = f"HB_Payment_{order_number}_{status}_v{version}.xlsx"
    drive_file_id, drive_url = _upload_payment_workbook(xlsx, filename, actor, order_number)
    doc = PaymentDocument.objects.create(
        order_number=order_number,
        status=status,
        version=version,
        filename=filename,
        drive_file_id=drive_file_id,
        drive_url=drive_url,
        generated_by=actor,
        finalized_by=actor if final else '',
        finalized_at=timezone.now() if final else None,
        row_count=summary.get('ready_count', 0),
        farmer_ids=[item['farmer_id'] for item in payment_readiness(order_number)['ready']],
        invoice_batch_ids=summary.get('invoice_batch_ids', []),
        validation_summary=summary,
    )
    return doc


def serialize_payment_document(doc: PaymentDocument) -> dict[str, Any]:
    return {
        'id': str(doc.id),
        'order_number': doc.order_number,
        'status': doc.status,
        'version': doc.version,
        'filename': doc.filename,
        'drive_url': doc.drive_url,
        'row_count': doc.row_count,
        'validation_summary': doc.validation_summary,
        'created_at': doc.created_at.isoformat() if doc.created_at else None,
        'finalized_at': doc.finalized_at.isoformat() if doc.finalized_at else None,
    }
