"""Reviewed Invoice Finance LAF catalogue and draft-product setup.

The source PDF is intentionally supplied at command runtime and is never part
of the repository.  This module owns only the reviewed semantic contract; PDF
coordinates remain a human calibration step in Django Admin.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from django.db import models, transaction

from core.models import (
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    Product,
    ProductVersion,
)
from core.services.origination_fields import (
    _field_schema_item,
    correct_draft_data_field_type,
    data_field_type_change_blockers,
    normalize_choice_options,
)
from core.services.origination_templates import (
    initial_template_configuration,
    upload_template_record,
    validate_template_pdf,
)
from core.services.product_catalog import active_product_version


class InvoiceFinanceSeedError(ValueError):
    """Safe setup error suitable for a management-command response."""


SECTIONS = (
    ('applicant_details', 'Applicant Details', 'Applicant identity and contact details.'),
    ('business_details', 'Business Details', 'Business identity and operating details.'),
    ('banking_details', 'Banking Details', 'Account to receive the approved facility.'),
    ('invoice_details', 'Invoice Details', 'Surrendered invoice and requested advance.'),
    ('signer_details', 'Signer Details', 'Representatives and internal approvers.'),
    ('acknowledgement', 'Acknowledgement', 'Applicant receipt acknowledgement.'),
)


def _field(
    key: str, label: str, data_type: str, section: str, *, required: bool,
    create: bool = True, category: str = 'Application', aliases: tuple[str, ...] = (),
    sensitivity: str = OriginationDataField.SENSITIVITY_PII,
    masking: str = OriginationDataField.MASK_PARTIAL,
    reporting: str = OriginationDataField.REPORT_UNAVAILABLE,
    source: str = OriginationDataField.SOURCE_USER_INPUT,
    options: tuple[tuple[str, str], ...] = (), validation: dict[str, Any] | None = None,
    width: str = 'half', help_text: str = '',
) -> dict[str, Any]:
    return {
        'key': key, 'label': label, 'type': data_type, 'section': section,
        'required': required, 'create': create, 'category': category,
        'aliases': list(aliases), 'sensitivity': sensitivity, 'masking': masking,
        'reporting': reporting, 'source': source,
        'options': [{'code': code, 'label': option_label} for code, option_label in options],
        'validation': validation or {}, 'width': width, 'help_text': help_text,
    }


FIELD_SPECS = (
    _field('applicant_full_name', 'Applicant Full Name', 'text', 'applicant_details', required=True,
           aliases=('Full Names', 'Applicant Name', 'Borrower Name')),
    _field('application_date', 'Application Date', 'date', 'applicant_details', required=True,
           create=False, sensitivity='internal', masking='none', source='system'),
    _field('applicant_id_number', 'Applicant National ID', 'national_id', 'applicant_details', required=True,
           create=False, aliases=('ID', 'ID Number', 'National ID')),
    _field('applicant_nationality', 'Applicant Nationality', 'text', 'applicant_details', required=True),
    _field('applicant_gender', 'Applicant Gender', 'choice', 'applicant_details', required=True,
           options=(('male', 'Male'), ('female', 'Female')), reporting='dimension'),
    _field('applicant_postal_address', 'Applicant Postal Address', 'text', 'applicant_details', required=False,
           create=False),
    _field('applicant_email', 'Applicant Email', 'text', 'applicant_details', required=False,
           create=False),
    _field('applicant_phone', 'Applicant Telephone', 'phone', 'applicant_details', required=True,
           create=False, aliases=('Telephone', 'Phone Number')),
    _field('applicant_residence_address', 'Applicant Residence Location', 'text', 'applicant_details', required=True,
           create=False, aliases=('Residence Location',)),
    _field('applicant_housing_tenure', 'Housing Tenure', 'choice', 'applicant_details', required=True,
           options=(('rented', 'Rented'), ('owned', 'Owned')), reporting='dimension'),
    _field('business_location', 'Business Location', 'text', 'business_details', required=True,
           aliases=('Office Location',), sensitivity='internal', masking='none'),
    _field('business_phone', 'Business Telephone', 'phone', 'business_details', required=False,
           aliases=('Office Telephone',)),
    _field('business_name', 'Business Name', 'text', 'business_details', required=True,
           aliases=('Company or Individual Represented',), sensitivity='internal', masking='none', reporting='dimension'),
    _field('business_registration_number', 'Business Registration Number', 'text', 'business_details', required=False,
           sensitivity='restricted', masking='partial'),
    _field('business_tax_pin', 'Business Tax PIN', 'text', 'business_details', required=True,
           aliases=('Business PIN', 'PIN'), sensitivity='restricted', masking='partial'),
    _field('disbursement_bank_name', 'Disbursement Bank Name', 'text', 'banking_details', required=True,
           sensitivity='restricted', masking='partial'),
    _field('disbursement_bank_branch', 'Disbursement Bank Branch', 'text', 'banking_details', required=True,
           sensitivity='restricted', masking='partial'),
    _field('disbursement_bank_account_name', 'Disbursement Account Name', 'text', 'banking_details', required=True,
           sensitivity='restricted', masking='partial'),
    _field('disbursement_bank_account_number', 'Disbursement Account Number', 'text', 'banking_details', required=True,
           sensitivity='restricted', masking='partial'),
    _field('invoice_face_value', 'Invoice Face Value', 'money', 'invoice_details', required=True,
           sensitivity='financial', masking='partial', reporting='metric'),
    _field('invoice_due_date', 'Invoice Due Date', 'date', 'invoice_details', required=True,
           sensitivity='financial', masking='partial', reporting='filter'),
    _field('loan_amount', 'Loan Amount Requested', 'money', 'invoice_details', required=True,
           create=False, sensitivity='financial', masking='partial', reporting='metric'),
    _field('invoice_advance_rate_percent', 'Invoice Advance Rate (%)', 'number', 'invoice_details', required=True,
           sensitivity='financial', masking='partial', reporting='metric', validation={'min': 0, 'max': 100}),
    _field('approval_amount', 'Approved Facility Amount', 'money', 'invoice_details', required=True,
           create=False, sensitivity='financial', masking='partial', reporting='metric'),
    _field('invoice_payer_representative_name', 'Invoice Payer Representative Name', 'text', 'signer_details', required=True),
    _field('invoice_payer_representative_phone', 'Invoice Payer Representative OTP Phone', 'phone', 'signer_details', required=True,
           help_text='Used to send the representative their remote signing link and OTP. This value is not printed on the LAF.'),
    _field('bro_1_name', 'Business Relationship Officer Name', 'text', 'signer_details', required=True,
           create=False, sensitivity='internal', masking='none'),
    _field('management_approver_name', 'Management Approver Name', 'text', 'signer_details', required=True,
           sensitivity='internal', masking='none'),
    _field('acknowledgement_amount', 'Acknowledged Amount Received', 'money', 'acknowledgement', required=True,
           create=False, sensitivity='financial', masking='partial', reporting='metric'),
)


SIGNER_RULES = (
    {
        'role': 'borrower', 'label': 'Borrower', 'required': True,
        'identity_fields': {
            'name': 'applicant_full_name', 'phone': 'applicant_phone',
            'national_id': 'applicant_id_number',
        },
        'slots': [
            {'key': 'declaration_signature', 'label': 'Applicant declaration signature', 'type': 'signature', 'required': True},
            {'key': 'declaration_date_signed', 'label': 'Applicant declaration date', 'type': 'date_signed', 'required': True},
            {'key': 'acknowledgement_signature', 'label': 'Applicant acknowledgement signature', 'type': 'signature', 'required': True},
            {'key': 'acknowledgement_date_signed', 'label': 'Applicant acknowledgement date', 'type': 'date_signed', 'required': True},
        ],
    },
    {
        'role': 'invoice_payer_representative', 'label': 'Invoice Payer Representative', 'required': True,
        'identity_fields': {
            'name': 'invoice_payer_representative_name',
            'phone': 'invoice_payer_representative_phone',
        },
        'slots': [
            {'key': 'invoice_payer_approval_signature', 'label': 'Invoice payer approval signature', 'type': 'signature', 'required': True},
            {'key': 'invoice_payer_approval_date_signed', 'label': 'Invoice payer approval date', 'type': 'date_signed', 'required': True},
        ],
    },
    {
        'role': 'bro_1', 'label': 'Business Relationship Officer', 'required': True,
        'identity_fields': {'name': 'bro_1_name'},
        'slots': [
            {'key': 'bro_approval_signature', 'label': 'BRO approval signature', 'type': 'signature', 'required': True},
            {'key': 'bro_approval_date_signed', 'label': 'BRO approval date', 'type': 'date_signed', 'required': True},
        ],
    },
    {
        'role': 'management_approver', 'label': 'Branch Manager or Management Approver', 'required': True,
        'identity_fields': {'name': 'management_approver_name'},
        'slots': [
            {'key': 'management_approval_signature', 'label': 'Management approval signature', 'type': 'signature', 'required': True},
            {'key': 'management_approval_date_signed', 'label': 'Management approval date', 'type': 'date_signed', 'required': True},
        ],
    },
)


def _product_version(product: Product) -> ProductVersion:
    current = active_product_version(product)
    if current:
        return current
    draft = product.versions.filter(status=ProductVersion.STATUS_DRAFT).order_by('-version').first()
    if draft:
        return draft
    raise InvoiceFinanceSeedError(
        'Invoice Finance has no current published terms or editable draft terms. '
        'Create its commercial ProductVersion in Django Admin first.'
    )


def preflight(*, product_code: str, pdf_path: str | Path) -> dict[str, Any]:
    product = Product.objects.filter(code__iexact=str(product_code or '').strip()).first()
    if not product:
        raise InvoiceFinanceSeedError(
            f'Global product {product_code!r} does not exist. Create its commercial terms first.'
        )
    version = _product_version(product)
    path = Path(pdf_path)
    if not path.is_file():
        raise InvoiceFinanceSeedError(f'Invoice Finance PDF was not found: {path}.')
    pdf_data = path.read_bytes()
    digest, page_count = validate_template_pdf(pdf_data)
    missing = [spec['key'] for spec in FIELD_SPECS if not spec['create'] and not OriginationDataField.objects.filter(key=spec['key']).exists()]
    if missing:
        raise InvoiceFinanceSeedError(
            'Required shared canonical fields are missing: ' + ', '.join(missing) + '. '
            'Create or restore these shared fields before replacing the product schema.'
        )
    incompatible = []
    for spec in FIELD_SPECS:
        existing = OriginationDataField.objects.filter(key=spec['key']).first()
        if not existing or existing.data_type == spec['type']:
            continue
        blockers = data_field_type_change_blockers(existing)
        if blockers:
            incompatible.append(
                f"{spec['key']} ({existing.data_type} -> {spec['type']}; "
                f"blocked by {', '.join(blockers)})"
            )
    if incompatible:
        raise InvoiceFinanceSeedError('Canonical type conflicts: ' + '; '.join(incompatible))
    draft = OriginationProductDefinition.objects.filter(
        product_key=product.code, lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
    ).order_by('-version').first()
    published = OriginationProductDefinition.objects.filter(
        product_key=product.code, lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
    ).order_by('-version').first()
    return {
        'product': product, 'product_version': version, 'draft': draft,
        'published': published, 'pdf_data': pdf_data, 'pdf_sha256': digest,
        'page_count': page_count,
    }


def _upsert_fields(*, actor) -> dict[str, OriginationDataField]:
    resolved = {}
    for spec in FIELD_SPECS:
        field = OriginationDataField.objects.filter(key=spec['key']).first()
        created = False
        if not field:
            if not spec['create']:
                raise InvoiceFinanceSeedError(f"Required shared field {spec['key']} is missing.")
            field = OriginationDataField(key=spec['key'], data_type=spec['type'], created_by=actor)
            created = True
        elif field.data_type != spec['type']:
            correct_draft_data_field_type(
                data_field=field, new_type=spec['type'], choice_options=spec['options'],
                structure_schema={}, actor=actor,
            )
            field.refresh_from_db()
        if field.preferred_field_id:
            raise InvoiceFinanceSeedError(
                f"{spec['key']} is a retired duplicate. Resolve its canonical replacement before seeding."
            )
        desired_options = normalize_choice_options(spec['options']) if spec['type'] == 'choice' else []
        if field.data_type == 'choice' and not created:
            desired_by_code = {item['code']: item for item in desired_options}
            desired_options = [
                desired_by_code.get(str(item.get('code') or ''), {**item, 'active': False})
                for item in (field.choice_options or []) if isinstance(item, dict)
            ] + [
                item for item in desired_options
                if item['code'] not in {str(old.get('code') or '') for old in (field.choice_options or []) if isinstance(old, dict)}
            ]
        before = {
            'label': field.label, 'aliases': field.aliases, 'category': field.category,
            'source_type': field.source_type, 'sensitivity': field.sensitivity,
            'masking_policy': field.masking_policy, 'reporting_use': field.reporting_use,
            'export_allowed': field.export_allowed, 'help_text': field.help_text,
            'choice_options': field.choice_options, 'active': field.active,
        }
        field.label = spec['label']
        field.aliases = list(dict.fromkeys([*(field.aliases or []), *spec['aliases']]))
        field.category = spec['category']
        field.source_type = spec['source']
        field.sensitivity = spec['sensitivity']
        field.masking_policy = spec['masking']
        field.reporting_use = spec['reporting']
        field.export_allowed = False
        field.help_text = spec['help_text']
        field.choice_options = desired_options
        field.active = True
        changed_fields = [key for key in before if before[key] != getattr(field, key)]
        if created or changed_fields:
            field.save()
            OriginationDataFieldEvent.objects.create(
                data_field=field, action='invoice_finance_seed_created' if created else 'invoice_finance_seed_updated',
                actor=actor, metadata={'key': field.key, 'changed_fields': changed_fields},
            )
        resolved[field.key] = field
    return resolved


def _form_schema(fields: dict[str, OriginationDataField]) -> dict[str, Any]:
    schema = {
        '_revision': 1,
        'sections': [
            {'key': key, 'label': label, 'help_text': help_text}
            for key, label, help_text in SECTIONS
        ],
        'fields': [],
    }
    for spec in FIELD_SPECS:
        if spec['source'] == OriginationDataField.SOURCE_SYSTEM:
            continue
        schema['fields'].append(_field_schema_item(fields[spec['key']], {
            'section_key': spec['section'], 'required': spec['required'],
            'width': spec['width'], 'help_text': spec['help_text'],
            'validation': spec['validation'], 'options': spec['options'],
        }))
    from core.services.origination_commercial_terms import merge_commercial_contract
    return merge_commercial_contract(schema, fields=fields)


@transaction.atomic
def _replace_draft(*, plan: dict[str, Any], actor, schema: dict[str, Any]) -> OriginationProductDefinition:
    draft = plan['draft']
    if draft:
        draft = OriginationProductDefinition.objects.select_for_update().get(pk=draft.pk)
    elif plan['published']:
        from core.services.origination_templates import clone_product_version
        draft = clone_product_version(plan['published'], actor=actor)
    else:
        next_version = (
            OriginationProductDefinition.objects.filter(product_key=plan['product'].code)
            .aggregate(models.Max('version'))['version__max'] or 0
        ) + 1
        draft = OriginationProductDefinition.objects.create(
            product_version=plan['product_version'], product_key=plan['product'].code,
            name=plan['product'].name, version=next_version,
            form_schema={'_revision': 0, 'sections': [], 'fields': []}, signer_rules=[],
            document_type=plan['product'].code, document_template_version=next_version,
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT, created_by=actor,
        )
    removed_assignments = draft.document_assignments.count()
    draft.document_assignments.all().delete()
    desired_signers = json.loads(json.dumps(SIGNER_RULES))
    changed = removed_assignments or any((
        draft.product_version_id != plan['product_version'].pk,
        draft.product_key != plan['product'].code,
        draft.name != plan['product'].name,
        draft.form_schema != schema,
        draft.signer_rules != desired_signers,
        draft.document_type != plan['product'].code,
    ))
    if changed:
        draft.product_version = plan['product_version']
        draft.product_key = plan['product'].code
        draft.name = plan['product'].name
        draft.form_schema = schema
        draft.signer_rules = desired_signers
        draft.document_type = plan['product'].code
        draft.save(update_fields=[
            'product_version', 'product_key', 'name', 'form_schema', 'signer_rules',
            'document_type', 'updated_at',
        ])
        OriginationProductDefinitionEvent.objects.create(
            product_definition=draft, action='invoice_finance_contract_replaced', actor=actor,
            metadata={
                'field_count': len(schema['fields']), 'signer_count': len(SIGNER_RULES),
                'removed_supporting_assignment_count': removed_assignments,
                'attach_section_ignored': True,
            },
        )
    return draft


def _template_for(*, draft, plan, actor) -> tuple[OriginationDocumentTemplate, bool]:
    existing = draft.document_templates.filter(
        source_sha256=plan['pdf_sha256'],
        status__in=[OriginationDocumentTemplate.STATUS_READY, OriginationDocumentTemplate.STATUS_UPLOAD_FAILED],
    ).order_by('-version').first()
    if existing:
        desired_schema = json.loads(json.dumps(draft.form_schema))
        desired_signers = json.loads(json.dumps(draft.signer_rules))
        if existing.form_schema != desired_schema or existing.signer_rules != desired_signers:
            existing.form_schema = desired_schema
            existing.signer_rules = desired_signers
            existing.save(update_fields=['form_schema', 'signer_rules', 'updated_at'])
        return existing, False
    version = (
        OriginationDocumentTemplate.objects.filter(document_type=draft.document_type)
        .aggregate(models.Max('version'))['version__max'] or 0
    ) + 1
    config = initial_template_configuration(draft)
    config['document_type'] = draft.document_type
    config['version'] = version
    template = OriginationDocumentTemplate(
        product_definition=draft, document_key='primary', document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED, display_order=0,
        document_type=draft.document_type, name='Invoice Finance LAF', version=version,
        source_filename='INVOICE FINANCE.pdf', source_sha256=plan['pdf_sha256'],
        source_byte_size=len(plan['pdf_data']), page_count=plan['page_count'],
        placement_config=config, form_schema=json.loads(json.dumps(draft.form_schema)),
        signer_rules=json.loads(json.dumps(draft.signer_rules)), created_by=actor,
    )
    template.full_clean()
    template.save()
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='created', actor=actor,
        metadata={
            'sha256': plan['pdf_sha256'], 'byte_size': len(plan['pdf_data']),
            'page_count': plan['page_count'], 'origin': 'invoice_finance_seed',
        },
    )
    return template, True


def apply_seed(*, product_code: str, pdf_path: str | Path, actor) -> dict[str, Any]:
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise InvoiceFinanceSeedError('The seed actor must be an active Django Superuser.')
    plan = preflight(product_code=product_code, pdf_path=pdf_path)
    with transaction.atomic():
        fields = _upsert_fields(actor=actor)
        from core.services.origination_commercial_terms import ensure_commercial_catalogue
        fields.update(ensure_commercial_catalogue(actor=actor))
        schema = _form_schema(fields)
        from core.services.loan_origination import validate_product_form_contract
        validate_product_form_contract(schema, list(SIGNER_RULES))
        draft = _replace_draft(plan=plan, actor=actor, schema=schema)
        template, created = _template_for(draft=draft, plan=plan, actor=actor)
    if created or template.status == OriginationDocumentTemplate.STATUS_UPLOAD_FAILED or not template.drive_file_id:
        template = upload_template_record(template, pdf_data=plan['pdf_data'], actor=actor)
    if template.status == OriginationDocumentTemplate.STATUS_UPLOAD_FAILED:
        raise InvoiceFinanceSeedError(template.upload_error or 'The Invoice Finance PDF could not be uploaded to Drive.')
    with transaction.atomic():
        for old in draft.document_templates.filter(
            status__in=[OriginationDocumentTemplate.STATUS_READY, OriginationDocumentTemplate.STATUS_UPLOAD_FAILED],
        ).exclude(pk=template.pk):
            old.status = OriginationDocumentTemplate.STATUS_RETIRED
            old.save(update_fields=['status', 'updated_at'])
            OriginationDocumentTemplateEvent.objects.create(
                template=old, action='retired_from_invoice_finance_draft', actor=actor,
                metadata={'replacement_template_id': str(template.pk)},
            )
        if (
            draft.document_template_name != template.name
            or draft.document_template_version != template.version
            or draft.document_template_sha256 != template.source_sha256
        ):
            draft.document_template_name = template.name
            draft.document_template_version = template.version
            draft.document_template_sha256 = template.source_sha256
            draft.save(update_fields=[
                'document_template_name', 'document_template_version',
                'document_template_sha256', 'updated_at',
            ])
    return {
        'product': plan['product'], 'product_version': plan['product_version'],
        'definition': draft, 'template': template, 'fields': fields,
        'created_template': created,
    }
