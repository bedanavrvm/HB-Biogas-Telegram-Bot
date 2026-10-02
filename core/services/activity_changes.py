"""Allowlisted, read-only comparisons of recorded workflow facts."""

FIELD_LABELS = {
    'customer_name': 'Customer name', 'client_name': 'Customer name',
    'national_id': 'National ID', 'primary_phone': 'Phone', 'secondary_phone': 'Other phone',
    'county': 'County', 'constituency': 'Constituency', 'branch': 'Branch',
    'village': 'Village', 'location': 'Location', 'gps_link': 'Location pin',
    'loan_officer': 'Loan officer', 'bro_name': 'Officer', 'product': 'Product',
    'status': 'Status', 'decision': 'Decision', 'comment': 'Comment',
    'imab_created': 'Created in IMAB', 'customer_no': 'Customer number',
    'credit_decision': 'Credit decision', 'final_decision': 'Final decision',
    'credit_comment': 'Credit comment', 'final_comment': 'Final comment',
    'order_number': 'Order number', 'invoice_number': 'Invoice number',
    'invoice_no': 'Invoice number', 'invoice_date_raw': 'Invoice date',
    'customer_id': 'National ID', 'customer_phone': 'Phone',
    'invoice_amount': 'Unit price', 'total_after_discount': 'Discounted price',
    'discount': 'Discount', 'payment': 'HB deposit', 'balance_due': 'Balance due',
    'payment_number': 'Payment number', 'payment_mode': 'Payment mode',
    'membership': 'Batch membership', 'case_count': 'Cases', 'document': 'Workbook',
    'signed_scan': 'Signed scan', 'amount': 'Amount', 'loan_amount': 'Loan amount',
    'deposit_paid_hbg': 'HB deposit', 'deposit_paid_jbl': 'JBL deposit',
    'lgf_balance': 'LGF balance', 'repayment_date': 'Repayment day',
    'repayment_day': 'Repayment day', 'repayment_tenor': 'Repayment period',
    'hbg_visit_date': 'HB visit', 'jbl_visit_date': 'JBL visit',
    'visit_date': 'Visit date', 'jbl_officer': 'Officer',
    'requisition_date': 'Order date', 'deferred_until': 'Deferred until',
    'installation_status': 'Installation', 'installed_on': 'Installed on',
    'installation_date': 'Installed on', 'planned_installation_date': 'Planned installation',
    'pending_installation_comment': 'Installation comment', 'installation_note': 'Installation note',
    'installation_report_submitted': 'Installation report', 'installation_readiness': 'Readiness',
    'installation_report_status': 'Installation report', 'readiness_status': 'Readiness',
    'serial_number': 'Serial number', 'hbg_salesperson': 'HB salesperson',
    'sub_county': 'Sub-county', 'complaint_description': 'Description',
    'commissioning_status': 'Commissioning', 'commissioned_on': 'Commissioned on',
    'commissioning_date': 'Commissioned on', 'pending_commissioning_comment': 'Commissioning comment',
    'commissioning_note': 'Commissioning note', 'cs_remarks': 'CS remarks',
    'priority': 'Priority', 'risk_level': 'Risk level', 'loan_at_risk': 'Loan at risk',
    'category_key': 'Category', 'branch_code': 'Branch', 'county_code': 'County',
    'sub_county_code': 'Sub-county', 'resolution_details': 'Resolution',
    'description': 'Description', 'resolution_comment': 'Comment',
}


def recorded_changes(before, after, *, labels=None):
    """Missing history is not a recorded blank; never infer it from live state."""
    if not isinstance(after, dict):
        return []
    before = before if isinstance(before, dict) else {}
    allowed = FIELD_LABELS if labels is None else labels
    return [
        {'field': key, 'label': allowed[key], 'old_value': before.get(key),
         'new_value': value, 'previous_recorded': key in before}
        for key, value in after.items()
        if key in allowed and (key not in before or before[key] != value)
        and not isinstance(value, (dict, list))
        and not isinstance(before.get(key), (dict, list))
    ]


def invoice_activity_changes(metadata):
    changes = (metadata or {}).get('changes', {})
    if not isinstance(changes, dict):
        return []
    before = {key: values['before'] for key, values in changes.items()
              if isinstance(values, dict) and 'before' in values}
    after = {key: values['after'] for key, values in changes.items()
             if isinstance(values, dict) and 'after' in values}
    return recorded_changes(before, after)
