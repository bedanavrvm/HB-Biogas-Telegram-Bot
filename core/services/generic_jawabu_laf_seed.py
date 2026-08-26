"""Reviewed reusable contract for the generic two-page Jawabu LAF.

The source PDF is supplied at command runtime and remains outside Git.  This
module creates a global primary-template family; assigning it to products is a
separate audited Admin action.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.db import models, transaction

from core.models import (
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
)
from core.services.origination_fields import _field_schema_item, normalize_choice_options
from core.services.origination_templates import (
    initial_template_configuration,
    upload_template_record,
    validate_template_pdf,
)


class GenericJawabuLafSeedError(ValueError):
    """Stable, staff-safe seed error."""


DOCUMENT_TYPE = 'jawabu_generic_laf'
DOCUMENT_NAME = 'Generic Jawabu LAF'

SECTIONS = (
    ('applicant_details', 'Applicant Details', 'Applicant identity, household and contact details.'),
    ('enterprise_details', 'Enterprise Details', 'Business location and declared monthly finances.'),
    ('loan_details', 'Loan Details', 'Requested facility and existing borrowing.'),
    ('security_details', 'Security Details', 'Assets pledged for this facility.'),
    ('guarantor_details', 'Guarantor Details', 'Required first guarantor and optional second guarantor.'),
)


def _field(
    key: str, label: str, data_type: str, section: str, *, required: bool,
    category: str, source: str = OriginationDataField.SOURCE_USER_INPUT,
    sensitivity: str = OriginationDataField.SENSITIVITY_PII,
    aliases: tuple[str, ...] = (), options: tuple[tuple[str, str], ...] = (),
    validation: dict[str, Any] | None = None,
    structure: dict[str, Any] | None = None, width: str = 'half',
    reporting: str = OriginationDataField.REPORT_UNAVAILABLE,
) -> dict[str, Any]:
    return {
        'key': key, 'label': label, 'type': data_type, 'section': section,
        'required': required, 'category': category, 'source': source,
        'sensitivity': sensitivity, 'aliases': list(aliases),
        'options': [{'code': code, 'label': option_label} for code, option_label in options],
        'validation': validation or {}, 'structure': structure or {},
        'width': width, 'reporting': reporting,
    }


EXTERNAL_LOANS_STRUCTURE = {
    'min_items': 0,
    'max_items': 3,
    'columns': [
        {'key': 'institution_name', 'label': 'Institution', 'type': 'text', 'required': True, 'validation': {'max_length': 180}},
        {'key': 'amount_advanced', 'label': 'Amount advanced', 'type': 'money', 'required': True, 'validation': {'min': '0'}},
        {'key': 'date_advanced', 'label': 'Date advanced', 'type': 'date', 'required': True, 'validation': {}},
        {'key': 'repayment_period', 'label': 'Repayment period', 'type': 'text', 'required': True, 'validation': {'max_length': 80}},
        {'key': 'outstanding_amount', 'label': 'Outstanding amount', 'type': 'money', 'required': True, 'validation': {'min': '0'}},
    ],
}

PLEDGED_ASSETS_STRUCTURE = {
    'min_items': 1,
    'max_items': 4,
    'columns': [
        {'key': 'description', 'label': 'Description', 'type': 'text', 'required': True, 'validation': {'max_length': 240}},
        {'key': 'year_of_purchase', 'label': 'Year of purchase', 'type': 'number', 'required': True, 'validation': {'min': 1900, 'max': 2200}},
        {'key': 'serial_number', 'label': 'Serial number', 'type': 'text', 'required': False, 'validation': {'max_length': 120}},
        {'key': 'current_value', 'label': 'Current value', 'type': 'money', 'required': True, 'validation': {'min': '0'}},
    ],
}

FIELD_SPECS = (
    _field('number_of_weeks', 'Number of Weeks', 'text', 'applicant_details', required=True, category='Application', sensitivity='internal'),
    _field('applicant_first_name', 'Applicant First Name', 'text', 'applicant_details', required=True, category='Applicant'),
    _field('applicant_middle_name', 'Applicant Middle Name', 'text', 'applicant_details', required=False, category='Applicant'),
    _field('applicant_surname', 'Applicant Surname', 'text', 'applicant_details', required=True, category='Applicant'),
    _field('applicant_id_number', 'Applicant National ID', 'national_id', 'applicant_details', required=True, category='Applicant', aliases=('ID Number', 'National ID'), reporting='filter'),
    _field('applicant_dob', 'Applicant Date of Birth', 'date', 'applicant_details', required=True, category='Applicant'),
    _field('applicant_email', 'Applicant Email', 'text', 'applicant_details', required=False, category='Applicant'),
    _field('applicant_marital_status', 'Marital Status', 'choice', 'applicant_details', required=True, category='Applicant', options=(('single', 'Single'), ('married', 'Married'), ('divorced', 'Divorced'), ('widowed', 'Widowed')), reporting='dimension'),
    _field('applicant_number_of_children', 'Number of Children', 'number', 'applicant_details', required=False, category='Applicant', sensitivity='internal', validation={'min': 0}),
    _field('applicant_number_of_other_dependants', 'Number of Other Dependants', 'number', 'applicant_details', required=False, category='Applicant', sensitivity='internal', validation={'min': 0}),
    _field('applicant_phone', 'Applicant Mobile Phone', 'phone', 'applicant_details', required=True, category='Applicant', aliases=('Mobile', 'Telephone'), reporting='filter'),
    _field('applicant_other_phone', 'Applicant Alternative Phone', 'phone', 'applicant_details', required=False, category='Applicant'),
    _field('applicant_postal_address', 'Applicant Postal Address', 'text', 'applicant_details', required=False, category='Applicant'),
    _field('applicant_postal_code', 'Applicant Postal Code', 'text', 'applicant_details', required=False, category='Applicant'),
    _field('applicant_town', 'Applicant Town', 'text', 'applicant_details', required=False, category='Applicant'),
    _field('applicant_next_of_kin', 'Spouse or Next of Kin Name', 'text', 'applicant_details', required=True, category='Applicant'),
    _field('applicant_next_of_kin_id', 'Spouse or Next of Kin National ID', 'national_id', 'applicant_details', required=False, category='Applicant'),
    _field('applicant_next_of_kin_phone', 'Spouse or Next of Kin Phone', 'phone', 'applicant_details', required=True, category='Applicant'),
    _field('applicant_residence_address', 'Present Residence Address', 'text', 'applicant_details', required=True, category='Applicant', width='full'),
    _field('applicant_housing_tenure', 'Residence Tenure', 'choice', 'applicant_details', required=True, category='Applicant', options=(('rented', 'Rented'), ('owned', 'Owned'), ('mortgage', 'Mortgage')), reporting='dimension'),
    _field('employer_business_address', 'Employer or Business Address', 'text', 'applicant_details', required=True, category='Business', width='full'),
    _field('business_type', 'Type of Business', 'text', 'enterprise_details', required=True, category='Business', sensitivity='internal'),
    _field('business_location', 'Business Location', 'text', 'enterprise_details', required=True, category='Business'),
    _field('monthly_income', 'Monthly Income', 'money', 'enterprise_details', required=True, category='Financial', sensitivity='financial', reporting='metric'),
    _field('monthly_expenses', 'Monthly Business Expenses', 'money', 'enterprise_details', required=True, category='Financial', sensitivity='financial', reporting='metric'),
    _field('enterprise_net_income', 'Enterprise Net Income', 'money', 'enterprise_details', required=True, category='Financial', sensitivity='financial', aliases=('First Net Income',), reporting='metric'),
    _field('monthly_household_expenses', 'Monthly Household Expenses', 'money', 'enterprise_details', required=True, category='Financial', sensitivity='financial', reporting='metric'),
    _field('household_net_income', 'Household Net Income', 'money', 'enterprise_details', required=True, category='Financial', sensitivity='financial', aliases=('Second Net Income',), reporting='metric'),
    _field('loan_amount', 'Amount Applied For', 'money', 'loan_details', required=True, category='Facility', sensitivity='financial', reporting='metric'),
    _field('own_contribution', 'Own Contribution', 'money', 'loan_details', required=True, category='Facility', sensitivity='financial'),
    _field('project_cost', 'Project Cost', 'money', 'loan_details', required=True, category='Facility', sensitivity='financial'),
    _field('loan_purpose', 'Loan Purpose', 'text', 'loan_details', required=True, category='Facility', sensitivity='internal', width='full'),
    _field('repayment_period', 'Repayment Period', 'text', 'loan_details', required=True, category='Facility', sensitivity='financial'),
    _field('daily_weekly_repayment_amount', 'Daily or Weekly Repayment Amount', 'money', 'loan_details', required=True, category='Facility', sensitivity='financial'),
    _field('external_loans', 'Loans in Other Financial Institutions', 'repeating_group', 'loan_details', required=False, category='Facility', sensitivity='financial', structure=EXTERNAL_LOANS_STRUCTURE, width='full'),
    _field('pledged_assets', 'Security Pledged', 'repeating_group', 'security_details', required=True, category='Security', sensitivity='financial', structure=PLEDGED_ASSETS_STRUCTURE, width='full'),
    _field('guarantor_1_name', 'Guarantor 1 Name', 'text', 'guarantor_details', required=True, category='Guarantor'),
    _field('guarantor_1_id_number', 'Guarantor 1 National ID', 'national_id', 'guarantor_details', required=True, category='Guarantor'),
    _field('guarantor_1_phone', 'Guarantor 1 Phone', 'phone', 'guarantor_details', required=True, category='Guarantor'),
    _field('guarantor_1_relationship', 'Guarantor 1 Relationship', 'text', 'guarantor_details', required=True, category='Guarantor'),
    _field('guarantor_1_residence_location', 'Guarantor 1 Residence Location', 'text', 'guarantor_details', required=True, category='Guarantor'),
    _field('guarantor_1_business_location', 'Guarantor 1 Business Location', 'text', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_1_employer', 'Guarantor 1 Employer', 'text', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_1_years_known', 'Guarantor 1 Years Known', 'text', 'guarantor_details', required=True, category='Guarantor', sensitivity='internal'),
    _field('guarantor_2_name', 'Guarantor 2 Name', 'text', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_2_id_number', 'Guarantor 2 National ID', 'national_id', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_2_phone', 'Guarantor 2 Phone', 'phone', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_2_relationship', 'Guarantor 2 Relationship', 'text', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_2_residence_location', 'Guarantor 2 Residence Location', 'text', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_2_business_location', 'Guarantor 2 Business Location', 'text', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_2_employer', 'Guarantor 2 Employer', 'text', 'guarantor_details', required=False, category='Guarantor'),
    _field('guarantor_2_years_known', 'Guarantor 2 Years Known', 'number', 'guarantor_details', required=False, category='Guarantor', sensitivity='internal', validation={'min': 0}),
    _field('product_code', 'Product Code', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='internal'),
    _field('product_name', 'Product Name', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='internal'),
    _field('loan_product', 'Loan Product', 'choice', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='internal', options=(('jawabu_express', 'Jawabu Express'), ('jawabu_advantage', 'Jawabu Advantage'), ('jawabu_landlord', 'Jawabu Landlord'), ('jawabu_almasi', 'Jawabu Almasi'), ('other', 'Other'))),
    _field('loan_product_other', 'Other Loan Product', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='internal'),
    _field('borrower_full_name', 'Borrower Full Name', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM),
    _field('deponent_full_name', 'Deponent Full Name', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM),
    _field('acknowledgement_recipient_name', 'Acknowledgement Recipient Name', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM),
    _field('approval_amount', 'Approved Amount', 'money', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial'),
    _field('amount_advanced', 'Amount Advanced', 'money', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial'),
    _field('acknowledgement_amount', 'Acknowledgement Amount', 'money', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial'),
    _field('installment_amount', 'Installment Amount', 'money', 'loan_details', required=True, category='Commercial Terms', source=OriginationDataField.SOURCE_USER_INPUT, sensitivity='financial'),
    _field('interest_rate', 'Interest Rate', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial'),
    _field('repayment_frequency', 'Repayment Frequency', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial'),
    _field('penalty_rate', 'Penalty Rate', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='financial'),
    _field('bro_1_name', 'Business Relationship Officer 1 Name', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='internal'),
    _field('bro_2_name', 'Business Relationship Officer 2 Name', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='internal'),
    _field('branch_manager_name', 'Branch Manager Name', 'text', 'loan_details', required=False, category='System', source=OriginationDataField.SOURCE_SYSTEM, sensitivity='internal'),
)

SIGNER_RULES = (
    {'role': 'borrower', 'label': 'Borrower', 'required': True, 'identity_fields': {'name': 'applicant_first_name', 'phone': 'applicant_phone', 'national_id': 'applicant_id_number'}, 'slots': [
        {'key': 'declaration_signature', 'label': 'Borrower declaration signature', 'type': 'signature', 'required': True},
        {'key': 'declaration_date_signed', 'label': 'Borrower declaration date', 'type': 'date_signed', 'required': True},
        {'key': 'loan_agreement_signature', 'label': 'Loan agreement signature', 'type': 'signature', 'required': True},
        {'key': 'loan_agreement_date_signed', 'label': 'Loan agreement date', 'type': 'date_signed', 'required': True},
        {'key': 'affidavit_signature', 'label': 'Affidavit signature', 'type': 'signature', 'required': True},
        {'key': 'acknowledgement_signature', 'label': 'Acknowledgement signature', 'type': 'signature', 'required': True},
        {'key': 'acknowledgement_date_signed', 'label': 'Acknowledgement date', 'type': 'date_signed', 'required': True},
    ]},
    {'role': 'guarantor_1', 'label': 'Guarantor 1', 'required': True, 'identity_fields': {'name': 'guarantor_1_name', 'phone': 'guarantor_1_phone', 'national_id': 'guarantor_1_id_number'}, 'slots': [
        {'key': 'guarantor_1_signature', 'label': 'Guarantor 1 signature', 'type': 'signature', 'required': True},
    ]},
    {'role': 'guarantor_2', 'label': 'Guarantor 2', 'required': False, 'identity_fields': {'name': 'guarantor_2_name', 'phone': 'guarantor_2_phone', 'national_id': 'guarantor_2_id_number'}, 'slots': [
        {'key': 'guarantor_2_signature', 'label': 'Guarantor 2 signature', 'type': 'signature', 'required': False},
    ]},
    {'role': 'bro_1', 'label': 'Business Relationship Officer 1', 'required': True, 'identity_fields': {}, 'slots': [
        {'key': 'bro_1_approval_signature', 'label': 'BRO 1 approval signature', 'type': 'signature', 'required': True},
        {'key': 'bro_1_approval_date_signed', 'label': 'BRO 1 approval date', 'type': 'date_signed', 'required': True},
    ]},
    {'role': 'bro_2', 'label': 'Business Relationship Officer 2', 'required': False, 'identity_fields': {}, 'slots': [
        {'key': 'bro_2_approval_signature', 'label': 'BRO 2 approval signature', 'type': 'signature', 'required': False},
        {'key': 'bro_2_approval_date_signed', 'label': 'BRO 2 approval date', 'type': 'date_signed', 'required': False},
    ]},
    {'role': 'branch_manager', 'label': 'Branch Manager', 'required': True, 'identity_fields': {}, 'slots': [
        {'key': 'branch_manager_approval_signature', 'label': 'Branch Manager approval signature', 'type': 'signature', 'required': True},
        {'key': 'branch_manager_approval_date_signed', 'label': 'Branch Manager approval date', 'type': 'date_signed', 'required': True},
    ]},
)

EVIDENCE_REQUIREMENTS = (
    {'key': 'guarantor_1_id_copy', 'label': 'Guarantor 1 ID Copy', 'description': 'Upload a clear copy of Guarantor 1 national ID.', 'type': 'document', 'workflow': 'loan_origination', 'enforcement_stage': 'review', 'required': True, 'validation': {}},
    {'key': 'guarantor_2_id_copy', 'label': 'Guarantor 2 ID Copy', 'description': 'Required when a second guarantor is provided.', 'type': 'document', 'workflow': 'loan_origination', 'enforcement_stage': 'review', 'required': False, 'validation': {'required_when': {'field': 'guarantor_2_name', 'operator': 'truthy'}}},
)


def preflight(*, pdf_path: str | Path) -> dict[str, Any]:
    path = Path(pdf_path)
    if not path.is_file():
        raise GenericJawabuLafSeedError(f'Generic Jawabu LAF PDF was not found: {path}.')
    pdf_data = path.read_bytes()
    digest, page_count = validate_template_pdf(pdf_data)
    incompatible = []
    for spec in FIELD_SPECS:
        existing = OriginationDataField.objects.filter(key=spec['key']).first()
        if not existing:
            continue
        if existing.data_type != spec['type']:
            incompatible.append(f"{spec['key']} ({existing.data_type} != {spec['type']})")
        elif spec['type'] == 'repeating_group' and (existing.structure_schema or {}) != spec['structure']:
            incompatible.append(f"{spec['key']} (repeatable structure differs)")
    if incompatible:
        raise GenericJawabuLafSeedError('Canonical field conflicts: ' + '; '.join(incompatible))
    existing = OriginationDocumentTemplate.objects.filter(
        document_type=DOCUMENT_TYPE, source_sha256=digest,
    ).order_by('-version').first()
    return {'path': path, 'pdf_data': pdf_data, 'pdf_sha256': digest, 'page_count': page_count, 'existing': existing}


def validate_catalogue_contract() -> None:
    """Reject incompatible canonical fields before an Admin upload writes anything."""

    incompatible = []
    for spec in FIELD_SPECS:
        existing = OriginationDataField.objects.filter(key=spec['key']).first()
        if not existing:
            continue
        if existing.preferred_field_id:
            incompatible.append(f"{spec['key']} is a retired duplicate")
        elif existing.data_type != spec['type']:
            incompatible.append(f"{spec['key']} ({existing.data_type} != {spec['type']})")
        elif spec['type'] == 'repeating_group' and (existing.structure_schema or {}) != spec['structure']:
            incompatible.append(f"{spec['key']} (repeatable structure differs)")
    if incompatible:
        raise GenericJawabuLafSeedError('Canonical field conflicts: ' + '; '.join(incompatible))


def _upsert_fields(*, actor) -> dict[str, OriginationDataField]:
    resolved = {}
    for spec in FIELD_SPECS:
        field = OriginationDataField.objects.filter(key=spec['key']).first()
        created = field is None
        if created:
            field = OriginationDataField(key=spec['key'], data_type=spec['type'], created_by=actor)
        if field.preferred_field_id:
            raise GenericJawabuLafSeedError(f"{spec['key']} is a retired duplicate; resolve it before seeding.")
        desired_options = normalize_choice_options(spec['options']) if spec['type'] == 'choice' else []
        if spec['type'] == 'choice' and not created:
            existing_options = [
                dict(item) for item in (field.choice_options or []) if isinstance(item, dict)
            ]
            existing_codes = {str(item.get('code') or '') for item in existing_options}
            desired_options = existing_options + [
                item for item in desired_options if item['code'] not in existing_codes
            ]
        before = {
            'label': field.label, 'aliases': field.aliases, 'category': field.category,
            'source_type': field.source_type, 'sensitivity': field.sensitivity,
            'masking_policy': field.masking_policy, 'reporting_use': field.reporting_use,
            'choice_options': field.choice_options, 'structure_schema': field.structure_schema,
            'active': field.active,
        }
        field.label = spec['label']
        field.aliases = list(dict.fromkeys([*(field.aliases or []), *spec['aliases']]))
        field.category = spec['category']
        field.source_type = spec['source']
        field.sensitivity = spec['sensitivity']
        field.masking_policy = 'partial' if spec['sensitivity'] in {'pii', 'financial', 'restricted'} else 'none'
        field.reporting_use = spec['reporting']
        field.export_allowed = False
        field.choice_options = desired_options
        field.structure_schema = spec['structure']
        field.active = True
        changed = [key for key in before if before[key] != getattr(field, key)]
        if created or changed:
            field.save()
            OriginationDataFieldEvent.objects.create(
                data_field=field,
                action='generic_jawabu_laf_seed_created' if created else 'generic_jawabu_laf_seed_updated',
                actor=actor, metadata={'key': field.key, 'changed_fields': changed},
            )
        resolved[field.key] = field
    return resolved


@transaction.atomic
def ensure_catalogue(*, actor) -> dict[str, OriginationDataField]:
    """Create/update the reviewed canonical catalogue for Admin and command flows."""

    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise GenericJawabuLafSeedError('The catalogue actor must be an active Django Superuser.')
    validate_catalogue_contract()
    fields = _upsert_fields(actor=actor)
    from core.services.origination_commercial_terms import ensure_commercial_catalogue
    fields.update(ensure_commercial_catalogue(actor=actor))
    return fields


def build_form_schema(fields: dict[str, OriginationDataField]) -> dict[str, Any]:
    schema = {
        '_revision': 1,
        'identity_contract': 'applicant_v1',
        'sections': [{'key': key, 'label': label, 'help_text': help_text} for key, label, help_text in SECTIONS],
        'fields': [],
        'evidence_requirements': json.loads(json.dumps(EVIDENCE_REQUIREMENTS)),
    }
    for spec in FIELD_SPECS:
        if spec['source'] == OriginationDataField.SOURCE_SYSTEM:
            continue
        item = _field_schema_item(fields[spec['key']], {
            'section_key': spec['section'], 'required': spec['required'],
            'width': spec['width'], 'validation': spec['validation'],
            'options': spec['options'], 'structure': spec['structure'],
        })
        if spec['type'] == 'repeating_group':
            item['repeatable_layout'] = {'column_widths': [50, 50]}
        schema['fields'].append(item)
    from core.services.origination_commercial_terms import merge_commercial_contract
    return merge_commercial_contract(schema, fields=fields)


@transaction.atomic
def _template_for(*, plan: dict[str, Any], schema: dict[str, Any], actor) -> tuple[OriginationDocumentTemplate, bool]:
    existing = plan['existing']
    if existing:
        if existing.status in {existing.STATUS_READY, existing.STATUS_UPLOAD_FAILED}:
            desired_schema = json.loads(json.dumps(schema))
            desired_signers = json.loads(json.dumps(SIGNER_RULES))
            changed = []
            if existing.form_schema != desired_schema:
                existing.form_schema = desired_schema
                changed.append('form_schema')
            if existing.signer_rules != desired_signers:
                existing.signer_rules = desired_signers
                changed.append('signer_rules')
            if changed:
                existing.save(update_fields=[*changed, 'updated_at'])
                OriginationDocumentTemplateEvent.objects.create(
                    template=existing, action='generic_jawabu_laf_contract_updated',
                    actor=actor, metadata={'changed_fields': changed},
                )
        return existing, False
    version = (
        OriginationDocumentTemplate.objects.filter(document_type=DOCUMENT_TYPE)
        .aggregate(models.Max('version'))['version__max'] or 0
    ) + 1
    config = initial_template_configuration(None, form_schema=schema)
    config.update({'document_type': DOCUMENT_TYPE, 'version': version})
    template = OriginationDocumentTemplate(
        product_definition=None, document_key='primary',
        document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
        display_order=0, document_type=DOCUMENT_TYPE, name=DOCUMENT_NAME,
        version=version, source_filename=plan['path'].name,
        source_sha256=plan['pdf_sha256'], source_byte_size=len(plan['pdf_data']),
        page_count=plan['page_count'], placement_config=config,
        form_schema=json.loads(json.dumps(schema)),
        signer_rules=json.loads(json.dumps(SIGNER_RULES)), created_by=actor,
    )
    template.full_clean()
    template.save()
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='created', actor=actor,
        metadata={'origin': 'generic_jawabu_laf_seed', 'sha256': plan['pdf_sha256'], 'page_count': plan['page_count']},
    )
    return template, True


def apply_seed(*, pdf_path: str | Path, actor) -> dict[str, Any]:
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise GenericJawabuLafSeedError('The seed actor must be an active Django Superuser.')
    plan = preflight(pdf_path=pdf_path)
    with transaction.atomic():
        fields = ensure_catalogue(actor=actor)
        schema = build_form_schema(fields)
        from core.services.loan_origination import validate_product_form_contract
        validate_product_form_contract(schema, list(SIGNER_RULES))
        template, created = _template_for(plan=plan, schema=schema, actor=actor)
    if created or template.status == template.STATUS_UPLOAD_FAILED or not template.drive_file_id:
        template = upload_template_record(template, pdf_data=plan['pdf_data'], actor=actor)
    if template.status == template.STATUS_UPLOAD_FAILED:
        raise GenericJawabuLafSeedError(template.upload_error or 'The generic LAF could not be uploaded to Drive.')
    return {'template': template, 'fields': fields, 'created_template': created, 'page_count': plan['page_count']}
