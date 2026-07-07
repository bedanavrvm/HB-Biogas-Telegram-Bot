"""
JBL Pipeline queue service.

Provides pure-Django queryset helpers for each pipeline stage, plus the
write functions that advance a farmer record through the workflow. The
credit decision gate is enforced here (server-side) so it is impossible
to bypass via direct API calls.

Stage overview:
  Stage 1 — HB imports farmer via CSV upload          → sign_date populated
  Stage 2 — JBL officer logs site visit               → jbl_visit_date populated
  Stage 3 — Credit analyst records decision            → credit_decision set
  Stage 4 — Admin assigns requisition / order number  → order_number set (GATED)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.utils import timezone

from core.models import JawabuFarmerMaster

logger = logging.getLogger(__name__)

# ── Approved statuses that signal a client may move to credit review ──────────
JBL_FORWARD_STATUSES = frozenset({
    'Approved',
    'Awaiting Analysis',
})

CREDIT_APPROVED = 'Approved'


# ── Queue filters ─────────────────────────────────────────────────────────────

def jbl_visit_queue():
    """
    Stage 2 queue — farmers HB has visited but JBL has not yet called on.

    Filter: HBG Visit Date present AND JBL Visit Date absent.
    """
    return JawabuFarmerMaster.objects.filter(
        jbl_visit_date__isnull=True,
        status='active',
    ).exclude(sign_date='').order_by('county', 'customer_name')


def credit_queue():
    """
    Stage 3 queue — farmers JBL has visited and moved forward, awaiting credit review.

    Filter: JBL Visit Date present AND Credit Decision empty or Pending.
    """
    return JawabuFarmerMaster.objects.filter(
        jbl_visit_date__isnull=False,
        status='active',
    ).exclude(
        credit_decision__in=['Approved', 'Rejected', 'Deferred', 'Exemption Approved'],
    ).order_by('jbl_visit_date', 'customer_name')


def requisition_queue():
    """
    Stage 4 queue — credit approved, order number not yet assigned.

    Filter: credit_decision = Approved AND order_number empty.
    """
    return JawabuFarmerMaster.objects.filter(
        credit_decision=CREDIT_APPROVED,
        order_number='',
    ).order_by('credit_decided_at', 'customer_name')


def deferred_queue():
    """
    Deferred / flagged cases — credit not moving forward.

    Filter: credit_decision in Rejected, Deferred, or JBL visit marked as
    Rejected by JBL / Cancelled / Client Withdrew / Opted for Cash.
    """
    from django.db.models import Q
    return JawabuFarmerMaster.objects.filter(
        status='active',
    ).filter(
        Q(credit_decision__in=['Rejected', 'Deferred']) |
        Q(jbl_visit_status__in=['Rejected by JBL', 'Cancelled', 'Client Withdrew', 'Opted for Cash'])
    ).order_by('-updated_at')


def all_cases(search: str = '', county: str = ''):
    """
    Full farmer list with optional search and county filter.
    Aggregates across all groups.
    """
    qs = JawabuFarmerMaster.objects.all()
    if county:
        qs = qs.filter(county__iexact=county)
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(customer_name__icontains=search) |
            Q(primary_phone__icontains=search) |
            Q(national_id__icontains=search)
        )
    return qs.order_by('county', 'customer_name')


# ── Queue counts (dashboard) ──────────────────────────────────────────────────

def pipeline_counts() -> dict[str, int]:
    """Return queue counts for all stages — drives the portal dashboard."""
    return {
        'jbl_queue': jbl_visit_queue().count(),
        'credit_queue': credit_queue().count(),
        'requisition_queue': requisition_queue().count(),
        'deferred': deferred_queue().count(),
        'total': all_cases().count(),
    }


# ── Write functions ───────────────────────────────────────────────────────────

def log_jbl_visit(
    farmer: JawabuFarmerMaster,
    *,
    visit_date: date,
    officer: str,
    visit_status: str,
    comment: str = '',
    sender: str = '',
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[bool, str]:
    """
    Record that a JBL officer has visited the farmer (Stage 2 advance).

    Returns (success, error_message).
    """
    # Validate status value
    valid_statuses = {choice[0] for choice in JawabuFarmerMaster.JBL_VISIT_STATUS_CHOICES}
    if visit_status and visit_status not in valid_statuses:
        return False, f"Invalid JBL visit status: '{visit_status}'"

    farmer.jbl_visit_date = visit_date
    farmer.jbl_officer = str(officer or sender or '').strip()
    farmer.jbl_visit_status = visit_status
    farmer.jbl_visit_comment = str(comment or '').strip()

    update_fields = [
        'jbl_visit_date', 'jbl_officer', 'jbl_visit_status',
        'jbl_visit_comment', 'updated_at',
    ]

    if latitude is not None and longitude is not None:
        farmer.latitude = latitude
        farmer.longitude = longitude
        farmer.gps_link = f"https://maps.google.com/?q={latitude},{longitude}"
        update_fields.extend(['latitude', 'longitude', 'gps_link'])

    farmer.save(update_fields=update_fields)
    logger.info(
        'JBL visit logged for farmer %s by %s: %s (coordinates: %s, %s)',
        farmer.id, sender or officer, visit_status, latitude, longitude,
    )
    # Sync change to master Google Sheet
    sync_farmer_to_master_sheet(farmer)
    return True, ''


def set_credit_decision(
    farmer: JawabuFarmerMaster,
    *,
    decision: str,
    sender: str = '',
) -> tuple[bool, str]:
    """
    Record the credit analyst's decision (Stage 3 advance).

    Returns (success, error_message).
    """
    valid_decisions = {choice[0] for choice in JawabuFarmerMaster.CREDIT_DECISION_CHOICES}
    if decision not in valid_decisions:
        return False, f"Invalid credit decision: '{decision}'. Must be one of: {', '.join(sorted(valid_decisions))}"

    old_decision = farmer.credit_decision
    farmer.credit_decision = decision
    farmer.credit_decided_by = str(sender or '').strip()
    farmer.credit_decided_at = timezone.now()
    farmer.save(update_fields=[
        'credit_decision', 'credit_decided_by', 'credit_decided_at', 'updated_at',
    ])
    logger.info(
        'Credit decision %s set for farmer %s by %s',
        decision, farmer.id, sender,
    )
    # Sync change to master Google Sheet
    sync_farmer_to_master_sheet(farmer)

    # Post Telegram notification if newly approved
    if decision == CREDIT_APPROVED and old_decision != CREDIT_APPROVED:
        _notify_credit_approved(farmer)

    return True, ''


def assign_order(
    farmer: JawabuFarmerMaster,
    *,
    order_number: str,
    requisition_date: date | None = None,
    sender: str = '',
) -> tuple[bool, str]:
    """
    Assign an order number and requisition date (Stage 4 advance).

    GATE: Credit Decision must be 'Approved'. Returns (success, error_message).
    """
    if farmer.credit_decision != CREDIT_APPROVED:
        return (
            False,
            f"Cannot assign order — Credit Decision is '{farmer.credit_decision or 'not set'}', "
            f"not Approved. Complete the credit analysis first."
        )

    order_number = str(order_number or '').strip()
    if not order_number:
        return False, 'Order number is required.'

    farmer.order_number = order_number
    farmer.requisition_date = requisition_date or date.today()
    farmer.save(update_fields=['order_number', 'requisition_date', 'updated_at'])
    logger.info(
        'Order %s assigned to farmer %s by %s',
        order_number, farmer.id, sender,
    )
    # Sync change to master Google Sheet
    sync_farmer_to_master_sheet(farmer)
    return True, ''


# ── Serialization helpers ─────────────────────────────────────────────────────

def farmer_to_card(farmer: JawabuFarmerMaster) -> dict[str, Any]:
    """Compact farmer representation for queue cards in the portal Mini App."""
    return {
        'id': str(farmer.id),
        'customer_name': farmer.customer_name,
        'national_id': farmer.national_id,
        'primary_phone': farmer.primary_phone,
        'county': farmer.county,
        'sub_county': farmer.sub_county,
        'village': farmer.village,
        'branch': farmer.branch,
        'hb_sales_person': farmer.hb_sales_person,
        'sign_date': farmer.sign_date,
        # Stage 2
        'jbl_visit_date': farmer.jbl_visit_date.isoformat() if farmer.jbl_visit_date else None,
        'jbl_officer': farmer.jbl_officer,
        'jbl_visit_status': farmer.jbl_visit_status,
        'jbl_visit_comment': farmer.jbl_visit_comment,
        # Stage 3
        'credit_decision': farmer.credit_decision,
        'credit_decided_by': farmer.credit_decided_by,
        'credit_decided_at': (
            farmer.credit_decided_at.isoformat() if farmer.credit_decided_at else None
        ),
        # Stage 4
        'requisition_date': farmer.requisition_date.isoformat() if farmer.requisition_date else None,
        'order_number': farmer.order_number,
        # Stage 7 — Invoice
        'invoice_number': farmer.invoice_number,
        'invoice_date': farmer.invoice_date.isoformat() if farmer.invoice_date else None,
        'invoice_amount': str(farmer.invoice_amount) if farmer.invoice_amount is not None else None,
        'discount': str(farmer.discount) if farmer.discount is not None else None,
        'payment': str(farmer.payment) if farmer.payment is not None else None,
        'balance_due': str(farmer.balance_due) if farmer.balance_due is not None else None,
        # Meta
        'pipeline_stage': _pipeline_stage(farmer),
        'updated_at': farmer.updated_at.isoformat(),
        'latitude': farmer.latitude,
        'longitude': farmer.longitude,
    }


def _pipeline_stage(farmer: JawabuFarmerMaster) -> int:
    """
    Returns the current pipeline stage number (1–7).
    Stage 7 means an invoice has been uploaded for this farmer.
    """
    if farmer.invoice_number:
        return 7
    if farmer.order_number:
        return 4
    if farmer.credit_decision == CREDIT_APPROVED:
        return 4  # approved but order not yet assigned
    if farmer.credit_decision:
        return 3
    if farmer.jbl_visit_date:
        return 3  # visited, awaiting credit
    if farmer.sign_date:
        return 2  # HB visited, awaiting JBL
    return 1


# ── Google Sheets Sync & Notifications ────────────────────────────────────────


def _sheet_number(value):
    if value is None:
        return ''
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def sync_farmer_to_master_sheet(farmer: JawabuFarmerMaster) -> bool:
    """
    Sync a farmer's updated pipeline fields to the master Google sheet.

    Also records a LiveSheetRecordChange audit entry for traceability.
    """
    from django.conf import settings
    from core.models import GroupSheetConfiguration, LiveSheetRecordChange
    from core.services.group_config import GroupRegistry
    from core.services.sheets import GoogleSheetsService
    from core.services.jawabu_master import (
        header_lookup_from_headers,
        build_master_existing_index,
        find_master_row_number,
        first_existing_header,
        set_header_value,
        update_master_sheet_row,
        normalize_header,
    )

    group_config = None
    # 1. Try GroupRegistry (loaded from settings at startup)
    from core.services.jawabu import is_jawabu_workflow
    for config in GroupRegistry.get_instance().list_groups().values():
        if is_jawabu_workflow(config):
            group_config = config
            break

    # 2. Fallback: query DB directly (covers test environments and admin-only configs)
    if not group_config:
        from core.models import GroupSheetConfiguration
        from core.services.group_config import GroupConfig
        db_config = GroupSheetConfiguration.objects.filter(enabled=True).first()
        if db_config:
            workflow = db_config.workflow or {}
            if workflow.get('type') == 'jawabu' or workflow.get('master_sync_enabled'):
                group_config = GroupConfig(
                    group_id=db_config.group_id,
                    sheet_id=db_config.sheet_id,
                    sheet_name=db_config.sheet_name or '',
                    enabled=db_config.enabled,
                    workflow=workflow,
                )

    if not group_config:
        logger.warning("No group configuration found for sync of farmer %s", farmer.id)
        return False

    workflow = getattr(group_config, 'workflow', None) or {}
    if not workflow.get('master_sync_enabled'):
        logger.info("Master sheet sync is disabled for group %s", group_config.group_id)
        return False

    sheet_id = str(workflow.get('master_sheet_id') or getattr(group_config, 'sheet_id', '') or '').strip()
    sheet_name = str(workflow.get('master_sheet_name') or 'Master Data').strip()
    header_row = int(workflow.get('master_header_row') or 3)
    data_start_row = int(workflow.get('master_data_start_row') or header_row + 2)

    if not sheet_id or not sheet_name:
        logger.warning("Master sheet config incomplete for group %s", group_config.group_id)
        return False

    try:
        service = GoogleSheetsService.get_instance(sheet_id=sheet_id, sheet_name=sheet_name)
        if not service.is_available():
            logger.warning("Google Sheets service unavailable for master sync")
            return False
        sheet = service._sheet

        headers = list(sheet.row_values(header_row))
        header_lookup = header_lookup_from_headers(headers)
        values = sheet.get_all_values()
        existing = build_master_existing_index(values, header_lookup, data_start_row)

        cleaned = {
            'duplicate_key': farmer.duplicate_key,
            'national_id': farmer.national_id,
            'primary_phone': farmer.primary_phone,
        }
        row_number = find_master_row_number(cleaned, existing)
        if not row_number:
            logger.warning("Farmer %s not found in master sheet rows", farmer.id)
            return False

        # Get row values and pad if needed
        row_values = list(values[row_number - 1]) if row_number - 1 < len(values) else []
        if len(row_values) < len(headers):
            row_values.extend([''] * (len(headers) - len(row_values)))

        # Update pipeline fields
        now_text = timezone.now().strftime('%d-%B-%Y %H:%M')
        changes = {}

        pipeline_fields = {
            'jbl_visit_date': (['Jawabu Visit Date', 'JBL Visit Date'], farmer.jbl_visit_date.strftime('%d-%B-%Y') if farmer.jbl_visit_date else ''),
            'jbl_officer': (['JBL BRO', 'JBL Officer'], farmer.jbl_officer),
            'jbl_visit_status': (['Jawabu Comment After Visit', 'JBL Visit Status'], farmer.jbl_visit_status),
            'jbl_visit_comment': (['Additional Comments', 'Jawabu Visit Comment', 'JBL Visit Comment'], farmer.jbl_visit_comment),
            'credit_decision': (['Credit Analysis', 'Credit Decision'], farmer.credit_decision),
            'requisition_date': (['Jawabu Requisition Date', 'Requisition Date'], farmer.requisition_date.strftime('%d-%B-%Y') if farmer.requisition_date else ''),
            'order_number': (['Order No.'], farmer.order_number),
            'latitude': (['Latitude', 'Lat'], str(farmer.latitude) if farmer.latitude is not None else ''),
            'longitude': (['Longitude', 'Long', 'Lng'], str(farmer.longitude) if farmer.longitude is not None else ''),
            'gps_link': (['GPS Link', 'Google Maps Link', 'Maps Link', 'GPS'], farmer.gps_link or ''),
            'invoice_number': (['Invoice Number', 'HBG Invoice Number'], farmer.invoice_number),
            'invoice_date': (['Invoice Date', 'HBG Invoice Date'], farmer.invoice_date.strftime('%d-%B-%Y') if farmer.invoice_date else ''),
            'invoice_amount': (['Invoice Amount', 'Invoice Value', 'Total Amount'], _sheet_number(farmer.invoice_amount)),
            'discount': (['Discount'], _sheet_number(farmer.discount)),
            'payment': (['Payment'], _sheet_number(farmer.payment)),
            'balance_due': (['Balance Due'], _sheet_number(farmer.balance_due)),
        }

        for field_name, (candidates, new_val) in pipeline_fields.items():
            header = first_existing_header(header_lookup, candidates)
            if header:
                idx = header_lookup[normalize_header(header)] - 1
                current_val = row_values[idx] if idx < len(row_values) else ''
                if str(current_val).strip() != str(new_val).strip():
                    set_header_value(row_values, header_lookup, header, new_val)
                    changes[header] = {'before': current_val, 'after': new_val}

        if changes:
            set_header_value(row_values, header_lookup, 'Last Updated At', now_text)
            update_master_sheet_row(sheet, row_number, row_values)

            # Create LiveSheetRecordChange audit entry
            LiveSheetRecordChange.objects.create(
                group_configuration=GroupSheetConfiguration.objects.filter(group_id=group_config.group_id).first(),
                group_id=group_config.group_id,
                sheet_id=sheet_id,
                sheet_tab=sheet_name,
                row_number=row_number,
                record_key=farmer.duplicate_key or farmer.national_id or farmer.primary_phone,
                action='update',
                changed_by='portal',
                changes=changes,
                status='success',
            )
            logger.info("Synced farmer %s changes to master sheet row %s: %s", farmer.id, row_number, changes)
        return True
    except Exception as exc:
        logger.error("Failed to sync farmer %s to master sheet: %s", farmer.id, exc, exc_info=True)
        return False


def _notify_credit_approved(farmer: JawabuFarmerMaster) -> None:
    """Notify the Telegram group (if configured) when a credit decision is Approved."""
    from django.conf import settings
    import requests

    # Find the group ID configured with jawabu workflow
    from core.services.group_config import GroupRegistry
    from core.services.jawabu import is_jawabu_workflow
    chat_id = None
    for config in GroupRegistry.get_instance().list_groups().values():
        if is_jawabu_workflow(config):
            chat_id = config.group_id
            break

    chat_id = chat_id or getattr(settings, 'TELEGRAM_DEFAULT_CHAT_ID', None)
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not chat_id or not bot_token:
        return

    text = (
        f"🎉 *Credit Approved* for:\n"
        f"👤 *Farmer:* {farmer.customer_name or 'Unknown'}\n"
        f"🆔 *ID:* {farmer.national_id or '—'}\n"
        f"📞 *Phone:* {farmer.primary_phone or '—'}\n"
        f"📍 *County:* {farmer.county or '—'}\n\n"
        f"Assign a requisition date and Order No. in the Pipeline Portal!"
    )
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    try:
        requests.post(
            url,
            data={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'},
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Failed to send credit approval notification to Telegram: %s", exc)



