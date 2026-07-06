import re
import copy
import io
import openpyxl
from datetime import date, datetime
from typing import Any
from core.models import JawabuFarmerMaster

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
    wb = openpyxl.load_workbook("requisition/JBL_Requisition_Form_184.xlsx")
    ws = wb.active
    
    # Fill headers
    date_str = requisition_date.strftime('%d-%b-%Y') if isinstance(requisition_date, (date, datetime)) else str(requisition_date)
    ws['F4'] = f"Date:   {date_str}"
    ws['I4'] = f"Batch / Order Ref:   {order_number}"
    
    N = len(farmers)
    
    # Adjust row count
    if N > 5:
        insert_count = N - 5
        ws.insert_rows(15, insert_count)
        for r in range(15, 15 + insert_count):
            copy_row_formatting(ws, 10, r)
    elif N < 5 and N > 0:
        delete_count = 5 - N
        ws.delete_rows(10 + N, delete_count)
        
    # Write the data
    for idx, farmer in enumerate(farmers):
        r = 10 + idx
        ws.cell(row=r, column=2, value=idx + 1)  # NO.
        ws.cell(row=r, column=3, value=farmer.customer_name)  # NAME OF THE CUSTOMER
        ws.cell(row=r, column=4, value=farmer.primary_phone)  # CONTACT NO.
        ws.cell(row=r, column=5, value=farmer.national_id)  # ID NO.
        ws.cell(row=r, column=6, value=farmer.credit_decision)  # CREDIT ANALYSIS
        ws.cell(row=r, column=7, value="")  # CALLUP COMMENT (blank)
        ws.cell(row=r, column=8, value=farmer.county)  # COUNTY
        ws.cell(row=r, column=9, value=farmer.landmark)  # LOCATION & NEAREST LANDMARK
        
        # Decide deposit paid to HBG vs JBL
        deposit = clean_deposit_float(farmer.actual_receipts)
        # The deposit amount will always be from HB unless explicitly specified otherwise
        is_hbg = True
        if farmer.lead_source and 'jbl' in farmer.lead_source.lower():
            is_hbg = False
            
        if is_hbg:
            ws.cell(row=r, column=10, value=deposit)  # HBG
            ws.cell(row=r, column=11, value="")  # JBL
        else:
            ws.cell(row=r, column=10, value="")  # HBG
            ws.cell(row=r, column=11, value=deposit)  # JBL
            
        ws.cell(row=r, column=12, value=farmer.hb_sales_person)  # HB SALES PERSON

    # Update formulas on the totals row (now at 10 + N)
    totals_row = 10 + N
    if N > 0:
        ws.cell(row=totals_row, column=10, value=f"=SUM(J10:J{9+N})")
        ws.cell(row=totals_row, column=11, value=f"=SUM(K10:K{9+N})")
        ws.cell(row=totals_row, column=12, value=f"=COUNTA(C10:C{9+N})")
    else:
        ws.cell(row=totals_row, column=10, value=0)
        ws.cell(row=totals_row, column=11, value=0)
        ws.cell(row=totals_row, column=12, value=0)
        
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
