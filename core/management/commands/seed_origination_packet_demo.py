"""Create a small synthetic origination packet for end-to-end Mini App checks."""

from __future__ import annotations

import hashlib
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import (
    OriginationDataField,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationProductDocumentAssignment,
)
from core.services.origination_fields import (
    attach_data_field,
    attach_data_field_to_template,
    create_data_field,
)
from core.services.origination_templates import (
    OriginationTemplateError,
    activate_template,
    initial_template_configuration,
    publish_calibration,
    publish_product_template,
    save_calibration_draft,
    upload_template_record,
)


PRODUCT_KEY = 'origination-packet-demo'
SUPPORTING_DOCUMENT_KEY = 'demo_guarantor_form'
SUPPORTING_DOCUMENT_TYPE = 'origination-demo-guarantor'

FIELD_SPECS = (
    ('demo_applicant_name', 'Demo applicant name', OriginationDataField.TYPE_TEXT, 'Applicant'),
    ('demo_requested_amount', 'Demo requested amount', OriginationDataField.TYPE_MONEY, 'Loan'),
    ('demo_guarantor_name', 'Demo guarantor name', OriginationDataField.TYPE_TEXT, 'Guarantor'),
    ('demo_guarantor_phone', 'Demo guarantor phone', OriginationDataField.TYPE_PHONE, 'Guarantor'),
)


