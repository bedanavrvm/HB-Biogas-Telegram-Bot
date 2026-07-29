"""Central registry for Django-owned operational Sheet publications.

Google Sheets is a reporting surface in this project.  The registry is kept
independent from any Google client so it can be used for header-only coverage
audits and for every publisher without importing models or performing I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


def normalize_header(value: object) -> str:
    """Normalize a Sheet header for safe alias matching."""
    return " ".join(
        re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split()
    )


@dataclass(frozen=True)
class PublicationField:
    name: str
    source: str
    aliases: tuple[str, ...]
    category: str
    publish: bool = True


def _field(name: str, source: str, aliases: Iterable[str], category: str) -> PublicationField:
    return PublicationField(name, source, tuple(dict.fromkeys(aliases)), category)


# This is deliberately operational rather than a mirror of every model field.
# Raw parser payloads, hashes, credentials, and internal debugging values stay
# in Django/audit tables and are not newly exposed in staff registers.
OPERATIONAL_FIELDS: dict[str, tuple[PublicationField, ...]] = {
    "jawabu_master": (
        _field("unit_number", "JawabuFarmerMaster.unit_number", ("Unit Number", "Unit No"), "workflow"),
        _field("customer_no", "JawabuFarmerMaster.customer_no", ("CUSTOMER NO", "Customer No", "Customer Number", "CUST NO", "Customer ID"), "identity"),
        _field("customer_name", "JawabuFarmerMaster.customer_name", ("Customer Name", "Client Name", "Name"), "identity"),
        _field("imab_customer_name", "JawabuFarmerMaster.imab_customer_name", ("NAME (IMAB)", "IMAB Name", "IMAB Customer Name"), "identity"),
        _field("national_id", "JawabuFarmerMaster.national_id", ("National ID", "ID Number", "ID NO", "ID NUMBER"), "identity"),
        _field("primary_phone", "JawabuFarmerMaster.primary_phone", ("Primary Phone", "Mobile No", "Mobile Number", "Contacts / Primary"), "identity"),
        _field("secondary_phone", "JawabuFarmerMaster.secondary_phone", ("Secondary Phone", "Contacts / Secondary"), "identity"),
        _field("branch", "JawabuFarmerMaster.branch", ("Branch", "Branch / Region"), "location"),
        _field("system_branch", "JawabuFarmerMaster.system_branch", ("System Branch", "IMAB Branch"), "location"),
        _field("county", "JawabuFarmerMaster.county", ("County",), "location"),
        _field("sub_county", "JawabuFarmerMaster.sub_county", ("Sub-County", "Sub County", "Constituency"), "location"),
        _field("ward", "JawabuFarmerMaster.ward", ("Ward",), "location"),
        _field("village", "JawabuFarmerMaster.village", ("Village",), "location"),
        _field("landmark", "JawabuFarmerMaster.landmark", ("Landmark", "Location & Nearest Landmark"), "location"),
        _field("gps_link", "JawabuFarmerMaster.gps_link", ("GPS Link", "Google Maps Link", "Maps Link", "GPS"), "location"),
        _field("latitude", "JawabuFarmerMaster.latitude", ("Latitude", "Lat"), "location"),
        _field("longitude", "JawabuFarmerMaster.longitude", ("Longitude", "Long", "Lng"), "location"),
        _field("hbg_visit_date", "JawabuFarmerMaster.hbg_visit_date", ("HBG Visit Date", "Sign Date"), "workflow"),
        _field("hbg_visit_comment", "JawabuFarmerMaster.comments", ("HBG Visit Comment", "HBG Comment", "Additional Comments"), "workflow"),
        _field("jbl_visit_date", "JawabuFarmerMaster.jbl_visit_date", ("JBL Visit Date", "Jawabu Visit Date"), "workflow"),
        _field("jbl_officer", "JawabuFarmerMaster.jbl_officer", ("JBL Officer", "JBL BRO"), "workflow"),
        _field("jbl_visit_status", "JawabuFarmerMaster.jbl_visit_status", ("JBL Visit Status", "Jawabu Comment After Visit"), "workflow"),
        _field("jbl_visit_comment", "JawabuFarmerMaster.jbl_visit_comment", ("JBL Visit Comment", "Jawabu Visit Comment", "BRO Comment"), "workflow"),
        _field("lead_source", "JawabuFarmerMaster.lead_source", ("Lead Source",), "workflow"),
        _field("hbg_contract_name", "JawabuFarmerMaster.hbg_contract_name", ("HBG Contract Name", "Contract Name"), "workflow"),
        _field("contract_type", "JawabuFarmerMaster.contract_type", ("Contract Type",), "workflow"),
        _field("installation_status", "JawabuFarmerMaster.installation_status", ("Installation Status",), "workflow"),
        _field("hb_sales_person", "JawabuFarmerMaster.hb_sales_person", ("HB Sales Person", "Sales Person"), "workflow"),
        _field("actual_receipts_currency", "JawabuFarmerMaster.actual_receipts_currency", ("Deposit Currency", "Actual Receipts Currency"), "financial"),
        _field("credit_decision", "JawabuFarmerMaster.credit_decision", ("Credit Decision", "Credit Analysis"), "decision"),
        _field("credit_decided_by", "JawabuFarmerMaster.credit_decided_by", ("Credit Decided By", "Credit Analyst"), "decision"),
        _field("credit_decided_at", "JawabuFarmerMaster.credit_decided_at", ("Credit Decided At", "Credit Decision Date"), "timestamp"),
        _field("imab_created", "JawabuFarmerMaster.imab_created", ("IMAB Created", "IS CUSTOMER CREATED ON IMAB?"), "workflow"),
        _field("system_loan_officer", "JawabuFarmerMaster.system_loan_officer", ("System Loan Officer", "Loan Officer"), "workflow"),
        _field("system_deposit_paid_jbl", "JawabuFarmerMaster.system_deposit_paid_jbl", ("Deposit Paid to JBL", "JBL Deposit", "LGF Balance"), "financial"),
        _field("deposit_paid_hbg", "JawabuFarmerMaster.deposit_paid_hbg", ("Deposit Paid to HBG", "Deposit Paid to HB", "DEPOSIT / HB"), "financial"),
        _field("repayment_date", "JawabuFarmerMaster.repayment_date", ("Repayment Date", "Repayment Dates"), "financial"),
        _field("repayment_day", "JawabuFarmerMaster.repayment_day", ("Repayment Day",), "financial"),
        _field("repayment_tenor", "JawabuFarmerMaster.repayment_tenor", ("Tenor", "Repayment Tenor"), "financial"),
        _field("repayment_tenor_months", "JawabuFarmerMaster.repayment_tenor_months", ("Tenor Months", "Repayment Tenor Months"), "financial"),
        _field("payment_product", "JawabuFarmerMaster.payment_product", ("Payment Product", "Product", "Product Name"), "financial"),
        _field("final_decision", "JawabuFarmerMaster.final_decision", ("Final Decision", "Head of Rural Decision"), "decision"),
        _field("final_decided_by", "JawabuFarmerMaster.final_decided_by", ("Final Decided By", "Decision By"), "decision"),
        _field("final_decided_at", "JawabuFarmerMaster.final_decided_at", ("Final Decided At", "Decision Date"), "timestamp"),
        _field("payment_call_up_comment", "JawabuFarmerMaster.final_decision_comment", ("Payment Call Up Comment", "Payment Comment", "HOR Payment Comment", "COL"), "decision"),
        _field("deferred_stage", "JawabuFarmerMaster.deferred_stage", ("Deferred Stage",), "workflow"),
        _field("deferred_until", "JawabuFarmerMaster.deferred_until", ("Deferred Until",), "timestamp"),
        _field("order_number", "JawabuFarmerMaster.order_number", ("Order No.", "Order No", "Order Number"), "documents"),
        _field("requisition_date", "JawabuFarmerMaster.requisition_date", ("Requisition Date", "Jawabu Requisition Date"), "documents"),
        _field("invoice_number", "JawabuFarmerMaster.invoice_number", ("Invoice Number", "HBG Invoice Number"), "documents"),
        _field("invoice_date", "JawabuFarmerMaster.invoice_date", ("Invoice Date", "HBG Invoice Date"), "documents"),
        _field("invoice_amount", "JawabuFarmerMaster.invoice_amount", ("Invoice Amount", "Invoice Value"), "financial"),
        _field("discount", "JawabuFarmerMaster.discount", ("Discount",), "financial"),
        _field("payment", "JawabuFarmerMaster.payment", ("Payment", "HBG Payment / Deposit"), "financial"),
        _field("balance_due", "JawabuFarmerMaster.balance_due", ("Balance Due", "HB Invoice Balance", "Balance Due (K)"), "financial"),
        _field("jbl_media_urls", "JawabuFarmerMaster.jbl_media_urls", ("Media URLs", "Drive Links", "LAF / Visit Media"), "documents"),
        _field("updated_at", "JawabuFarmerMaster.updated_at", ("Last Updated At",), "timestamp"),
    ),
    "internal_order": (
        _field("order_record_id", "derived", ("ORDER RECORD ID", "Record ID"), "audit"),
        _field("order_number", "JawabuFarmerMaster.order_number", ("ORDER NO", "Order No.", "Order No"), "documents"),
        _field("requisition_date", "JawabuFarmerMaster.requisition_date", ("REQUISITION DATE", "Requisition Date"), "documents"),
        _field("hbg_visit_date", "JawabuFarmerMaster.hbg_visit_date", ("HBG Visit Date", "Sign Date"), "workflow"),
        _field("jbl_visit_date", "JawabuFarmerMaster.jbl_visit_date", ("DATE VISITED", "JBL Visit Date"), "workflow"),
        _field("hbg_visit_comment", "JawabuFarmerMaster.comments", ("HBG Visit Comment", "Additional Comments"), "workflow"),
        _field("customer_name", "JawabuFarmerMaster.customer_name", ("CUSTOMER NAME", "Client Name", "Name"), "identity"),
        _field("branch", "JawabuFarmerMaster.branch", ("BRANCH",), "location"),
        _field("system_branch", "JawabuFarmerMaster.system_branch", ("SYSTEM BRANCH", "IMAB BRANCH"), "location"),
        _field("national_id", "JawabuFarmerMaster.national_id", ("ID NUMBER", "National ID", "ID NO"), "identity"),
        _field("primary_phone", "JawabuFarmerMaster.primary_phone", ("CONTACTS / PRIMARY", "Primary Phone", "Mobile No"), "identity"),
        _field("secondary_phone", "JawabuFarmerMaster.secondary_phone", ("CONTACTS / SECONDARY", "Secondary Phone"), "identity"),
        _field("county", "JawabuFarmerMaster.county", ("COUNTY",), "location"),
        _field("sub_county", "JawabuFarmerMaster.sub_county", ("SUB-COUNTY", "Sub County", "Constituency"), "location"),
        _field("ward", "JawabuFarmerMaster.ward", ("WARD", "Ward"), "location"),
        _field("village", "JawabuFarmerMaster.village", ("VILLAGE", "Village"), "location"),
        _field("landmark", "JawabuFarmerMaster.landmark", ("LOCATION AND NEAREST LANDMARK", "Landmark"), "location"),
        _field("gps_link", "JawabuFarmerMaster.gps_link", ("GPS Link", "Google Maps Link", "Maps Link"), "location"),
        _field("jbl_officer", "JawabuFarmerMaster.jbl_officer", ("VISITED BY", "JBL BRO", "JBL Officer"), "workflow"),
        _field("hb_sales_person", "JawabuFarmerMaster.hb_sales_person", ("HB STAFF", "Sales Person"), "workflow"),
        _field("system_loan_officer", "JawabuFarmerMaster.system_loan_officer", ("SYSTEM LOAN OFFICER", "Loan Officer"), "workflow"),
        _field("deposit_paid_hbg", "JawabuFarmerMaster.deposit_paid_hbg", ("DEPOSIT / HB", "Deposit Paid to HBG"), "financial"),
        _field("system_deposit_paid_jbl", "JawabuFarmerMaster.system_deposit_paid_jbl", ("DEPOSIT / JBL", "Deposit Paid to JBL", "LGF Balance"), "financial"),
        _field("jbl_visit_comment", "JawabuFarmerMaster.jbl_visit_comment", ("BRO COMMENT", "JBL Visit Comment"), "workflow"),
        _field("credit_decision", "JawabuFarmerMaster.credit_decision", ("CREDIT ANALYSIS", "Credit Analysis"), "decision"),
        _field("imab_created", "JawabuFarmerMaster.imab_created", ("IS CUSTOMER CREATED ON IMAB?", "IMAB Created"), "workflow"),
        _field("customer_no", "JawabuFarmerMaster.customer_no", ("CUSTOMER NO", "Customer Number"), "identity"),
        _field("repayment_date", "JawabuFarmerMaster.repayment_date", ("REPAYMENT DATE", "Repayment Date"), "financial"),
        _field("repayment_tenor", "JawabuFarmerMaster.repayment_tenor", ("TENOR", "Repayment Tenor"), "financial"),
        _field("payment_product", "JawabuFarmerMaster.payment_product", ("PAYMENT PRODUCT", "Product", "Product Name"), "financial"),
        _field("payment_call_up_comment", "JawabuFarmerMaster.final_decision_comment", ("PAYMENT CALL UP COMMENT", "Payment Comment"), "decision"),
        _field("final_decision", "JawabuFarmerMaster.final_decision", ("FINAL DECISION",), "decision"),
        _field("jbl_media_urls", "JawabuFarmerMaster.jbl_media_urls", ("MEDIA URLS", "Drive Links"), "documents"),
        _field("updated_at", "JawabuFarmerMaster.updated_at", ("LAST UPDATED AT",), "timestamp"),
    ),
    "tat_tracker": (
        _field("case_id", "TatTrackerCase.case_id", ("Case ID",), "identity"),
        _field("client_name", "TatTrackerCase.client_name", ("Client Name", "Customer Name"), "identity"),
        _field("national_id", "TatTrackerCase.national_id", ("National ID", "ID Number"), "identity"),
        _field("primary_phone", "TatTrackerCase.primary_phone", ("Primary Phone", "Mobile No"), "identity"),
        _field("branch", "TatTrackerCase.branch", ("Branch",), "location"),
        _field("product", "TatTrackerCase.product_label", ("Product", "Product Name"), "workflow"),
        _field("bro_name", "TatTrackerCase.bro_name", ("BRO", "BRO Name"), "workflow"),
        _field("current_stage", "TatTrackerCase.current_stage", ("Current Stage",), "workflow"),
        _field("status", "TatTrackerCase.status", ("Status",), "workflow"),
        _field("created_at", "TatTrackerCase.created_at", ("Created At",), "timestamp"),
        _field("updated_at", "TatTrackerCase.updated_at", ("Last Updated At",), "timestamp"),
        _field("tat", "derived", ("TAT", "TAT Hours", "TAT Days"), "timestamp"),
    ),
    "complaint_register": (
        _field("complaint_id", "ParsedMessage.complaint_id", ("Complaint ID", "Case ID"), "identity"),
        _field("date_reported", "ParsedMessage.timestamp", ("Date Reported", "Reported Date"), "timestamp"),
        _field("customer_name", "ParsedMessage.customer_name", ("Customer Name", "Client Name"), "identity"),
        _field("customer_id", "ParsedMessage.customer_id", ("Customer ID", "National ID"), "identity"),
        _field("customer_phone", "ParsedMessage.customer_phone", ("Customer Phone", "Mobile No"), "identity"),
        _field("branch_region", "ParsedMessage.branch_region", ("Branch / Region", "Branch", "County"), "location"),
        _field("complaint_category", "ParsedMessage.complaint_category", ("Complaint Category", "Category"), "workflow"),
        _field("complaint_description", "ParsedMessage.complaint_description", ("Complaint Description", "Description"), "workflow"),
        _field("gps_link", "ParsedMessage.gps_link", ("GPS Link", "Maps Link"), "location"),
        _field("status", "ParsedMessage.complaint_status", ("Status", "Case Status"), "workflow"),
        _field("resolution_details", "ParsedMessage.resolution_details", ("Resolution Details", "Resolution"), "decision"),
        _field("date_resolved", "ParsedMessage.date_resolved", ("Date Resolved", "Closed Date"), "timestamp"),
        _field("days_open", "derived", ("Days Open", "Age"), "timestamp"),
    ),
    "spin_credit": (
        _field("request_id", "SpinCreditRequest.request_id", ("Request ID",), "identity"),
        _field("request_datetime", "SpinCreditRequest.created_at", ("Request Date/Time", "Request Date"), "timestamp"),
        _field("branch", "SpinCreditRequest.branch", ("Branch",), "location"),
        _field("requested_by", "SpinCreditRequest.requested_by", ("Requested By",), "workflow"),
        _field("credit_analyst_name", "SpinCreditRequest.credit_analyst_name", ("Credit Analyst Name",), "workflow"),
        _field("request_type", "SpinCreditRequest.request_type", ("Request Type",), "workflow"),
        _field("customer_name", "SpinCreditRequest.customer_name", ("Customer Name",), "identity"),
        _field("national_id", "SpinCreditRequest.national_id", ("National ID",), "identity"),
        _field("primary_phone", "SpinCreditRequest.primary_phone", ("Primary Phone",), "identity"),
        _field("loan_product", "SpinCreditRequest.loan_product", ("Loan Product", "Product"), "financial"),
        _field("requested_amount", "SpinCreditRequest.requested_amount", ("Requested Amount",), "financial"),
        _field("tenor", "SpinCreditRequest.tenor", ("Tenor",), "financial"),
        _field("attachment_names", "derived", ("Attachments",), "documents"),
        _field("media_urls", "derived", ("Media URLs", "Drive Links"), "documents"),
        _field("parse_status", "SpinCreditRequest.parse_status", ("Parse Status",), "workflow"),
        _field("analysis_status", "SpinCreditRequest.analysis_status", ("Analysis Status",), "decision"),
        _field("analyst_response", "SpinCreditRequest.analyst_response", ("Analyst Response",), "decision"),
    ),
    "fca": (
        _field("order_record_id", "FcaImportRecord.order_record_id", ("ORDER RECORD ID", "Record ID"), "identity"),
        _field("customer_name", "FcaImportRecord.customer_name", ("CUSTOMER NAME", "Customer Name"), "identity"),
        _field("primary_phone", "FcaImportRecord.primary_phone", ("CONTACTS / PRIMARY", "Primary Phone"), "identity"),
        _field("national_id", "derived", ("ID NUMBER", "National ID"), "identity"),
        _field("branch", "derived", ("BRANCH", "Branch"), "location"),
        _field("county", "derived", ("COUNTY", "County"), "location"),
        _field("sub_county", "derived", ("SUB-COUNTY", "Sub County", "Constituency"), "location"),
        _field("ward", "derived", ("WARD", "Ward"), "location"),
        _field("village", "derived", ("VILLAGE", "Village"), "location"),
        _field("landmark", "derived", ("LOCATION AND NEAREST LANDMARK", "Landmark"), "location"),
        _field("deposit_hb", "derived", ("DEPOSIT / HB", "Deposit Paid to HB"), "financial"),
        _field("fca_visit_date", "FcaImportRecord.fca_visit_date", ("FCA VISIT DATE", "JBL Visit Date"), "workflow"),
        _field("fca_comment", "FcaImportRecord.fca_comment", ("FCA COMMENT", "JBL Visit Comment"), "workflow"),
        _field("fca_decision", "FcaImportRecord.fca_decision", ("FCA DECISION", "JBL Visit Status"), "decision"),
        _field("fca_import_status", "FcaImportRecord.import_status", ("FCA IMPORT STATUS", "Import Status"), "workflow"),
    ),
}


def fields_for_surface(surface: str) -> tuple[PublicationField, ...]:
    return tuple(field for field in OPERATIONAL_FIELDS.get(surface, ()) if field.publish)


def aliases_for(surface: str, field_name: str) -> tuple[str, ...]:
    for field in fields_for_surface(surface):
        if field.name == field_name:
            return field.aliases
    return ()


def coverage_for_headers(surface: str, headers: Iterable[object]) -> dict:
    """Return a header-only coverage report; no Sheet data rows are read."""
    actual = [str(header or "").strip() for header in headers]
    normalized = {normalize_header(header): header for header in actual if normalize_header(header)}
    present = []
    missing = []
    for field in fields_for_surface(surface):
        matched = next((normalized[normalize_header(alias)] for alias in field.aliases if normalize_header(alias) in normalized), "")
        item = {
            "field": field.name,
            "source": field.source,
            "category": field.category,
            "header": matched,
            "aliases": list(field.aliases),
        }
        (present if matched else missing).append(item)
    return {
        "surface": surface,
        "headers": actual,
        "present": present,
        "missing": missing,
        "present_count": len(present),
        "missing_count": len(missing),
    }


def coverage_for_configuration(config, headers: Iterable[object]) -> dict:
    """Select the operational registry surface for a GroupSheetConfiguration."""
    workflow = getattr(config, "workflow", None) or {}
    workflow_type = str(workflow.get("type") or "case")
    surface = {
        "jawabu": "jawabu_master",
        "jawabu_homebiogas": "jawabu_master",
        "order_approval": "internal_order",
        "tat_tracker": "tat_tracker",
        "spin_credit_analysis": "spin_credit",
        "fca": "fca",
    }.get(workflow_type, "complaint_register")
    return coverage_for_headers(surface, headers)


def surfaces_for_configuration(config) -> list[dict[str, str]]:
    """Return configured publication surfaces without reading any Sheet data."""
    workflow = getattr(config, 'workflow', None) or {}
    workflow_type = str(workflow.get('type') or 'case')
    if workflow_type in {'jawabu', 'jawabu_homebiogas'}:
        targets = []
        if workflow.get('master_sync_enabled') or workflow.get('master_sheet_id'):
            targets.append({
                'surface': 'jawabu_master',
                'sheet_id': str(workflow.get('master_sheet_id') or getattr(config, 'sheet_id', '') or ''),
                'sheet_name': str(workflow.get('master_sheet_name') or 'Master Data'),
                'header_row': str(workflow.get('master_header_row') or 3),
            })
        if workflow.get('internal_order_sync_enabled') or workflow.get('internal_order_sheet_id'):
            targets.append({
                'surface': 'internal_order',
                'sheet_id': str(workflow.get('internal_order_sheet_id') or ''),
                'sheet_name': str(workflow.get('internal_order_sheet_name') or 'Orders'),
                'header_row': str(workflow.get('internal_order_header_row') or 2),
            })
        if targets:
            return targets
    surface = {
        'order_approval': 'internal_order',
        'tat_tracker': 'tat_tracker',
        'spin_credit_analysis': 'spin_credit',
        'fca': 'fca',
    }.get(workflow_type, 'complaint_register')
    return [{
        'surface': surface,
        'sheet_id': str(getattr(config, 'sheet_id', '') or ''),
        'sheet_name': str(getattr(config, 'sheet_name', '') or ''),
        'header_row': str(workflow.get('header_row') or 1),
    }]
