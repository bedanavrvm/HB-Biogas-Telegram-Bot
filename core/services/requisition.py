import re
import copy
import io
import os
import openpyxl
from datetime import date, datetime
from typing import Any
from openpyxl.utils import get_column_letter
from django.conf import settings
from core.models import JawabuFarmerMaster


class RequisitionTemplateError(RuntimeError):
    pass

def clean_deposit_float(val: Any) -> float | int | None:
    if not val:
        return None
    try:
        cleaned = re.sub(r'[^\d.]', '', str(val))
        if not cleaned:
            return None
        if '.' in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return None

def copy_row_formatting(ws: Any, src_row: int, dst_row: int) -> None:
    for col in range(1, ws.max_column + 1):
        src_cell = ws.cell(row=src_row, column=col)
        dst_cell = ws.cell(row=dst_row, column=col)
        dst_cell.font = copy.copy(src_cell.font)
        dst_cell.border = copy.copy(src_cell.border)
        dst_cell.fill = copy.copy(src_cell.fill)
        dst_cell.alignment = copy.copy(src_cell.alignment)
        dst_cell.number_format = src_cell.number_format

def generate_requisition_excel(farmers: list[JawabuFarmerMaster], order_number: str, requisition_date: date) -> bytes:
    import os
    from django.conf import settings
    from core.models import RequisitionTemplate

    active_template = RequisitionTemplate.objects.filter(is_active=True).first()
    if active_template and active_template.file:
        try:
            template_path = active_template.file.path
        except (NotImplementedError, ValueError):
            template_path = ''
        if not template_path or not os.path.exists(template_path):
            raise RequisitionTemplateError(
                'The active requisition template file is not available on this server. '
                'Upload the Excel template again in Django Admin > Requisition templates, '
                'or attach persistent storage for Render media files.'
            )
    else:
        template_path = os.path.join(settings.BASE_DIR, 'requisition', 'JBL_Requisition_Form_184.xlsx')
        if not os.path.exists(template_path):
            raise RequisitionTemplateError(
                'No requisition Excel template is configured. Upload the template in '
                'Django Admin > Requisition templates and mark it active.'
            )

    wb = openpyxl.load_workbook(template_path)
    ws = wb.active
    
    # 1. Search for date and order ref cell placeholders in rows 1 to 7
    date_cell = None
    order_ref_cell = None
    for r in range(1, 8):
        for c in range(1, 15):
            cell = ws.cell(row=r, column=c)
            val = str(cell.value or "").strip()
            val_clean = val.upper().replace(" ", "")
            if "DATE:" in val_clean:
                date_cell = cell
            elif "ORDERNO:" in val_clean or "BATCH/ORDERREF:" in val_clean or "ORDERREF:" in val_clean:
                order_ref_cell = cell

    date_str = requisition_date.strftime('%d-%b-%Y') if isinstance(requisition_date, (date, datetime)) else str(requisition_date)
    if date_cell:
        orig = str(date_cell.value)
        prefix = orig.split(":")[0] + ":"
        date_cell.value = f"{prefix}   {date_str}"
    else:
        ws['A4'] = f"Date:   {date_str}"

    if order_ref_cell:
        orig = str(order_ref_cell.value)
        prefix = orig.split(":")[0] + ":"
        order_ref_cell.value = f"{prefix}   {order_number}"
    else:
        ws['H4'] = f"Order No:   {order_number}"
    
    # 2. Find main header row
    header_row_idx = None
    for r in range(1, 40):
        for c in range(1, 20):
            val = ws.cell(row=r, column=c).value
            if val and "NAME OF THE CUSTOMER" in str(val).upper():
                header_row_idx = r
                break
        if header_row_idx:
            break

    if not header_row_idx:
        header_row_idx = 7

    # 3. Map columns dynamically using word boundaries
    col_mapping = {}
    
    def get_words(text):
        return set(re.findall(r'\b\w+\b', text.upper()))
        
    for c in range(1, 16):
        h_val = ws.cell(row=header_row_idx, column=c).value
        sub_val = ws.cell(row=header_row_idx + 1, column=c).value
        
        h_text = str(h_val or "").strip()
        sub_text = str(sub_val or "").strip()
        
        # Combined words
        words = get_words(h_text) | get_words(sub_text)
        
        if h_text.upper() in ("NO.", "NO"):
            col_mapping["no"] = c
        elif "NAME" in words and "CUSTOMER" in words:
            col_mapping["name"] = c
        elif "CONTACT" in words or "PHONE" in words:
            col_mapping["phone"] = c
        elif "ID" in words and "PAID" not in words:
            col_mapping["id"] = c
        elif "CREDIT" in words:
            col_mapping["credit"] = c
        elif "CALLUP" in words or ("CALL" in words and "COMMENT" in words):
            col_mapping["callup"] = c
        elif "COUNTY" in words:
            col_mapping["county"] = c
        elif "LANDMARK" in words or "LOCATION" in words:
            col_mapping["landmark"] = c
        elif "HBG" in words:
            col_mapping["hbg"] = c
        elif "JBL" in words:
            col_mapping["jbl"] = c
        elif "SALES" in words:
            col_mapping["sales"] = c

    col_no = col_mapping.get("no", 1)
    col_name = col_mapping.get("name", 2)
    col_phone = col_mapping.get("phone", 3)
    col_id = col_mapping.get("id", 4)
    col_credit = col_mapping.get("credit", 5)
    col_callup = col_mapping.get("callup", 6)
    col_county = col_mapping.get("county", 7)
    col_landmark = col_mapping.get("landmark", 8)
    col_hbg = col_mapping.get("hbg", 9)
    col_jbl = col_mapping.get("jbl", 10)
    col_sales = col_mapping.get("sales", 11)

    # 4. Dynamically count pre-filled data rows in template
    first_data_row = None
    last_data_row = None
    for r in range(header_row_idx + 2, 50):
        val = ws.cell(row=r, column=col_no).value
        is_num = False
        if val is not None:
            try:
                int(str(val).strip())
                is_num = True
            except ValueError:
                pass
                
        if is_num:
            if first_data_row is None:
                first_data_row = r
            last_data_row = r
        else:
            if first_data_row is not None:
                break
                
    if first_data_row is None:
        first_data_row = 10
        last_data_row = 14
        
    template_data_rows = last_data_row - first_data_row + 1
    N = len(farmers)
    
    totals_row_idx = last_data_row + 1
    
    # 5. Adjust row count dynamically
    if N > template_data_rows:
        insert_count = N - template_data_rows
        ws.insert_rows(totals_row_idx, insert_count)
        for r in range(totals_row_idx, totals_row_idx + insert_count):
            copy_row_formatting(ws, first_data_row, r)
    elif N < template_data_rows:
        delete_count = template_data_rows - N
        ws.delete_rows(first_data_row + N, delete_count)
        
    # 6. Write the data
    for idx, farmer in enumerate(farmers):
        r = first_data_row + idx
        ws.cell(row=r, column=col_no, value=idx + 1)  # NO.
        ws.cell(row=r, column=col_name, value=farmer.customer_name)  # NAME OF THE CUSTOMER
        ws.cell(row=r, column=col_phone, value=farmer.primary_phone)  # CONTACT NO.
        ws.cell(row=r, column=col_id, value=farmer.national_id)  # ID NO.
        ws.cell(row=r, column=col_credit, value=farmer.credit_decision)  # CREDIT ANALYSIS
        ws.cell(row=r, column=col_callup, value="")  # CALLUP COMMENT (blank)
        ws.cell(row=r, column=col_county, value=farmer.county)  # COUNTY
        ws.cell(row=r, column=col_landmark, value=farmer.landmark)  # LOCATION & NEAREST LANDMARK
        
        deposit = clean_deposit_float(farmer.actual_receipts)
        is_hbg = True
        if farmer.lead_source and 'jbl' in farmer.lead_source.lower():
            is_hbg = False
            
        if is_hbg:
            ws.cell(row=r, column=col_hbg, value=deposit)  # HBG
            ws.cell(row=r, column=col_jbl, value="")  # JBL
        else:
            ws.cell(row=r, column=col_hbg, value="")  # HBG
            ws.cell(row=r, column=col_jbl, value=deposit)  # JBL
            
        ws.cell(row=r, column=col_sales, value=farmer.hb_sales_person)  # HB SALES PERSON

    # 7. Write the totals row right after the client data
    new_totals_row = first_data_row + N
    ws.insert_rows(new_totals_row, 1)
    copy_row_formatting(ws, first_data_row, new_totals_row)
    
    ws.cell(row=new_totals_row, column=col_name, value="TOTAL CUSTOMERS:                    TOTAL DEPOSITS →")
    ws.cell(row=new_totals_row, column=col_name).font = openpyxl.styles.Font(bold=True)
    
    col_letter_hbg = get_column_letter(col_hbg)
    col_letter_jbl = get_column_letter(col_jbl)
    col_letter_name = get_column_letter(col_name)
    
    if N > 0:
        ws.cell(row=new_totals_row, column=col_hbg, value=f"=SUM({col_letter_hbg}{first_data_row}:{col_letter_hbg}{first_data_row + N - 1})")
        ws.cell(row=new_totals_row, column=col_jbl, value=f"=SUM({col_letter_jbl}{first_data_row}:{col_letter_jbl}{first_data_row + N - 1})")
        ws.cell(row=new_totals_row, column=col_sales, value=f"=COUNTA({col_letter_name}{first_data_row}:{col_letter_name}{first_data_row + N - 1})")
    else:
        ws.cell(row=new_totals_row, column=col_hbg, value=0)
        ws.cell(row=new_totals_row, column=col_jbl, value=0)
        ws.cell(row=new_totals_row, column=col_sales, value=0)
        
    ws.cell(row=new_totals_row, column=col_hbg).font = openpyxl.styles.Font(bold=True)
    ws.cell(row=new_totals_row, column=col_jbl).font = openpyxl.styles.Font(bold=True)
    ws.cell(row=new_totals_row, column=col_sales).font = openpyxl.styles.Font(bold=True)
        
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