def _synthetic_pdf(title: str = 'Demo LAF', labels: tuple[str, ...] = ()) -> bytes:
    """A one-page synthetic PDF with only test labels and no customer data."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    stream = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    }))
    resources = page[NameObject('/Resources')]
    resources[NameObject('/Font')] = DictionaryObject({NameObject('/F1'): font})
    escaped_title = str(title).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    commands = ['BT', '/F1 18 Tf', '72 790 Td', f'({escaped_title}) Tj', '/F1 10 Tf']
    for index, label in enumerate(labels):
        escaped_label = str(label).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        commands.extend(['0 -58 Td', f'({escaped_label}) Tj'])
    commands.append('ET')
    content = DecodedStreamObject()
    content.set_data(('\n'.join(commands) + '\n').encode('latin-1'))
    page[NameObject('/Contents')] = writer._add_object(content)
    writer.write(stream)
    return stream.getvalue()


def _field_overlay(context_key: str, index: int) -> dict:
    return {
        'context_key': context_key,
        'page_number': 1,
        'units': 'pt',
        'box': {'x': 72, 'y': 700 - (index * 58), 'width': 300, 'height': 24},
    }


def _complete_configuration(template: OriginationDocumentTemplate, *, include_borrower_signature: bool) -> dict:
    product = template.product_definition
    config = initial_template_configuration(product)
    config['document_type'] = template.document_type
    config['version'] = template.version
    schema = template.form_schema if template.document_role == template.ROLE_SUPPORTING else product.form_schema
    fields = [
        item for item in (schema or {}).get('fields', [])
        if isinstance(item, dict) and item.get('key')
    ]
    config['field_overlay_manifest']['fields'] = {
        str(item['key']): _field_overlay(str(item['key']), index)
        for index, item in enumerate(fields)
    }
    if include_borrower_signature:
        config['signature_overlay_manifest']['slots'] = {
            'borrower.signature': {
                'role': 'borrower', 'slot_key': 'signature',
                'slot_type': 'signature', 'label': 'Demo borrower signature',
                'page_number': 1, 'units': 'pt',
                'box': {'x': 72, 'y': 120, 'width': 220, 'height': 40},
            },
        }
    return config


class Command(BaseCommand):
    help = (
        'Seed one synthetic, fully published loan-origination LAF and a supporting '
        'guarantor document. No customer data is created. Use --apply to write.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Username of the Django Superuser recorded in the audit trail.')
        parser.add_argument('--apply', action='store_true', help='Create the synthetic product, PDFs, templates, and assignment.')

    def _actor(self, username):
        actor = get_user_model().objects.filter(username=username, is_active=True).first()
        if not actor or not actor.is_superuser:
            raise CommandError('--actor must identify an active Django Superuser.')
        return actor

    def _ensure_field(self, *, key, label, data_type, category, actor):
        existing = OriginationDataField.objects.filter(key=key).first()
        if existing:
            if existing.data_type != data_type:
                raise CommandError(
                    f'Canonical test field {key!r} already exists with an incompatible type.',
                )
            return existing
        field, _created = create_data_field(
            payload={
                'key': key, 'label': label, 'type': data_type, 'category': category,
                'sensitivity': (
                    OriginationDataField.SENSITIVITY_FINANCIAL
                    if data_type == OriginationDataField.TYPE_MONEY
                    else OriginationDataField.SENSITIVITY_PII
                ),
                'reporting_use': OriginationDataField.REPORT_UNAVAILABLE,
                'export_allowed': False,
            },
            actor=actor,
        )
        return field

    def _create_uploaded_template(self, *, product, document_key, document_role, document_type,
                                  name, form_schema, signer_rules, pdf_data, actor):
        config = initial_template_configuration(product)
        config['document_type'] = document_type
        config['version'] = 1
        template = OriginationDocumentTemplate.objects.create(
            product_definition=product,
            document_key=document_key,
            document_role=document_role,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            display_order=0 if document_role == OriginationDocumentTemplate.ROLE_PRIMARY else 10,
            document_type=document_type,
            name=name,
            version=1,
            source_filename=f'{document_key}.pdf',
            source_sha256=hashlib.sha256(pdf_data).hexdigest(),
            source_byte_size=len(pdf_data),
            page_count=1,
            placement_config=config,
            form_schema=form_schema,
            signer_rules=signer_rules,
            created_by=actor,
        )
        uploaded = upload_template_record(template, pdf_data=pdf_data, actor=actor)
        if uploaded.status == uploaded.STATUS_UPLOAD_FAILED:
            raise CommandError(
                f'Could not upload {name}: {uploaded.upload_error or "unknown Drive error"}',
            )
        return uploaded

    def handle(self, *args, **options):
        actor = self._actor(options['actor'])
        existing = OriginationProductDefinition.objects.filter(product_key=PRODUCT_KEY).order_by('-version').first()
        if existing:
            if existing.is_active and existing.lifecycle_status == existing.STATUS_PUBLISHED:
                assignment = existing.document_assignments.filter(
                    document_key=SUPPORTING_DOCUMENT_KEY,
                ).select_related('template').first()
                if assignment:
                    self.stdout.write(self.style.SUCCESS(
                        f'Demo already exists: {existing.name} v{existing.version} ({existing.pk}). '
                        f'Supporting template family: {assignment.template.name}.',
                    ))
                    return
            raise CommandError(
                'A partial or draft demo product already exists. It was left intact for auditability; '
                'review it in Admin before running this command again.',
            )
        if not options['apply']:
            self.stdout.write(
                'Dry run: would create one synthetic product, primary LAF, global guarantor form, '
                'four canonical demo fields, and a latest-compatible assignment. Re-run with --apply.',
            )
            return
        if not str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip():
            raise CommandError('GOOGLE_DRIVE_MEDIA_FOLDER_ID must be configured before seeding PDFs.')

        try:
            canonical = {
                key: self._ensure_field(
                    key=key, label=label, data_type=data_type, category=category, actor=actor,
                )
                for key, label, data_type, category in FIELD_SPECS
            }
            product = OriginationProductDefinition.objects.create(
                product_key=PRODUCT_KEY,
                name='Origination packet demo',
                version=1,
                form_schema={
                    '_revision': 0,
                    'sections': [
                        {'key': 'applicant', 'label': 'Applicant', 'help_text': 'Synthetic test values only.'},
                        {'key': 'loan', 'label': 'Loan request', 'help_text': 'Synthetic test values only.'},
                    ],
                    'fields': [],
                },
                signer_rules=[{
                    'role': 'borrower', 'required': True,
                    'slots': [{'key': 'signature', 'label': 'Demo borrower signature', 'type': 'signature', 'required': True}],
                }],
                document_type=PRODUCT_KEY,
                document_template_version=1,
                lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
                created_by=actor,
            )
            for key, section_key in (
                ('demo_applicant_name', 'applicant'), ('demo_requested_amount', 'loan'),
            ):
                product, _ = attach_data_field(
                    product=product, data_field=canonical[key],
                    presentation={'section_key': section_key, 'required': True, 'width': 'full'},
                    actor=actor,
                    expected_schema_revision=int((product.form_schema or {}).get('_revision') or 0),
                )

            supporting_pdf = _synthetic_pdf(
                'Demo guarantor form',
                ('Applicant name', 'Requested amount', 'Guarantor name', 'Guarantor phone'),
            )
            supporting = self._create_uploaded_template(
                product=None,
                document_key=SUPPORTING_DOCUMENT_KEY,
                document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
                document_type=SUPPORTING_DOCUMENT_TYPE,
                name='Demo guarantor form',
                form_schema={
                    '_revision': 0,
                    'sections': [
                        {'key': 'application', 'label': 'Application details', 'help_text': ''},
                        {'key': 'guarantor', 'label': 'Guarantor details', 'help_text': ''},
                    ],
                    'fields': [],
                },
                signer_rules=[],
                pdf_data=supporting_pdf, actor=actor,
            )
            for key in canonical:
                supporting, _ = attach_data_field_to_template(
                    template=supporting, data_field=canonical[key],
                    presentation={
                        'section_key': 'guarantor' if key.startswith('demo_guarantor_') else 'application',
                        'required': True, 'width': 'full',
                    },
                    actor=actor,
                    expected_schema_revision=int((supporting.form_schema or {}).get('_revision') or 0),
                )
            support_config = _complete_configuration(supporting, include_borrower_signature=False)
            support_draft = save_calibration_draft(
                template=supporting, configuration=support_config, actor=actor, expected_revision=1,
                client_request_id='seed-origination-demo-supporting',
            )
            publish_calibration(template=supporting, revision=support_draft.revision, actor=actor)
            supporting = activate_template(supporting, actor=actor)

            assignment = OriginationProductDocumentAssignment.objects.create(
                product_definition=product, template=supporting,
                version_policy=OriginationProductDocumentAssignment.VERSION_LATEST_COMPATIBLE,
                document_key=SUPPORTING_DOCUMENT_KEY, name=supporting.name,
                display_order=10, inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
                created_by=actor,
            )

            primary = self._create_uploaded_template(
                product=product, document_key='primary',
                document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                document_type=product.document_type, name='Demo primary LAF',
                form_schema=product.form_schema, signer_rules=product.signer_rules,
                pdf_data=_synthetic_pdf(
                    'Demo primary LAF', ('Applicant name', 'Requested amount'),
                ),
                actor=actor,
            )
            primary_config = _complete_configuration(primary, include_borrower_signature=True)
            primary_draft = save_calibration_draft(
                template=primary, configuration=primary_config, actor=actor, expected_revision=1,
                client_request_id='seed-origination-demo-primary',
            )
            product, primary, _published = publish_product_template(
                template=primary, revision=primary_draft.revision, actor=actor,
                client_request_id='seed-origination-demo-product',
            )
        except OriginationTemplateError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f'Created {product.name} v{product.version} ({product.pk}) with primary LAF '
            f'{primary.pk} and supporting document {assignment.name} ({supporting.pk}).',
        ))
        self.stdout.write(
            'Open Loan Origination, create a new application for “Origination packet demo”, '
            'complete the two main fields, then preview the main LAF. The required Demo guarantor form '
            'will appear next and asks only for the two guarantor fields.',
        )
