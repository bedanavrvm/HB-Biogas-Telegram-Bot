"""Reviewed, catalogue-first seed contracts for the operational Main LAF set.

The PDFs deliberately remain outside Git.  This module binds each reviewed
source file to an exact digest and builds unpublished global catalogue
templates; it never publishes visual coordinates or changes product policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from django.db import models, transaction

from core.models import (
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationDocumentProductEligibility,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    Product,
)
from core.services.generic_jawabu_laf_seed import (
    EVIDENCE_REQUIREMENTS as GENERIC_EVIDENCE,
    EXTERNAL_LOANS_STRUCTURE,
    FIELD_SPECS as GENERIC_FIELDS,
    PLEDGED_ASSETS_STRUCTURE,
    SIGNER_RULES as GENERIC_SIGNERS,
)
from core.services.invoice_finance_origination_seed import (
    FIELD_SPECS as INVOICE_FIELDS,
    SIGNER_RULES as INVOICE_SIGNERS,
)
from core.services.origination_fields import _field_schema_item, normalize_choice_options
from core.services.origination_templates import (
    initial_template_configuration,
    upload_template_record,
    validate_template_pdf,
)
from core.services.product_catalog import active_product_version


class MainLafSeedError(ValueError):
    """Stable, staff-safe Main-LAF seed failure."""


def _field(
    key: str,
    label: str,
    data_type: str,
    section: str,
    *,
    required: bool = False,
    category: str = 'Application',
    source: str = OriginationDataField.SOURCE_USER_INPUT,
    sensitivity: str = OriginationDataField.SENSITIVITY_PII,
    aliases: Iterable[str] = (),
    options: Iterable[tuple[str, str]] = (),
    validation: dict[str, Any] | None = None,
    structure: dict[str, Any] | None = None,
    width: str = 'half',
    reporting: str = OriginationDataField.REPORT_UNAVAILABLE,
    help_text: str = '',
) -> dict[str, Any]:
    return {
        'key': key,
        'label': label,
        'type': data_type,
        'section': section,
        'required': required,
        'category': category,
        'source': source,
        'sensitivity': sensitivity,
        'aliases': list(aliases),
        'options': [{'code': code, 'label': option_label} for code, option_label in options],
        'validation': validation or {},
        'structure': structure or {},
        'width': width,
        'reporting': reporting,
        'help_text': help_text,
    }


def _clone(spec: dict[str, Any], section: str, *, required: bool | None = None) -> dict[str, Any]:
    cloned = json.loads(json.dumps(spec))
    cloned['section'] = section
    if required is not None:
        cloned['required'] = required
    cloned.setdefault('help_text', '')
    return cloned


def _generic(*keys: str, section: str, required: set[str] | None = None) -> tuple[dict[str, Any], ...]:
    by_key = {item['key']: item for item in GENERIC_FIELDS}
    required = required or set()
    return tuple(_clone(by_key[key], section, required=True if key in required else None) for key in keys)


APPLICANT_CORE = (
    'applicant_first_name', 'applicant_middle_name', 'applicant_surname',
    'applicant_id_number', 'applicant_dob', 'applicant_email',
    'applicant_marital_status', 'applicant_phone', 'applicant_other_phone',
    'applicant_postal_address', 'applicant_postal_code', 'applicant_town',
    'applicant_residence_address', 'applicant_housing_tenure',
    'employer_business_address',
)


GUARANTOR_ONE = tuple(
    item['key'] for item in GENERIC_FIELDS if item['key'].startswith('guarantor_1_')
)
GUARANTOR_TWO = tuple(
    item['key'] for item in GENERIC_FIELDS if item['key'].startswith('guarantor_2_')
)


SME_COLLATERAL_STRUCTURE = {
    'min_items': 1,
    'max_items': 6,
    'columns': [
        {'key': 'description', 'label': 'Description', 'type': 'text', 'required': True,
         'validation': {'max_length': 240}},
        {'key': 'year_of_manufacture', 'label': 'Year of manufacture', 'type': 'number',
         'required': False, 'validation': {'min': 1900, 'max': 2200}},
        {'key': 'serial_number', 'label': 'Serial number', 'type': 'text', 'required': False,
         'validation': {'max_length': 120}},
        {'key': 'current_value', 'label': 'Current value', 'type': 'money', 'required': True,
         'validation': {'min': '0'}},
    ],
}

OTHER_INCOME_STRUCTURE = {
    'min_items': 0,
    'max_items': 6,
    'columns': [
        {'key': 'source', 'label': 'Income source', 'type': 'text', 'required': True,
         'validation': {'max_length': 160}},
        {'key': 'amount', 'label': 'Monthly amount', 'type': 'money', 'required': True,
         'validation': {'min': '0'}},
    ],
}


def _signer(
    role: str, label: str, *, required: bool = True,
    identity_fields: dict[str, str] | None = None,
    prefix: str | None = None, stamp: bool = False,
) -> dict[str, Any]:
    prefix = prefix or role
    slots = [
        {'key': f'{prefix}_signature', 'label': f'{label} signature', 'type': 'signature',
         'required': required},
        {'key': f'{prefix}_date_signed', 'label': f'{label} signing date', 'type': 'date_signed',
         'required': required},
    ]
    if stamp:
        slots.append({'key': f'{prefix}_stamp', 'label': f'{label} stamp', 'type': 'stamp',
                      'required': required})
    return {
        'role': role, 'label': label, 'required': required,
        'identity_fields': identity_fields or {}, 'slots': slots,
    }


BORROWER_SPLIT = _signer(
    'borrower', 'Borrower', identity_fields={
        'name': 'applicant_first_name', 'phone': 'applicant_phone',
        'national_id': 'applicant_id_number',
    }, prefix='borrower',
)


LIPA_FIELDS = (
    *_generic(*APPLICANT_CORE, section='applicant_details', required={
        'applicant_first_name', 'applicant_surname', 'applicant_id_number',
        'applicant_phone', 'applicant_residence_address',
    }),
    _field('spouse_name', 'Spouse Name', 'text', 'applicant_details'),
    _field('spouse_phone', 'Spouse Phone', 'phone', 'applicant_details'),
    _field('next_of_kin_name', 'Next of Kin Name', 'text', 'applicant_details', required=True),
    _field('next_of_kin_phone', 'Next of Kin Phone', 'phone', 'applicant_details', required=True),
    _field('livestock_cow_count', 'Number of Cows', 'number', 'applicant_details', required=True,
           sensitivity='internal', validation={'min': 0}),
    _field('land_ownership_type', 'Land Ownership', 'choice', 'applicant_details', required=True,
           options=(('own', 'Own'), ('family', 'Family'), ('leased', 'Leased')),
           reporting='dimension'),
    _field('applicant_sublocation', 'Sub-location', 'text', 'applicant_details'),
    _field('applicant_sub_county', 'Sub-county', 'sub_county', 'applicant_details', required=True),
    _field('applicant_county', 'County', 'county', 'applicant_details', required=True),
    _field('applicant_residence_years', 'Years at Current Residence', 'number',
           'applicant_details', validation={'min': 0}),
    _field('biogas_system_size', 'Biogas System Size', 'text', 'biogas_details', required=True,
           sensitivity='internal'),
    _field('biogas_source', 'Biogas System Source', 'text', 'biogas_details', required=True,
           sensitivity='internal'),
    _field('biogas_brand', 'Biogas Brand', 'text', 'biogas_details', required=True,
           sensitivity='internal'),
    _field('financing_plan', 'Financing Plan', 'text', 'affordability', required=True,
           sensitivity='financial'),
    _field('deposit_capacity_amount', 'Deposit Capacity', 'money', 'affordability', required=True,
           sensitivity='financial', validation={'min': '5000'}),
    _field('comfortable_monthly_repayment_amount', 'Comfortable Monthly Repayment', 'money',
           'affordability', required=True, sensitivity='financial', validation={'min': '0'}),
    _field('income_source_employment', 'Income from Employment', 'boolean', 'affordability'),
    _field('income_source_business', 'Income from Business', 'boolean', 'affordability'),
    _field('income_source_farming', 'Income from Farming', 'boolean', 'affordability'),
    _field('income_source_other', 'Other Income Source', 'text', 'affordability'),
    _field('monthly_income', 'Monthly Income', 'money', 'affordability', required=True,
           sensitivity='financial', validation={'min': '0'}, reporting='metric'),
    _field('monthly_expenses', 'Average Monthly Expenses', 'money', 'affordability', required=True,
           sensitivity='financial', validation={'min': '0'}, reporting='metric'),
    _field('homebiogas_deposit_amount', 'HomeBiogas Deposit', 'money', 'affordability',
           sensitivity='financial', validation={'min': '0'}),
    _field('jbl_deposit_amount', 'JBL Deposit', 'money', 'affordability',
           sensitivity='financial', validation={'min': '0'}),
    _field('preferred_repayment_date', 'Preferred Repayment Date', 'date', 'affordability'),
    _field('crb_loans_current', 'CRB Loans Current', 'boolean', 'borrowing_details', required=True,
           sensitivity='financial'),
    _field('active_external_loan', 'Has Active External Loan', 'boolean', 'borrowing_details',
           required=True, sensitivity='financial'),
    _field('external_loans', 'Other Active Loans', 'repeating_group', 'borrowing_details',
           structure=EXTERNAL_LOANS_STRUCTURE, width='full', sensitivity='financial'),
    _field('pledged_assets', 'Security Asset Schedule', 'repeating_group', 'security_details',
           required=True, structure=PLEDGED_ASSETS_STRUCTURE, width='full', sensitivity='financial'),
    *_generic(*GUARANTOR_ONE, section='guarantor_details'),
)


SUPPLIER_FIELDS = (
    _field('supplier_name', 'Supplier Name', 'text', 'supplier_details', required=True,
           sensitivity='internal'),
    _field('supplier_payment_details', 'Supplier Payment Details', 'textarea', 'supplier_details',
           required=True, sensitivity='restricted', width='full'),
    _field('supplier_contact_name', 'Supplier Representative Name', 'text', 'supplier_details',
           required=True),
    _field('supplier_contact_phone', 'Supplier Representative OTP Phone', 'phone',
           'supplier_details', required=True,
           help_text='Used for verified signing and not printed when the source LAF has no phone box.'),
    _field('supplier_code', 'Supplier Code', 'text', 'supplier_details', sensitivity='internal'),
)


MICRO_ASSET_FIELDS = (
    *_generic(*APPLICANT_CORE, section='applicant_details', required={
        'applicant_first_name', 'applicant_surname', 'applicant_id_number', 'applicant_phone',
        'applicant_residence_address',
    }),
    *SUPPLIER_FIELDS,
    _field('asset_item_purchased', 'Item Purchased', 'text', 'supplier_details', required=True,
           sensitivity='internal'),
    _field('asset_purchase_price', 'Purchase Price', 'money', 'supplier_details', required=True,
           sensitivity='financial', validation={'min': '0'}),
    _field('asset_use_type', 'Asset Use', 'choice', 'supplier_details', required=True,
           options=(('home', 'Home use'), ('commercial', 'Commercial use')), reporting='dimension'),
    _field('loan_purpose', 'Loan Purpose', 'text', 'loan_details', required=True,
           sensitivity='internal', width='full'),
    _field('pledged_assets', 'Security Pledged', 'repeating_group', 'security_details',
           required=True, structure=PLEDGED_ASSETS_STRUCTURE, width='full', sensitivity='financial'),
    *_generic(*GUARANTOR_ONE, section='guarantor_details'),
    *_generic(*GUARANTOR_TWO, section='guarantor_details'),
)


WATER_TANK_FIELDS = (
    *_generic(*APPLICANT_CORE, section='applicant_details', required={
        'applicant_first_name', 'applicant_surname', 'applicant_id_number', 'applicant_phone',
        'applicant_residence_address',
    }),
    _field('water_tank_capacity_litres', 'Water Tank Capacity (Litres)', 'number',
           'water_tank_details', required=True, sensitivity='internal', validation={'min': 1}),
    _field('water_tank_source', 'Water Tank Source', 'text', 'water_tank_details', required=True,
           sensitivity='internal'),
    _field('water_tank_brand', 'Water Tank Brand', 'text', 'water_tank_details', required=True,
           sensitivity='internal'),
    *SUPPLIER_FIELDS,
    _field('loan_purpose', 'Loan Purpose', 'text', 'loan_details', required=True,
           sensitivity='internal', width='full'),
    _field('pledged_assets', 'Security Pledged', 'repeating_group', 'security_details',
           required=True, structure=PLEDGED_ASSETS_STRUCTURE, width='full', sensitivity='financial'),
    *_generic(*GUARANTOR_ONE, section='guarantor_details'),
)


SME_FIELDS = (
    *_generic(*APPLICANT_CORE, section='applicant_details', required={
        'applicant_first_name', 'applicant_surname', 'applicant_id_number', 'applicant_phone',
        'applicant_residence_address',
    }),
    _field('business_name', 'Business Name', 'text', 'business_details', required=True,
           sensitivity='internal', reporting='dimension'),
    _field('business_type', 'Business Type', 'text', 'business_details', required=True,
           sensitivity='internal'),
    _field('business_license_number', 'Business Licence Number', 'text', 'business_details',
           sensitivity='restricted'),
    _field('business_location', 'Business Physical Location', 'text', 'business_details',
           required=True),
    _field('business_location_block', 'Business Block', 'text', 'business_details'),
    _field('business_premises_tenure', 'Business Premises Tenure', 'choice', 'business_details',
           required=True, options=(('owned', 'Owned'), ('rented', 'Rented')), reporting='dimension'),
    _field('business_monthly_rent', 'Business Monthly Rent', 'money', 'business_details',
           sensitivity='financial', validation={'min': '0'}),
    _field('business_years_at_current_location', 'Years at Current Business Location', 'number',
           'business_details', validation={'min': 0}),
    _field('business_previous_location', 'Previous Business Location', 'text', 'business_details'),
    _field('business_employee_count', 'Total Employees', 'number', 'business_details',
           validation={'min': 0}),
    _field('business_full_time_employee_count', 'Full-time Employees', 'number',
           'business_details', validation={'min': 0}),
    _field('business_casual_employee_count', 'Casual Employees', 'number', 'business_details',
           validation={'min': 0}),
    _field('employer_name', 'Employer Name', 'text', 'employment_details'),
    _field('employment_start_date', 'Employed Since', 'date', 'employment_details'),
    _field('employment_position', 'Employment Position', 'text', 'employment_details'),
    _field('employment_type', 'Employment Type', 'choice', 'employment_details',
           options=(('permanent', 'Permanent'), ('contract', 'Contract'))),
    _field('employment_contract_end_date', 'Contract End Date', 'date', 'employment_details'),
    _field('gross_monthly_salary', 'Gross Monthly Salary', 'money', 'employment_details',
           sensitivity='financial', validation={'min': '0'}),
    _field('net_monthly_salary', 'Net Monthly Salary', 'money', 'employment_details',
           sensitivity='financial', validation={'min': '0'}),
    _field('comfortable_monthly_repayment_amount', 'Comfortable Monthly Repayment', 'money',
           'loan_details', required=True, sensitivity='financial', validation={'min': '0'}),
    _field('loan_purpose', 'Loan Purpose', 'text', 'loan_details', required=True,
           sensitivity='internal', width='full'),
    _field('project_cost', 'Project Cost', 'money', 'loan_details', required=True,
           sensitivity='financial', validation={'min': '0'}),
    _field('own_contribution', 'Own Contribution', 'money', 'loan_details', required=True,
           sensitivity='financial', validation={'min': '0'}),
    _field('external_loans', 'Outstanding Loan History', 'repeating_group', 'loan_details',
           structure=EXTERNAL_LOANS_STRUCTURE, width='full', sensitivity='financial'),
    _field('business_sales_amount', 'Business Sales', 'money', 'business_appraisal',
           required=True, sensitivity='financial', validation={'min': '0'}),
    _field('business_other_income_lines', 'Other Business Income', 'repeating_group',
           'business_appraisal', structure=OTHER_INCOME_STRUCTURE, width='full',
           sensitivity='financial'),
    _field('business_purchases_amount', 'Business Purchases', 'money', 'business_appraisal',
           required=True, sensitivity='financial', validation={'min': '0'}),
    _field('business_rent_expense', 'Business Rent Expense', 'money', 'business_appraisal',
           sensitivity='financial', validation={'min': '0'}),
    _field('business_payroll_expense', 'Salaries and Wages', 'money', 'business_appraisal',
           sensitivity='financial', validation={'min': '0'}),
    _field('business_utilities_expense', 'Business Utilities', 'money', 'business_appraisal',
           sensitivity='financial', validation={'min': '0'}),
    _field('business_other_expense', 'Other Business Expenses', 'money', 'business_appraisal',
           sensitivity='financial', validation={'min': '0'}),
    _field('business_total_income', 'Total Business Income', 'money', 'business_appraisal',
           source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial', reporting='metric'),
    _field('business_total_expenses', 'Total Business Expenses', 'money', 'business_appraisal',
           source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial', reporting='metric'),
    _field('business_net_surplus', 'Business Net Surplus or Deficit', 'money',
           'business_appraisal', source=OriginationDataField.SOURCE_SYSTEM,
           sensitivity='financial', reporting='metric'),
    _field('household_spouse_net_salary', 'Spouse Net Salary', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_pension_income', 'Household Pension Income', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_other_income', 'Other Household Income', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_rent_expense', 'Household Rent', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_school_fees_expense', 'School Fees', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_transport_expense', 'Transport', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_utilities_expense', 'Household Utilities', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_food_expense', 'Food', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_other_loan_repayment', 'Other Loan Repayment', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_medical_expense', 'Medical', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_entertainment_expense', 'Entertainment', 'money', 'household_budget',
           sensitivity='financial', validation={'min': '0'}),
    _field('household_total_income', 'Total Household Income', 'money', 'household_budget',
           source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial', reporting='metric'),
    _field('household_total_expenses', 'Total Household Expenses', 'money', 'household_budget',
           source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial', reporting='metric'),
    _field('household_net_surplus', 'Household Net Surplus or Deficit', 'money',
           'household_budget', source=OriginationDataField.SOURCE_SYSTEM,
           sensitivity='financial', reporting='metric'),
    _field('manufactured_collateral_assets', 'Security and Collateral', 'repeating_group',
           'security_details', required=True, structure=SME_COLLATERAL_STRUCTURE, width='full',
           sensitivity='financial'),
    _field('referee_name', 'Referee Name', 'text', 'referee_details', required=True),
    _field('referee_address', 'Referee Address', 'text', 'referee_details'),
    _field('referee_email', 'Referee Email', 'text', 'referee_details'),
    _field('referee_phone', 'Referee Phone', 'phone', 'referee_details', required=True),
    _field('referee_relationship', 'Referee Relationship', 'text', 'referee_details', required=True),
    *_generic(*GUARANTOR_ONE, section='guarantor_details'),
    *_generic(*GUARANTOR_TWO, section='guarantor_details'),
    _field('referral_source', 'Referral Source', 'choice', 'referral_details', options=(
        ('jawabu_staff', 'Jawabu staff'), ('advertisement', 'Advertisement'),
        ('social_media', 'Social media'), ('marketing_contact', 'Marketing contact'),
        ('friend_family', 'Friend or family'), ('print_media', 'Magazine or newspaper'),
        ('agent', 'Agent'),
    )),
    _field('referral_agent_name', 'Referral Agent Name', 'text', 'referral_details'),
    _field('referral_agent_id_number', 'Referral Agent National ID', 'national_id',
           'referral_details'),
)


COMMON_APPROVAL_SIGNERS = (
    _signer('bro_1', 'Business Relationship Officer 1'),
    _signer('bro_2', 'Business Relationship Officer 2', required=False),
    _signer('branch_manager', 'Branch Manager'),
)

SUPPLIER_SIGNER = _signer(
    'supplier_representative', 'Supplier Representative', identity_fields={
        'name': 'supplier_contact_name', 'phone': 'supplier_contact_phone',
    }, prefix='supplier_representative', stamp=True,
)


def _evidence(key: str, label: str, *, required: bool = True,
              required_when: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        'key': key, 'label': label, 'description': f'Upload {label.lower()}.',
        'type': 'document', 'workflow': 'loan_origination', 'enforcement_stage': 'review',
        'required': required,
        'validation': {'required_when': required_when} if required_when else {},
    }


@dataclass(frozen=True)
class MainLafDefinition:
    key: str
    filename: str
    sha256: str
    byte_size: int
    page_count: int
    document_type: str
    name: str
    product_code: str | None
    sections: tuple[tuple[str, str, str], ...]
    fields: tuple[dict[str, Any], ...]
    signers: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...] = ()
    review_notes: tuple[str, ...] = ()


DEFINITIONS = (
    MainLafDefinition(
        'invoice_finance', 'INVOICE FINANCE.pdf',
        '730e5cc0b2a112bc2c07fb408b0de9455cb5bf669471d138fb0172224d3d0947',
        110684, 1, 'invoice_finance_laf', 'Invoice Finance LAF', 'invoice_finance',
        (
            ('applicant_details', 'Applicant Details', 'Applicant identity and contact details.'),
            ('business_details', 'Business Details', 'Business and tax identity.'),
            ('banking_details', 'Banking Details', 'Account used for disbursement.'),
            ('invoice_details', 'Invoice Details', 'Surrendered invoice and requested advance.'),
            ('signer_details', 'Signer Details', 'Invoice payer and internal approvers.'),
            ('acknowledgement', 'Acknowledgement', 'Borrower receipt acknowledgement.'),
        ), tuple({
            **item,
            'source': (
                OriginationDataField.SOURCE_SYSTEM
                if item['key'] in {
                    'application_date', 'approval_amount', 'acknowledgement_amount',
                    'bro_1_name', 'management_approver_name',
                }
                else item.get('source', OriginationDataField.SOURCE_USER_INPUT)
            ),
            'help_text': item.get('help_text', ''),
        } for item in INVOICE_FIELDS) + (
            _field(
                'is_first_origination_application', 'First Origination Application', 'boolean',
                'applicant_details', source=OriginationDataField.SOURCE_SYSTEM,
                sensitivity='internal',
                help_text='Derived from prior non-cancelled applications for the matched national ID.',
            ),
        ),
        tuple(
            {**item, 'identity_fields': {}}
            if item['role'] in {'bro_1', 'management_approver'}
            else json.loads(json.dumps(item))
            for item in INVOICE_SIGNERS
        ),
        (
            _evidence('invoice_copy', 'Copy of the surrendered invoice'),
            _evidence('applicant_id_copy', 'Copy of the applicant national ID', required=False,
                      required_when={'operator': 'first_origination_application'}),
        ),
    ),
    MainLafDefinition(
        'generic', 'JBL LAF Generic.pdf',
        '5e7d264c0cf3e4264e9ab768fd89a4fd1dab131eedd733cce439ce11c6e345f1',
        845590, 2, 'jawabu_generic_laf', 'Generic Jawabu LAF', None,
        (
            ('applicant_details', 'Applicant Details', 'Applicant and household details.'),
            ('enterprise_details', 'Enterprise Details', 'Enterprise finances and location.'),
            ('loan_details', 'Loan Details', 'Facility request and other borrowing.'),
            ('security_details', 'Security Details', 'Assets pledged for the facility.'),
            ('guarantor_details', 'Guarantor Details', 'Guarantor identities.'),
        ), tuple({**item, 'help_text': item.get('help_text', '')} for item in GENERIC_FIELDS),
        tuple(json.loads(json.dumps(item)) for item in GENERIC_SIGNERS),
        tuple(json.loads(json.dumps(item)) for item in GENERIC_EVIDENCE),
        ('Residence and business sketch boxes are evidence/calibration areas, not text fields.',),
    ),
    MainLafDefinition(
        'lipa_mdogo_mdogo', 'Jawabu LAF-Lipa Mdogo Mdogo NEW (2).pdf',
        '5e5ca308bd9e5f3d44f15af1a200e28bd3cf0b688312a24390835dcfd26f9b13',
        810471, 2, 'lipa_mdogo_mdogo_laf', 'Lipa Mdogo Mdogo Biogas LAF', 'biogas',
        (
            ('applicant_details', 'Applicant Details', 'Applicant, household and location details.'),
            ('biogas_details', 'Biogas Details', 'Selected biogas system.'),
            ('affordability', 'Affordability', 'Income, expenses and deposits.'),
            ('borrowing_details', 'Borrowing Details', 'CRB and active external borrowing.'),
            ('security_details', 'Security Details', 'Security asset schedule.'),
            ('guarantor_details', 'Guarantor Details', 'Guarantor identity.'),
        ), LIPA_FIELDS,
        (BORROWER_SPLIT, _signer('guarantor_1', 'Guarantor 1', identity_fields={
            'name': 'guarantor_1_name', 'phone': 'guarantor_1_phone',
            'national_id': 'guarantor_1_id_number',
        }), _signer('bro_1', 'Business Relationship Officer'),
         _signer('credit_analyst', 'Back Office or Credit Analyst'),
         _signer('branch_manager', 'Branch Manager')),
        (
            _evidence('customer_photo', 'Customer photograph'),
            _evidence('livestock_photo', 'Photograph of the cows'),
            _evidence('mpesa_statement', 'M-Pesa statement'),
            _evidence('applicant_id_copy', 'Copy of the applicant national ID'),
            _evidence('residence_location_pin', 'Residence location pin'),
        ),
        ('HomeBiogas and Jawabu recommendation narratives are controlled workflow outcomes, not officer inputs.',),
    ),
    MainLafDefinition(
        'micro_asset', 'Jawabu LAF-Micro Asset Loan.pdf',
        'da128ee33a9052531976f2cb15756dd161dc44f747daa111527184a58bc756eb',
        2492019, 2, 'micro_asset_laf', 'Micro Asset Loan LAF', 'micro_asset',
        (
            ('applicant_details', 'Applicant Details', 'Applicant and residence details.'),
            ('supplier_details', 'Supplier Details', 'Asset supplier and payment details.'),
            ('loan_details', 'Loan Details', 'Facility and purpose.'),
            ('security_details', 'Security Details', 'Security pledged.'),
            ('guarantor_details', 'Guarantor Details', 'Guarantor identities.'),
        ), MICRO_ASSET_FIELDS,
        (BORROWER_SPLIT, _signer('guarantor_1', 'Guarantor 1', identity_fields={
            'name': 'guarantor_1_name', 'phone': 'guarantor_1_phone',
            'national_id': 'guarantor_1_id_number',
        }), _signer('guarantor_2', 'Guarantor 2', required=False, identity_fields={
            'name': 'guarantor_2_name', 'phone': 'guarantor_2_phone',
            'national_id': 'guarantor_2_id_number',
        }), SUPPLIER_SIGNER, *COMMON_APPROVAL_SIGNERS),
        (_evidence('residence_sketch', 'Residence sketch or location evidence', required=False),),
        ('The residual tank-delivery sketch label is a source-template defect and has no canonical field.',),
    ),
    MainLafDefinition(
        'water_tank', 'Jawabu LAF-Water Tank.pdf',
        '0ed3bb9de5f0635b99f62356e23bed704913424c5b4c44c80cc79ff37283bae8',
        307524, 2, 'water_tank_laf', 'Water Tank LAF', 'water_tank',
        (
            ('applicant_details', 'Applicant Details', 'Applicant and residence details.'),
            ('water_tank_details', 'Water Tank Details', 'Tank capacity, source and brand.'),
            ('supplier_details', 'Supplier Details', 'Tank supplier and payment details.'),
            ('loan_details', 'Loan Details', 'Facility and purpose.'),
            ('security_details', 'Security Details', 'Security pledged.'),
            ('guarantor_details', 'Guarantor Details', 'Guarantor identity.'),
        ), WATER_TANK_FIELDS,
        (BORROWER_SPLIT, _signer('guarantor_1', 'Guarantor 1', identity_fields={
            'name': 'guarantor_1_name', 'phone': 'guarantor_1_phone',
            'national_id': 'guarantor_1_id_number',
        }), SUPPLIER_SIGNER, *COMMON_APPROVAL_SIGNERS),
        (
            _evidence('residence_sketch', 'Residence sketch or location evidence', required=False),
            _evidence('delivery_location_sketch', 'Tank delivery location evidence', required=False),
        ),
        ('Both printed tank-size boxes use water_tank_capacity_litres.',),
    ),
    MainLafDefinition(
        'sme_logbook', 'SME-LOGBOOK LAF.pdf',
        '4e4a95c814e1ac64058e39510658f86f3bbad770b5ab5961a0f782167a697416',
        5534460, 4, 'sme_logbook_laf', 'SME-LOGBOOK LAF', 'logbook',
        (
            ('applicant_details', 'Applicant Details', 'Applicant and residence details.'),
            ('business_details', 'Business Details', 'Business premises and employees.'),
            ('employment_details', 'Employment Details', 'Applicant employment and salary.'),
            ('loan_details', 'Loan Details', 'Facility request and borrowing.'),
            ('business_appraisal', 'Business Appraisal', 'Profit and loss inputs.'),
            ('household_budget', 'Household Budget', 'Household income and expenses.'),
            ('security_details', 'Security Details', 'Manufactured collateral assets.'),
            ('referee_details', 'Referee Details', 'Next-of-kin referee.'),
            ('guarantor_details', 'Guarantor Details', 'Guarantor identities.'),
            ('referral_details', 'Referral Details', 'Marketing referral source.'),
        ), SME_FIELDS,
        (BORROWER_SPLIT, _signer('guarantor_1', 'Guarantor 1', identity_fields={
            'name': 'guarantor_1_name', 'phone': 'guarantor_1_phone',
            'national_id': 'guarantor_1_id_number',
        }), _signer('guarantor_2', 'Guarantor 2', identity_fields={
            'name': 'guarantor_2_name', 'phone': 'guarantor_2_phone',
            'national_id': 'guarantor_2_id_number',
        }), _signer('bro_1', 'Business Relationship Officer'),
         _signer('bro_2', 'Senior Business Relationship Officer'),
         _signer('branch_manager', 'Manager'),
         _signer('management_approver', 'Chief Executive Officer')),
        (
            _evidence('mpesa_statement_12_months', 'Twelve-month M-Pesa statement'),
            _evidence('bank_statement_6_months', 'Six-month bank statement'),
            _evidence('payslips_2_months', 'Two-month payslips', required=False,
                      required_when={'field': 'employment_type', 'operator': 'truthy'}),
            _evidence('guarantor_1_id_copy', 'Guarantor 1 national ID copy'),
            _evidence('guarantor_2_id_copy', 'Guarantor 2 national ID copy'),
        ),
        ('Overlay reference_number over the pre-printed No. 3096 before publication.',
         'Business and household totals and net surplus are derived, not officer inputs.'),
    ),
)

DEFINITIONS_BY_KEY = {item.key: item for item in DEFINITIONS}


def source_path(definition: MainLafDefinition, laf_root: str | Path) -> Path:
    root = Path(laf_root)
    direct = root / definition.filename
    nested = root / 'MAIN' / definition.filename
    return direct if direct.is_file() else nested


def _source_plan(definition: MainLafDefinition, laf_root: str | Path) -> dict[str, Any]:
    path = source_path(definition, laf_root)
    if not path.is_file():
        raise MainLafSeedError(f'{definition.name} PDF was not found: {path}.')
    data = path.read_bytes()
    digest, page_count = validate_template_pdf(data)
    if digest != definition.sha256 or len(data) != definition.byte_size or page_count != definition.page_count:
        raise MainLafSeedError(
            f'{definition.name} source does not match the reviewed contract '
            f'(expected {definition.sha256[:12]}..., {definition.byte_size} bytes, '
            f'{definition.page_count} pages; received {digest[:12]}..., {len(data)} bytes, '
            f'{page_count} pages). Re-analyse and update the reviewed seed before applying it.'
        )
    return {'path': path, 'pdf_data': data, 'sha256': digest, 'page_count': page_count}


def _product(definition: MainLafDefinition) -> Product | None:
    if not definition.product_code:
        return None
    product = Product.objects.filter(code__iexact=definition.product_code).first()
    if not product:
        raise MainLafSeedError(
            f'Global product {definition.product_code!r} required by {definition.name} does not exist.'
        )
    if not product.active:
        raise MainLafSeedError(f'Global product {definition.product_code!r} is inactive.')
    if not active_product_version(product):
        draft_exists = product.versions.filter(status='draft').exists()
        if not draft_exists:
            raise MainLafSeedError(
                f'Global product {definition.product_code!r} has no published or draft ProductVersion.'
            )
    return product


def _validate_field_contract(definition: MainLafDefinition) -> None:
    seen: dict[str, dict[str, Any]] = {}
    for spec in definition.fields:
        previous = seen.get(spec['key'])
        if previous and (
            previous['type'] != spec['type']
            or (spec['type'] == 'repeating_group' and previous.get('structure') != spec.get('structure'))
        ):
            raise MainLafSeedError(f'{definition.name} defines conflicting field {spec["key"]}.')
        seen[spec['key']] = spec
        existing = OriginationDataField.objects.filter(key=spec['key']).first()
        if not existing:
            continue
        if existing.preferred_field_id:
            raise MainLafSeedError(f'{spec["key"]} is a retired duplicate.')
        if existing.data_type != spec['type']:
            raise MainLafSeedError(
                f'{spec["key"]} uses {existing.data_type}, not reviewed type {spec["type"]}.'
            )
        if spec['type'] == 'repeating_group' and (existing.structure_schema or {}) != (spec.get('structure') or {}):
            raise MainLafSeedError(f'{spec["key"]} has an incompatible repeatable structure.')


def preflight_seed(definition: MainLafDefinition, *, laf_root: str | Path) -> dict[str, Any]:
    source = _source_plan(definition, laf_root)
    product = _product(definition)
    _validate_field_contract(definition)
    candidates = OriginationDocumentTemplate.objects.filter(
        document_type=definition.document_type, source_sha256=definition.sha256,
        product_definition__isnull=True,
    ).order_by('-version')
    return {**source, 'definition': definition, 'product': product, 'candidates': list(candidates)}


def _ensure_fields(definition: MainLafDefinition, *, actor) -> dict[str, OriginationDataField]:
    resolved: dict[str, OriginationDataField] = {}
    for spec in definition.fields:
        field = OriginationDataField.objects.filter(key=spec['key']).first()
        if not field:
            options = normalize_choice_options(spec.get('options') or []) if spec['type'] == 'choice' else []
            field = OriginationDataField.objects.create(
                key=spec['key'], label=spec['label'], aliases=spec.get('aliases') or [],
                category=spec.get('category') or 'Application', data_type=spec['type'],
                source_type=spec.get('source') or OriginationDataField.SOURCE_USER_INPUT,
                sensitivity=spec.get('sensitivity') or OriginationDataField.SENSITIVITY_PII,
                masking_policy=(
                    OriginationDataField.MASK_NONE
                    if spec.get('sensitivity') in {'public', 'internal'}
                    else OriginationDataField.MASK_PARTIAL
                ),
                reporting_use=spec.get('reporting') or OriginationDataField.REPORT_UNAVAILABLE,
                export_allowed=False, help_text=spec.get('help_text') or '',
                choice_options=options, structure_schema=spec.get('structure') or {},
                active=True, created_by=actor,
            )
            OriginationDataFieldEvent.objects.create(
                data_field=field, action='main_laf_seed_created', actor=actor,
                metadata={'laf': definition.key, 'key': field.key},
            )
        else:
            changed: list[str] = []
            aliases = list(dict.fromkeys([*(field.aliases or []), *(spec.get('aliases') or [])]))
            if aliases != field.aliases:
                field.aliases = aliases
                changed.append('aliases')
            if field.data_type == OriginationDataField.TYPE_CHOICE:
                desired = normalize_choice_options(spec.get('options') or [])
                existing_codes = {str(item.get('code') or '') for item in field.choice_options or []}
                merged = [*(field.choice_options or []), *(item for item in desired if item['code'] not in existing_codes)]
                if merged != field.choice_options:
                    field.choice_options = merged
                    changed.append('choice_options')
            if changed:
                field.save(update_fields=[*changed, 'updated_at'])
                OriginationDataFieldEvent.objects.create(
                    data_field=field, action='main_laf_seed_extended', actor=actor,
                    metadata={'laf': definition.key, 'changed_fields': changed},
                )
        resolved[field.key] = field
    from core.services.origination_commercial_terms import ensure_commercial_catalogue
    resolved.update(ensure_commercial_catalogue(actor=actor))
    return resolved


def build_form_schema(
    definition: MainLafDefinition, fields: dict[str, OriginationDataField],
) -> dict[str, Any]:
    schema = {
        '_revision': 1,
        'identity_contract': 'applicant_v1',
        'sections': [
            {'key': key, 'label': label, 'help_text': help_text}
            for key, label, help_text in definition.sections
        ],
        'fields': [],
        'evidence_requirements': json.loads(json.dumps(definition.evidence)),
        'seed_review_notes': list(definition.review_notes),
    }
    for spec in definition.fields:
        if spec.get('source') == OriginationDataField.SOURCE_SYSTEM:
            continue
        item = _field_schema_item(fields[spec['key']], {
            'section_key': spec['section'], 'required': spec.get('required', False),
            'width': spec.get('width') or 'half', 'help_text': spec.get('help_text') or '',
            'validation': spec.get('validation') or {}, 'options': spec.get('options') or [],
            'structure': spec.get('structure') or {},
        })
        if spec['type'] == 'repeating_group':
            item['repeatable_layout'] = {'column_widths': [50, 50]}
        schema['fields'].append(item)
    from core.services.origination_commercial_terms import merge_commercial_contract
    return merge_commercial_contract(schema, fields=fields)


def _contract_matches(
    template: OriginationDocumentTemplate, *, definition: MainLafDefinition,
    schema: dict[str, Any], product: Product | None,
) -> bool:
    actual_products = set(template.product_eligibilities.values_list('product_id', flat=True))
    expected_products = {product.pk} if product else set()
    return (
        template.product_definition_id is None
        and template.document_role == template.ROLE_PRIMARY
        and template.document_key == 'primary'
        and template.form_schema == schema
        and template.signer_rules == list(definition.signers)
        and actual_products == expected_products
    )


@transaction.atomic
def _template_for(
    plan: dict[str, Any], *, schema: dict[str, Any], actor,
) -> tuple[OriginationDocumentTemplate, bool]:
    definition: MainLafDefinition = plan['definition']
    product: Product | None = plan['product']
    for candidate in plan['candidates']:
        if _contract_matches(candidate, definition=definition, schema=schema, product=product):
            return candidate, False
    version = (
        OriginationDocumentTemplate.objects.filter(document_type=definition.document_type)
        .aggregate(models.Max('version'))['version__max'] or 0
    ) + 1
    config = initial_template_configuration(None, form_schema=schema)
    config.update({'document_type': definition.document_type, 'version': version})
    template = OriginationDocumentTemplate(
        product_definition=None, document_key='primary',
        document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
        officer_selectable=False, default_selected=False, display_order=0,
        document_type=definition.document_type, name=definition.name, version=version,
        source_filename=definition.filename, source_sha256=definition.sha256,
        source_byte_size=definition.byte_size, page_count=definition.page_count,
        placement_config=config, form_schema=json.loads(json.dumps(schema)),
        signer_rules=json.loads(json.dumps(definition.signers)), created_by=actor,
    )
    template.full_clean()
    template.save()
    if product:
        OriginationDocumentProductEligibility.objects.create(
            template=template, product=product, created_by=actor,
        )
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='main_laf_seed_created', actor=actor,
        metadata={
            'seed_key': definition.key, 'sha256': definition.sha256,
            'page_count': definition.page_count,
            'eligible_product_codes': [definition.product_code] if definition.product_code else [],
        },
    )
    return template, True


def apply_seed(definition: MainLafDefinition, *, laf_root: str | Path, actor) -> dict[str, Any]:
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise MainLafSeedError('The seed actor must be an active Django Superuser.')
    plan = preflight_seed(definition, laf_root=laf_root)
    with transaction.atomic():
        fields = _ensure_fields(definition, actor=actor)
        schema = build_form_schema(definition, fields)
        from core.services.loan_origination import validate_product_form_contract
        validate_product_form_contract(schema, list(definition.signers))
        template, created = _template_for(plan, schema=schema, actor=actor)
    if created or template.status == template.STATUS_UPLOAD_FAILED or not template.drive_file_id:
        template = upload_template_record(template, pdf_data=plan['pdf_data'], actor=actor)
    if template.status == template.STATUS_UPLOAD_FAILED:
        raise MainLafSeedError(template.upload_error or f'{definition.name} could not be uploaded.')
    return {
        'definition': definition, 'template': template, 'fields': fields,
        'product': plan['product'], 'created_template': created,
    }


def selected_definitions(key: str) -> tuple[MainLafDefinition, ...]:
    if key == 'all':
        return DEFINITIONS
    try:
        return (DEFINITIONS_BY_KEY[key],)
    except KeyError as exc:
        raise MainLafSeedError(f'Unknown Main LAF seed {key!r}.') from exc
