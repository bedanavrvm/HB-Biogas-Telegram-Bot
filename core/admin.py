import json
import logging
import re
import uuid

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connections, models, transaction
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.widgets import UnfoldAdminFileFieldWidget, UnfoldAdminSelectWidget
from urllib.parse import urlencode

from core.services.workflow_presets import (
    MANUAL_PRESET,
    build_workflow_from_preset,
    defaults_for_preset,
    get_preset,
    preset_choices,
    preset_for_workflow,
)
from core.services.branches import global_branch_choices, workflow_branches as configured_workflow_branches
from core.services.tat_tracker import (
    PRODUCTS,
    cleanup_tat_sheet_duplicate_case_ids,
    configured_products,
    is_tat_tracker_workflow,
    resync_tat_tracker_cases,
    soft_delete_tat_case,
)
from core.services.telegram_launchers import MINI_APP_LAUNCHER_CHOICES, default_launcher_keys

from .models import (
    ComplaintCaseEvidence,
    ComplaintCaseControl,
    ComplaintCaseEvent,
    ComplaintCategory,
    ComplaintCategoryAlias,
    ComplaintCategoryAvailability,
    CaseUpdate,
    FcaImportRecord,
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    JawabuCustomer,
    JawabuCustomerPhoneHistory,
    JawabuCustomerFieldProvenance,
    JawabuPipelineEvent,
    BusinessCalendarHoliday,
    TatEscalationRule,
    WorkflowSlaEscalation,
    WorkflowTatDailyMetric,
    WorkflowTimelineAnnotation,
    JawabuDataQualityIssue,
    JawabuDataQualityResolution,
    JawabuFarmerUploadBatch,
    JawabuVisitRecord,
    LiveSheetRecordChange,
    MediaAttachment,
    JawabuApprovalDelegation,
    JawabuApprovalDelegationEvent,
    JawabuApprovalRecord,
    JawabuApprovalCondition,
    JawabuMediaAccessEvent,
    BranchServiceArea,
    LocationConfigurationEvent,
    LocationMappingIssue,
    LocationPolicyState,
    OperationalLocation,
    OperationalLocationAlias,
    Product,
    ProductAlias,
    ProductAvailability,
    ProductCustomAttribute,
    ProductFee,
    ProductMappingIssue,
    ProductRequirement,
    ProductTatConfiguration,
    ProductVersion,
    ProductVersionEvent,
    OrderApprovalUpdate,
    InvoiceUploadBatch,
    InvoiceIdentityReview,
    InvoiceNameChangeBatch,
    InvoiceNameChangeItem,
    InvoiceNameChangeLetterArtifact,
    InvoiceNameChangeLetterTemplate,
    JawabuRelatedPerson,
    JawabuHouseholdRelationship,
    ParsedInvoice,
    PortalVoiceTranscriptionAttempt,
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationFieldReviewIssue,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationTemplateConfigurationRevision,
    LoanOriginationApplication,
    OriginationReportingValue,
    OriginationApplicationEvent,
    OriginationCorrectionItem,
    OriginationCorrectionRequest,
    OriginationRequirementEvidence,
    OriginationApplicationDocument,
    OriginationProductDocumentAssignment,
    OriginationSigningPackage,
    OriginationSigningAction,
    OriginationSignerSession,
    OriginationOtpChallenge,
    OriginationSigningRequestEvent,
    OriginationStampAsset,
    PaymentDocument,
    PaymentDocumentTemplate,
    RawMessage,
    ProcessedMessage,
    ParsedMessage,
    RequisitionBatch,
    RequisitionTemplate,
    SpinCreditRequest,
    SpinBatchReviewItem,
    SheetRegisterContract,
    SheetSyncAuditSnapshot,
    SheetSyncDiscrepancy,
    TatTrackerCase,
    TatTrackerEvent,
    TatRepairJob,
    UserProfile,
    UserMiniAppPreference,
    AccessGrant,
    WorkflowRoleCapability,
    WorkflowRoleCapabilityAuditEvent,
    AccessControlChangeRequest,
    AccessControlCheckerAssignment,
    WorkflowConfigurationChangeRequest,
    AccessControlPolicySnapshot,
    EmergencyAccessGrant,
    AccessControlNotification,
    CapabilityUsageDaily,
    DocumentSignoffPolicy,
    DocumentPhysicalSignoff,
    DocumentPhysicalSignoffEvent,
    ComplianceAuditChainState,
    ComplianceAuditCheckpoint,
    ComplianceAuditEvent,
    IntegrationCircuitState,
    IntegrationOperation,
)

logger = logging.getLogger(__name__)


class OriginationProductDefinitionForm(forms.ModelForm):
    product_version = forms.ModelChoiceField(
        queryset=ProductVersion.objects.none(), required=False,
        help_text='Global product terms version used by this form and LAF.',
        widget=UnfoldAdminSelectWidget,
    )
    product_key = forms.SlugField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(required=False, widget=forms.HiddenInput)
    form_schema = forms.JSONField(widget=forms.HiddenInput)
    signer_rules = forms.JSONField(widget=forms.HiddenInput)
    laf_pdf = forms.FileField(
        required=False,
        label='LAF PDF template',
        help_text=(
            'Upload the blank LAF PDF. After saving, the visual alignment builder '
            'opens so these form variables can be assigned and drawn on the document.'
        ),
        widget=UnfoldAdminFileFieldWidget(attrs={'accept': 'application/pdf'}),
    )

    class Meta:
        model = OriginationProductDefinition
        fields = (
            'product_version', 'laf_pdf', 'product_key', 'name',
            'form_schema', 'signer_rules',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product_version'].queryset = ProductVersion.objects.filter(
            status__in=[
                ProductVersion.STATUS_DRAFT,
                ProductVersion.STATUS_SCHEDULED,
                ProductVersion.STATUS_PUBLISHED,
            ],
        ).select_related('product').order_by('product__name', '-version')
        if self.instance.pk and not self.instance._state.adding:
            # A version may change its presentation contract while it is a
            # draft, but it must not move into another product's version line.
            self.fields['product_key'].disabled = True
            if self.instance.document_templates.filter(
                status__in=[
                    OriginationDocumentTemplate.STATUS_READY,
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                ],
            ).exists():
                self.fields['laf_pdf'].help_text = (
                    'Optional replacement PDF. The current draft template is retained '
                    'as immutable history and the new PDF starts with a fresh alignment.'
                )

    def clean(self):
        cleaned = super().clean()
        schema = cleaned.get('form_schema')
        signer_rules = cleaned.get('signer_rules')
        product_version = cleaned.get('product_version')
        laf_pdf = cleaned.get('laf_pdf')
        if product_version:
            cleaned['product_key'] = product_version.product.code
            cleaned['name'] = product_version.product.name
            self.instance.product_key = product_version.product.code
            self.instance.name = product_version.product.name
            self.instance.document_type = product_version.product.code
        product_key = str(cleaned.get('product_key') or self.instance.product_key or '').strip()
        if (
            self.instance._state.adding
            and product_key
            and OriginationProductDefinition.objects.filter(product_key=product_key).exists()
        ):
            self.add_error(
                'product_version',
                'This product already has an origination loan-form version. '
                'Open it from Origination product definitions and use “Create editable next version” instead.',
            )
        if laf_pdf:
            if not str(laf_pdf.name).lower().endswith('.pdf'):
                self.add_error('laf_pdf', 'Upload a PDF file.')
            else:
                from core.services.origination_templates import (
                    OriginationTemplateError, validate_template_pdf,
                )
                pdf_data = laf_pdf.read()
                laf_pdf.seek(0)
                try:
                    validate_template_pdf(pdf_data)
                except OriginationTemplateError as exc:
                    self.add_error('laf_pdf', str(exc))
        if schema is None or signer_rules is None:
            return cleaned
        from core.services.loan_origination import OriginationError, validate_product_form_contract
        try:
            validate_product_form_contract(schema, signer_rules)
        except OriginationError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return cleaned


class OriginationProductDefinitionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        terms_label = (
            f'terms v{obj.product_version.version}'
            if obj.product_version_id else 'legacy terms link'
        )
        return f'{obj.name} - loan form v{obj.version} ({terms_label})'


DOCUMENT_CONDITION_OPERATORS = (
    ('equals', 'is equal to'),
    ('not_equals', 'is not equal to'),
    ('truthy', 'is confirmed / has a value'),
    ('falsy', 'is not confirmed / is blank'),
)


def _simple_document_condition(rule):
    """Return the supported Admin representation without exposing the JSON DSL."""
    if not isinstance(rule, dict) or not rule:
        return None
    if set(rule) - {'field', 'operator', 'value'}:
        return None
    field = str(rule.get('field') or '').strip()
    operator = str(rule.get('operator') or '').strip()
    if field and operator in dict(DOCUMENT_CONDITION_OPERATORS):
        return {
            'field': field,
            'operator': operator,
            'value': rule.get('value', ''),
        }
    return None


def _product_condition_fields(product):
    """Small, presentation-safe catalogue for a document inclusion rule."""
    fields = (product.form_schema or {}).get('fields', []) if product else []
    return [
        {
            'key': str(item.get('key') or ''),
            'label': str(item.get('label') or item.get('key') or ''),
            'type': str(item.get('type') or 'text'),
            'options': list(item.get('options') or []),
        }
        for item in fields
        if isinstance(item, dict) and str(item.get('key') or '').strip()
    ]


class DocumentApplicabilityRuleFormMixin:
    """A small, non-technical editor for the supported document rule shape."""

    def _condition_product(self):
        product = getattr(self.instance, 'product_definition', None)
        raw_product_id = (
            self.data.get('product_definition') if self.is_bound
            else self.initial.get('product_definition')
        )
        if raw_product_id:
            product = OriginationProductDefinition.objects.filter(pk=raw_product_id).first()
        return product

    def _configure_condition_editor(self):
        product = self._condition_product()
        self._condition_fields = _product_condition_fields(product)
        self._condition_by_key = {item['key']: item for item in self._condition_fields}
        self.fields['condition_field'].choices = [
            ('', 'Always include')
        ] + [
            (item['key'], f"{item['label']} ({item['key']})")
            for item in self._condition_fields
        ]
        rule = _simple_document_condition(getattr(self.instance, 'applicability_rule', {}))
        self._legacy_condition_rule = bool(getattr(self.instance, 'applicability_rule', {})) and not rule
        if rule and not self.is_bound:
            self.initial.update({
                'condition_field': rule['field'],
                'condition_operator': rule['operator'],
                'condition_value': str(rule['value']).lower() if isinstance(rule['value'], bool) else rule['value'],
            })
        if self._legacy_condition_rule:
            self.fields['condition_field'].help_text = (
                'This legacy document uses a multi-part rule. It remains unchanged when this record is saved. '
                'Create a new assignment if you need a different rule.'
            )

    def _clean_condition_rule(self, cleaned):
        selected = str(cleaned.get('condition_field') or '').strip()
        if not selected:
            return getattr(self.instance, 'applicability_rule', {}) if self._legacy_condition_rule else {}
        operator = str(cleaned.get('condition_operator') or '').strip()
        if not operator:
            self.add_error('condition_operator', 'Choose how the application answer should be compared.')
            return {}
        field = self._condition_by_key.get(selected)
        if not field:
            self.add_error('condition_field', 'Choose a field from the selected loan form.')
            return {}
        value = cleaned.get('condition_value')
        if operator in {'truthy', 'falsy'}:
            return {'field': selected, 'operator': operator}
        if value in (None, ''):
            self.add_error('condition_value', 'Choose or enter the answer that makes this document applicable.')
            return {}
        if field['type'] == 'boolean':
            value = str(value).strip().lower() == 'true'
        return {'field': selected, 'operator': operator, 'value': value}


class OriginationDocumentTemplateForm(DocumentApplicabilityRuleFormMixin, forms.ModelForm):
    # ModelForm's metaclass only collects declared fields from this concrete
    # class, so keep the visual-rule controls here as well as their shared
    # behaviour in the mixin.
    condition_field = forms.ChoiceField(
        required=False, label='Only include this document when',
        help_text='Leave as Always include unless this form is needed only for a particular application answer.',
        widget=UnfoldAdminSelectWidget,
    )
    condition_operator = forms.ChoiceField(
        required=False, choices=DOCUMENT_CONDITION_OPERATORS,
        label='Comparison', widget=UnfoldAdminSelectWidget,
    )
    condition_value = forms.CharField(
        required=False, label='Answer',
        help_text='Choose the answer that makes this document applicable.',
    )
    product_definition = OriginationProductDefinitionChoiceField(
        queryset=OriginationProductDefinition.objects.none(), required=False,
        empty_label='Select a draft loan form definition',
        label='Loan form definition',
        help_text='Draft form/schema linked to the global product terms that own this PDF.',
        widget=UnfoldAdminSelectWidget,
    )
    pdf_file = forms.FileField(
        help_text='Approved PDF. It is stored in the configured restricted Drive folder.',
        widget=UnfoldAdminFileFieldWidget,
    )

    class Meta:
        model = OriginationDocumentTemplate
        fields = (
            'product_definition', 'document_key', 'name', 'document_role',
            'inclusion_mode', 'display_order', 'officer_selectable',
            'default_selected', 'applicability_rule', 'form_schema',
            'signer_rules', 'pdf_file',
        )
        widgets = {
            # These remain the audited storage format, but are authored through
            # the visual builder below rather than as hand-written JSON.
            'applicability_rule': forms.HiddenInput,
            'form_schema': forms.HiddenInput,
            'signer_rules': forms.HiddenInput,
        }

    @staticmethod
    def eligible_product_definitions():
        return OriginationProductDefinition.objects.filter(
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
        ).select_related(
            'product_version', 'product_version__product',
        ).order_by('name', '-version')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product_definition'].queryset = self.eligible_product_definitions()
        defaults = {
            'document_key': 'primary',
            'document_role': OriginationDocumentTemplate.ROLE_PRIMARY,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_REQUIRED,
            'display_order': 0,
            'officer_selectable': False,
            'default_selected': False,
            'applicability_rule': {},
            'form_schema': {},
            'signer_rules': [],
        }
        if not self.is_bound:
            for key, value in defaults.items():
                self.fields[key].initial = value
        for key in defaults:
            self.fields[key].required = False
        self._configure_condition_editor()

    def clean(self):
        cleaned = super().clean()
        pdf_file = cleaned.get('pdf_file')
        product = cleaned.get('product_definition')
        if not pdf_file:
            return cleaned
        cleaned['document_key'] = str(cleaned.get('document_key') or 'primary').strip()
        cleaned['document_role'] = cleaned.get('document_role') or OriginationDocumentTemplate.ROLE_PRIMARY
        cleaned['inclusion_mode'] = cleaned.get('inclusion_mode') or OriginationDocumentTemplate.INCLUDE_REQUIRED
        cleaned['display_order'] = cleaned.get('display_order') or 0
        cleaned['officer_selectable'] = bool(cleaned.get('officer_selectable'))
        cleaned['default_selected'] = bool(cleaned.get('default_selected'))
        cleaned['applicability_rule'] = self._clean_condition_rule(cleaned)
        cleaned['form_schema'] = cleaned.get('form_schema') or {}
        cleaned['signer_rules'] = cleaned.get('signer_rules') or []
        for key, value in cleaned.items():
            if key in self.fields:
                setattr(self.instance, key, value)
        if not str(pdf_file.name).lower().endswith('.pdf'):
            self.add_error('pdf_file', 'Upload a PDF file.')
            return cleaned
        document_key = cleaned['document_key']
        if product and product.document_templates.exclude(
            status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
        ).filter(document_key=document_key).exists():
            self.add_error('document_key', 'This product version already has a document with this key.')
            return cleaned
        from core.services.origination_templates import (
            OriginationTemplateError, initial_template_configuration, validate_template_pdf,
        )
        pdf_data = pdf_file.read()
        pdf_file.seek(0)
        try:
            digest, page_count = validate_template_pdf(pdf_data)
        except OriginationTemplateError as exc:
            raise forms.ValidationError(str(exc)) from exc
        self.instance.product_definition = product
        role = cleaned['document_role']
        if not product and role != OriginationDocumentTemplate.ROLE_SUPPORTING:
            self.add_error('product_definition', 'A primary LAF must belong to a draft loan form.')
            return cleaned
        self.instance.document_type = (
            product.document_type if role == OriginationDocumentTemplate.ROLE_PRIMARY
            else f'{product.product_key}-{document_key}'[:80] if product
            else document_key[:80]
        )
        self.instance.version = (
            product.version if product else
            (OriginationDocumentTemplate.objects.filter(document_type=self.instance.document_type)
             .aggregate(models.Max('version'))['version__max'] or 0) + 1
        )
        self.instance.source_filename = str(pdf_file.name)[:255]
        self.instance.source_sha256 = digest
        self.instance.source_byte_size = len(pdf_data)
        self.instance.page_count = page_count
        self.instance.placement_config = initial_template_configuration(product)
        self.instance.placement_config['version'] = self.instance.version
        self.instance.placement_config['document_type'] = self.instance.document_type
        # The product contract is the only source of primary-LAF form fields.
        # Supporting forms have their own visual schema and signer slots.
        self.instance.form_schema = (
            product.form_schema if role == OriginationDocumentTemplate.ROLE_PRIMARY and product
            else cleaned.get('form_schema') or {}
        )
        self.instance.signer_rules = (
            product.signer_rules if role == OriginationDocumentTemplate.ROLE_PRIMARY and product
            else cleaned.get('signer_rules') or []
        )
        sample_context = self.instance.placement_config.setdefault('sample_context', {})
        for field in (self.instance.form_schema or {}).get('fields', []):
            if isinstance(field, dict) and field.get('key'):
                sample_context.setdefault(
                    str(field['key']), str(field.get('label') or field['key']).replace('_', ' ').title(),
                )
        if role == OriginationDocumentTemplate.ROLE_SUPPORTING and not self.instance.form_schema:
            self.instance.form_schema = {'_revision': 0, 'sections': [], 'fields': []}
        from core.services.origination_documents import validate_applicability_rule
        allowed_fields = {
            str(item.get('key')) for item in ((product.form_schema if product else {}) or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        }
        allowed_fields.update(
            str(item.get('key')) for item in (self.instance.form_schema or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        )
        try:
            validate_applicability_rule(
                cleaned.get('applicability_rule') or {}, allowed_fields=allowed_fields,
            )
        except ValueError as exc:
            self.add_error('applicability_rule', str(exc))
        self._pdf_data = pdf_data
        return cleaned


class OriginationProductDocumentAssignmentForm(DocumentApplicabilityRuleFormMixin, forms.ModelForm):
    """Derive each product assignment's identity from its shared template."""

    condition_field = forms.ChoiceField(
        required=False, label='Only include this document when',
        help_text='Leave as Always include unless this form is needed only for a particular application answer.',
        widget=UnfoldAdminSelectWidget,
    )
    condition_operator = forms.ChoiceField(
        required=False, choices=DOCUMENT_CONDITION_OPERATORS,
        label='Comparison', widget=UnfoldAdminSelectWidget,
    )
    condition_value = forms.CharField(
        required=False, label='Answer',
        help_text='Choose the answer that makes this document applicable.',
    )

    class Meta:
        model = OriginationProductDocumentAssignment
        fields = (
            'product_definition', 'template', 'version_policy', 'inclusion_mode',
            'display_order', 'officer_selectable', 'default_selected', 'applicability_rule',
        )
        widgets = {
            'product_definition': UnfoldAdminSelectWidget,
            'template': UnfoldAdminSelectWidget,
            'version_policy': UnfoldAdminSelectWidget,
            'inclusion_mode': UnfoldAdminSelectWidget,
            'applicability_rule': forms.HiddenInput,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_condition_editor()

    def clean(self):
        cleaned = super().clean()
        cleaned['applicability_rule'] = self._clean_condition_rule(cleaned)
        template = cleaned.get('template')
        if template:
            # A product assignment chooses a governed document family. It must
            # not create another, typo-prone key and name for that same form.
            self.instance.document_key = template.document_key
            self.instance.name = template.name
        return cleaned


class ProductSupportingDocumentSetupForm(forms.Form):
    """Product-scoped, non-JSON setup form for a reusable supporting PDF."""

    MODE_EXISTING = 'existing'
    MODE_NEW = 'new'
    mode = forms.ChoiceField(
        choices=((MODE_EXISTING, 'Use a published reusable document'), (MODE_NEW, 'Create a reusable document')),
        initial=MODE_EXISTING, widget=forms.RadioSelect, label='How do you want to add it?',
    )
    template = forms.ModelChoiceField(
        queryset=OriginationDocumentTemplate.objects.none(), required=False,
        empty_label='Choose a published document', label='Published document',
        help_text='Its newest compatible published version will be used for new applications.',
        widget=UnfoldAdminSelectWidget,
    )
    name = forms.CharField(required=False, max_length=180, label='Document name')
    document_key = forms.SlugField(
        required=False, max_length=80, label='Document key',
        help_text='A stable short ID, for example guarantor_form. It cannot be changed after publication.',
    )
    pdf_file = forms.FileField(
        required=False, label='Supporting PDF',
        widget=UnfoldAdminFileFieldWidget,
    )
    form_schema = forms.JSONField(required=False, widget=forms.HiddenInput)
    signer_rules = forms.JSONField(required=False, widget=forms.HiddenInput)
    inclusion_mode = forms.ChoiceField(
        choices=OriginationDocumentTemplate.INCLUDE_CHOICES,
        initial=OriginationDocumentTemplate.INCLUDE_REQUIRED,
        label='When is this document needed?', widget=UnfoldAdminSelectWidget,
    )
    display_order = forms.IntegerField(initial=10, min_value=0, label='Display order')
    officer_selectable = forms.BooleanField(
        required=False, label='Officer selectable',
        help_text='Required for an optional document.',
    )
    default_selected = forms.BooleanField(
        required=False, label='Selected by default',
        help_text='Only applies to officer-selectable documents.',
    )
    condition_field = forms.ChoiceField(
        required=False, label='Only include this document when',
        help_text='Leave as Always include unless it depends on an answer in the main loan form.',
        widget=UnfoldAdminSelectWidget,
    )
    condition_operator = forms.ChoiceField(
        required=False, choices=DOCUMENT_CONDITION_OPERATORS,
        label='Comparison', widget=UnfoldAdminSelectWidget,
    )
    condition_value = forms.CharField(required=False, label='Answer')

    def __init__(self, *args, product: OriginationProductDefinition, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        self.fields['template'].queryset = OriginationDocumentTemplate.objects.filter(
            product_definition__isnull=True,
            document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
            status=OriginationDocumentTemplate.STATUS_ACTIVE,
            published_configuration_revision__isnull=False,
        ).order_by('name', '-version')
        self._condition_by_key = {
            item['key']: item for item in _product_condition_fields(product)
        }
        self.fields['condition_field'].choices = [('', 'Always include')] + [
            (item['key'], f"{item['label']} ({item['key']})")
            for item in self._condition_by_key.values()
        ]

    def _condition_rule(self, cleaned):
        field_key = str(cleaned.get('condition_field') or '').strip()
        if not field_key:
            return {}
        operator = str(cleaned.get('condition_operator') or '').strip()
        if not operator:
            self.add_error('condition_operator', 'Choose how the application answer should be compared.')
            return {}
        field = self._condition_by_key.get(field_key)
        if not field:
            self.add_error('condition_field', 'Choose a field from this loan form.')
            return {}
        if operator in {'truthy', 'falsy'}:
            return {'field': field_key, 'operator': operator}
        value = cleaned.get('condition_value')
        if value in (None, ''):
            self.add_error('condition_value', 'Enter the answer that makes this document applicable.')
            return {}
        if field['type'] == 'boolean':
            value = str(value).lower() == 'true'
        return {'field': field_key, 'operator': operator, 'value': value}

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('mode')
        cleaned['applicability_rule'] = self._condition_rule(cleaned)
        if cleaned.get('inclusion_mode') == OriginationDocumentTemplate.INCLUDE_OPTIONAL:
            if not cleaned.get('officer_selectable'):
                self.add_error('officer_selectable', 'Optional documents must be officer selectable.')
        elif cleaned.get('default_selected'):
            self.add_error('default_selected', 'Only optional documents can be selected by default.')
        if mode == self.MODE_EXISTING:
            if not cleaned.get('template'):
                self.add_error('template', 'Choose a published reusable document.')
            return cleaned
        if mode != self.MODE_NEW:
            self.add_error('mode', 'Choose how to add the supporting document.')
            return cleaned
        for field_name, label in (('name', 'document name'), ('document_key', 'document key'), ('pdf_file', 'supporting PDF')):
            if not cleaned.get(field_name):
                self.add_error(field_name, f'Provide the {label}.')
        schema = cleaned.get('form_schema') or {}
        signers = cleaned.get('signer_rules') or []
        from core.services.loan_origination import OriginationError, validate_product_form_contract
        from core.services.origination_templates import OriginationTemplateError, validate_template_pdf
        try:
            validate_product_form_contract(schema, signers, require_signers=False)
        except OriginationError as exc:
            self.add_error('form_schema', str(exc))
        for field in (schema.get('fields') or []) if isinstance(schema, dict) else []:
            if not isinstance(field, dict):
                continue
            canonical_id = field.get('data_field_id')
            canonical = OriginationDataField.objects.filter(pk=canonical_id, active=True).first()
            if not canonical or canonical.key != str(field.get('key') or '') or canonical.data_type != str(field.get('type') or ''):
                self.add_error('form_schema', 'Every supporting-document field must come from the active canonical field catalogue.')
                break
        pdf_file = cleaned.get('pdf_file')
        if pdf_file:
            if not str(pdf_file.name).lower().endswith('.pdf'):
                self.add_error('pdf_file', 'Upload a PDF file.')
            else:
                data = pdf_file.read()
                pdf_file.seek(0)
                try:
                    validate_template_pdf(data)
                except OriginationTemplateError as exc:
                    self.add_error('pdf_file', str(exc))
        return cleaned


class CompactModelAdmin(ModelAdmin):
    """Shared dense layout for editable operational records."""

    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True


class OriginationGodModeAdminMixin:
    """Expose an explicit Superuser purge for Origination records only."""

    change_form_template = 'admin/core/origination_god_mode/change_form.html'

    def get_urls(self):
        return [
            path(
                '<path:object_id>/god-mode-purge/',
                self.admin_site.admin_view(self.origination_god_mode_purge_view),
                name=(
                    f'{self.model._meta.app_label}_{self.model._meta.model_name}'
                    '_god_mode_purge'
                ),
            ),
        ] + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = {**(extra_context or {})}
        if object_id and request.user.is_active and request.user.is_superuser:
            context['origination_god_mode_purge_url'] = reverse(
                'admin:'
                f'{self.model._meta.app_label}_{self.model._meta.model_name}'
                '_god_mode_purge',
                args=[object_id],
            )
        return super().changeform_view(request, object_id, form_url, context)

    def origination_god_mode_purge_view(self, request, object_id):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponse(status=404)
        expected_confirmation = str(obj.pk)
        error = ''
        if request.method == 'POST':
            confirmation = str(request.POST.get('confirmation') or '').strip()
            reason = str(request.POST.get('reason') or '').strip()
            if confirmation != expected_confirmation:
                error = f'Type the exact record ID: {expected_confirmation}'
            elif not reason:
                error = 'Provide a reason for this permanent purge.'
            else:
                from core.services.origination_god_mode import (
                    OriginationGodModeError, purge_origination_record,
                )
                try:
                    counts = purge_origination_record(
                        record=obj, actor=request.user, reason=reason,
                    )
                except OriginationGodModeError as exc:
                    error = str(exc)
                except Exception:
                    logger.exception(
                        'Origination God mode purge failed: model=%s object_id=%s actor_id=%s',
                        self.model._meta.label, object_id, request.user.pk,
                    )
                    error = 'The Origination purge failed. No database changes were committed.'
                else:
                    logger.warning(
                        'Origination God mode purge completed: model=%s object_id=%s '
                        'actor_id=%s reason=%r counts=%s drive_files_untouched=true',
                        self.model._meta.label, object_id, request.user.pk, reason[:500], counts,
                    )
                    summary = ', '.join(
                        f'{count} {label}' for label, count in counts.items()
                    ) or 'the selected record'
                    self.message_user(
                        request,
                        f'God mode purge completed: {summary}. Drive files were left untouched.',
                        level=messages.WARNING,
                    )
                    return HttpResponseRedirect(reverse(
                        f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist',
                    ))
        elif request.method != 'GET':
            response = HttpResponse(status=405)
            response['Allow'] = 'GET, POST'
            return response
        from core.services.origination_god_mode import preview_origination_purge
        return TemplateResponse(
            request,
            'admin/core/origination_god_mode/confirm_purge.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': f'God mode purge: {self.model._meta.verbose_name}',
                'original': obj,
                'object_id': expected_confirmation,
                'error': error,
                'impact': preview_origination_purge(obj),
                'back_url': reverse(
                    f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change',
                    args=[obj.pk],
                ),
            },
        )


@admin.register(SheetRegisterContract)
class SheetRegisterContractAdmin(CompactModelAdmin):
    """Controlled, publication-only register contracts and manual audits."""

    list_display = ('register_key', 'group_configuration', 'sheet_name', 'subject_type', 'publication_mode', 'enabled', 'updated_at')
    list_filter = ('enabled', 'subject_type', 'publication_mode')
    search_fields = ('register_key', 'sheet_name', 'group_configuration__group_id', 'group_configuration__display_name')
    list_select_related = ('group_configuration',)
    readonly_fields = ('created_at', 'updated_at')
    actions = ('run_selected_register_audits',)
    fieldsets = (
        ('Register', {
            'fields': (
                ('group_configuration', 'register_key'),
                ('sheet_name', 'subject_type'),
                ('header_row', 'data_start_row', 'row_key_header'),
                ('publication_mode', 'enabled'),
            ),
        }),
        ('Schema and ownership', {
            'description': (
                'Google Sheets are view-only publication registers. List the expected headers in order and assign every header '
                'one owner: backend_owned, formula_owned, derived, or immutable. Only backend_owned/immutable fields with a '
                'model_field are compared during a TAT divergence audit.'
            ),
            'fields': ('expected_headers', 'field_ownership'),
        }),
        ('Audit', {'fields': (('created_at', 'updated_at'),), 'classes': ('collapse',)}),
    )

    @admin.action(description='Run selected register audits (read-only Sheets)')
    def run_selected_register_audits(self, request, queryset):
        from core.services.sync_governance import audit_sheet_register

        outcomes = []
        for contract in queryset.select_related('group_configuration'):
            result = audit_sheet_register(contract, checked_by=request.user.get_username(), persist=True)
            outcomes.append(f"{contract.register_key}: {result['status']}")
        self.message_user(request, 'Register audit recorded — ' + '; '.join(outcomes), level=messages.INFO)


@admin.register(SheetSyncAuditSnapshot)
class SheetSyncAuditSnapshotAdmin(CompactModelAdmin):
    """Append-only compliance evidence; source Sheet values are never shown."""

    list_display = ('created_at', 'contract', 'status', 'rows_checked', 'discrepancy_count', 'checked_by', 'error_code')
    list_filter = ('status', 'contract__subject_type', 'contract__group_configuration')
    search_fields = ('contract__register_key', 'contract__group_configuration__group_id', 'checked_by', 'error_code')
    list_select_related = ('contract', 'contract__group_configuration')
    readonly_fields = (
        'contract', 'status', 'expected_header_fingerprint', 'actual_header_fingerprint',
        'missing_headers', 'duplicate_headers', 'reordered_headers', 'rows_checked',
        'discrepancy_count', 'error_code', 'error', 'checked_by', 'created_at',
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ('GET', 'HEAD') and super().has_change_permission(request, obj)


@admin.register(SheetSyncDiscrepancy)
class SheetSyncDiscrepancyAdmin(CompactModelAdmin):
    """Privacy-preserving audit differences; values are represented by hashes."""

    list_display = ('kind', 'record_key', 'field_name', 'snapshot', 'created_at')
    list_filter = ('kind', 'snapshot__status', 'snapshot__contract__group_configuration')
    search_fields = ('record_key', 'field_name', 'snapshot__contract__register_key')
    list_select_related = ('snapshot', 'snapshot__contract', 'snapshot__contract__group_configuration')
    readonly_fields = (
        'snapshot', 'record_key', 'field_name', 'kind', 'expected_value_hash',
        'actual_value_hash', 'detail', 'created_at',
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ('GET', 'HEAD') and super().has_change_permission(request, obj)


@admin.register(OperationalLocation)
class OperationalLocationAdmin(CompactModelAdmin):
    """Governed location identity used by Portal, forms, parsers, and grants."""

    list_display = ('location_type', 'name', 'code', 'parent', 'active', 'sort_order', 'updated_at')
    list_filter = ('location_type', 'active')
    search_fields = ('name', 'code', 'aliases__alias')
    ordering = ('location_type', 'sort_order', 'name')
    readonly_fields = ('published_at', 'retired_at', 'created_at', 'updated_at')
    fieldsets = (
        ('Location', {
            'fields': (
                ('location_type', 'name'), ('code', 'parent'),
                ('sort_order', 'active'),
                ('source_name', 'source_reference'),
            ),
        }),
        ('Audit', {
            'fields': (('published_at', 'retired_at'), ('created_at', 'updated_at')),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        values = list(super().get_readonly_fields(request, obj))
        if obj:
            values.extend(['location_type', 'code', 'parent'])
        return tuple(dict.fromkeys(values))

    def save_model(self, request, obj, form, change):
        from core.services.location_catalog import _record_event

        before = {}
        previous_name = ''
        if change:
            previous = OperationalLocation.objects.get(pk=obj.pk)
            previous_name = previous.name
            before = {
                'name': previous.name, 'active': previous.active,
                'sort_order': previous.sort_order,
            }
        if not obj.active and not obj.retired_at:
            obj.retired_at = timezone.now()
        elif obj.active:
            obj.retired_at = None
        super().save_model(request, obj, form, change)
        if previous_name and previous_name.casefold() != obj.name.casefold():
            OperationalLocationAlias.objects.get_or_create(
                location=obj,
                normalized_alias=re.sub(r'[^a-z0-9]+', '_', previous_name.casefold()).strip('_'),
                defaults={
                    'location_type': obj.location_type,
                    'alias': previous_name,
                    'created_by': request.user,
                },
            )
        _record_event(
            subject_type='operational_location', subject_id=obj.pk,
            action='location_created' if not change else 'location_updated',
            actor=request.user, before=before,
            after={'name': obj.name, 'code': obj.code, 'active': obj.active, 'sort_order': obj.sort_order},
        )


@admin.register(OperationalLocationAlias)
class OperationalLocationAliasAdmin(CompactModelAdmin):
    list_display = ('alias', 'location_type', 'location', 'parent', 'active', 'created_at')
    list_filter = ('location_type', 'active')
    search_fields = ('alias', 'location__name', 'location__code')
    readonly_fields = ('location_type', 'parent', 'normalized_alias', 'created_by', 'created_at', 'retired_at')

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj:
            fields.append('location')
        return fields

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from core.services.location_catalog import _record_event

        before = {'active': obj.active} if change else {}
        if not obj.created_by_id:
            obj.created_by = request.user
        if not obj.active and not obj.retired_at:
            obj.retired_at = timezone.now()
        elif obj.active:
            obj.retired_at = None
        super().save_model(request, obj, form, change)
        _record_event(
            subject_type='operational_location_alias', subject_id=obj.pk,
            action='alias_updated' if change else 'alias_created', actor=request.user,
            before=before,
            after={'location_code': obj.location.code, 'alias': obj.alias, 'active': obj.active},
        )


@admin.register(BranchServiceArea)
class BranchServiceAreaAdmin(CompactModelAdmin):
    list_display = ('branch', 'area', 'is_primary', 'active', 'created_at', 'retired_at')
    list_filter = ('active', 'is_primary', 'branch', 'area__location_type')
    search_fields = ('branch__name', 'branch__code', 'area__name', 'area__code')
    autocomplete_fields = ('branch', 'area')
    readonly_fields = ('created_by', 'retired_by', 'created_at', 'retired_at')

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj:
            fields.extend(['branch', 'area'])
        return fields

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from core.services.location_catalog import _record_event

        before = {}
        if change:
            previous = BranchServiceArea.objects.get(pk=obj.pk)
            before = {'active': previous.active, 'is_primary': previous.is_primary}
        elif not obj.created_by_id:
            obj.created_by = request.user
        if not obj.active and not obj.retired_at:
            obj.retired_at = timezone.now()
            obj.retired_by = request.user
            obj.is_primary = False
        elif obj.active:
            obj.retired_at = None
            obj.retired_by = None
        super().save_model(request, obj, form, change)
        _record_event(
            subject_type='branch_service_area', subject_id=obj.pk,
            action='service_area_updated' if change else 'service_area_created',
            actor=request.user, before=before,
            after={
                'branch_code': obj.branch.code, 'area_code': obj.area.code,
                'active': obj.active, 'is_primary': obj.is_primary,
            },
        )


@admin.register(LocationPolicyState)
class LocationPolicyStateAdmin(CompactModelAdmin):
    list_display = ('mode', 'readiness_status', 'updated_by', 'updated_at')
    readonly_fields = ('mode', 'readiness_details', 'source_manifest', 'updated_by', 'updated_at')
    actions = ('publish_audit_mode', 'publish_strict_mode')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Readiness')
    def readiness_status(self, obj):
        from core.services.location_catalog import catalog_readiness
        return 'Ready for strict mode' if catalog_readiness()['ready'] else 'Audit cleanup required'

    @admin.display(description='Readiness details')
    def readiness_details(self, obj):
        from core.services.location_catalog import catalog_readiness
        return json.dumps(catalog_readiness(), indent=2)

    @admin.action(description='Publish audit-only location policy')
    def publish_audit_mode(self, request, queryset):
        from core.services.location_catalog import publish_policy
        publish_policy(mode='audit', actor=request.user)

    @admin.action(description='Publish strict location policy after readiness check')
    def publish_strict_mode(self, request, queryset):
        from core.services.location_catalog import LocationCatalogError, publish_policy
        try:
            publish_policy(mode='strict', actor=request.user)
        except LocationCatalogError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)


@admin.register(LocationMappingIssue)
class LocationMappingIssueAdmin(CompactModelAdmin):
    list_display = ('location_type', 'raw_value', 'source_workflow', 'source_model', 'source_field', 'status', 'created_at')
    list_filter = ('status', 'location_type', 'source_workflow', 'source_model')
    search_fields = ('raw_value', 'normalized_value', 'source_record_id', 'detail')
    autocomplete_fields = ('location',)
    readonly_fields = (
        'location_type', 'raw_value', 'normalized_value', 'source_workflow',
        'source_model', 'source_field', 'source_record_id', 'detail', 'created_at',
        'resolved_by', 'resolved_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        previous_status = (
            LocationMappingIssue.objects.filter(pk=obj.pk).values_list('status', flat=True).first()
            if change else ''
        )
        if obj.location_id and previous_status == LocationMappingIssue.STATUS_OPEN:
            from core.services.location_catalog import resolve_mapping_issue
            resolve_mapping_issue(obj, location=obj.location, actor=request.user)
            return
        super().save_model(request, obj, form, change)
        if previous_status and previous_status != obj.status:
            from core.services.location_catalog import _record_event
            _record_event(
                subject_type='location_mapping_issue', subject_id=obj.pk,
                action='mapping_issue_status_changed', actor=request.user,
                before={'status': previous_status}, after={'status': obj.status},
            )


@admin.register(LocationConfigurationEvent)
class LocationConfigurationEventAdmin(CompactModelAdmin):
    list_display = ('subject_type', 'subject_id', 'action', 'actor', 'occurred_at')
    list_filter = ('subject_type', 'action', 'occurred_at')
    search_fields = ('subject_id', 'request_id')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


PRODUCT_WORKFLOW_CHOICES = [
    ('', 'All workflows'),
    ('jawabu_portal', 'Jawabu Portal'),
    ('loan_origination', 'Loan Origination'),
    ('tat_tracker', 'TAT Tracker'),
    ('spin_credit_analysis', 'SPIN / Credit Analysis'),
    ('order_approval', 'Order Approval'),
    ('complaint_cases', 'Complaint Cases'),
]

PRODUCT_REQUIREMENT_STAGE_CHOICES = [
    ('', 'No transition gate'),
    ('created', 'Case or request creation'),
    ('review', 'Review submission'),
    ('signing', 'Signing preparation'),
    ('completed', 'Analysis completion'),
    ('credit_decision', 'Credit decision'),
    ('final_decision', 'Final decision'),
    ('order', 'Order preparation'),
    ('payment', 'Payment preparation'),
]


class ProductAliasInline(TabularInline):
    model = ProductAlias
    extra = 1
    fields = ('alias',)


class ProductAvailabilityForm(forms.ModelForm):
    workflow = forms.ChoiceField(choices=PRODUCT_WORKFLOW_CHOICES, required=False)

    class Meta:
        model = ProductAvailability
        fields = ('branch', 'workflow', 'channel', 'active')


class ProductAvailabilityInline(TabularInline):
    model = ProductAvailability
    form = ProductAvailabilityForm
    extra = 1
    fields = ('branch', 'workflow', 'channel', 'active')


@admin.register(Product)
class ProductAdmin(CompactModelAdmin):
    """Canonical identity shared by every workflow and external adapter."""

    list_display = ('name', 'code', 'category', 'active', 'current_terms', 'sort_order', 'updated_at')
    list_filter = ('active', 'category')
    search_fields = ('name', 'code', 'aliases__alias')
    ordering = ('sort_order', 'name')
    readonly_fields = ('created_at', 'updated_at', 'terms_link')
    inlines = (ProductAliasInline, ProductAvailabilityInline)
    fieldsets = (
        ('Global identity', {'fields': (('name', 'code'), ('category', 'active'), 'description', 'sort_order')}),
        ('Commercial terms', {'fields': ('terms_link',)}),
        ('Audit', {'fields': (('created_at', 'updated_at'),), 'classes': ('collapse',)}),
    )

    @admin.display(description='Current terms')
    def current_terms(self, obj):
        from core.services.product_catalog import active_product_version
        version = active_product_version(obj)
        return f'v{version.version}' if version else 'Configuration required'

    @admin.display(description='Terms versions')
    def terms_link(self, obj):
        if not obj.pk:
            return 'Save the product before adding commercial terms.'
        url = reverse('admin:core_productversion_changelist') + '?' + urlencode({'product__id__exact': obj.pk})
        add_url = reverse('admin:core_productversion_add') + '?' + urlencode({'product': obj.pk})
        return format_html('<a class="button" href="{}">Manage versions</a> <a class="button" href="{}">Add version</a>', url, add_url)

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj:
            fields.append('code')
        return fields

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


class ProductFeeInline(TabularInline):
    model = ProductFee
    extra = 0
    fields = (
        'position', 'key', 'label', 'fee_type', 'fixed_amount', 'percentage',
        'calculation_basis', 'minimum_amount', 'maximum_amount',
        'collection_mode', 'mandatory',
    )


class ProductRequirementForm(forms.ModelForm):
    workflow = forms.ChoiceField(choices=PRODUCT_WORKFLOW_CHOICES, required=False)
    enforcement_stage = forms.ChoiceField(
        choices=PRODUCT_REQUIREMENT_STAGE_CHOICES, required=False,
        help_text='The workflow transition that must block until this evidence is complete.',
    )
    minimum = forms.DecimalField(required=False, help_text='Optional numeric minimum for amount evidence.')
    maximum = forms.DecimalField(required=False, help_text='Optional numeric maximum for amount evidence.')

    class Meta:
        model = ProductRequirement
        fields = (
            'position', 'key', 'label', 'description', 'requirement_type',
            'workflow', 'enforcement_stage', 'required', 'active',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(PRODUCT_REQUIREMENT_STAGE_CHOICES)
        known = {value for value, _label in choices}
        try:
            for configuration in ProductTatConfiguration.objects.only('stages'):
                for stage in configuration.stages or []:
                    key = str(stage.get('key') or '').strip()
                    label = str(stage.get('label') or key).strip()
                    if key and key not in known:
                        choices.append((key, f'TAT: {label}'))
                        known.add(key)
        except Exception:
            pass
        current_stage = str(getattr(self.instance, 'enforcement_stage', '') or '')
        if current_stage and current_stage not in known:
            choices.append((current_stage, current_stage.replace('_', ' ').title()))
        self.fields['enforcement_stage'].choices = choices
        config = self.instance.validation_config if self.instance.pk else {}
        self.fields['minimum'].initial = config.get('min')
        self.fields['maximum'].initial = config.get('max')

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.validation_config = {
            key: str(value) for key, value in {
                'min': self.cleaned_data.get('minimum'),
                'max': self.cleaned_data.get('maximum'),
            }.items() if value is not None
        }
        if commit:
            instance.save()
        return instance


class ProductRequirementInline(StackedInline):
    model = ProductRequirement
    form = ProductRequirementForm
    extra = 0
    fields = (
        ('position', 'key'), ('label', 'requirement_type'), 'description',
        ('workflow', 'enforcement_stage'), ('required', 'active'), ('minimum', 'maximum'),
    )


class ProductCustomAttributeForm(forms.ModelForm):
    choice_options = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 3}),
        help_text='For Choice attributes, enter one option per line.',
    )
    visible_in_workflows = forms.MultipleChoiceField(
        choices=PRODUCT_WORKFLOW_CHOICES[1:], required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Leave empty to expose this attribute to every workflow.',
    )
    minimum = forms.DecimalField(required=False)
    maximum = forms.DecimalField(required=False)
    pattern = forms.CharField(required=False, help_text='Optional regular expression for text values.')
    default_input = forms.CharField(
        required=False,
        help_text='Optional default shown to staff. For Yes / No use yes or no.',
    )

    class Meta:
        model = ProductCustomAttribute
        fields = ('position', 'key', 'label', 'attribute_type', 'required', 'help_text')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['choice_options'].initial = '\n'.join(str(item) for item in (self.instance.options or []))
        self.fields['visible_in_workflows'].initial = self.instance.workflow_visibility or []
        config = self.instance.validation_config or {}
        self.fields['minimum'].initial = config.get('min')
        self.fields['maximum'].initial = config.get('max')
        self.fields['pattern'].initial = config.get('pattern')
        default = self.instance.default_value
        if isinstance(default, bool):
            default = 'yes' if default else 'no'
        self.fields['default_input'].initial = '' if default is None else str(default)

    def clean_default_input(self):
        value = str(self.cleaned_data.get('default_input') or '').strip()
        attribute_type = self.cleaned_data.get('attribute_type')
        if attribute_type == ProductCustomAttribute.TYPE_BOOLEAN and value.casefold() not in {
            '', 'yes', 'no', 'true', 'false',
        }:
            raise ValidationError('A Yes / No default must be yes or no.')
        return value

    def clean_pattern(self):
        import re
        value = str(self.cleaned_data.get('pattern') or '').strip()
        if value:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValidationError(f'Invalid regular expression: {exc}.') from exc
        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.options = [
            item.strip() for item in self.cleaned_data.get('choice_options', '').splitlines()
            if item.strip()
        ]
        instance.workflow_visibility = list(self.cleaned_data.get('visible_in_workflows') or [])
        instance.validation_config = {
            key: str(value) for key, value in {
                'min': self.cleaned_data.get('minimum'), 'max': self.cleaned_data.get('maximum'),
                'pattern': self.cleaned_data.get('pattern'),
            }.items() if value not in (None, '')
        }
        default = str(self.cleaned_data.get('default_input') or '').strip()
        if not default:
            instance.default_value = None
        elif instance.attribute_type == ProductCustomAttribute.TYPE_BOOLEAN:
            normalized = default.casefold()
            instance.default_value = normalized in {'yes', 'true'}
        else:
            instance.default_value = default
        if commit:
            instance.save()
        return instance


class ProductCustomAttributeInline(StackedInline):
    model = ProductCustomAttribute
    form = ProductCustomAttributeForm
    extra = 0
    fields = (
        ('position', 'key'), ('label', 'attribute_type'), ('required',), 'help_text',
        'choice_options', 'visible_in_workflows', ('minimum', 'maximum'), 'pattern', 'default_input',
    )


class ProductTatConfigurationInline(StackedInline):
    model = ProductTatConfiguration
    extra = 0
    max_num = 1
    fields = (
        ('sheet_name', 'case_prefix'), ('remarks_col', 'status_col', 'tat_start_col'),
        'stage_columns', 'stages', 'stage_tat_columns',
    )
    classes = ('collapse',)


@admin.register(ProductVersion)
class ProductVersionAdmin(CompactModelAdmin):
    list_display = (
        'product', 'version', 'status', 'effective_from', 'effective_to',
        'amount_range', 'interest_summary', 'repayment_frequency', 'published_by',
    )
    list_filter = ('status', 'currency', 'interest_method', 'repayment_frequency', 'product')
    search_fields = ('product__name', 'product__code')
    readonly_fields = ('version', 'status', 'supersedes', 'created_by', 'published_by', 'published_at', 'created_at', 'updated_at')
    actions = ('publish_selected_versions', 'create_next_version')
    inlines = (ProductFeeInline, ProductRequirementInline, ProductCustomAttributeInline, ProductTatConfigurationInline)
    fieldsets = (
        ('Version', {'fields': (('product', 'version', 'status'), ('effective_from', 'effective_to'), 'supersedes')}),
        ('Amount and tenor', {'fields': (('currency', 'min_amount', 'max_amount'), ('min_tenor', 'max_tenor', 'tenor_unit'))}),
        ('Interest and repayment', {'fields': (
            ('interest_method', 'interest_rate', 'interest_rate_period'), 'repayment_frequency',
            ('quote_amount_field_key', 'quote_tenor_field_key'),
        )}),
        ('Publication audit', {'fields': (('created_by', 'created_at'), ('published_by', 'published_at'), 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='Amount range')
    def amount_range(self, obj):
        maximum = f'{obj.max_amount:,.2f}' if obj.max_amount is not None else 'No maximum'
        return f'{obj.currency} {obj.min_amount:,.2f} – {maximum}'

    @admin.display(description='Interest')
    def interest_summary(self, obj):
        return f'{obj.interest_rate}% {obj.interest_rate_period} · {obj.get_interest_method_display()}'

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != obj.STATUS_DRAFT:
            return tuple(field.name for field in self.model._meta.fields)
        return self.readonly_fields

    def get_inline_instances(self, request, obj=None):
        instances = super().get_inline_instances(request, obj)
        if obj and obj.status != obj.STATUS_DRAFT:
            for inline in instances:
                inline.has_add_permission = lambda request, obj=None: False
                inline.has_change_permission = lambda request, obj=None: False
                inline.has_delete_permission = lambda request, obj=None: False
        return instances

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            raise PermissionDenied
        if change and obj.status != obj.STATUS_DRAFT:
            raise PermissionDenied
        if not change:
            obj.version = (ProductVersion.objects.filter(product=obj.product).aggregate(models.Max('version'))['version__max'] or 0) + 1
            obj.created_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)

    @admin.action(description='Publish selected product version')
    def publish_selected_versions(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one product version.', level=messages.ERROR)
            return
        from core.services.product_catalog import ProductCatalogError, publish_product_version
        try:
            version = publish_product_version(version=queryset.first(), actor=request.user)
        except (ProductCatalogError, ValidationError) as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, f'{version} is {version.status}.', level=messages.SUCCESS)

    @admin.action(description='Create editable next version')
    def create_next_version(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one product version.', level=messages.ERROR)
            return
        from core.services.product_catalog import clone_product_version
        version = clone_product_version(queryset.first(), actor=request.user)
        return HttpResponseRedirect(reverse('admin:core_productversion_change', args=[version.pk]))

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductMappingIssue)
class ProductMappingIssueAdmin(CompactModelAdmin):
    list_display = ('raw_value', 'source_workflow', 'source_model', 'source_record_id', 'status', 'product', 'created_at')
    list_filter = ('status', 'source_workflow', 'source_model')
    search_fields = ('raw_value', 'normalized_value', 'source_record_id')
    readonly_fields = ('raw_value', 'normalized_value', 'source_workflow', 'source_model', 'source_record_id', 'status', 'resolved_by', 'resolved_at', 'created_at')

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            raise PermissionDenied
        if obj.product_id and obj.status == obj.STATUS_OPEN:
            from core.services.product_catalog import resolve_product_mapping_issue
            resolve_product_mapping_issue(obj, product=obj.product, actor=request.user)
            return
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductVersionEvent)
class ProductVersionEventAdmin(CompactModelAdmin):
    list_display = ('product_version', 'action', 'actor', 'occurred_at')
    list_filter = ('action', 'occurred_at')
    search_fields = ('product_version__product__name', 'product_version__product__code')

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class JawabuCustomerPhoneHistoryInline(TabularInline):
    model = JawabuCustomerPhoneHistory
    extra = 0
    fields = ('phone', 'source', 'is_current', 'first_seen_at', 'last_seen_at')
    readonly_fields = ('first_seen_at', 'last_seen_at')


@admin.register(JawabuCustomer)
class JawabuCustomerAdmin(CompactModelAdmin):
    list_display = ('national_id', 'primary_phone', 'customer_no', 'identity_enforced', 'updated_at')
    list_filter = ('identity_enforced',)
    search_fields = ('national_id', 'primary_phone', 'customer_no')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (JawabuCustomerPhoneHistoryInline,)
    fieldsets = (
        ('Customer identity', {
            'fields': (
                ('national_id', 'primary_phone'),
                ('customer_no', 'identity_enforced'),
            ),
        }),
        ('Audit', {
            'fields': (('created_at', 'updated_at'),),
            'classes': ('collapse',),
        }),
    )


class GovernedConfigurationAuditAdmin(CompactModelAdmin):
    """Show governed configuration evidence without a direct admin write path."""

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BusinessCalendarHoliday)
class BusinessCalendarHolidayAdmin(GovernedConfigurationAuditAdmin):
    """Calendar evidence is inspected here; changes use the TAT reviewer flow."""

    list_display = ('date', 'name', 'active', 'updated_at')
    list_filter = ('active',)
    search_fields = ('name',)
    ordering = ('date',)


@admin.register(TatEscalationRule)
class TatEscalationRuleAdmin(GovernedConfigurationAuditAdmin):
    """Approved escalation rules are immutable evidence, not admin toggles."""

    list_display = ('group_configuration', 'branch', 'threshold_percent', 'routing_role', 'active', 'approved_by', 'approved_at')
    list_filter = ('active', 'routing_role', 'branch')
    search_fields = ('group_configuration__display_name', 'group_configuration__group_id', 'branch')


@admin.register(WorkflowConfigurationChangeRequest)
class WorkflowConfigurationChangeRequestAdmin(GovernedConfigurationAuditAdmin):
    list_display = ('setting_key', 'group_configuration', 'status', 'requested_by', 'requested_at', 'reviewed_by', 'reviewed_at')
    list_filter = ('setting_key', 'status', 'workflow')
    search_fields = ('reason', 'requested_by__username', 'reviewed_by__username', 'group_configuration__display_name')


@admin.register(UserMiniAppPreference)
class UserMiniAppPreferenceAdmin(CompactModelAdmin):
    list_display = ('user', 'workflow', 'default_screen', 'compact_cards', 'alert_mode', 'updated_at')
    list_filter = ('workflow', 'alert_mode', 'compact_cards')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    readonly_fields = ('user', 'workflow', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(JawabuPipelineEvent)
class JawabuPipelineEventAdmin(CompactModelAdmin):
    list_display = ('farmer', 'action', 'transition_code', 'from_state', 'to_state', 'actor', 'occurred_at')
    list_filter = ('action', 'stage_key', 'transition_code', 'source', 'occurred_at')
    search_fields = ('farmer__national_id', 'farmer__primary_phone', 'actor')
    readonly_fields = ('farmer', 'action', 'stage_key', 'actor', 'actor_telegram_id', 'actor_user', 'authority_user', 'source', 'request_id', 'transition_code', 'from_state', 'to_state', 'reason', 'revision_before', 'revision_after', 'old_values', 'new_values', 'metadata', 'occurred_at', 'created_at')


@admin.register(WorkflowSlaEscalation)
class WorkflowSlaEscalationAdmin(CompactModelAdmin):
    list_display = ('workflow', 'subject_id', 'branch', 'stage_key', 'responsible_role', 'responsible_actor', 'escalation_level', 'overdue_minutes', 'status', 'escalation_date')
    list_filter = ('workflow', 'status', 'escalation_level', 'stage_key', 'branch', 'escalation_date')
    search_fields = ('subject_id', 'group_id', 'branch', 'stage_key', 'responsible_role', 'responsible_actor')
    readonly_fields = ('workflow', 'subject_id', 'group_id', 'stage_key', 'branch', 'responsible_role', 'responsible_actor', 'target_minutes', 'overdue_minutes', 'escalation_level', 'threshold_percent', 'escalation_date', 'created_at', 'acknowledged_at', 'resolved_at')

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == 'resolved':
            return [field.name for field in self.model._meta.fields]
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        # Escalation rows are daily, idempotent operational records.  Record
        # the human acknowledgement/resolution rather than leaving a status
        # flip with no accountable actor or timestamp.
        now = timezone.now()
        if obj.status == 'acknowledged' and not obj.acknowledged_at:
            obj.acknowledged_by = request.user
            obj.acknowledged_at = now
        elif obj.status == 'resolved' and not obj.resolved_at:
            obj.resolved_by = request.user
            obj.resolved_at = now
        super().save_model(request, obj, form, change)


@admin.register(JawabuDataQualityIssue)
class JawabuDataQualityIssueAdmin(CompactModelAdmin):
    list_display = ('farmer', 'field_name', 'code', 'severity', 'active', 'detected_at', 'resolved_at')
    list_filter = ('active', 'severity', 'field_name', 'code')
    search_fields = ('farmer__customer_name', 'farmer__national_id', 'message')
    readonly_fields = ('farmer', 'field_name', 'code', 'severity', 'message', 'active', 'detected_at', 'resolved_at')

    def save_formset(self, request, form, formset, change):
        """Resolution evidence is append-only and always records the staff actor."""
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, JawabuDataQualityResolution):
                if not instance.pk:
                    instance.actor = request.user.get_username()
                instance.save()
                issue = instance.issue
                if issue.active:
                    issue.active = False
                    issue.resolved_at = timezone.now()
                    issue.save(update_fields=['active', 'resolved_at'])
        formset.save_m2m()


class JawabuDataQualityResolutionInline(TabularInline):
    model = JawabuDataQualityResolution
    extra = 0
    fields = ('action', 'note', 'actor', 'before_value', 'after_value', 'created_at')
    readonly_fields = ('actor', 'created_at')
    can_delete = False


JawabuDataQualityIssueAdmin.inlines = (JawabuDataQualityResolutionInline,)


@admin.register(JawabuCustomerFieldProvenance)
class JawabuCustomerFieldProvenanceAdmin(CompactModelAdmin):
    list_display = ('farmer', 'field_name', 'source', 'source_reference', 'source_row_number', 'actor', 'occurred_at')
    list_filter = ('source', 'field_name', 'occurred_at')
    search_fields = ('farmer__customer_name', 'farmer__national_id', 'source_reference', 'actor')
    readonly_fields = (
        'farmer', 'field_name', 'old_value', 'new_value', 'source', 'source_reference',
        'source_row_number', 'actor', 'occurred_at',
    )


def _tat_target_field_name(product_key: str, target_key: str) -> str:
    safe_key = str(target_key).replace('-', '_')
    return f'tat_target_{product_key}_{safe_key}'


def _tat_target_form_field(product_key: str, target_key: str) -> forms.IntegerField:
    product = PRODUCTS[product_key]
    if target_key == 'total':
        label = f'{product.label} total target minutes'
        help_text = 'Overall case SLA target in minutes.'
    else:
        stage = next(stage for stage in product.stages if stage.key == target_key)
        label = f'{product.label}: {stage.label} target minutes'
        help_text = 'Leave blank to show TAT without SLA status for this stage.'
    return forms.IntegerField(
        required=False,
        min_value=0,
        label=label,
        help_text=help_text,
    )


TAT_TARGET_FIELD_GROUPS = []
for _product_key, _product in PRODUCTS.items():
    _fields = [_tat_target_field_name(_product_key, 'total')]
    _fields.extend(
        _tat_target_field_name(_product_key, stage.key)
        for stage in _product.stages
    )
    TAT_TARGET_FIELD_GROUPS.append((_product_key, _product.label, tuple(_fields)))


class ReadOnlyAuditAdmin(ModelAdmin):
    """Prevent admin edits that would not be written back to the live sheet."""

    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TestDataDeleteAdmin(ReadOnlyAuditAdmin):
    """Allow scoped cleanup of test records without enabling production deletes."""

    def has_delete_permission(self, request, obj=None):
        delete_enabled = bool(
            getattr(settings, 'DEBUG', False)
            or getattr(settings, 'ALLOW_ADMIN_AUDIT_DELETE', False)
        )
        return delete_enabled and bool(request.user and request.user.is_superuser)


class GroupSheetConfigurationAdminForm(forms.ModelForm):
    """Admin helper that can generate workflow JSON from a simple preset."""

    workflow_preset = forms.ChoiceField(
        choices=preset_choices,
        required=False,
        initial=MANUAL_PRESET,
        help_text=(
            'Select a preset to generate workflow JSON automatically. '
            'Choose Manual JSON for custom workflows.'
        ),
    )
    jawabu_tat_targets_minutes = forms.JSONField(
        required=False,
        initial={'overall': None, 'stages': {}},
        label='Jawabu Portal TAT targets (minutes)',
        help_text='Optional overall and per-stage targets, stored as minutes.',
        widget=forms.Textarea(attrs={'rows': 5, 'cols': 80}),
    )
    case_header_row = forms.IntegerField(
        required=False,
        min_value=1,
        initial=get_preset('case')['admin_fields']['header_row']['initial'],
        label=get_preset('case')['admin_fields']['header_row']['label'],
        help_text=get_preset('case')['admin_fields']['header_row']['help_text'],
    )
    case_field_headers = forms.JSONField(
        required=False,
        initial=get_preset('case')['admin_fields']['field_headers']['initial'],
        label=get_preset('case')['admin_fields']['field_headers']['label'],
        help_text=get_preset('case')['admin_fields']['field_headers']['help_text'],
        widget=forms.Textarea(attrs={'rows': 6, 'cols': 80}),
    )
    order_approval_search_tabs = forms.CharField(
        required=False,
        initial=get_preset('order_approval')['admin_fields']['search_tabs']['initial'],
        label=get_preset('order_approval')['admin_fields']['search_tabs']['label'],
        help_text=get_preset('order_approval')['admin_fields']['search_tabs']['help_text'],
    )
    order_approval_match_field = forms.ChoiceField(
        choices=get_preset('order_approval')['admin_fields']['match_field']['choices'],
        required=False,
        initial=get_preset('order_approval')['admin_fields']['match_field']['initial'],
        label=get_preset('order_approval')['admin_fields']['match_field']['label'],
        help_text=get_preset('order_approval')['admin_fields']['match_field']['help_text'],
    )
    order_approval_media_field = forms.ChoiceField(
        choices=get_preset('order_approval')['admin_fields']['media_field']['choices'],
        required=False,
        initial=get_preset('order_approval')['admin_fields']['media_field']['initial'],
        label=get_preset('order_approval')['admin_fields']['media_field']['label'],
        help_text=get_preset('order_approval')['admin_fields']['media_field']['help_text'],
    )
    order_approval_header_row = forms.IntegerField(
        required=False,
        min_value=1,
        initial=get_preset('order_approval')['admin_fields']['header_row']['initial'],
        label=get_preset('order_approval')['admin_fields']['header_row']['label'],
        help_text=get_preset('order_approval')['admin_fields']['header_row']['help_text'],
    )
    order_approval_media_root_folder = forms.CharField(
        required=False,
        initial=get_preset('order_approval')['admin_fields']['media_root_folder']['initial'],
        label=get_preset('order_approval')['admin_fields']['media_root_folder']['label'],
        help_text=get_preset('order_approval')['admin_fields']['media_root_folder']['help_text'],
    )
    spin_header_row = forms.IntegerField(
        required=False,
        min_value=1,
        initial=get_preset('spin_credit_analysis')['admin_fields']['header_row']['initial'],
        label=get_preset('spin_credit_analysis')['admin_fields']['header_row']['label'],
        help_text=get_preset('spin_credit_analysis')['admin_fields']['header_row']['help_text'],
    )
    spin_legacy_batch_sheet_name = forms.CharField(
        required=False,
        initial=get_preset('spin_credit_analysis')['admin_fields']['legacy_batch_sheet_name']['initial'],
        label=get_preset('spin_credit_analysis')['admin_fields']['legacy_batch_sheet_name']['label'],
        help_text=get_preset('spin_credit_analysis')['admin_fields']['legacy_batch_sheet_name']['help_text'],
    )
    spin_branches = forms.MultipleChoiceField(
        choices=(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='SPIN group branches',
        help_text=(
            'Branches this Telegram group may submit or edit. Choices come from '
            'the global WORKFLOW_BRANCH_CHOICES setting.'
        ),
    )
    spin_default_branch = forms.ChoiceField(
        choices=(),
        required=False,
        label='Default SPIN branch',
        help_text=(
            'Preselect a branch for new SPIN requests. Leave blank when staff '
            'must select a branch each time.'
        ),
    )

    jawabu_import_start_date = forms.DateField(
        required=False,
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=get_preset('jawabu_homebiogas')['admin_fields']['import_start_date']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['import_start_date']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['import_start_date']['help_text'],
    )

    jawabu_master_sync_enabled = forms.BooleanField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['master_sync_enabled']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['master_sync_enabled']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['master_sync_enabled']['help_text'],
    )
    jawabu_master_sheet_id = forms.CharField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['master_sheet_id']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['master_sheet_id']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['master_sheet_id']['help_text'],
    )
    jawabu_master_sheet_name = forms.CharField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['master_sheet_name']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['master_sheet_name']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['master_sheet_name']['help_text'],
    )
    jawabu_master_header_row = forms.IntegerField(
        required=False,
        min_value=1,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['master_header_row']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['master_header_row']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['master_header_row']['help_text'],
    )
    jawabu_master_data_start_row = forms.IntegerField(
        required=False,
        min_value=1,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['master_data_start_row']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['master_data_start_row']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['master_data_start_row']['help_text'],
    )
    jawabu_master_import_log_sheet_name = forms.CharField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['master_import_log_sheet_name']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['master_import_log_sheet_name']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['master_import_log_sheet_name']['help_text'],
    )

    jawabu_internal_order_sync_enabled = forms.BooleanField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sync_enabled']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sync_enabled']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sync_enabled']['help_text'],
    )
    jawabu_internal_order_sheet_id = forms.CharField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sheet_id']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sheet_id']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sheet_id']['help_text'],
    )
    jawabu_internal_order_sheet_name = forms.CharField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sheet_name']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sheet_name']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_sheet_name']['help_text'],
    )
    jawabu_internal_order_header_row = forms.IntegerField(
        required=False,
        min_value=1,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_header_row']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_header_row']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_header_row']['help_text'],
    )
    jawabu_internal_order_data_start_row = forms.IntegerField(
        required=False,
        min_value=1,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_data_start_row']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_data_start_row']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_data_start_row']['help_text'],
    )
    jawabu_internal_order_record_id_prefix = forms.CharField(
        required=False,
        initial=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_record_id_prefix']['initial'],
        label=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_record_id_prefix']['label'],
        help_text=get_preset('jawabu_homebiogas')['admin_fields']['internal_order_record_id_prefix']['help_text'],
    )

    mini_app_launchers = forms.MultipleChoiceField(
        choices=MINI_APP_LAUNCHER_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Pinned JBL Apps',
        help_text='Choose the generic Mini Apps available from this group\'s pinned JBL Apps message.',
    )
    class Meta:
        model = GroupSheetConfiguration
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workflow = getattr(self.instance, 'workflow', None) or {}
        self._set_spin_branch_choices(workflow)
        configured_launchers = workflow.get('mini_app_launchers')
        selected_launchers = (
            configured_launchers
            if isinstance(configured_launchers, list)
            else default_launcher_keys(workflow)
        )
        self.fields['mini_app_launchers'].initial = selected_launchers
        self.initial['mini_app_launchers'] = selected_launchers
        preset_key = preset_for_workflow(workflow)
        self.fields['workflow_preset'].initial = preset_key
        if preset_key == 'case':
            self.fields['workflow_preset'].initial = 'case'
            defaults = defaults_for_preset('case')
            sheet_schema = getattr(self.instance, 'sheet_schema', None) or {}
            self.fields['case_header_row'].initial = (
                sheet_schema.get('header_row')
                or workflow.get('header_row')
                or defaults['workflow'].get('header_row', 1)
            )
            self.fields['case_field_headers'].initial = (
                sheet_schema.get('field_headers')
                or sheet_schema.get('headers')
                or defaults['sheet_schema'].get('field_headers', {})
            )
        if preset_key == 'order_approval':
            self.fields['workflow_preset'].initial = 'order_approval'
            self.fields['order_approval_search_tabs'].initial = ', '.join(
                workflow.get('search_sheet_names')
                or defaults_for_preset('order_approval')['workflow']['search_sheet_names']
            )
            self.fields['order_approval_match_field'].initial = (
                workflow.get('match_field')
                or defaults_for_preset('order_approval')['workflow']['match_field']
            )
            self.fields['order_approval_media_field'].initial = (
                workflow.get('media_field')
                or defaults_for_preset('order_approval')['workflow']['media_field']
            )
            self.fields['order_approval_header_row'].initial = (
                workflow.get('header_row')
                or defaults_for_preset('order_approval')['workflow']['header_row']
            )
            self.fields['order_approval_media_root_folder'].initial = (
                workflow.get('media_root_folder')
                or defaults_for_preset('order_approval')['workflow'].get('media_root_folder', '')
            )
        if preset_key == 'spin_credit_analysis':
            self.fields['workflow_preset'].initial = 'spin_credit_analysis'
            defaults = defaults_for_preset('spin_credit_analysis')['workflow']
            self.fields['spin_header_row'].initial = (
                workflow.get('header_row')
                or defaults.get('header_row', 1)
            )
            self.fields['spin_legacy_batch_sheet_name'].initial = (
                workflow.get('legacy_batch_sheet_name')
                or defaults.get('legacy_batch_sheet_name', 'SPIN Legacy Batch')
            )
        if preset_key == 'tat_tracker':
            self.fields['workflow_preset'].initial = 'tat_tracker'
        if preset_key == 'tat_tracker' or workflow.get('tat_targets_minutes'):
            self._populate_tat_target_initials(workflow)
        if preset_key == 'jawabu_homebiogas':
            self.fields['workflow_preset'].initial = 'jawabu_homebiogas'
            defaults = defaults_for_preset('jawabu_homebiogas')['workflow']
            self.fields['jawabu_tat_targets_minutes'].initial = workflow.get('jawabu_tat_targets_minutes') or {'overall': None, 'stages': {}}
            self.fields['jawabu_import_start_date'].initial = (
                workflow.get('import_start_date')
                or defaults.get('import_start_date')
            )
            self.fields['jawabu_master_sync_enabled'].initial = bool(
                workflow.get('master_sync_enabled', defaults.get('master_sync_enabled'))
            )
            self.fields['jawabu_master_sheet_id'].initial = (
                workflow.get('master_sheet_id')
                or defaults.get('master_sheet_id', '')
            )
            self.fields['jawabu_master_sheet_name'].initial = (
                workflow.get('master_sheet_name')
                or defaults.get('master_sheet_name', 'Master Data')
            )
            self.fields['jawabu_master_header_row'].initial = (
                workflow.get('master_header_row')
                or defaults.get('master_header_row', 3)
            )
            self.fields['jawabu_master_data_start_row'].initial = (
                workflow.get('master_data_start_row')
                or defaults.get('master_data_start_row', 5)
            )
            self.fields['jawabu_master_import_log_sheet_name'].initial = (
                workflow.get('master_import_log_sheet_name')
                or defaults.get('master_import_log_sheet_name', 'Farmers Upload Log')
            )
            self.fields['jawabu_internal_order_sync_enabled'].initial = bool(
                workflow.get('internal_order_sync_enabled', defaults.get('internal_order_sync_enabled'))
            )
            self.fields['jawabu_internal_order_sheet_id'].initial = (
                workflow.get('internal_order_sheet_id')
                or defaults.get('internal_order_sheet_id', '')
            )
            self.fields['jawabu_internal_order_sheet_name'].initial = (
                workflow.get('internal_order_sheet_name')
                or defaults.get('internal_order_sheet_name', 'Orders')
            )
            self.fields['jawabu_internal_order_header_row'].initial = (
                workflow.get('internal_order_header_row')
                or defaults.get('internal_order_header_row', 2)
            )
            self.fields['jawabu_internal_order_data_start_row'].initial = (
                workflow.get('internal_order_data_start_row')
                or defaults.get('internal_order_data_start_row', 3)
            )
            self.fields['jawabu_internal_order_record_id_prefix'].initial = (
                workflow.get('internal_order_record_id_prefix')
                or defaults.get('internal_order_record_id_prefix', 'JBL')
            )

    def _set_spin_branch_choices(self, workflow: dict) -> None:
        configured = configured_workflow_branches(
            workflow,
            default=global_branch_choices(),
        )
        available = list(dict.fromkeys([
            *global_branch_choices(),
            *configured,
            str(workflow.get('default_branch') or '').strip(),
        ]))
        available = [branch for branch in available if branch]
        self.fields['spin_branches'].choices = [
            (branch, branch) for branch in available
        ]
        self.fields['spin_default_branch'].choices = [
            ('', 'No default — staff select a branch'),
            *[(branch, branch) for branch in configured],
        ]
        default_branch = str(workflow.get('default_branch') or '').strip()
        if default_branch not in configured:
            default_branch = ''
        self.fields['spin_branches'].initial = configured
        self.initial['spin_branches'] = configured
        self.fields['spin_default_branch'].initial = default_branch
        self.initial['spin_default_branch'] = default_branch

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('workflow_preset') == MANUAL_PRESET:
            return cleaned

        if cleaned.get('workflow_preset') == 'order_approval':
            tabs = self.order_approval_tabs()
            if not tabs:
                self.add_error(
                    'order_approval_search_tabs',
                    'Enter at least one worksheet tab.',
                )
        return cleaned

    def clean_spin_default_branch(self):
        default_branch = str(self.cleaned_data.get('spin_default_branch') or '').strip()
        selected_branches = self.cleaned_data.get('spin_branches') or []
        if default_branch and default_branch not in selected_branches:
            raise forms.ValidationError(
                'The default SPIN branch must be one of the selected group branches.'
            )
        return default_branch

    def order_approval_tabs(self) -> list[str]:
        raw = self.cleaned_data.get('order_approval_search_tabs', '')
        return [
            tab.strip()
            for tab in str(raw or '').split(',')
            if tab.strip()
        ]

    def generated_workflow(self) -> dict | None:
        preset_key = self.cleaned_data.get('workflow_preset') or MANUAL_PRESET
        if preset_key == MANUAL_PRESET:
            workflow = dict(self.cleaned_data.get('workflow') or {})
            existing_workflow = getattr(self.instance, 'workflow', None) or {}
            self._apply_selected_launchers(workflow)
            if workflow.get('type') in {'jawabu', 'jawabu_homebiogas'} or workflow.get('master_sync_enabled'):
                workflow['jawabu_tat_targets_minutes'] = self.cleaned_data.get('jawabu_tat_targets_minutes') or {'overall': None, 'stages': {}}
            if (
                workflow.get('type') == 'tat_tracker'
                or existing_workflow.get('type') == 'tat_tracker'
                or workflow.get('tat_targets_minutes')
                or existing_workflow.get('tat_targets_minutes')
            ):
                workflow['tat_targets_minutes'] = self.tat_targets_minutes()
                return workflow
            return workflow
        workflow = build_workflow_from_preset(
            preset_key,
            overrides={
                'case_header_row': self.cleaned_data.get('case_header_row'),
                'search_sheet_names': self.order_approval_tabs(),
                'match_field': self.cleaned_data.get('order_approval_match_field'),
                'media_field': self.cleaned_data.get('order_approval_media_field'),
                'header_row': self.cleaned_data.get('order_approval_header_row'),
                'legacy_batch_sheet_name': self.cleaned_data.get('spin_legacy_batch_sheet_name'),
                'spin_header_row': self.cleaned_data.get('spin_header_row'),
                'spin_branches': self.cleaned_data.get('spin_branches'),
                'spin_default_branch': self.cleaned_data.get('spin_default_branch'),
                'media_root_folder': self.cleaned_data.get(
                    'order_approval_media_root_folder'
                ),
                'import_start_date': self.cleaned_data.get('jawabu_import_start_date'),
                'master_sync_enabled': self.cleaned_data.get('jawabu_master_sync_enabled'),
                'master_sheet_id': self.cleaned_data.get('jawabu_master_sheet_id'),
                'master_sheet_name': self.cleaned_data.get('jawabu_master_sheet_name'),
                'master_header_row': self.cleaned_data.get('jawabu_master_header_row'),
                'master_data_start_row': self.cleaned_data.get('jawabu_master_data_start_row'),
                'master_import_log_sheet_name': self.cleaned_data.get('jawabu_master_import_log_sheet_name'),
                'internal_order_sync_enabled': self.cleaned_data.get('jawabu_internal_order_sync_enabled'),
                'internal_order_sheet_id': self.cleaned_data.get('jawabu_internal_order_sheet_id'),
                'internal_order_sheet_name': self.cleaned_data.get('jawabu_internal_order_sheet_name'),
                'internal_order_header_row': self.cleaned_data.get('jawabu_internal_order_header_row'),
                'internal_order_data_start_row': self.cleaned_data.get('jawabu_internal_order_data_start_row'),
                'internal_order_record_id_prefix': self.cleaned_data.get('jawabu_internal_order_record_id_prefix'),
                'existing_workflow': getattr(self.instance, 'workflow', None) or {},
                'tat_targets_minutes': self.tat_targets_minutes(),
            },
        )
        self._apply_selected_launchers(workflow)
        if preset_key == 'jawabu_homebiogas':
            workflow['jawabu_tat_targets_minutes'] = self.cleaned_data.get('jawabu_tat_targets_minutes') or {'overall': None, 'stages': {}}
        return workflow

    def _apply_selected_launchers(self, workflow: dict) -> None:
        """Keep no selection as the workflow default instead of disabling every app."""
        selected = list(self.cleaned_data.get('mini_app_launchers') or [])
        if selected:
            workflow['mini_app_launchers'] = selected
        else:
            workflow.pop('mini_app_launchers', None)

    def tat_targets_minutes(self) -> dict:
        existing_workflow = (
            self.cleaned_data.get('workflow')
            or getattr(self.instance, 'workflow', None)
            or {}
        )
        current_targets = existing_workflow.get('tat_targets_minutes') or {}
        targets = {
            product_key: {
                'total': product_targets.get('total'),
                'stages': dict(product_targets.get('stages') or {}),
            }
            for product_key, product_targets in current_targets.items()
            if isinstance(product_targets, dict)
        }
        for product_key, _label, field_names in TAT_TARGET_FIELD_GROUPS:
            product_targets = targets.setdefault(product_key, {'stages': {}})
            product_targets.setdefault('stages', {})
            total_field = _tat_target_field_name(product_key, 'total')
            total = self.cleaned_data.get(total_field)
            if total is not None:
                product_targets['total'] = int(total)
            for field_name in field_names:
                stage_key = field_name.replace(f'tat_target_{product_key}_', '', 1)
                if stage_key == 'total':
                    continue
                value = self.cleaned_data.get(field_name)
                if value is not None:
                    product_targets['stages'][stage_key] = int(value)
        return {
            product_key: {
                key: value
                for key, value in product_targets.items()
                if key != 'stages' or value
            }
            for product_key, product_targets in targets.items()
            if product_targets.get('total') is not None or product_targets.get('stages')
        }

    def _populate_tat_target_initials(self, workflow: dict):
        targets = workflow.get('tat_targets_minutes') or {}
        defaults = defaults_for_preset('tat_tracker')['workflow'].get('tat_targets_minutes') or {}
        for product_key, _product_label, field_names in TAT_TARGET_FIELD_GROUPS:
            product_targets = targets.get(product_key) or defaults.get(product_key) or {}
            stage_targets = product_targets.get('stages') or {}
            total_field = _tat_target_field_name(product_key, 'total')
            self.fields[total_field].initial = product_targets.get('total')
            self.initial[total_field] = product_targets.get('total')
            for field_name in field_names:
                stage_key = field_name.replace(f'tat_target_{product_key}_', '', 1)
                if stage_key == 'total':
                    continue
                value = stage_targets.get(stage_key)
                self.fields[field_name].initial = value
                self.initial[field_name] = value

    def generated_sheet_schema(self) -> dict | None:
        preset_key = self.cleaned_data.get('workflow_preset') or MANUAL_PRESET
        if preset_key != 'case':
            return None
        defaults = defaults_for_preset('case').get('sheet_schema') or {}
        schema = dict(defaults)
        header_row = self.cleaned_data.get('case_header_row')
        if header_row:
            schema['header_row'] = max(int(header_row), 1)
        field_headers = self.cleaned_data.get('case_field_headers') or {}
        if field_headers:
            schema['field_headers'] = dict(field_headers)
        else:
            schema['field_headers'] = {}
        return schema

    def apply_preset_defaults(self, obj):
        preset_key = self.cleaned_data.get('workflow_preset') or MANUAL_PRESET
        defaults = defaults_for_preset(preset_key)
        if defaults.get('sheet_name') and not obj.sheet_name:
            obj.sheet_name = defaults['sheet_name']
        if defaults.get('sheet_schema') is not None and not obj.sheet_schema:
            obj.sheet_schema = defaults['sheet_schema']
        if defaults.get('parser_rules') is not None and not obj.parser_rules:
            obj.parser_rules = defaults['parser_rules']


for _product_key, _product_label, _field_names in TAT_TARGET_FIELD_GROUPS:
    for _field_name in _field_names:
        _target_key = _field_name.replace(f'tat_target_{_product_key}_', '', 1)
        _field = _tat_target_form_field(_product_key, _target_key)
        GroupSheetConfigurationAdminForm.base_fields[_field_name] = _field
        GroupSheetConfigurationAdminForm.declared_fields[_field_name] = _field


@admin.register(TatTrackerCase)
class TatTrackerCaseAdmin(TestDataDeleteAdmin):
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = [
        'case_id', 'group_id', 'product_label', 'client_name', 'branch',
        'status', 'current_stage', 'is_deleted', 'deleted_at', 'updated_at',
    ]
    list_filter = ['is_deleted', 'group_id', 'product_key', 'branch', 'status', 'current_stage']
    search_fields = ['case_id', 'client_name', 'national_id', 'primary_phone', 'bro_name', 'branch']
    actions = ['mark_selected_deleted']

    def has_delete_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def delete_model(self, request, obj):
        deleted = soft_delete_tat_case(
            obj,
            actor_name=request.user.get_username(),
            actor_role='ADMIN',
            reason='Deleted from Django admin.',
        )
        if deleted:
            self.message_user(request, f'{obj.case_id} marked as deleted. Audit event preserved.', messages.SUCCESS)
        else:
            self.message_user(request, f'{obj.case_id} was already marked as deleted.', messages.WARNING)

    def delete_queryset(self, request, queryset):
        deleted_count = 0
        with transaction.atomic():
            for case in queryset.select_for_update():
                if soft_delete_tat_case(
                    case,
                    actor_name=request.user.get_username(),
                    actor_role='ADMIN',
                    reason='Bulk deleted from Django admin.',
                ):
                    deleted_count += 1
        self.message_user(request, f'{deleted_count} TAT case(s) marked as deleted. Audit events preserved.', messages.SUCCESS)

    @admin.action(description='Mark selected TAT cases as deleted')
    def mark_selected_deleted(self, request, queryset):
        self.delete_queryset(request, queryset)


@admin.register(TatTrackerEvent)
class TatTrackerEventAdmin(ReadOnlyAuditAdmin):
    list_display = ['case', 'stage_label', 'transition_code', 'from_state', 'to_state', 'actor_name', 'source', 'synced_to_sheet', 'created_at']
    list_filter = ['group_id', 'source', 'stage_key', 'transition_code', 'synced_to_sheet', 'created_at']
    search_fields = ['case__case_id', 'case__client_name', 'actor_name', 'stage_label']


@admin.register(RawMessage)
class RawMessageAdmin(ReadOnlyAuditAdmin):
    list_display = ['sender', 'received_at', 'has_image', 'created_at']
    list_filter = ['has_image', 'received_at']
    search_fields = ['sender', 'content']
    readonly_fields = ['id', 'created_at']


@admin.register(ProcessedMessage)
class ProcessedMessageAdmin(ReadOnlyAuditAdmin):
    list_display = ['message_hash', 'status', 'processed_at']
    list_filter = ['status', 'processed_at']
    search_fields = ['message_hash']
    readonly_fields = ['id', 'processed_at']


@admin.register(ParsedMessage)
class ParsedMessageAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'message_id', 'group_id', 'sheet_name', 'sender', 'customer_name',
        'customer_phone', 'complaint_status', 'synced_to_sheets', 'timestamp'
    ]
    list_filter = [
        'group_id', 'sheet_id', 'sheet_name', 'synced_to_sheets',
        'image_flag', 'complaint_status', 'timestamp',
    ]
    search_fields = [
        'sender', 'customer_name', 'customer_phone', 'customer_id',
        'message_id', 'sheet_id',
    ]
    readonly_fields = ['id', 'created_at', 'synced_at']


@admin.register(CaseUpdate)
class CaseUpdateAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'parsed_message', 'group_id', 'updated_by', 'old_status',
        'new_status', 'sync_status', 'created_at',
    ]
    list_filter = ['group_id', 'new_status', 'sync_status', 'created_at']
    search_fields = [
        'parsed_message__message_id', 'parsed_message__customer_name',
        'updated_by', 'resolution_text', 'raw_update_text',
    ]
    readonly_fields = ['id', 'created_at']


@admin.register(OrderApprovalUpdate)
class OrderApprovalUpdateAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'id_number', 'group_id', 'sheet_tab', 'row_number', 'sender',
        'update_status', 'created_at',
    ]
    list_filter = ['group_id', 'sheet_id', 'sheet_tab', 'update_status', 'created_at']
    search_fields = [
        'id_number', 'sender', 'telegram_message_id', 'raw_text',
        'sheet_id', 'sheet_tab',
    ]
    readonly_fields = ['id', 'created_at']


@admin.register(MediaAttachment)
class MediaAttachmentAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'jawabu_farmer', 'business_key_value', 'group_id', 'file_type', 'original_filename',
        'storage_provider', 'upload_status', 'captured_at', 'created_at',
    ]
    list_filter = [
        'group_id', 'file_type', 'storage_provider', 'upload_status', 'jawabu_farmer', 'created_at',
    ]
    search_fields = [
        'business_key_value', 'telegram_file_id', 'original_filename',
        'drive_file_id', 'drive_url', 'content_hash',
    ]
    readonly_fields = [field.name for field in MediaAttachment._meta.fields]


class JawabuApprovalDelegationForm(forms.Form):
    """Small, deliberate Admin surface for a temporary approval hand-off."""

    delegate = forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True).order_by('username'))
    gate = forms.ChoiceField(choices=JawabuApprovalDelegation.GATE_CHOICES)
    branch = forms.ChoiceField(required=False, choices=())
    product = forms.ChoiceField(required=False, choices=())
    expires_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='Maximum 14 days from now.',
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), max_length=2000)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].choices = [('', 'All branches')] + [(value, value) for value in global_branch_choices()]
        self.fields['product'].choices = [('', 'All products')] + [(value, value) for value in configured_products()]


@admin.register(JawabuApprovalDelegation)
class JawabuApprovalDelegationAdmin(ReadOnlyAuditAdmin):
    """Delegations are created/revoked through services, never raw edits."""

    list_display = ('delegate', 'gate', 'branch', 'product', 'authorized_by', 'starts_at', 'expires_at', 'active', 'revoke_action')
    list_filter = ('gate', 'branch', 'product')
    search_fields = ('delegate__username', 'authorized_by__username', 'reason')
    readonly_fields = [field.name for field in JawabuApprovalDelegation._meta.fields]
    change_list_template = 'admin/core/jawabuapprovaldelegation/change_list.html'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path('grant/', self.admin_site.admin_view(self.grant_view), name='core_jawabuapprovaldelegation_grant'),
            path('<path:delegation_id>/revoke/', self.admin_site.admin_view(self.revoke_view), name='core_jawabuapprovaldelegation_revoke'),
        ] + super().get_urls()

    @admin.display(description='Action')
    def revoke_action(self, obj):
        if not obj.active:
            return '-'
        return format_html(
            '<a href="{}">Revoke</a>',
            reverse('admin:core_jawabuapprovaldelegation_revoke', args=[obj.pk]),
        )

    def grant_view(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        form = JawabuApprovalDelegationForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            from core.services.jawabu_approvals import JawabuApprovalError, create_delegation
            from core.services.telegram_identity import user_access
            expiry = form.cleaned_data['expires_at']
            if timezone.is_naive(expiry):
                expiry = timezone.make_aware(expiry, timezone.get_current_timezone())
            try:
                delegation = create_delegation(
                    delegate=form.cleaned_data['delegate'], gate=form.cleaned_data['gate'],
                    authorized_by=request.user,
                    authorization_access=user_access(request.user, 'jawabu_portal'),
                    branch=form.cleaned_data['branch'], product=form.cleaned_data['product'],
                    expires_at=expiry, reason=form.cleaned_data['reason'],
                )
            except ValidationError as exc:
                form.add_error(None, '; '.join(exc.messages))
            else:
                messages.success(request, f'Temporary approval delegation created until {delegation.expires_at:%d-%b-%Y %H:%M}.')
                return HttpResponseRedirect(reverse('admin:core_jawabuapprovaldelegation_changelist'))
        return TemplateResponse(request, 'admin/core/jawabuapprovaldelegation/grant.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Grant temporary Portal approval authority', 'form': form,
        })

    def revoke_view(self, request, delegation_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        delegation = self.get_queryset(request).filter(pk=delegation_id).first()
        if not delegation:
            raise PermissionDenied
        if request.method == 'POST':
            from core.services.jawabu_approvals import revoke_delegation
            from core.services.telegram_identity import user_access
            try:
                revoke_delegation(
                    delegation_id=delegation.pk, actor=request.user,
                    access=user_access(request.user, 'jawabu_portal'),
                    reason=str(request.POST.get('reason') or ''),
                )
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                messages.success(request, 'Temporary approval delegation revoked.')
                return HttpResponseRedirect(reverse('admin:core_jawabuapprovaldelegation_changelist'))
        return TemplateResponse(request, 'admin/core/jawabuapprovaldelegation/revoke.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Revoke temporary approval authority', 'delegation': delegation,
        })


@admin.register(JawabuApprovalRecord)
class JawabuApprovalRecordAdmin(ReadOnlyAuditAdmin):
    list_display = ('farmer', 'gate', 'decision', 'status', 'reason_code', 'authority_role', 'decided_at', 'expires_at')
    list_filter = ('gate', 'decision', 'status', 'reason_code')
    search_fields = ('farmer__customer_name', 'farmer__national_id', 'decided_by_label', 'comment')
    readonly_fields = [field.name for field in JawabuApprovalRecord._meta.fields]


@admin.register(JawabuApprovalCondition)
class JawabuApprovalConditionAdmin(ReadOnlyAuditAdmin):
    list_display = ('approval', 'description', 'satisfied_at', 'satisfied_by')
    list_filter = ('approval__gate',)
    search_fields = ('approval__farmer__customer_name', 'description')
    readonly_fields = [field.name for field in JawabuApprovalCondition._meta.fields]


@admin.register(JawabuApprovalDelegationEvent)
class JawabuApprovalDelegationEventAdmin(ReadOnlyAuditAdmin):
    list_display = ('delegation', 'action', 'actor', 'created_at')
    list_filter = ('action', 'created_at')
    readonly_fields = [field.name for field in JawabuApprovalDelegationEvent._meta.fields]


@admin.register(JawabuMediaAccessEvent)
class JawabuMediaAccessEventAdmin(ReadOnlyAuditAdmin):
    list_display = ('farmer', 'attachment', 'actor', 'action', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('farmer__customer_name', 'farmer__national_id', 'attachment__original_filename', 'actor__username')
    readonly_fields = [field.name for field in JawabuMediaAccessEvent._meta.fields]


@admin.register(ComplaintCaseEvidence)
class ComplaintCaseEvidenceAdmin(ReadOnlyAuditAdmin):
    list_display = ['parsed_message', 'original_filename', 'group_id', 'uploaded_by', 'upload_status', 'created_at']
    list_filter = ['group_id', 'upload_status', 'created_at']
    search_fields = ['parsed_message__message_id', 'original_filename', 'uploaded_by', 'drive_file_id']
    readonly_fields = ['id', 'created_at']


class SuperuserComplaintConfigurationAdmin(ModelAdmin):
    """Complaint policy configuration is a technical Superuser responsibility."""

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ComplaintCategory)
class ComplaintCategoryAdmin(SuperuserComplaintConfigurationAdmin):
    list_display = ('label', 'key', 'default_priority', 'default_sla_hours', 'active', 'updated_at')
    list_filter = ('active', 'default_priority')
    search_fields = ('label', 'key', 'aliases__alias')
    readonly_fields = ('created_by', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ComplaintCategoryAlias)
class ComplaintCategoryAliasAdmin(SuperuserComplaintConfigurationAdmin):
    list_display = ('alias', 'category', 'active', 'created_at')
    list_filter = ('active', 'category')
    search_fields = ('alias', 'category__label')
    readonly_fields = ('normalized_alias', 'created_at')


@admin.register(ComplaintCategoryAvailability)
class ComplaintCategoryAvailabilityAdmin(SuperuserComplaintConfigurationAdmin):
    list_display = ('category', 'group_configuration', 'active', 'created_at')
    list_filter = ('active', 'group_configuration')
    readonly_fields = ('created_at',)


@admin.register(ComplaintCaseControl)
class ComplaintCaseControlAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'parsed_message', 'category', 'branch_ref', 'assigned_to', 'priority',
        'sla_due_at', 'revision', 'sync_status',
    )
    list_filter = ('priority', 'sync_status', 'customer_match_status', 'category', 'branch_ref')
    search_fields = ('parsed_message__message_id', 'parsed_message__customer_name', 'assigned_to__username')
    readonly_fields = [field.name for field in ComplaintCaseControl._meta.fields]


@admin.register(ComplaintCaseEvent)
class ComplaintCaseEventAdmin(ReadOnlyAuditAdmin):
    list_display = ('case', 'revision', 'action', 'actor', 'request_id', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('case__parsed_message__message_id', 'actor_label', 'request_id', 'payload_hash')
    readonly_fields = [field.name for field in ComplaintCaseEvent._meta.fields]


@admin.register(LiveSheetRecordChange)
class LiveSheetRecordChangeAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'record_key', 'action', 'group_id', 'sheet_tab', 'row_number',
        'changed_by', 'status', 'created_at',
    ]
    list_filter = ['action', 'status', 'group_id', 'sheet_id', 'sheet_tab', 'created_at']
    search_fields = [
        'record_key', 'group_id', 'sheet_id', 'sheet_tab', 'changed_by', 'error',
    ]


@admin.register(JawabuVisitRecord)
class JawabuVisitRecordAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'national_id', 'primary_phone', 'group_id', 'sheet_tab', 'row_number',
        'duplicate_status', 'import_status', 'sender', 'created_at',
    ]
    list_filter = [
        'group_id', 'sheet_id', 'sheet_tab', 'duplicate_status',
        'import_status', 'created_at',
    ]
    search_fields = [
        'national_id', 'primary_phone', 'duplicate_key', 'duplicate_group_id',
        'sender', 'raw_text', 'sync_error',
    ]
    readonly_fields = ['id', 'created_at']



@admin.register(JawabuFarmerUploadBatch)
class JawabuFarmerUploadBatchAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'source_filename', 'import_kind', 'group_id', 'status', 'total_rows',
        'review_needed', 'committed_count', 'skipped_count', 'archive_file_id', 'sender', 'created_at',
    ]
    list_filter = ['import_kind', 'status', 'group_id', 'created_at', 'committed_at', 'archive_last_sync_at']
    search_fields = ['source_filename', 'group_id', 'sender', 'telegram_message_id', 'error', 'archive_error']
    list_select_related = ['created_by']
    # The raw source is retained only to drive an authorised archive retry. It
    # is deliberately not rendered as a giant PII-bearing binary field in the
    # Admin; use the IT-only Portal review surface for parsed rows instead.
    exclude = ['source_content']
class JawabuFarmerMasterAdminForm(forms.ModelForm):
    county = forms.ChoiceField(required=False)
    branch = forms.ChoiceField(required=False)

    class Meta:
        model = JawabuFarmerMaster
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.services.branches import global_branch_choices
        from core.services.locations import global_county_choices

        branch_values = list(global_branch_choices())
        county_values = list(global_county_choices())
        current_branch = str(getattr(self.instance, 'branch', '') or '').strip()
        current_county = str(getattr(self.instance, 'county', '') or '').strip()
        if current_branch and current_branch not in branch_values:
            branch_values.append(current_branch)
        if current_county and current_county not in county_values:
            county_values.append(current_county)
        self.fields['branch'].choices = [('', 'Select branch')] + [(value, value) for value in branch_values]
        self.fields['county'].choices = [('', 'Select county')] + [(value, value) for value in county_values]


@admin.register(JawabuFarmerMaster)
class JawabuFarmerMasterAdmin(ModelAdmin):
    form = JawabuFarmerMasterAdminForm
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = [
        'customer_name', 'national_id', 'primary_phone', 'county',
        'sub_county', 'lead_source', 'hb_sales_person', 'status', 'updated_at',
    ]
    list_filter = ['status', 'county', 'branch', 'lead_source', 'installation_status', 'source', 'updated_at']
    search_fields = [
        'customer_name', 'national_id', 'primary_phone', 'secondary_phone',
        'duplicate_key', 'external_id', 'hbg_contract_name', 'hb_sales_person', 'county', 'sub_county',
    ]
    readonly_fields = [
        'id', 'source', 'source_name', 'source_row_number',
        'source_fingerprint', 'duplicate_key', 'raw_data', 'last_imported_at',
        'created_at', 'updated_at',
    ]
    list_display = [
        'customer_name', 'national_id', 'primary_phone', 'county',
        'sub_county', 'lead_source', 'hb_sales_person', 'jbl_visit_date',
        'jbl_visit_status', 'credit_decision', 'order_number', 'status', 'updated_at',
    ]
    list_filter = [
        'status', 'county', 'branch', 'lead_source', 'installation_status',
        'source', 'jbl_visit_status', 'credit_decision', 'updated_at',
    ]
    fieldsets = (
        ('Customer', {
            'fields': (
                ('customer_name', 'national_id'),
                ('primary_phone', 'secondary_phone'),
                ('external_id', 'unit_number'),
                'status',
            ),
        }),
        ('Location', {
            'fields': (
                ('county', 'sub_county'),
                ('ward', 'village'),
                'landmark',
                'branch',
                'gps_link',
                ('latitude', 'longitude'),
                ('latitude_value', 'longitude_value'),
            ),
        }),
        ('Farmers Source Fields', {
            'fields': (
                ('hbg_contract_name', 'lead_source'),
                ('contract_type', 'installation_status'),
                ('actual_receipts_currency', 'actual_receipts'),
                ('deposit_paid_hbg', 'hb_sales_person'),
                ('hbg_visit_date', 'sign_date'),
                'created_date',
                'comments',
            ),
        }),
        ('Stage 2 — JBL Visit', {
            'fields': (
                ('jbl_visit_date', 'jbl_officer'),
                'jbl_visit_status',
                'jbl_visit_comment',
                'jbl_media_urls',
            ),
            'description': 'Logged by the JBL BRO after visiting the farmer.',
        }),
        ('Stage 3 — Credit Decision', {
            'fields': (
                ('credit_decision', 'credit_decided_by'),
                'credit_decided_at',
            ),
            'description': (
                'Set by the credit analyst. Only when Credit Decision = Approved '
                'can a requisition date and order number be assigned.'
            ),
        }),
        ('System Export / Payment', {
            'fields': (
                ('imab_created', 'customer_no'),
                ('imab_customer_name', 'system_branch'),
                ('system_loan_officer', 'system_deposit_paid_jbl'),
                ('repayment_date', 'repayment_day'),
                ('repayment_tenor', 'repayment_tenor_months'),
                'payment_product',
            ),
            'description': 'Values imported from the system export and used for payment generation.',
            'classes': ('compact-section',),
        }),
        ('Final Review / Decision', {
            'fields': (
                ('final_decision', 'final_decided_by'),
                'final_decision_comment',
                'final_decided_at',
                ('deferred_stage', 'deferred_until'),
                'deferred_at',
            ),
            'description': 'Head of Rural decision and deferred-case tracking.',
            'classes': ('compact-section',),
        }),
        ('Stage 4 — Requisition', {
            'fields': (('requisition_date', 'order_number'),),
            'description': 'Filled by admin once credit is approved. Gate enforced by the portal.',
        }),
        ('Stage 7 — Invoice', {
            'fields': (
                ('invoice_number', 'invoice_date'),
                ('invoice_amount', 'discount'),
                ('payment', 'balance_due'),
            ),
            'description': (
                'Populated automatically when a combined invoice PDF is uploaded '
                'via the portal Batches tab. Can also be set manually.'
            ),
        }),
        ('Import / Cleaning', {
            'fields': (
                'cleaning_notes', 'duplicate_key', 'source', 'source_name',
                ('source_row_number', 'source_fingerprint'),
                'last_imported_at',
                'raw_data', ('created_at', 'updated_at'),
            ),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        # Manual Admin edits are another data boundary: normalize before save
        # and refresh the review queue afterwards instead of leaving stale flags.
        from core.services.jawabu_validation import canonicalize_farmer, refresh_data_quality_issues

        canonicalize_farmer(obj, strict=False)
        super().save_model(request, obj, form, change)
        refresh_data_quality_issues(obj)


@admin.register(FcaImportRecord)
class FcaImportRecordAdmin(ReadOnlyAuditAdmin):
    list_display = [
        'customer_name', 'primary_phone', 'fca_decision', 'group_id',
        'sheet_tab', 'row_number', 'import_status', 'source_filename',
        'source_row', 'created_at',
    ]
    list_filter = [
        'group_id', 'sheet_id', 'sheet_tab', 'fca_decision',
        'import_status', 'created_at',
    ]
    search_fields = [
        'customer_name', 'primary_phone', 'source_filename', 'source_sheet',
        'fca_comment', 'fca_decision', 'sync_error',
    ]
    readonly_fields = ['id', 'created_at']


@admin.register(GroupSheetConfiguration)
class GroupSheetConfigurationAdmin(ModelAdmin):
    form = GroupSheetConfigurationAdminForm
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    inlines = []
    actions = ['publish_jbl_apps_launchers', 'preview_jbl_apps_launchers']
    list_display = [
        'display_label', 'group_id', 'enabled', 'sheet_name',
        'sheet_link', 'sheet_coverage_link', 'live_records_link', 'data_records_link',
        'media_records_link', 'tat_repair_link', 'tat_duplicate_link', 'updated_at',
    ]
    list_filter = ['enabled', 'sheet_name', 'updated_at']
    search_fields = ['group_id', 'display_name', 'sheet_id', 'sheet_name']
    readonly_fields = [
        'created_at', 'updated_at', 'sheet_link', 'sheet_analyzer_link',
        'sheet_coverage_link', 'live_records_link', 'data_records_link', 'media_records_link',
        'reset_group_data_link', 'tat_repair_link', 'tat_duplicate_link',
    ]
    fieldsets = (
        ('Group Routing', {
            'fields': (
                'enabled', 'group_id', 'display_name', 'sheet_id',
                'sheet_name', 'sheet_link', 'live_records_link', 'data_records_link',
                'media_records_link', 'sheet_analyzer_link', 'sheet_coverage_link', 'reset_group_data_link',
                'tat_repair_link', 'tat_duplicate_link',
            ),
            'description': (
                'Map one Telegram group to one Google Sheet tab. '
                'This admin configuration overrides GROUP_MAPPING_JSON for '
                'the same group ID.'
            ),
        }),
        ('Spreadsheet Schema', {
            'fields': ('sheet_schema',),
            'description': (
                'Optional JSON mapping from canonical workflow fields to this '
                'sheet\'s column headers.'
            ),
            'classes': ('tab',),
        }),
        ('Workflow Preset', {
            'fields': ('workflow_preset',),
            'description': (
                'Select Case / Complaints for the existing complaint intake '
                'workflow, Order Approval for BRO updates, Jawabu HomeBiogas '
                'for WhatsApp visit exports, or Manual JSON for a custom '
                'workflow. The workflow JSON below will be generated '
                'automatically where a preset applies. '
                'Only the relevant settings section will expand below.'
            ),
            'classes': ('tab',),
        }),
        ('Pinned JBL Apps Launcher', {
            'fields': ('mini_app_launchers',),
            'description': (
                'Select the generic Mini Apps available in this Telegram group. '
                'Use the Publish JBL Apps launcher action after saving; saving alone never sends Telegram messages.'
            ),
            'classes': ('tab',),
        }),
        ('Case / Complaints Settings', {
            'fields': (
                'case_header_row',
                'case_field_headers',
            ),
            'description': (
                'Header row and optional canonical-field header mappings for '
                'the complaint register workflow.'
            ),
            'classes': ('tab', 'preset-section', 'preset-case'),
        }),
        ('Order Approval Settings', {
            'fields': (
                'order_approval_search_tabs',
                'order_approval_match_field',
                'order_approval_media_field',
                'order_approval_header_row',
                'order_approval_media_root_folder',
            ),
            'description': 'Sheet tabs and matching config for the Order Approval (BRO) workflow.',
            'classes': ('tab', 'preset-section', 'preset-order_approval'),
        }),
        ('SPIN / CRB Settings', {
            'fields': (
                'spin_header_row',
                'spin_legacy_batch_sheet_name',
                'spin_branches',
                'spin_default_branch',
            ),
            'description': 'Header, import tab, and per-group branch settings for the SPIN / CRB workflow.',
            'classes': ('tab', 'preset-section', 'preset-spin_credit_analysis'),
        }),
        ('TAT Tracker Targets', {
            'fields': tuple(
                field_name
                for _product_key, _product_label, field_names in TAT_TARGET_FIELD_GROUPS
                for field_name in field_names
            ),
            'description': (
                'SLA targets in minutes. Total target controls overall case SLA; '
                'stage targets control each stage badge/status in the Mini App. '
                'Leave a stage blank to show minutes without SLA status.'
            ),
            'classes': ('tab', 'preset-section', 'preset-tat_tracker'),
        }),
        ('Jawabu HomeBiogas Settings', {
            'fields': (
                'jawabu_import_start_date',
                'jawabu_master_sync_enabled',
                'jawabu_master_sheet_id',
                'jawabu_master_sheet_name',
                'jawabu_master_header_row',
                'jawabu_master_data_start_row',
                'jawabu_master_import_log_sheet_name',
                'jawabu_internal_order_sync_enabled',
                'jawabu_internal_order_sheet_id',
                'jawabu_internal_order_sheet_name',
                'jawabu_internal_order_header_row',
                'jawabu_internal_order_data_start_row',
                'jawabu_internal_order_record_id_prefix',
                'jawabu_tat_targets_minutes',
            ),
            'description': 'Master Data sync plus optional downstream internal Order Sheet sync for the Jawabu HomeBiogas workflow.',
            'classes': ('tab', 'preset-section', 'preset-jawabu_homebiogas'),
        }),
        ('Advanced Workflow And Parser Rules', {
            'fields': ('workflow', 'parser_rules'),
            'description': (
                'Optional per-group workflow and parser settings. Use a '
                'preset where possible; custom workflows can define their own '
                'JSON here.'
            ),
            'classes': ('tab',),
        }),
        ('Metadata', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('tab',),
        }),
    )

    class Media:
        js = ('admin/js/workflow_preset_toggle.js',)

    def tat_repair_view(self, request, object_id):
        config = self.get_object(request, object_id)
        if config is None:
            return HttpResponseRedirect(reverse('admin:core_groupsheetconfiguration_changelist'))
        if not request.user.is_superuser:
            raise PermissionDenied('Only superusers can run a TAT Sheet repair.')
        if not is_tat_tracker_workflow(config):
            self.message_user(request, 'This group is not configured for the TAT Tracker.', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:core_groupsheetconfiguration_change', args=[config.pk]))

        products = configured_products(config.workflow)
        product_options = [(product.key, product.label) for product in products]
        selected_product = str(
            (request.POST.get('product') if request.method == 'POST' else request.GET.get('product')) or ''
        ).strip()
        if selected_product and selected_product not in {key for key, _label in product_options}:
            raise PermissionDenied('The selected product is not enabled for this TAT group.')
        try:
            offset = max(0, int(request.POST.get('offset') if request.method == 'POST' else request.GET.get('offset') or 0))
        except (TypeError, ValueError):
            offset = 0
        include_unlinked = (
            request.POST.get('include_unlinked') == '1'
            if request.method == 'POST'
            else request.GET.get('include_unlinked') == '1'
        )

        context = {
            **self.admin_site.each_context(request),
            'title': 'Reconcile TAT cases with the Sheet',
            'opts': self.model._meta,
            'config': config,
            'product_options': product_options,
            'selected_product': selected_product,
            'offset': offset,
            'include_unlinked': include_unlinked,
            'batch_limit': 25,
            'change_url': reverse('admin:core_groupsheetconfiguration_change', args=[config.pk]),
            'status_url_template': reverse('admin:core_groupsheetconfiguration_tat_repair_status', args=[config.pk, '00000000-0000-0000-0000-000000000000']),
        }
        if request.method == 'POST':
            action = request.POST.get('action') or 'repair'
            if action == 'retry_failures':
                from core.services.tat_repair_jobs import create_repair_job, serialize_repair_job, start_repair_job

                retry_job = TatRepairJob.objects.filter(
                    pk=request.POST.get('job_id'),
                    group_configuration=config,
                ).first()
                if retry_job is None or retry_job.status not in {'completed', 'completed_with_errors', 'failed'}:
                    context['confirmation_error'] = 'That repair job is not available for retry.'
                elif request.POST.get('confirm') != 'RETRY FAILED':
                    context['confirmation_error'] = 'Type RETRY FAILED exactly to retry the recorded failures.'
                else:
                    failed_case_ids = [
                        str(failure.get('case_id') or '').strip()
                        for failure in (retry_job.failures or [])
                        if isinstance(failure, dict) and str(failure.get('case_id') or '').strip()
                    ]
                    if not failed_case_ids:
                        context['confirmation_error'] = 'This job has no recorded case IDs to retry.'
                    else:
                        new_job = create_repair_job(
                            config,
                            product_key=retry_job.product_key,
                            requested_by=request.user.get_username(),
                            include_unlinked=True,
                            case_ids=failed_case_ids,
                        )
                        start_repair_job(new_job.id)
                        self.message_user(
                            request,
                            f'Retry started for {new_job.total_cases} failed case(s).',
                            level=messages.SUCCESS,
                        )
                        return HttpResponseRedirect(f'{request.path}?job={new_job.id}')
                context['repair_job'] = serialize_repair_job(retry_job) if retry_job else None
                if retry_job:
                    context['repair_job_status_url'] = reverse(
                        'admin:core_groupsheetconfiguration_tat_repair_status',
                        args=[config.pk, retry_job.id],
                    )
            elif request.POST.get('confirm') != 'REPAIR':
                context['confirmation_error'] = 'Type REPAIR exactly to authorize this batch.'
                return TemplateResponse(request, 'admin/core/groupsheetconfiguration/tat_repair.html', context)
            else:
                preview_key = {
                    'config_id': str(config.pk),
                    'product': selected_product,
                    'offset': offset,
                    'include_unlinked': include_unlinked,
                }
                if request.session.get('tat_repair_preview') != preview_key:
                    context['confirmation_error'] = 'Preview this exact batch before running its repair.'
                    return TemplateResponse(request, 'admin/core/groupsheetconfiguration/tat_repair.html', context)
                from core.services.tat_repair_jobs import create_repair_job, start_repair_job
                job = create_repair_job(
                    config,
                    product_key=selected_product,
                    requested_by=request.user.get_username(),
                    include_unlinked=include_unlinked,
                )
                start_repair_job(job.id)
                self.message_user(request, 'TAT case reconciliation started in the background. Progress is checkpointed after every case.', level=messages.SUCCESS)
                return HttpResponseRedirect(f'{request.path}?job={job.id}')
        else:
            job_id = str(request.GET.get('job') or '').strip()
            if job_id:
                job = TatRepairJob.objects.filter(pk=job_id, group_configuration=config).first()
                if job:
                    from core.services.tat_repair_jobs import serialize_repair_job, start_repair_job
                    if job.status in {'queued', 'running'}:
                        start_repair_job(job.id)
                    context['repair_job'] = serialize_repair_job(job)
                    context['repair_job_status_url'] = reverse(
                        'admin:core_groupsheetconfiguration_tat_repair_status',
                        args=[config.pk, job.id],
                    )
            if not context.get('repair_job'):
                context['preview'] = resync_tat_tracker_cases(
                    config,
                    dry_run=True,
                    limit=25,
                    offset=offset,
                    product_key=selected_product,
                    include_unlinked=include_unlinked,
                )
                request.session['tat_repair_preview'] = {
                    'config_id': str(config.pk),
                    'product': selected_product,
                    'offset': offset,
                    'include_unlinked': include_unlinked,
                }
        return TemplateResponse(request, 'admin/core/groupsheetconfiguration/tat_repair.html', context)

    @staticmethod
    def _tat_duplicate_signature(product_reports):
        """Return a stable preview fingerprint for the confirmation step."""
        normalized = []
        for item in product_reports:
            normalized.append({
                'product': item['product'],
                'reports': [
                    {
                        'case_id': report['case_id'],
                        'rows': report['rows'],
                        'keep_row': report['keep_row'],
                        'delete_rows': report['delete_rows'],
                        'canonical_row': report.get('canonical_row'),
                        'linked': report['linked'],
                    }
                    for report in item.get('reports', [])
                ],
            })
        return json.dumps(normalized, sort_keys=True, separators=(',', ':'))

    def _scan_tat_duplicate_rows(self, config, selected_product=''):
        """Read duplicate IDs from configured TAT sheets without modifying them."""
        products = configured_products(config.workflow)
        if selected_product:
            products = [product for product in products if product.key == selected_product]

        product_reports = []
        errors = []
        for product in products:
            try:
                from core.services.sheets import get_sheets_service

                service = get_sheets_service(
                    sheet_id=config.sheet_id,
                    sheet_name=product.sheet_name,
                )
                if not service.is_available() or not getattr(service, '_sheet', None):
                    raise RuntimeError('Google Sheets is unavailable for this product sheet.')
                reports = cleanup_tat_sheet_duplicate_case_ids(
                    service._sheet,
                    group_id=config.group_id,
                    apply=False,
                )
                product_reports.append({
                    'product': product.key,
                    'label': product.label,
                    'sheet_name': product.sheet_name,
                    'reports': reports,
                })
            except Exception:
                # Keep provider details out of the Admin response; the server
                # log retains the underlying exception for diagnosis.
                logger.exception(
                    'Could not scan TAT duplicate rows for group %s product %s',
                    config.group_id,
                    product.key,
                )
                errors.append(
                    f'{product.label}: Google Sheets could not be read. Check the sheet configuration and server logs.'
                )
        return product_reports, errors

    def tat_duplicate_view(self, request, object_id):
        """Preview and explicitly clean duplicate TAT case-ID rows from Admin."""
        config = self.get_object(request, object_id)
        if config is None:
            return HttpResponseRedirect(reverse('admin:core_groupsheetconfiguration_changelist'))
        if not request.user.is_superuser:
            raise PermissionDenied('Only superusers can clean duplicate TAT Sheet rows.')
        if not is_tat_tracker_workflow(config):
            self.message_user(request, 'This group is not configured for the TAT Tracker.', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:core_groupsheetconfiguration_change', args=[config.pk]))

        products = configured_products(config.workflow)
        product_options = [(product.key, product.label) for product in products]
        selected_product = str(
            (request.POST.get('product') if request.method == 'POST' else request.GET.get('product')) or ''
        ).strip()
        if selected_product and selected_product not in {key for key, _label in product_options}:
            raise PermissionDenied('The selected product is not enabled for this TAT group.')
        include_unlinked = (
            request.POST.get('include_unlinked') == '1'
            if request.method == 'POST'
            else request.GET.get('include_unlinked') == '1'
        )

        product_reports, scan_errors = self._scan_tat_duplicate_rows(config, selected_product)
        signature = self._tat_duplicate_signature(product_reports)
        context = {
            **self.admin_site.each_context(request),
            'title': 'Clean duplicate TAT Sheet rows',
            'opts': self.model._meta,
            'config': config,
            'product_options': product_options,
            'selected_product': selected_product,
            'include_unlinked': include_unlinked,
            'product_reports': product_reports,
            'scan_errors': scan_errors,
            'duplicate_count': sum(len(item['reports']) for item in product_reports),
            'change_url': reverse('admin:core_groupsheetconfiguration_change', args=[config.pk]),
            'repair_url': reverse('admin:core_groupsheetconfiguration_tat_repair', args=[config.pk]),
        }

        if request.method == 'POST':
            if request.POST.get('action') != 'clean':
                context['confirmation_error'] = 'Use the Clean duplicate rows button to make changes.'
            elif request.POST.get('confirm') != 'CLEAN DUPLICATES':
                context['confirmation_error'] = 'Type CLEAN DUPLICATES exactly to authorize deletion.'
            elif scan_errors:
                context['confirmation_error'] = 'The preview could not be completed. Resolve the Sheet errors and preview again.'
            elif request.session.get('tat_duplicate_preview') != {
                'config_id': str(config.pk),
                'product': selected_product,
                'include_unlinked': include_unlinked,
                'signature': signature,
            }:
                context['confirmation_error'] = 'Preview this exact selection immediately before cleaning.'
            else:
                cleaned = []
                clean_errors = []
                from core.services.sheets import get_sheets_service

                for item in product_reports:
                    if not item['reports']:
                        continue
                    try:
                        service = get_sheets_service(
                            sheet_id=config.sheet_id,
                            sheet_name=item['sheet_name'],
                        )
                        reports = cleanup_tat_sheet_duplicate_case_ids(
                            service._sheet,
                            group_id=config.group_id,
                            group_configuration=config,
                            actor=request.user.get_username(),
                            apply=True,
                            include_unlinked=include_unlinked,
                        )
                        cleaned.append((item['label'], reports))
                    except Exception:
                        logger.exception(
                            'Could not clean TAT duplicate rows for group %s product %s',
                            config.group_id,
                            item['product'],
                        )
                        clean_errors.append(
                            f"{item['label']}: cleanup failed; no success was recorded for this product."
                        )
                request.session.pop('tat_duplicate_preview', None)
                verification_failures = [
                    report
                    for _label, reports in cleaned
                    for report in reports
                    if not report.get('skipped_unlinked')
                    and (
                        report.get('verification_status') != 'verified'
                        or (report.get('linked') and report.get('resync_status') != 'synced')
                    )
                ]
                if clean_errors or verification_failures:
                    if verification_failures:
                        failed_cases = ', '.join(report['case_id'] for report in verification_failures[:5])
                        clean_errors.append(
                            f'Survivor verification or re-publication did not complete for: {failed_cases}. '
                            'No successful cleanup was recorded for those cases; review Live sheet record changes and TAT sync errors.'
                        )
                    context['confirmation_error'] = ' '.join(clean_errors)
                else:
                    removed = sum(
                        len(report['delete_rows'])
                        for _label, reports in cleaned
                        for report in reports
                        if not report.get('skipped_unlinked')
                    )
                    self.message_user(
                        request,
                        f'Cleanup completed. Removed {removed} duplicate Sheet row(s); each linked surviving row was verified by immutable case ID and re-published from Django.',
                        level=messages.SUCCESS,
                    )
                    return HttpResponseRedirect(request.path)
        else:
            request.session['tat_duplicate_preview'] = {
                'config_id': str(config.pk),
                'product': selected_product,
                'include_unlinked': include_unlinked,
                'signature': signature,
            }
        return TemplateResponse(request, 'admin/core/groupsheetconfiguration/tat_duplicates.html', context)

    def tat_repair_status_view(self, request, object_id, job_id):
        config = self.get_object(request, object_id)
        if config is None or not request.user.is_superuser:
            raise PermissionDenied('Only superusers can view TAT repair jobs.')
        job = TatRepairJob.objects.filter(pk=job_id, group_configuration=config).first()
        if job is None:
            return JsonResponse({'ok': False, 'error': 'Repair job not found.'}, status=404)
        from core.services.tat_repair_jobs import serialize_repair_job, start_repair_job
        if job.status in {'queued', 'running'}:
            start_repair_job(job.id)
        return JsonResponse({'ok': True, 'job': serialize_repair_job(job)})

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop('publish_jbl_apps_launchers', None)
        return actions

    @admin.display(description='Reconcile TAT cases by case ID')
    def tat_repair_link(self, obj):
        if not obj or not obj.pk or not is_tat_tracker_workflow(obj):
            return '-'
        url = reverse('admin:core_groupsheetconfiguration_tat_repair', args=[obj.pk])
        return format_html('<a class="button" href="{}">Reconcile TAT cases</a>', url)

    @admin.display(description='Clean duplicate TAT rows')
    def tat_duplicate_link(self, obj):
        if not obj or not obj.pk or not is_tat_tracker_workflow(obj):
            return '-'
        url = reverse('admin:core_groupsheetconfiguration_tat_duplicates', args=[obj.pk])
        return format_html('<a class="button" href="{}">Find duplicate TAT rows</a>', url)

    @admin.action(description='Publish / refresh JBL Apps launcher')
    def publish_jbl_apps_launchers(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                'Only superusers can publish Telegram launcher messages.',
                level=messages.ERROR,
            )
            return
        from core.services.telegram_launchers import TelegramLauncherError, publish_group_launcher

        published = 0
        for config in queryset:
            try:
                result = publish_group_launcher(config)
            except TelegramLauncherError as exc:
                self.message_user(
                    request,
                    f'{config.display_name or config.group_id}: {exc}',
                    level=messages.ERROR,
                )
                continue
            published += 1
            self.message_user(
                request,
                f"{config.display_name or config.group_id}: {result['action']} launcher message {result['message_id']}.",
                level=messages.SUCCESS,
            )
        if published:
            self._clear_runtime_config_cache()

    @admin.action(description='Preview JBL Apps launcher')
    def preview_jbl_apps_launchers(self, request, queryset):
        from core.services.telegram_launchers import TelegramLauncherError, preview_group_launcher

        for config in queryset:
            try:
                preview = preview_group_launcher(config)
                labels = ', '.join(
                    button['text']
                    for row in preview['reply_markup']['inline_keyboard']
                    for button in row
                )
                self.message_user(
                    request,
                    f'{config.display_name or config.group_id}: JBL Apps - {labels}.',
                    level=messages.INFO,
                )
            except TelegramLauncherError as exc:
                self.message_user(
                    request,
                    f'{config.display_name or config.group_id}: {exc}',
                    level=messages.ERROR,
                )
    def get_inlines(self, request, obj=None):
        # Staff identity and scope are managed centrally on Django Users.
        return []

    @admin.display(description='Group')
    def display_label(self, obj):
        return obj.display_name or obj.group_id

    @admin.display(description='Sheet')
    def sheet_link(self, obj):
        url = obj.sheet_url()
        if not url:
            return '-'
        return format_html('<a href="{}" target="_blank" rel="noopener">Open sheet</a>', url)

    @admin.display(description='Analyze sheet')
    def sheet_analyzer_link(self, obj):
        if not obj or not obj.pk:
            return 'Save this configuration before analyzing the sheet.'
        if not obj.sheet_id:
            return 'Add a Google Sheet ID before analyzing.'
        url = reverse('admin:core_groupsheetconfiguration_analyze', args=[obj.pk])
        return format_html('<a class="button" href="{}">Analyze columns and dropdowns</a>', url)

    @admin.display(description='Live sheet rows')
    def live_records_link(self, obj):
        if not obj or not obj.pk:
            return 'Save this configuration before viewing live rows.'
        url = reverse('admin:core_groupsheetconfiguration_live_records', args=[obj.pk])
        return format_html('<a class="button" href="{}">Open live sheet records</a>', url)

    @admin.display(description='Field coverage')
    def sheet_coverage_link(self, obj):
        if not obj or not obj.pk:
            return 'Save this configuration before checking field coverage.'
        if not obj.sheet_id:
            return 'Add a Google Sheet ID before checking field coverage.'
        url = reverse('admin:core_groupsheetconfiguration_coverage', args=[obj.pk])
        return format_html('<a class="button" href="{}">Check published fields</a>', url)

    @admin.display(description='Django data')
    def data_records_link(self, obj):
        if not obj or not obj.pk:
            return 'Save this configuration before viewing records.'

        workflow_type = str((obj.workflow or {}).get('type') or 'case')
        if workflow_type == 'order_approval':
            url = self._filtered_admin_url(
                'admin:core_orderapprovalupdate_changelist',
                group_id=obj.group_id,
                sheet_id=obj.sheet_id,
            )
            label = 'View order update audit'
        elif workflow_type == 'jawabu_homebiogas':
            url = self._filtered_admin_url(
                'admin:core_jawabuvisitrecord_changelist',
                group_id=obj.group_id,
                sheet_id=obj.sheet_id,
            )
            label = 'View Jawabu import audit'
        elif workflow_type == 'tat_tracker':
            url = self._filtered_admin_url(
                'admin:core_tattrackercase_changelist',
                group_id=obj.group_id,
                sheet_id=obj.sheet_id,
            )
            label = 'View TAT tracker cases'
        else:
            url = self._filtered_admin_url(
                'admin:core_parsedmessage_changelist',
                group_id=obj.group_id,
                sheet_id=obj.sheet_id,
                sheet_name=obj.sheet_name,
            )
            label = 'View complaint cases'
        return format_html('<a class="button" href="{}">{}</a>', url, label)

    @admin.display(description='Media')
    def media_records_link(self, obj):
        if not obj or not obj.pk:
            return 'Save this configuration before viewing media.'
        url = self._filtered_admin_url(
            'admin:core_mediaattachment_changelist',
            group_id=obj.group_id,
        )
        return format_html('<a href="{}">View media audit</a>', url)

    @admin.display(description='Reset local group data')
    def reset_group_data_link(self, obj):
        if not obj or not obj.pk:
            return 'Save this configuration before resetting local data.'
        url = reverse('admin:core_groupsheetconfiguration_reset_data', args=[obj.pk])
        return format_html('<a class="button deletelink" href="{}">Reset local DB data</a>', url)

    @staticmethod
    def _filtered_admin_url(route_name: str, **filters) -> str:
        query = {
            f'{field}__exact': value
            for field, value in filters.items()
            if value not in (None, '')
        }
        url = reverse(route_name)
        return f'{url}?{urlencode(query)}' if query else url

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/tat-repair/',
                self.admin_site.admin_view(self.tat_repair_view),
                name='core_groupsheetconfiguration_tat_repair',
            ),
            path(
                '<path:object_id>/tat-duplicates/',
                self.admin_site.admin_view(self.tat_duplicate_view),
                name='core_groupsheetconfiguration_tat_duplicates',
            ),
            path(
                '<path:object_id>/tat-repair/<uuid:job_id>/status/',
                self.admin_site.admin_view(self.tat_repair_status_view),
                name='core_groupsheetconfiguration_tat_repair_status',
            ),
            path(
                '<path:object_id>/analyze-sheet/',
                self.admin_site.admin_view(self.analyze_sheet_view),
                name='core_groupsheetconfiguration_analyze',
            ),
            path(
                '<path:object_id>/field-coverage/',
                self.admin_site.admin_view(self.field_coverage_view),
                name='core_groupsheetconfiguration_coverage',
            ),
            path(
                '<path:object_id>/live-records/',
                self.admin_site.admin_view(self.live_records_view),
                name='core_groupsheetconfiguration_live_records',
            ),
            path(
                '<path:object_id>/reset-group-data/',
                self.admin_site.admin_view(self.reset_group_data_view),
                name='core_groupsheetconfiguration_reset_data',
            ),
        ]
        return custom_urls + urls

    def field_coverage_view(self, request, object_id):
        """Inspect only the configured header row; never import Sheet rows."""
        config = self.get_object(request, object_id)
        if not config:
            messages.error(request, 'Configuration was not found.')
            return HttpResponseRedirect('../')
        if not self.has_view_permission(request, config):
            messages.error(request, 'You do not have permission to view this configuration.')
            return HttpResponseRedirect('../')

        from core.services.sheet_publication import coverage_for_headers, surfaces_for_configuration
        from core.services.sheets import get_sheets_service

        reports = []
        error = ''
        for target in surfaces_for_configuration(config):
            try:
                header_row = max(int(target.get('header_row') or 1), 1)
            except (TypeError, ValueError):
                header_row = 1
            try:
                service = get_sheets_service(
                    sheet_id=target.get('sheet_id') or config.sheet_id,
                    sheet_name=target.get('sheet_name') or config.sheet_name,
                    sheet_schema=config.sheet_schema or {},
                )
                if not service.is_available():
                    reports.append({
                        'surface': target['surface'],
                        'sheet_name': target['sheet_name'],
                        'error': 'Google Sheets service unavailable or sheet not accessible.',
                    })
                    continue
                # Header-only read is intentional: Sheets are a publication
                # surface and must not be treated as a backend import source.
                headers = service._sheet.row_values(header_row)
                report = coverage_for_headers(target['surface'], headers)
                report.update({'sheet_name': target['sheet_name'], 'header_row': header_row})
                reports.append(report)
            except Exception as exc:
                logger.warning('Sheet field coverage failed for %s: %s', config, exc, exc_info=True)
                reports.append({
                    'surface': target['surface'],
                    'sheet_name': target['sheet_name'],
                    'error': 'Could not read the configured Sheet header row.',
                })
        if not reports:
            error = 'No publication Sheet is configured for this workflow.'

        context = {
            **self.admin_site.each_context(request),
            'title': f'Sheet field coverage: {config.display_name or config.group_id}',
            'opts': self.model._meta,
            'original': config,
            'config': config,
            'reports': reports,
            'error': error,
        }
        return TemplateResponse(
            request,
            'admin/core/groupsheetconfiguration/field_coverage.html',
            context,
        )

    def reset_group_data_view(self, request, object_id):
        config = self.get_object(request, object_id)
        if not config:
            messages.error(request, 'Configuration was not found.')
            return HttpResponseRedirect('../')
        if not self.has_change_permission(request, config):
            messages.error(request, 'You do not have permission to reset this group data.')
            return HttpResponseRedirect('../')

        from core.services.group_reset import group_data_counts, reset_group_data

        workflow = config.workflow or {}
        is_spin_workflow = str(workflow.get('type') or '') == 'spin_credit_analysis'
        spin_legacy_batch_sheet_name = str(
            workflow.get('legacy_batch_sheet_name') or 'SPIN Legacy Batch'
        ).strip() or 'SPIN Legacy Batch'
        counts = group_data_counts(
            config.group_id,
            spin_legacy_batch_sheet_name=spin_legacy_batch_sheet_name,
        )
        if request.method == 'POST':
            if request.POST.get('confirm_reset') != 'yes':
                messages.error(request, 'Tick the confirmation checkbox before resetting group data.')
                return HttpResponseRedirect(request.path)
            include_farmer_uploads = request.POST.get('include_farmer_uploads') == 'yes'
            include_all_farmer_master = request.POST.get('include_all_farmer_master') == 'yes'
            include_order_records = request.POST.get('include_order_records') == 'yes'
            include_drive_upload_records = request.POST.get('include_drive_upload_records') == 'yes'
            include_spin_legacy_batch = request.POST.get('include_spin_legacy_batch') == 'yes'
            result = reset_group_data(
                config.group_id,
                include_farmer_uploads=include_farmer_uploads,
                include_all_farmer_master=include_all_farmer_master,
                include_order_records=include_order_records,
                include_drive_upload_records=include_drive_upload_records,
                include_spin_legacy_batch=include_spin_legacy_batch,
                spin_legacy_batch_sheet_name=spin_legacy_batch_sheet_name,
            )
            deleted_total = sum(result.get('deleted', {}).values())
            self._clear_runtime_config_cache()
            messages.success(
                request,
                f'Reset complete for {config.display_name or config.group_id}. '
                f'Deleted {deleted_total} local database record(s). '
                'Google Sheets and Drive files were not changed.',
            )
            change_url = reverse(
                'admin:core_groupsheetconfiguration_change',
                args=[config.pk],
            )
            return HttpResponseRedirect(change_url)

        context = {
            **self.admin_site.each_context(request),
            'title': f'Reset local data: {config.display_name or config.group_id}',
            'opts': self.model._meta,
            'original': config,
            'config': config,
            'counts': counts,
            'total_count': sum(counts.values()),
            'is_spin_workflow': is_spin_workflow,
            'spin_legacy_batch_sheet_name': spin_legacy_batch_sheet_name,
            'has_change_permission': self.has_change_permission(request, config),
        }
        return TemplateResponse(
            request,
            'admin/core/groupsheetconfiguration/reset_group_data.html',
            context,
        )

    def analyze_sheet_view(self, request, object_id):
        config = self.get_object(request, object_id)
        if not config:
            messages.error(request, 'Configuration was not found.')
            return HttpResponseRedirect('../')
        if not self.has_change_permission(request, config):
            messages.error(request, 'You do not have permission to change this configuration.')
            return HttpResponseRedirect('../')

        from core.services.sheet_analyzer import (
            analyze_google_sheet,
            apply_analysis_to_config,
        )

        analysis = analyze_google_sheet(
            sheet_id=config.sheet_id,
            sheet_name=config.sheet_name,
            workflow=config.workflow or {},
        )
        if request.method == 'POST' and request.POST.get('action') == 'apply':
            if analysis.get('status') == 'success':
                apply_analysis_to_config(config, analysis)
                self._clear_runtime_config_cache()
                messages.success(
                    request,
                    'Sheet analysis applied. Schema, workflow dropdowns, and analysis metadata were saved.',
                )
                change_url = reverse(
                    'admin:core_groupsheetconfiguration_change',
                    args=[config.pk],
                )
                return HttpResponseRedirect(change_url)
            messages.error(
                request,
                analysis.get('error') or 'Sheet analysis failed.',
            )

        context = {
            **self.admin_site.each_context(request),
            'title': f'Analyze sheet: {config.display_name or config.group_id}',
            'opts': self.model._meta,
            'original': config,
            'config': config,
            'analysis': analysis,
            'has_change_permission': self.has_change_permission(request, config),
        }
        return TemplateResponse(
            request,
            'admin/core/groupsheetconfiguration/analyze_sheet.html',
            context,
        )

    def live_records_view(self, request, object_id):
        config = self.get_object(request, object_id)
        if not config:
            messages.error(request, 'Configuration was not found.')
            return HttpResponseRedirect('../')
        if not self.has_view_permission(request, config):
            messages.error(request, 'You do not have permission to view this configuration.')
            return HttpResponseRedirect('../')

        from core.services.live_sheet_records import (
            LiveSheetRecordError,
            allowed_sheet_tabs,
            load_live_sheet_table,
        )

        tabs = allowed_sheet_tabs(config)
        selected_tab = str(
            request.POST.get('sheet_tab')
            or request.GET.get('sheet_tab')
            or (tabs[0] if tabs else '')
        ).strip()
        edit_row = self._positive_int(
            request.POST.get('row_number') or request.GET.get('row')
        )
        action = request.POST.get('action', '')

        if request.method == 'POST' and action in {'update', 'delete'}:
            messages.error(
                request,
                'SHEET_IMPORT_DISABLED: Sheets are view-only. Update or archive the record in Django.',
            )
            return HttpResponseRedirect(
                f"{request.path}?{urlencode({'sheet_tab': selected_tab})}"
            )

        table = None
        load_error = ''
        try:
            table = load_live_sheet_table(config, selected_tab)
        except LiveSheetRecordError as exc:
            load_error = str(exc)

        edit_record = None
        if table and edit_row:
            edit_record = next(
                (
                    row for row in table['rows']
                    if row['row_number'] == edit_row
                ),
                None,
            )
            if not edit_record:
                messages.warning(request, 'That worksheet row no longer exists.')

        context = {
            **self.admin_site.each_context(request),
            'title': f'Live sheet records: {config.display_name or config.group_id}',
            'opts': self.model._meta,
            'original': config,
            'config': config,
            'tabs': tabs,
            'selected_tab': selected_tab,
            'table': table,
            'load_error': load_error,
            'edit_record': edit_record,
            'has_change_permission': False,
        }
        return TemplateResponse(
            request,
            'admin/core/groupsheetconfiguration/live_records.html',
            context,
        )

    @staticmethod
    def _positive_int(value):
        try:
            value = int(value)
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sync_case_mirror(config):
        return {
            'status': 'disabled',
            'code': 'SHEET_IMPORT_DISABLED',
            'errors': ['SHEET_IMPORT_DISABLED'],
        }

    @staticmethod
    def _warn_on_mirror_failure(request, result):
        if result and result.get('status') not in {'success', 'disabled'}:
            messages.warning(
                request,
                'The live Google Sheet changed, but the Django case mirror could '
                'not be refreshed. Run /sync after checking sheet access.',
            )

    @staticmethod
    def _audit_live_sheet_change(config, request, action, result):
        changes = (
            result.get('changes', {})
            if action == 'update'
            else result.get('deleted_values', {})
        )
        LiveSheetRecordChange.objects.create(
            group_configuration=config,
            group_id=config.group_id,
            sheet_id=config.sheet_id,
            sheet_tab=result.get('sheet_tab', ''),
            row_number=result.get('row_number') or 0,
            record_key=result.get('record_key', ''),
            action=action,
            changed_by=request.user.get_username(),
            changes=changes,
            status='success',
        )

    @staticmethod
    def _audit_live_sheet_failure(
        config,
        request,
        action,
        sheet_tab,
        row_number,
        error,
    ):
        LiveSheetRecordChange.objects.create(
            group_configuration=config,
            group_id=config.group_id,
            sheet_id=config.sheet_id,
            sheet_tab=sheet_tab,
            row_number=row_number or 0,
            action=action,
            changed_by=request.user.get_username(),
            status='failed',
            error=error,
        )

    def save_model(self, request, obj, form, change):
        apply_defaults = getattr(form, 'apply_preset_defaults', None)
        if apply_defaults:
            apply_defaults(obj)
        generated_workflow = getattr(form, 'generated_workflow', lambda: None)()
        if generated_workflow:
            obj.workflow = generated_workflow
        generated_sheet_schema = getattr(form, 'generated_sheet_schema', lambda: None)()
        if generated_sheet_schema is not None:
            obj.sheet_schema = generated_sheet_schema
        super().save_model(request, obj, form, change)
        self._clear_runtime_config_cache()
        self.message_user(
            request,
            'Configuration saved. Runtime group routing cache was refreshed.',
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        self._clear_runtime_config_cache()
    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        self._clear_runtime_config_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        self._clear_runtime_config_cache()

    @staticmethod
    def _clear_runtime_config_cache():
        from core.services.group_config import GroupRegistry
        from core.services.sheets import GoogleSheetsService

        GroupRegistry._instance = None
        GoogleSheetsService.clear_instances()


class RequisitionTemplateForm(forms.ModelForm):
    class Meta:
        model = RequisitionTemplate
        fields = '__all__'

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if upload and ('file' in self.changed_data or not self.instance.pk):
            from core.services.template_validation import validate_template_bytes
            data = upload.read()
            upload.seek(0)
            validate_template_bytes(data, 'requisition')
        return upload


class PaymentDocumentTemplateForm(forms.ModelForm):
    class Meta:
        model = PaymentDocumentTemplate
        fields = '__all__'

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if upload and ('file' in self.changed_data or not self.instance.pk):
            from core.services.template_validation import validate_template_bytes
            data = upload.read()
            upload.seek(0)
            validate_template_bytes(data, 'payment')
        return upload


class InvoiceNameChangeLetterTemplateForm(forms.ModelForm):
    class Meta:
        model = InvoiceNameChangeLetterTemplate
        fields = '__all__'
        widgets = {
            'file': UnfoldAdminFileFieldWidget(attrs={
                'accept': '.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            }),
        }

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if upload and ('file' in self.changed_data or not self.instance.pk):
            from core.services.invoice_name_change_letters import validate_template_file
            try:
                validate_template_file(upload)
            except ValueError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return upload


@admin.register(RequisitionTemplate)
class RequisitionTemplateAdmin(ModelAdmin):
    form = RequisitionTemplateForm
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = ('name', 'version_status', 'is_active', 'file', 'drive_url', 'drive_uploaded_at', 'created_at', 'updated_at')
    list_editable = ('is_active',)
    readonly_fields = (
        'original_filename', 'content_type', 'size', 'checksum',
        'drive_file_id', 'drive_url', 'drive_uploaded_at', 'drive_upload_error',
        'created_at', 'updated_at',
    )

    search_fields = ('name', 'original_filename', 'drive_file_id', 'drive_url')

    @admin.display(description='Version')
    def version_status(self, obj):
        return 'CURRENT / USED' if obj.is_active else 'Archived'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if 'file' in form.changed_data or not obj.drive_file_id:
            from core.services.template_storage import upload_template_record_to_drive
            upload_template_record_to_drive(obj, category='Requisition')


@admin.register(PaymentDocumentTemplate)
class PaymentDocumentTemplateAdmin(ModelAdmin):
    form = PaymentDocumentTemplateForm
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = ('name', 'version_status', 'is_active', 'file', 'drive_url', 'drive_uploaded_at', 'created_at', 'updated_at')
    list_editable = ('is_active',)
    readonly_fields = (
        'original_filename', 'content_type', 'size', 'checksum',
        'drive_file_id', 'drive_url', 'drive_uploaded_at', 'drive_upload_error',
        'created_at', 'updated_at',
    )
    search_fields = ('name', 'original_filename', 'drive_file_id', 'drive_url')

    @admin.display(description='Version')
    def version_status(self, obj):
        return 'CURRENT / USED' if obj.is_active else 'Archived'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if 'file' in form.changed_data or not obj.drive_file_id:
            from core.services.template_storage import upload_template_record_to_drive
            upload_template_record_to_drive(obj, category='Payment Documents')


@admin.register(InvoiceNameChangeLetterTemplate)
class InvoiceNameChangeLetterTemplateAdmin(ModelAdmin):
    form = InvoiceNameChangeLetterTemplateForm
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = (
        'name', 'version_status', 'file', 'drive_url', 'drive_uploaded_at',
        'created_at', 'updated_at',
    )
    list_filter = ('is_active', 'created_at')
    readonly_fields = (
        'template_key', 'original_filename', 'content_type', 'size', 'checksum',
        'drive_file_id', 'drive_url', 'drive_uploaded_at', 'drive_upload_error',
        'created_at', 'updated_at',
    )
    search_fields = ('name', 'original_filename', 'drive_file_id')

    @admin.display(description='Version')
    def version_status(self, obj):
        return 'CURRENT / USED' if obj.is_active else 'Archived'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if 'file' in form.changed_data or not obj.drive_file_id:
            from core.services.invoice_name_change_letters import DOCX_MIME_TYPE
            from core.services.template_storage import upload_template_record_to_drive
            ok, error = upload_template_record_to_drive(
                obj, category='Invoice Name Changes', mime_type=DOCX_MIME_TYPE,
            )
            if not ok:
                self.message_user(
                    request,
                    f'Template saved locally, but the Drive backup failed: {error}',
                    level=messages.WARNING,
                )


@admin.register(RequisitionBatch)
class RequisitionBatchAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'order_number', 'version', 'preview_version', 'requisition_date',
        'farmer_count', 'status', 'filename', 'preview_filename',
        'generated_by', 'drive_url', 'created_at', 'updated_at',
    )
    list_filter = ('status', 'requisition_date', 'created_at')
    search_fields = ('order_number', 'generated_by', 'filename', 'drive_file_id', 'drive_url')


@admin.register(InvoiceUploadBatch)
class InvoiceUploadBatchAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'original_filename', 'status', 'total_pages', 'total_parsed',
        'matched_count', 'unmatched_count', 'uploaded_by', 'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = ('original_filename', 'uploaded_by', 'drive_file_id', 'drive_url')


@admin.register(PortalVoiceTranscriptionAttempt)
class PortalVoiceTranscriptionAttemptAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'farmer', 'field_name', 'user', 'requested_language', 'detected_language', 'status', 'duration_ms', 'provider',
        'model_name', 'deletion_status', 'created_at', 'expires_at',
    )
    list_filter = ('field_name', 'requested_language', 'detected_language', 'status', 'provider', 'model_name', 'deletion_status', 'created_at')
    search_fields = ('farmer__customer_name', 'request_id', 'provider_request_id', 'user__username')


@admin.register(ParsedInvoice)
class ParsedInvoiceAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'invoice_no', 'status', 'customer_name', 'customer_id',
        'customer_phone', 'matched_order_number', 'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = (
        'invoice_no', 'customer_name', 'customer_id', 'customer_phone',
        'matched_order_number', 'batch__original_filename',
    )


@admin.register(InvoiceIdentityReview)
class InvoiceIdentityReviewAdmin(ReadOnlyAuditAdmin):
    list_display = ('invoice', 'farmer', 'status', 'decided_by', 'decided_at', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('invoice__invoice_no', 'farmer__customer_name', 'decided_by', 'decision_note')


@admin.register(JawabuRelatedPerson)
class JawabuRelatedPersonAdmin(ReadOnlyAuditAdmin):
    list_display = ('full_name', 'national_id', 'primary_phone', 'linked_customer', 'created_by', 'created_at')
    search_fields = ('full_name', 'national_id', 'primary_phone')


@admin.register(JawabuHouseholdRelationship)
class JawabuHouseholdRelationshipAdmin(ReadOnlyAuditAdmin):
    list_display = ('farmer', 'related_person', 'relationship_type', 'status', 'confirmed_by', 'confirmed_at')
    list_filter = ('relationship_type', 'status', 'created_at')
    search_fields = ('farmer__customer_name', 'related_person__full_name', 'confirmed_by')


@admin.register(InvoiceNameChangeBatch)
class InvoiceNameChangeBatchAdmin(ReadOnlyAuditAdmin):
    list_display = ('reference', 'status', 'sent_artifact', 'created_by', 'sent_by', 'sent_at', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('reference', 'created_by', 'sent_reference')


@admin.register(InvoiceNameChangeItem)
class InvoiceNameChangeItemAdmin(ReadOnlyAuditAdmin):
    list_display = ('batch', 'farmer', 'original_invoice', 'replacement_invoice', 'status', 'completed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('farmer__customer_name', 'original_invoice__invoice_no', 'replacement_invoice__invoice_no')


@admin.register(InvoiceNameChangeLetterArtifact)
class InvoiceNameChangeLetterArtifactAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'batch', 'version', 'status', 'filename', 'generated_by',
        'drive_url', 'generated_at',
    )
    list_filter = ('status', 'generated_at')
    search_fields = ('batch__reference', 'filename', 'generated_by', 'checksum', 'drive_file_id')


@admin.register(PaymentDocument)
class PaymentDocumentAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'order_number', 'payment_number', 'status', 'version', 'filename', 'row_count',
        'generated_by', 'reviewed_by', 'finalized_by', 'drive_url', 'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = ('order_number', 'payment_number', 'filename', 'generated_by', 'finalized_by', 'drive_file_id', 'drive_url')


@admin.register(DocumentSignoffPolicy)
class DocumentSignoffPolicyAdmin(CompactModelAdmin):
    """Read-only effective policy with maker-checker proposals only."""

    list_display = ('document_type', 'approval_roles_display', 'is_active', 'updated_at')
    list_filter = ('document_type', 'is_active')
    readonly_fields = ('document_type', 'workflow', 'approval_role', 'approval_roles', 'is_active', 'updated_at')
    change_list_template = 'admin/core/documentsignoffpolicy/change_list.html'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path('propose/', self.admin_site.admin_view(self.propose_policy), name='core_documentsignoffpolicy_propose'),
        ] + super().get_urls()

    @admin.display(description='Authorised Portal roles')
    def approval_roles_display(self, obj):
        return ', '.join(obj.effective_approval_roles)

    def propose_policy(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        from core.services.access_control import create_document_signoff_policy_request
        from core.services.access_policies import WORKFLOW_ROLES

        role_options = list(WORKFLOW_ROLES['jawabu_portal'])
        if request.method == 'POST':
            try:
                change_request = create_document_signoff_policy_request(
                    requester=request.user,
                    document_type=str(request.POST.get('document_type') or ''),
                    approval_roles=request.POST.getlist('approval_roles'),
                    reason=str(request.POST.get('reason') or ''),
                )
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                messages.success(request, 'Document sign-off policy proposal is pending independent approval. No live sign-off access changed.')
                return HttpResponseRedirect(reverse('admin:core_accesscontrolchangerequest_change', args=[change_request.pk]))
        return TemplateResponse(request, 'admin/core/documentsignoffpolicy/propose.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Propose document sign-off policy',
            'document_types': DocumentSignoffPolicy.DOCUMENT_TYPE_CHOICES,
            'role_options': role_options,
            'policies': DocumentSignoffPolicy.objects.order_by('document_type'),
        })


@admin.register(DocumentPhysicalSignoff)
class DocumentPhysicalSignoffAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'document_type', 'source_version', 'status', 'source_filename',
        'scan_filename', 'uploaded_by', 'approved_by', 'approved_at', 'created_at',
    )
    list_filter = ('document_type', 'status', 'created_at')
    search_fields = (
        'requisition_batch__order_number', 'payment_document__order_number',
        'payment_document__payment_number', 'scan_filename', 'source_checksum', 'scan_checksum',
    )
    readonly_fields = [field.name for field in DocumentPhysicalSignoff._meta.fields]


@admin.register(DocumentPhysicalSignoffEvent)
class DocumentPhysicalSignoffEventAdmin(ReadOnlyAuditAdmin):
    list_display = ('created_at', 'signoff', 'action', 'actor')
    list_filter = ('action', 'created_at')
    search_fields = ('signoff__scan_filename', 'actor__username', 'note')
    readonly_fields = [field.name for field in DocumentPhysicalSignoffEvent._meta.fields]


@admin.register(ComplianceAuditEvent)
class ComplianceAuditEventAdmin(ReadOnlyAuditAdmin):
    """Investigator-facing read/export interface for immutable evidence."""

    list_display = (
        'chain_position', 'occurred_at', 'workflow', 'action', 'origin',
        'subject_type', 'subject_id', 'actor_label', 'sensitive',
    )
    list_filter = ('workflow', 'category', 'origin', 'sensitive', 'retention_class', 'occurred_at')
    search_fields = ('subject_id', 'customer_reference', 'actor_label', 'authority_label', 'request_id', 'action')
    readonly_fields = [field.name for field in ComplianceAuditEvent._meta.fields]
    list_select_related = ('actor', 'authority_user')
    date_hierarchy = 'occurred_at'

    def has_change_permission(self, request, obj=None):
        # Read-only fields are useful for legacy audit models, but this ledger
        # must not expose a save route at all. PostgreSQL also enforces this.
        return False

    def get_urls(self):
        return [
            path('export/csv/', self.admin_site.admin_view(self.export_csv), name='core_complianceauditevent_export_csv'),
            path('export/pdf/', self.admin_site.admin_view(self.export_pdf), name='core_complianceauditevent_export_pdf'),
            path('verify/', self.admin_site.admin_view(self.verify), name='core_complianceauditevent_verify'),
        ] + super().get_urls()

    def _can_export(self, request):
        return bool(request.user.is_superuser or request.user.has_perm('core.export_complianceauditevent'))

    def _record_access(self, request, action: str):
        from core.services.compliance_audit import record_sensitive_access

        record_sensitive_access(
            workflow='access_control',
            action=action,
            subject_type='compliance_audit_ledger',
            subject_id='global',
            actor=request.user,
            request_id=str(request.headers.get('X-Request-ID') or uuid.uuid4()),
            metadata={'filters_used': bool(request.GET), 'method': request.method},
        )

    def changelist_view(self, request, extra_context=None):
        if self.has_view_permission(request):
            self._record_access(request, 'audit.ledger.searched')
        return super().changelist_view(request, extra_context=extra_context)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if object_id and self.has_view_permission(request):
            self._record_access(request, 'audit.ledger.viewed')
        return super().changeform_view(request, object_id, form_url, extra_context)

    def _events_for_request(self, request):
        from core.services.compliance_audit import filtered_events

        return filtered_events(filters=request.GET).order_by('-chain_position')[:10000]

    def export_csv(self, request):
        if not self._can_export(request):
            raise PermissionDenied
        from core.services.compliance_audit import evidence_csv

        self._record_access(request, 'audit.ledger.exported_csv')
        response = HttpResponse(evidence_csv(self._events_for_request(request)), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="jbl-compliance-audit-evidence.csv"'
        return response

    def export_pdf(self, request):
        if not self._can_export(request):
            raise PermissionDenied
        from core.services.compliance_audit import evidence_pdf

        self._record_access(request, 'audit.ledger.exported_pdf')
        try:
            payload = evidence_pdf(self._events_for_request(request))
        except Exception as exc:
            messages.error(request, f'Could not create the compliance evidence PDF: {exc}')
            return HttpResponseRedirect(reverse('admin:core_complianceauditevent_changelist'))
        response = HttpResponse(payload, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="jbl-compliance-audit-evidence.pdf"'
        return response

    def verify(self, request):
        if not (request.user.is_superuser or request.user.has_perm('core.verify_complianceauditevent')):
            raise PermissionDenied
        from core.services.compliance_audit import verify_integrity

        self._record_access(request, 'audit.ledger.integrity_verified')
        result = verify_integrity()
        if result.ok:
            messages.success(request, f'Integrity verified across {result.checked} compliance audit events.')
        else:
            messages.error(request, f'Integrity failed at position {result.first_error_position}: {result.first_error}')
        return HttpResponseRedirect(reverse('admin:core_complianceauditevent_changelist'))


@admin.register(ComplianceAuditChainState)
class ComplianceAuditChainStateAdmin(ReadOnlyAuditAdmin):
    list_display = ('singleton', 'last_position', 'last_hash', 'updated_at')
    readonly_fields = [field.name for field in ComplianceAuditChainState._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ComplianceAuditCheckpoint)
class ComplianceAuditCheckpointAdmin(ReadOnlyAuditAdmin):
    list_display = ('checkpoint_date', 'chain_position', 'event_count', 'status', 'delivery_attempts', 'delivered_at')
    list_filter = ('status', 'checkpoint_date')
    readonly_fields = [field.name for field in ComplianceAuditCheckpoint._meta.fields]


@admin.register(IntegrationOperation)
class IntegrationOperationAdmin(ReadOnlyAuditAdmin):
    list_display = ('integration', 'operation_type', 'source_model', 'source_id', 'status', 'attempts', 'next_retry_at', 'updated_at')
    list_filter = ('integration', 'operation_type', 'status')
    search_fields = ('source_model', 'source_id', 'request_id', 'deduplication_key')
    readonly_fields = [field.name for field in IntegrationOperation._meta.fields]


@admin.register(IntegrationCircuitState)
class IntegrationCircuitStateAdmin(ReadOnlyAuditAdmin):
    list_display = ('integration', 'status', 'consecutive_failures', 'next_probe_at', 'last_success_at', 'updated_at')
    list_filter = ('status',)
    readonly_fields = [field.name for field in IntegrationCircuitState._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(SpinCreditRequest)
class SpinCreditRequestAdmin(TestDataDeleteAdmin):
    list_display = (
        'request_datetime', 'request_type', 'customer_name', 'national_id',
        'primary_phone', 'requested_amount', 'import_status', 'requested_by',
    )
    list_filter = ('request_type', 'import_status', 'source_chat', 'created_at')
    search_fields = (
        'customer_name', 'national_id', 'primary_phone', 'secondary_phone',
        'requested_by', 'raw_message', 'source_message_hash',
    )


@admin.register(SpinBatchReviewItem)
class SpinBatchReviewItemAdmin(ReadOnlyAuditAdmin):
    list_display = ('category', 'status', 'group_id', 'source_sender', 'source_received_at', 'reviewed_by')
    list_filter = ('group_id', 'category', 'status', 'created_at')
    search_fields = ('source_sender', 'raw_message', 'source_message_hash', 'reviewed_by')
    readonly_fields = [field.name for field in SpinBatchReviewItem._meta.fields]


class UserProfileAdminForm(forms.ModelForm):
    telegram_id = forms.CharField(
        required=False,
        disabled=True,
        label='Telegram ID',
        help_text='Stored automatically after the user first opens a Mini App with verified Telegram authentication.',
    )

    class Meta:
        model = UserProfile
        fields = (
            'telegram_username', 'telegram_id', 'phone_number',
            'signing_national_id', 'signing_phone_number', 'signing_email',
        )

    def clean_telegram_username(self):
        return str(self.cleaned_data.get('telegram_username') or '').strip().lstrip('@').lower()


class UserProfileInline(StackedInline):
    model = UserProfile
    form = UserProfileAdminForm
    extra = 0
    max_num = 1
    fields = (
        ('telegram_username', 'telegram_id'), 'phone_number',
        ('signing_national_id', 'signing_phone_number', 'signing_email'),
    )


class WorkflowScopedSelect(forms.Select):
    def __init__(self, *args, workflow_map=None, **kwargs):
        self.workflow_map = workflow_map or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        raw_value = str(getattr(value, 'value', value) or '')
        workflows = self.workflow_map.get(raw_value)
        if workflows:
            option['attrs']['data-workflows'] = ','.join(sorted(workflows))
        return option


class GroupConfigurationAccessSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None:
            option['attrs']['data-workflow-type'] = str((instance.workflow or {}).get('type') or '')
        return option


class GroupConfigurationAccessField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        workflow_type = str((obj.workflow or {}).get('type') or 'unconfigured')
        label = obj.display_name or obj.group_id
        return f'[{workflow_type}] {label}'


def _configure_access_scope_fields(form) -> None:
    """Populate catalog-backed access choices only after Django has started."""
    from core.services.access_policies import branch_choices, product_choices

    branches = branch_choices()
    products = product_choices()
    form.fields['branch'].choices = branches
    form.fields['product'].choices = products
    form.fields['branch'].widget.workflow_map = {
        '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
        **{value: {'jawabu_portal', 'tat_tracker'} for value, _ in branches if value},
    }
    form.fields['product'].widget.workflow_map = {
        '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
        **{value: {'jawabu_portal', 'tat_tracker'} for value, _ in products if value},
    }
    form.fields['group_configuration'].queryset = GroupSheetConfiguration.objects.filter(enabled=True)


class AccessGrantAdminForm(forms.ModelForm):
    from core.services.access_policies import (
        branch_choices, product_choices, role_choices, role_workflow_map,
    )

    role_workflows = role_workflow_map()
    role = forms.ChoiceField(
        choices=role_choices(),
        label='Role tag',
        help_text='This workflow role tag controls queues/actions. Multiple active role tags and scopes are allowed.',
        widget=WorkflowScopedSelect(workflow_map=role_workflows),
    )
    branch = forms.ChoiceField(
        choices=(('', 'All branches'),), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
        }),
    )
    product = forms.ChoiceField(
        choices=(('', 'All products'),), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
        }),
    )
    group_configuration = GroupConfigurationAccessField(
        queryset=GroupSheetConfiguration.objects.none(),
        required=False,
        empty_label='All compatible groups',
        widget=GroupConfigurationAccessSelect,
    )

    class Meta:
        model = AccessGrant
        fields = ('active', 'workflow', 'role', 'branch', 'product', 'group_configuration')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configure_access_scope_fields(self)
        self.fields['active'].help_text = 'Only active grants are used for authorization and TAT dropdowns.'

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        from django.core.exceptions import ValidationError
        from core.services.access_policies import validate_access_scope
        try:
            cleaned['role'] = validate_access_scope(
                workflow=cleaned.get('workflow'), role=cleaned.get('role'),
                branch=cleaned.get('branch', ''), product=cleaned.get('product', ''),
                group_configuration=cleaned.get('group_configuration'),
            )
        except ValidationError as exc:
            for field, messages_list in exc.message_dict.items():
                for message in messages_list:
                    self.add_error(field, message)
        return cleaned

    class Media:
        js = ('admin/js/access_grant_inline.js',)


class AccessGrantRequestForm(AccessGrantAdminForm):
    request_key = forms.CharField(
        widget=forms.HiddenInput(), initial=uuid.uuid4, max_length=128,
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Explain the operational need. The grant will remain inactive until a different designated approver applies it.',
    )


class AccessControlCheckerAssignmentForm(forms.Form):
    reason = forms.CharField(
        label='Reason',
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Required. This appointment or revocation is permanently audit-logged.',
    )


class AccessGrantInline(StackedInline):
    model = AccessGrant
    form = AccessGrantAdminForm
    extra = 0
    fields = (
        ('active', 'workflow', 'role'),
        ('branch', 'product', 'group_configuration'),
        'source',
    )
    readonly_fields = ('source',)

    def has_add_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)


@admin.register(WorkflowTatDailyMetric)
class WorkflowTatDailyMetricAdmin(ReadOnlyAuditAdmin):
    list_display = ('metric_date', 'workflow', 'branch', 'product_key', 'stage_key', 'responsible_role', 'responsible_actor', 'active_count', 'completed_count', 'overdue_count', 'median_sla_minutes')
    list_filter = ('metric_date', 'workflow', 'branch', 'product_key', 'stage_key')
    search_fields = ('group_id', 'branch', 'product_key', 'stage_key', 'responsible_role', 'responsible_actor')


@admin.register(WorkflowTimelineAnnotation)
class WorkflowTimelineAnnotationAdmin(CompactModelAdmin):
    """Allow authorised append-only history annotations, never event edits."""

    list_display = ('workflow', 'subject_id', 'source_event_id', 'kind', 'actor', 'created_at')
    list_filter = ('workflow', 'kind', 'created_at')
    search_fields = ('subject_id', 'source_event_id', 'note', 'artifact_name')
    readonly_fields = ('actor', 'authority_user', 'created_at')

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return [field.name for field in self.model._meta.fields]
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.actor = request.user
            obj.authority_user = request.user
        super().save_model(request, obj, form, change)


@admin.register(WorkflowRoleCapability)
class WorkflowRoleCapabilityAdmin(CompactModelAdmin):
    """A deliberately constrained, audited role-to-capability policy matrix."""

    list_display = ('workflow', 'role', 'capability_key', 'enabled', 'updated_at')
    list_filter = ('workflow', 'role', 'enabled')
    search_fields = ('role', 'capability_key')
    readonly_fields = ('updated_at',)
    change_list_template = 'admin/core/workflowrolecapability/change_list.html'

    # The matrix is the only editing surface.  It records a before/after audit
    # event and applies capability dependencies, neither of which an inline
    # list edit or a per-row form can guarantee.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path('matrix/', self.admin_site.admin_view(self.matrix_view), name='core_workflowrolecapability_matrix'),
        ] + super().get_urls()

    def matrix_view(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        from core.services.access_policies import canonical_access_role, WORKFLOW_ROLES
        from core.services.access_control import capability_impact, create_capability_request
        from core.services.workflow_capabilities import capabilities_for_workflow

        selected_workflow = str(request.POST.get('workflow') or request.GET.get('workflow') or 'jawabu_portal')
        workflows = list(AccessGrant.WORKFLOW_CHOICES)
        if selected_workflow not in dict(workflows):
            selected_workflow = workflows[0][0]
        role_options = list(WORKFLOW_ROLES.get(selected_workflow, ()))
        definitions = capabilities_for_workflow(selected_workflow)
        if request.method == 'POST' and request.POST.get('propose_matrix'):
            selected_role = canonical_access_role(selected_workflow, request.POST.get('role', ''))
            valid_roles = {value for value, _label in role_options}
            if selected_role not in valid_roles:
                messages.error(request, 'Choose a valid role for this workflow.')
            else:
                submitted = {
                    item.key for item in definitions
                    if request.POST.get(f'capability:{item.key}') == 'on'
                }
                target_roles = [selected_role]
                for raw_role in request.POST.getlist('apply_roles'):
                    normalized = canonical_access_role(selected_workflow, raw_role)
                    if normalized in valid_roles and normalized not in target_roles:
                        target_roles.append(normalized)
                try:
                    change_request = create_capability_request(
                        requester=request.user, workflow=selected_workflow,
                        roles=target_roles, capability_keys=submitted,
                        reason=str(request.POST.get('reason') or ''),
                        request_key=str(request.POST.get('request_key') or ''),
                    )
                except ValidationError as exc:
                    messages.error(request, '; '.join(exc.messages))
                else:
                    messages.success(request, f'One atomic change request for {len(target_roles)} role(s) is pending independent approval. No live access changed.')
                    return HttpResponseRedirect(reverse('admin:core_accesscontrolchangerequest_changelist'))
        selected_role = canonical_access_role(selected_workflow, request.GET.get('role') or (role_options[0][0] if role_options else ''))
        copy_from_role = canonical_access_role(selected_workflow, request.GET.get('copy_from') or '')
        enabled_keys = set(WorkflowRoleCapability.objects.filter(
            workflow=selected_workflow, role=copy_from_role or selected_role,
            effect=WorkflowRoleCapability.EFFECT_ALLOW,
        ).values_list('capability_key', flat=True))
        rows = [
            {'definition': definition, 'enabled': definition.key in enabled_keys}
            for definition in definitions
        ]
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Mini App access matrix',
            'workflows': workflows,
            'selected_workflow': selected_workflow,
            'role_options': role_options,
            'role_rows': [
                {'value': value, 'label': label, 'impact': capability_impact(selected_workflow, value)}
                for value, label in role_options
            ],
            'role_impacts': {value: capability_impact(selected_workflow, value) for value, _label in role_options},
            'impact': capability_impact(selected_workflow, selected_role),
            'selected_role': selected_role,
            'copy_from_role': copy_from_role,
            'rows': rows,
            'request_key': uuid.uuid4(),
            'audit_events': WorkflowRoleCapabilityAuditEvent.objects.filter(
                workflow=selected_workflow, role=selected_role,
            ).select_related('actor')[:8],
        }
        return TemplateResponse(request, 'admin/core/workflowrolecapability/matrix.html', context)


@admin.register(WorkflowRoleCapabilityAuditEvent)
class WorkflowRoleCapabilityAuditEventAdmin(CompactModelAdmin):
    list_display = ('created_at', 'workflow', 'role', 'actor', 'source')
    list_filter = ('workflow', 'role', 'source')
    search_fields = ('role', 'actor__username', 'actor__first_name', 'actor__last_name')
    readonly_fields = ('workflow', 'role', 'actor', 'changes', 'source', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccessControlChangeRequest)
class AccessControlChangeRequestAdmin(CompactModelAdmin):
    """Approval queue; direct model edits would bypass the recorded diff."""

    list_display = ('requested_at', 'change_type', 'workflow', 'role', 'target_user', 'status', 'requested_by', 'reviewed_by')
    list_filter = ('status', 'change_type', 'workflow')
    search_fields = ('role', 'target_user__username', 'requested_by__username', 'reason')
    readonly_fields = (
        'change_type', 'workflow', 'role', 'target_roles', 'request_key', 'target_user', 'before_snapshot', 'proposed_snapshot',
        'impact', 'reason', 'status', 'policy_version', 'requested_by', 'requested_at',
        'reviewed_by', 'reviewed_at', 'review_comment', 'applied_at', 'source_request',
    )
    change_form_template = 'admin/core/accesscontrolchangerequest/change_form.html'
    change_list_template = 'admin/core/accesscontrolchangerequest/change_list.html'

    def get_urls(self):
        return [
            path('export/csv/', self.admin_site.admin_view(self.export_csv), name='core_accesscontrolchangerequest_export_csv'),
            path('export/pdf/', self.admin_site.admin_view(self.export_pdf), name='core_accesscontrolchangerequest_export_pdf'),
        ] + super().get_urls()

    def export_csv(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        from core.services.access_control_reporting import evidence_csv
        response = HttpResponse(evidence_csv(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="miniapp-access-control-evidence.csv"'
        return response

    def export_pdf(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        from core.services.access_control_reporting import evidence_pdf
        try:
            payload = evidence_pdf()
        except Exception as exc:
            messages.error(request, f'Could not create the PDF evidence report: {exc}')
            return HttpResponseRedirect(reverse('admin:core_accesscontrolchangerequest_changelist'))
        response = HttpResponse(payload, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="miniapp-access-control-evidence.pdf"'
        return response

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        from core.services.access_control import can_approve_access_change

        return can_approve_access_change(request.user)

    def has_view_permission(self, request, obj=None):
        from core.services.access_control import can_approve_access_change

        return can_approve_access_change(request.user) or super().has_view_permission(request, obj)

    def has_module_permission(self, request):
        from core.services.access_control import can_approve_access_change

        return can_approve_access_change(request.user) or super().has_module_permission(request)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if request.method == 'POST' and ('approve_request' in request.POST or 'reject_request' in request.POST):
            from core.services.access_control import approve_request, reject_request
            try:
                if 'approve_request' in request.POST:
                    result = approve_request(request_id=object_id, approver=request.user, review_comment=str(request.POST.get('review_comment') or ''))
                    message = 'Request applied.' if result.status == result.STATUS_APPLIED else 'Request is stale and was not applied.'
                    messages.success(request, message)
                else:
                    reject_request(request_id=object_id, approver=request.user, review_comment=str(request.POST.get('review_comment') or ''))
                    messages.success(request, 'Request rejected.')
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            return HttpResponseRedirect(reverse('admin:core_accesscontrolchangerequest_change', args=[object_id]))
        if object_id:
            from core.services.access_control import (
                bootstrap_override_available,
                can_approve_access_change,
                request_diff,
            )
            change_request = AccessControlChangeRequest.objects.get(pk=object_id)
            can_approve = can_approve_access_change(request.user)
            bootstrap_override = bootstrap_override_available(change_request, request.user)
            extra_context = {
                **(extra_context or {}),
                'request_diff': request_diff(change_request),
                'can_approve_access_change': can_approve,
                'can_approve_request': can_approve and (
                    change_request.requested_by_id != request.user.pk or bootstrap_override
                ),
                'can_reject_request': can_approve and change_request.requested_by_id != request.user.pk,
                'bootstrap_override_available': bootstrap_override,
            }
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields


@admin.register(AccessControlPolicySnapshot)
class AccessControlPolicySnapshotAdmin(CompactModelAdmin):
    list_display = ('version', 'request', 'created_at')
    readonly_fields = ('version', 'request', 'state', 'created_at')
    search_fields = ('request__workflow', 'request__role')
    change_form_template = 'admin/core/accesscontrolpolicysnapshot/change_form.html'

    def get_urls(self):
        return [
            path('<uuid:object_id>/propose-revert/', self.admin_site.admin_view(self.propose_revert), name='core_accesscontrolpolicysnapshot_propose_revert'),
        ] + super().get_urls()

    def propose_revert(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        snapshot = AccessControlPolicySnapshot.objects.get(pk=object_id)
        if request.method == 'POST':
            from core.services.access_control import create_rollback_request
            try:
                change_request = create_rollback_request(snapshot=snapshot, requester=request.user, reason=str(request.POST.get('reason') or ''))
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                messages.success(request, 'Rollback proposal submitted for independent approval.')
                return HttpResponseRedirect(reverse('admin:core_accesscontrolchangerequest_change', args=[change_request.pk]))
        return TemplateResponse(request, 'admin/core/accesscontrolpolicysnapshot/propose_revert.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': f'Propose rollback of policy version {snapshot.version}', 'snapshot': snapshot,
        })

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(AccessControlCheckerAssignment)
class AccessControlCheckerAssignmentAdmin(CompactModelAdmin):
    """Evidence-only view; checker authority changes only from a user record."""

    list_display = ('user', 'source', 'appointed_by', 'appointed_at', 'revoked_at', 'revoked_by')
    list_filter = ('source', 'revoked_at')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'appointment_reason')
    list_select_related = ('user', 'appointed_by', 'revoked_by')
    readonly_fields = (
        'user', 'appointed_by', 'appointment_reason', 'source', 'appointed_at',
        'revoked_at', 'revoked_by', 'revocation_reason',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmergencyAccessGrant)
class EmergencyAccessGrantAdmin(CompactModelAdmin):
    list_display = ('user', 'workflow', 'role', 'activated_by', 'expires_at', 'revoked_at')
    list_filter = ('workflow',)
    search_fields = ('user__username', 'role', 'reason')
    readonly_fields = (
        'user', 'workflow', 'role', 'branch', 'product', 'product_ref',
        'group_configuration', 'reason', 'request_id', 'activated_by',
        'activated_at', 'expires_at', 'revoked_at', 'revoked_by',
        'revocation_reason',
    )
    actions = ('revoke_selected_emergency_access',)

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    @admin.action(description='Revoke selected active emergency access')
    def revoke_selected_emergency_access(self, request, queryset):
        from core.services.access_control import revoke_emergency_grant

        changed = 0
        for grant in queryset:
            _grant, revoked = revoke_emergency_grant(
                actor=request.user,
                grant=grant,
                reason='Explicitly revoked from the Django Admin emergency-access register.',
            )
            changed += int(revoked)
        messages.success(request, f'{changed} emergency access grant(s) revoked and audit-logged.')


@admin.register(AccessControlNotification)
class AccessControlNotificationAdmin(CompactModelAdmin):
    list_display = ('created_at', 'event', 'channel', 'recipient', 'status')
    list_filter = ('event', 'channel', 'status')
    readonly_fields = ('request', 'recipient', 'channel', 'event', 'status', 'error', 'created_at', 'delivered_at')
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CapabilityUsageDaily)
class CapabilityUsageDailyAdmin(CompactModelAdmin):
    list_display = ('day', 'user', 'workflow', 'capability_key', 'use_count', 'last_used_at')
    list_filter = ('workflow', 'day')
    search_fields = ('user__username', 'capability_key')
    readonly_fields = ('day', 'user', 'workflow', 'capability_key', 'use_count', 'last_used_at')
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


class StaffUserCreationForm(forms.Form):
    from core.services.access_policies import (
        branch_choices, product_choices, role_choices, role_workflow_map,
    )

    role_workflows = role_workflow_map()
    LOGIN_TELEGRAM = 'telegram'
    LOGIN_DJANGO = 'django'
    login_method = forms.ChoiceField(choices=(
        (LOGIN_TELEGRAM, 'Telegram Mini App'),
        (LOGIN_DJANGO, 'Django Admin login'),
    ))
    display_name = forms.CharField(max_length=255, help_text='The staff member’s full name.')
    telegram_username = forms.CharField(
        max_length=100, required=False,
        help_text='Enter the current Telegram username. The numeric ID is bound after the first signed Mini App login.',
    )
    django_username = forms.CharField(
        max_length=150, required=False,
        help_text='Required only for a password-based Django Admin account.',
    )
    email = forms.EmailField(required=False)
    password = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Required only for a Django Admin account.',
    )
    workflow = forms.ChoiceField(choices=AccessGrant.WORKFLOW_CHOICES)
    role = forms.ChoiceField(
        choices=role_choices(),
        label='Role tag',
        help_text='For TAT Tracker, choose BRO to include this user in the BRO dropdown.',
        widget=WorkflowScopedSelect(workflow_map=role_workflows),
    )
    branch = forms.ChoiceField(
        choices=(('', 'All branches'),), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
        }),
    )
    product = forms.ChoiceField(
        choices=(('', 'All products'),), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
        }),
    )
    group_configuration = GroupConfigurationAccessField(
        queryset=GroupSheetConfiguration.objects.none(), required=False,
        empty_label='All compatible groups', widget=GroupConfigurationAccessSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configure_access_scope_fields(self)

    def clean_telegram_username(self):
        username = self.cleaned_data.get('telegram_username', '').strip().lstrip('@').lower()
        if username and UserProfile.objects.filter(telegram_username__iexact=username).exists():
            raise forms.ValidationError('That Telegram username is already enrolled.')
        return username

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if cleaned.get('login_method') == self.LOGIN_TELEGRAM:
            if not cleaned.get('telegram_username'):
                self.add_error('telegram_username', 'Enter the staff member’s Telegram username.')
        else:
            username = str(cleaned.get('django_username') or '').strip()
            if not username:
                self.add_error('django_username', 'Enter a Django username.')
            elif get_user_model().objects.filter(username__iexact=username).exists():
                self.add_error('django_username', 'That Django username already exists.')
            if not cleaned.get('password'):
                self.add_error('password', 'Enter a password for the Django Admin account.')
        if self.errors:
            return cleaned
        from django.core.exceptions import ValidationError
        from core.services.access_policies import validate_access_scope
        try:
            cleaned['role'] = validate_access_scope(
                workflow=cleaned.get('workflow'), role=cleaned.get('role'),
                branch=cleaned.get('branch', ''), product=cleaned.get('product', ''),
                group_configuration=cleaned.get('group_configuration'),
            )
        except ValidationError as exc:
            for field, messages_list in exc.message_dict.items():
                for message in messages_list:
                    self.add_error(field, message)
        return cleaned

    class Media:
        js = ('admin/js/access_grant_inline.js',)


class UnfoldUserAdmin(ModelAdmin, DjangoUserAdmin):
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = ('username', 'email', 'first_name', 'last_name', 'role_tags', 'is_staff', 'is_active')
    inlines = (UserProfileInline, AccessGrantInline)
    change_list_template = 'admin/auth/user/change_list.html'
    change_form_template = 'admin/auth/user/change_form.html'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('access_grants')

    def save_model(self, request, obj, form, change):
        # The lifecycle signal uses this transient actor for compliance
        # attribution and retires all effective access on active -> inactive.
        obj._access_retirement_actor = request.user
        return super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        """Route technical-root grant edits through the audited override service.

        A raw inline save would bypass the policy ledger and leave Mini App
        clients with no version signal to re-evaluate effective access.
        Non-AccessGrant inlines retain Django's normal save behaviour.
        """
        if formset.model is not AccessGrant:
            return super().save_formset(request, form, formset, change)
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied('Only an active Django Superuser can directly manage Access Grants.')

        from core.services.access_control import apply_superuser_grant_override

        target_user = formset.instance
        formset.save(commit=False)
        deleted = list(formset.deleted_objects)
        changed = [instance for instance, _changed_fields in formset.changed_objects]
        created = list(formset.new_objects)
        applied = 0
        with transaction.atomic():
            # Delete first so a scope can be moved onto a currently occupied
            # unique key without a transient uniqueness collision.
            for grant in deleted:
                apply_superuser_grant_override(
                    actor=request.user,
                    user=target_user,
                    grant=grant,
                    operation='delete',
                )
                applied += 1
            for instance in changed:
                existing = AccessGrant.objects.select_related('group_configuration').get(pk=instance.pk)
                apply_superuser_grant_override(
                    actor=request.user,
                    user=target_user,
                    workflow=instance.workflow,
                    role=instance.role,
                    branch=instance.branch,
                    product=instance.product,
                    group_configuration=instance.group_configuration,
                    active=instance.active,
                    grant=existing,
                )
                applied += 1
            for instance in created:
                apply_superuser_grant_override(
                    actor=request.user,
                    user=target_user,
                    workflow=instance.workflow,
                    role=instance.role,
                    branch=instance.branch,
                    product=instance.product,
                    group_configuration=instance.group_configuration,
                    active=instance.active,
                )
                applied += 1
        formset.save_m2m()
        if applied:
            messages.success(
                request,
                f'{applied} Access Grant change(s) applied immediately by Django Superuser override and audit-logged.',
            )

    @admin.display(description='Role tags')
    def role_tags(self, obj):
        workflow_labels = dict(AccessGrant.WORKFLOW_CHOICES)
        grants = [grant for grant in obj.access_grants.all() if grant.active]
        if not grants:
            return '—'
        tags = {
            (grant.workflow, grant.role)
            for grant in grants
        }
        return ', '.join(
            f"{workflow_labels.get(workflow, workflow)}: {role}"
            for workflow, role in sorted(tags)
        )

    @staticmethod
    def _recover_unusable_connection():
        """Drop a stale failed connection before constructing user inlines.

        A database error caught by an earlier request can leave a persistent
        PostgreSQL connection in ``INERROR`` until it is closed.  Django's
        normal connection cleanup only probes connections it already knows
        encountered an error; this admin surface may be the first request
        after a custom migration/enrolment action swallowed one.  User forms
        build dynamic branch/group choices during rendering, so recovering
        here avoids turning that stale state into a misleading 500 page.
        Never close a connection owned by an active atomic block.
        """
        connection = connections['default']
        if connection.connection is None or connection.in_atomic_block:
            return
        # ``is_usable()`` only checks whether the PostgreSQL socket answers;
        # psycopg can still report that socket as usable while its transaction
        # is aborted after a caught IntegrityError.  Any subsequent query then
        # raises ``current transaction is aborted`` until the connection is
        # rolled back or closed.  Close it here so Django opens a clean one.
        transaction_status = getattr(
            getattr(connection.connection, 'info', None), 'transaction_status', None,
        )
        status_name = str(getattr(transaction_status, 'name', transaction_status)).upper()
        if status_name.endswith('INERROR'):
            connection.close()
            return
        # Some PostgreSQL/driver combinations expose no useful transaction
        # status object.  Probe the connection itself as a fallback; a failed
        # ``SELECT 1`` is the definitive signal that this request must start
        # with a fresh connection.
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except DatabaseError:
            connection.close()
            return
        try:
            usable = connection.is_usable()
        except DatabaseError:
            usable = False
        if not usable:
            connection.close()

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        self._recover_unusable_connection()
        if object_id:
            target_user = self.get_object(request, object_id)
            if target_user is not None:
                from core.services.access_control import active_checker_assignment_for_user

                extra_context = {
                    **(extra_context or {}),
                    'access_control_checker_assignment': active_checker_assignment_for_user(target_user),
                }
        return super().changeform_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url='', extra_context=None):
        """Use one guided flow for identity and initial workflow access."""
        return HttpResponseRedirect(reverse('admin:auth_user_add_staff'))

    def get_urls(self):
        custom_urls = [
            path(
                'add-staff/',
                self.admin_site.admin_view(self.add_staff_view),
                name='auth_user_add_staff',
            ),
            path('<int:object_id>/request-access/', self.admin_site.admin_view(self.request_access_view), name='auth_user_request_access'),
            path('<int:object_id>/emergency-access/', self.admin_site.admin_view(self.emergency_access_view), name='auth_user_emergency_access'),
            path('<int:object_id>/effective-access/', self.admin_site.admin_view(self.effective_access_view), name='auth_user_effective_access'),
            path('<int:object_id>/appoint-access-checker/', self.admin_site.admin_view(self.appoint_access_checker_view), name='auth_user_appoint_access_checker'),
            path('<int:object_id>/revoke-access-checker/', self.admin_site.admin_view(self.revoke_access_checker_view), name='auth_user_revoke_access_checker'),
        ]
        return custom_urls + super().get_urls()

    def add_staff_view(self, request):
        """Create a canonical user and initial workflow grant in one operation."""
        self._recover_unusable_connection()
        if not request.user.is_superuser:
            raise PermissionDenied
        creation_form = StaffUserCreationForm(request.POST or None)
        if request.method == 'POST' and creation_form.is_valid():
            user = self._create_staff_user(creation_form.cleaned_data, request.user)
            messages.success(request, f'{user.get_full_name() or user.get_username()} was created with immediate, audit-logged workflow access.')
            return HttpResponseRedirect(reverse('admin:auth_user_change', args=(user.pk,)))
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Add staff user',
            'creation_form': creation_form,
            'media': self.media + creation_form.media,
        }
        return TemplateResponse(request, 'admin/auth/user/add_staff.html', context)

    @staticmethod
    @transaction.atomic
    def _create_staff_user(data, requester):
        User = get_user_model()
        telegram_username = data.get('telegram_username', '')
        if data['login_method'] == StaffUserCreationForm.LOGIN_TELEGRAM:
            safe_username = re.sub(r'[^a-z0-9_]', '_', telegram_username)[:100]
            django_username = f'tg_pending_{safe_username}'
            if User.objects.filter(username=django_username).exists():
                django_username = f'{django_username}_{uuid.uuid4().hex[:8]}'
        else:
            django_username = data['django_username'].strip()
        name_parts = data['display_name'].strip().split(None, 1)
        user = User(
            username=django_username,
            first_name=name_parts[0] if name_parts else '',
            last_name=name_parts[1] if len(name_parts) > 1 else '',
            email=data.get('email', ''),
            is_active=True,
            is_staff=data['login_method'] == StaffUserCreationForm.LOGIN_DJANGO,
        )
        if data['login_method'] == StaffUserCreationForm.LOGIN_DJANGO:
            user.set_password(data['password'])
        else:
            user.set_unusable_password()
        user.save()
        UserProfile.objects.create(user=user, telegram_username=telegram_username)
        from core.services.access_control import apply_superuser_grant_override
        apply_superuser_grant_override(
            actor=requester, user=user, workflow=data['workflow'], role=data['role'],
            branch=data.get('branch', ''), product=data.get('product', ''),
            group_configuration=data.get('group_configuration'),
        )
        return user

    def request_access_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        user = self.get_object(request, object_id)
        if user is None:
            raise PermissionDenied
        form = AccessGrantRequestForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            from core.services.access_control import create_grant_request
            change_request = create_grant_request(
                requester=request.user, user=user, workflow=form.cleaned_data['workflow'], role=form.cleaned_data['role'],
                branch=form.cleaned_data.get('branch', ''), product=form.cleaned_data.get('product', ''),
                group_configuration=form.cleaned_data.get('group_configuration'), active=form.cleaned_data.get('active', True),
                reason=form.cleaned_data['reason'], request_key=form.cleaned_data['request_key'],
            )
            messages.success(request, 'Access request submitted for independent approval.')
            return HttpResponseRedirect(reverse('admin:core_accesscontrolchangerequest_change', args=[change_request.pk]))
        return TemplateResponse(request, 'admin/auth/user/access_request.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': f'Request Mini App access: {user.get_username()}', 'form': form, 'target_user': user,
        })

    def appoint_access_checker_view(self, request, object_id):
        """Appoint a non-superuser checker through the audited root boundary."""
        if not request.user.is_superuser:
            raise PermissionDenied
        user = self.get_object(request, object_id)
        if user is None:
            raise PermissionDenied
        from core.services.access_control import appoint_access_control_checker

        form = AccessControlCheckerAssignmentForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            try:
                _assignment, created = appoint_access_control_checker(
                    actor=request.user,
                    user=user,
                    reason=form.cleaned_data['reason'],
                )
            except (PermissionDenied, ValidationError) as exc:
                form.add_error(None, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                message = (
                    f'{user.get_username()} is now an independent access control checker.'
                    if created else f'{user.get_username()} is already an active access control checker.'
                )
                messages.success(request, message)
                return HttpResponseRedirect(reverse('admin:auth_user_change', args=[user.pk]))
        return TemplateResponse(request, 'admin/auth/user/access_checker_assignment.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Appoint access control checker: {user.get_username()}',
            'form': form,
            'target_user': user,
            'mode': 'appoint',
        })

    def revoke_access_checker_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        user = self.get_object(request, object_id)
        if user is None:
            raise PermissionDenied
        from core.services.access_control import active_checker_assignment_for_user, revoke_access_control_checker

        assignment = active_checker_assignment_for_user(user)
        if assignment is None:
            messages.info(request, f'{user.get_username()} is not an active access control checker.')
            return HttpResponseRedirect(reverse('admin:auth_user_change', args=[user.pk]))
        form = AccessControlCheckerAssignmentForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            try:
                _assignment, changed = revoke_access_control_checker(
                    actor=request.user,
                    assignment=assignment,
                    reason=form.cleaned_data['reason'],
                )
            except (PermissionDenied, ValidationError) as exc:
                form.add_error(None, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                messages.success(
                    request,
                    f'{user.get_username()} is no longer an access control checker.' if changed
                    else f'{user.get_username()} is already inactive as an access control checker.',
                )
                return HttpResponseRedirect(reverse('admin:auth_user_change', args=[user.pk]))
        return TemplateResponse(request, 'admin/auth/user/access_checker_assignment.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Revoke access control checker: {user.get_username()}',
            'form': form,
            'target_user': user,
            'mode': 'revoke',
            'assignment': assignment,
        })

    def emergency_access_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        user = self.get_object(request, object_id)
        if user is None:
            raise PermissionDenied
        form = AccessGrantRequestForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            from core.services.access_control import create_emergency_grant
            grant = create_emergency_grant(
                actor=request.user, user=user, workflow=form.cleaned_data['workflow'], role=form.cleaned_data['role'],
                branch=form.cleaned_data.get('branch', ''), product=form.cleaned_data.get('product', ''),
                group_configuration=form.cleaned_data.get('group_configuration'), reason=form.cleaned_data['reason'],
                request_id=form.cleaned_data['request_key'],
            )
            messages.warning(request, f'Emergency access is active until {grant.expires_at:%d-%b-%Y %H:%M}. Approvers were notified.')
            return HttpResponseRedirect(reverse('admin:auth_user_change', args=[user.pk]))
        return TemplateResponse(request, 'admin/auth/user/access_request.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': f'Emergency access (four hours): {user.get_username()}', 'form': form, 'target_user': user, 'emergency': True,
        })

    def effective_access_view(self, request, object_id):
        user = self.get_object(request, object_id)
        if user is None or not request.user.is_superuser:
            raise PermissionDenied
        from core.services.telegram_identity import user_access
        from core.services.workflow_capabilities import capabilities_payload
        from core.services.portal_permissions import portal_capability_scope
        rows = []
        for workflow, label in AccessGrant.WORKFLOW_CHOICES:
            access = user_access(user, workflow)
            capabilities = capabilities_payload(user, workflow, access=access)
            scoped_capabilities = []
            if workflow == 'jawabu_portal':
                for capability in capabilities:
                    scope = portal_capability_scope(user, capability, access=access)
                    scoped_capabilities.append({
                        'key': capability,
                        'assignments': [
                            f"{item['role']}: {item['branch'] or 'All branches'} / {item['product'] or 'All products'}"
                            for item in scope['assignments']
                        ],
                    })
            rows.append({
                'workflow': label, 'roles': access['roles'], 'branches': access['branches'],
                'products': access['products'], 'capabilities': capabilities,
                'capability_scopes': scoped_capabilities,
                'emergency': access.get('emergency_grants', []),
            })
        return TemplateResponse(request, 'admin/auth/user/effective_access.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': f'Effective Mini App access: {user.get_username()}', 'target_user': user, 'rows': rows,
        })


class UnfoldGroupAdmin(ModelAdmin, DjangoGroupAdmin):
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True


class OriginationDataFieldAdminForm(forms.ModelForm):
    """Admin validation for controlled draft-only type corrections."""

    class Meta:
        model = OriginationDataField
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'data_type' in self.fields:
            self.fields['data_type'].help_text = (
                'Correctable while this field exists only in draft loan forms or ready '
                'templates. Once published or captured in an application, create a replacement '
                'field instead.'
            )
        if 'source_type' in self.fields:
            self.fields['source_type'].help_text = (
                'Governance changes apply to future application snapshots; existing applications '
                'keep their frozen contract.'
            )
        if 'help_text' in self.fields:
            self.fields['help_text'].help_text = (
                'Default guidance for future attachments. A product or document may keep its own '
                'presentation-specific guidance.'
            )

    def clean_data_type(self):
        data_type = self.cleaned_data['data_type']
        if not self.instance.pk:
            return data_type
        original = OriginationDataField.objects.filter(pk=self.instance.pk).first()
        if not original or original.data_type == data_type:
            return data_type
        from core.services.origination_fields import data_field_type_change_blockers
        blockers = data_field_type_change_blockers(original)
        if blockers:
            raise forms.ValidationError(
                'This type is frozen because the field is used by '
                f"{', '.join(blockers)}. Create a correctly typed replacement field, or use the "
                'Origination testing reset before correcting this catalogue entry.'
            )
        return data_type

    def clean_choice_options(self):
        options = self.cleaned_data.get('choice_options') or []
        if not self.instance.pk:
            return options
        original = OriginationDataField.objects.filter(pk=self.instance.pk).values_list(
            'choice_options', flat=True,
        ).first() or []
        previous_codes = {
            str(item.get('code') or '') for item in original if isinstance(item, dict)
        }
        current_codes = {
            str(item.get('code') or '') for item in options if isinstance(item, dict)
        }
        removed = sorted(previous_codes - current_codes)
        if removed and self.cleaned_data.get('data_type') == OriginationDataField.TYPE_CHOICE:
            raise forms.ValidationError(
                'Canonical choice codes cannot be removed. Mark obsolete options inactive so '
                'historical values remain interpretable. Missing: ' + ', '.join(removed)
            )
        return options


@admin.register(OriginationDataField)
class OriginationDataFieldAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    form = OriginationDataFieldAdminForm
    change_list_template = 'admin/core/originationdatafield/change_list.html'
    list_select_related = ('preferred_field',)
    list_display = (
        'key', 'label', 'data_type', 'category', 'source_type', 'sensitivity',
        'reporting_use', 'terminology_status', 'active', 'updated_at',
    )
    list_filter = (
        'active', 'data_type', 'source_type', 'sensitivity', 'reporting_use',
        'export_allowed', 'terminology_reviewed_distinct', 'category',
    )
    search_fields = ('key', 'label', 'category')
    readonly_fields = (
        'preferred_field', 'terminology_reviewed_distinct',
        'created_by', 'created_at', 'updated_at',
    )
    fieldsets = (
        ('Canonical identity', {
            'fields': (('key', 'label'), 'aliases', ('category', 'data_type')),
            'description': (
                'The stable key is locked after creation. A Superuser may correct the data type '
                'only while every use is still an editable draft; attached draft schemas are '
                'updated together.'
            ),
        }),
        ('Governance', {'fields': (
            ('source_type', 'sensitivity'), ('masking_policy', 'reporting_use'),
            ('export_allowed', 'active'),
            ('preferred_field', 'terminology_reviewed_distinct'),
        ), 'description': (
            'Editable governance for future applications. Every application already created keeps '
            'the governance values frozen in its schema snapshot.'
        )}),
        ('Input contract', {
            'fields': ('help_text', 'choice_options'),
            'description': (
                'Edit default guidance and choice labels for future configuration. Existing '
                'product-specific labels, rules, and application snapshots are preserved.'
            ),
        }),
        ('Audit', {'fields': (('created_by', 'created_at'), 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='Terminology')
    def terminology_status(self, obj):
        if obj.preferred_field_id:
            return f'Legacy → {obj.preferred_field.key}'
        if obj.terminology_reviewed_distinct:
            return 'Confirmed distinct'
        return 'Preferred'

    def get_urls(self):
        return [
            path(
                'terminology-audit/',
                self.admin_site.admin_view(self.terminology_audit_view),
                name='core_originationdatafield_terminology_audit',
            ),
        ] + super().get_urls()

    def terminology_audit_view(self, request):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        from core.services.origination_fields import (
            OriginationFieldError,
            consolidate_data_field,
            mark_data_field_terminology_distinct,
            terminology_audit_candidates,
        )
        if request.method == 'POST':
            try:
                action = str(request.POST.get('action') or '')
                if action == 'consolidate':
                    duplicate = OriginationDataField.objects.get(pk=request.POST.get('duplicate_id'))
                    preferred = OriginationDataField.objects.get(pk=request.POST.get('preferred_id'))
                    consolidate_data_field(
                        duplicate=duplicate, preferred=preferred, actor=request.user,
                    )
                    messages.success(
                        request,
                        f'{duplicate.label} is now a historical alias of {preferred.label}. '
                        'Existing applications and PDF mappings were left unchanged.',
                    )
                elif action == 'distinct':
                    data_field = OriginationDataField.objects.get(pk=request.POST.get('field_id'))
                    mark_data_field_terminology_distinct(
                        data_field=data_field, actor=request.user,
                    )
                    messages.success(request, f'{data_field.label} was confirmed as a distinct concept.')
                else:
                    raise OriginationFieldError('Choose a terminology review action.')
            except (OriginationDataField.DoesNotExist, OriginationFieldError, ValidationError) as exc:
                messages.error(request, str(exc))
            return HttpResponseRedirect(
                reverse('admin:core_originationdatafield_terminology_audit'),
            )
        from core.services.origination_terminology import ORIGINATION_TERMINOLOGY
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Origination terminology audit',
            'candidates': terminology_audit_candidates(),
            'terminology': ORIGINATION_TERMINOLOGY,
        }
        return TemplateResponse(
            request, 'admin/core/originationdatafield/terminology_audit.html', context,
        )

    def save_model(self, request, obj, form, change):
        before = None
        if change:
            before = OriginationDataField.objects.filter(pk=obj.pk).values(
                'label', 'aliases', 'category', 'data_type', 'source_type',
                'sensitivity', 'masking_policy',
                'reporting_use', 'export_allowed', 'help_text', 'choice_options', 'active',
                'preferred_field_id', 'terminology_reviewed_distinct',
            ).first()
        if not obj.created_by_id:
            obj.created_by = request.user
        correction = None
        if before and before['data_type'] != obj.data_type:
            from core.services.origination_fields import correct_draft_data_field_type
            correction = correct_draft_data_field_type(
                data_field=obj, new_type=obj.data_type,
                choice_options=obj.choice_options, structure_schema=obj.structure_schema,
                actor=request.user,
            )
        super().save_model(request, obj, form, change)
        after = {
            'label': obj.label, 'aliases': obj.aliases, 'category': obj.category,
            'data_type': obj.data_type, 'source_type': obj.source_type,
            'sensitivity': obj.sensitivity, 'masking_policy': obj.masking_policy,
            'reporting_use': obj.reporting_use, 'export_allowed': obj.export_allowed,
            'help_text': obj.help_text, 'choice_options': obj.choice_options,
            'active': obj.active,
            'preferred_field_id': obj.preferred_field_id,
            'terminology_reviewed_distinct': obj.terminology_reviewed_distinct,
        }
        action = 'created' if not change else ('deactivated' if before and before['active'] and not obj.active else 'updated')
        OriginationDataFieldEvent.objects.create(
            data_field=obj, action=action, actor=request.user,
            metadata={
                'key': obj.key, 'type': obj.data_type,
                'draft_contracts_updated': correction or {},
                'changed_fields': sorted(
                    key for key, value in after.items() if not before or before.get(key) != value
                ),
            },
        )

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and 'key' not in fields:
            fields.append('key')
        return tuple(fields)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OriginationFieldReviewIssue)
class OriginationFieldReviewIssueAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    list_display = (
        'legacy_key', 'legacy_type', 'product_definition', 'reason', 'status',
        'assigned_to', 'updated_at',
    )
    list_filter = ('status', 'reason', 'legacy_type')
    search_fields = (
        'legacy_key', 'legacy_label', 'product_definition__product_key',
        'product_definition__name',
    )
    readonly_fields = (
        'product_definition', 'legacy_key', 'legacy_type', 'legacy_label', 'reason',
        'suggested_field', 'resolved_by', 'resolved_at', 'created_at', 'updated_at',
    )
    fields = (
        'product_definition', ('legacy_key', 'legacy_type'), 'legacy_label', 'reason',
        'suggested_field', 'assigned_to', 'status', 'resolution_field',
        'resolution_notes', ('resolved_by', 'resolved_at'), ('created_at', 'updated_at'),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            raise PermissionDenied
        original = OriginationFieldReviewIssue.objects.get(pk=obj.pk)
        if obj.status == OriginationFieldReviewIssue.STATUS_OPEN:
            original.assigned_to = obj.assigned_to
            original.save(update_fields=['assigned_to', 'updated_at'])
            return
        from core.services.origination_fields import resolve_review_issue
        resolve_review_issue(
            issue=original, status=obj.status, resolution_field=obj.resolution_field,
            notes=obj.resolution_notes, actor=request.user,
        )

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OriginationProductDocumentAssignment)
class OriginationProductDocumentAssignmentAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    form = OriginationProductDocumentAssignmentForm
    change_form_template = 'admin/core/originationproductdocumentassignment/change_form.html'
    list_display = (
        'name', 'product_definition', 'document_key', 'version_policy',
        'resolved_template_version', 'inclusion_mode', 'display_order',
    )
    list_filter = ('version_policy', 'inclusion_mode', 'product_definition__lifecycle_status')
    search_fields = ('name', 'document_key', 'product_definition__name', 'template__name')
    fields = (
        'product_definition', ('template', 'version_policy'),
        ('inclusion_mode', 'display_order'), ('officer_selectable', 'default_selected'),
        ('condition_field', 'condition_operator'), 'condition_value',
        'applicability_rule', 'created_by', 'created_at',
    )
    readonly_fields = ('created_by', 'created_at')

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = {
            **(extra_context or {}),
            'origination_condition_fields_by_product': {
                str(item.pk): _product_condition_fields(item)
                for item in OriginationProductDefinition.objects.filter(
                    lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
                )
            },
        }
        return super().changeform_view(request, object_id, form_url, context)

    @admin.display(description='Currently resolves to')
    def resolved_template_version(self, obj):
        from core.services.origination_templates import resolve_assignment_template
        resolved = resolve_assignment_template(obj)
        if not resolved:
            return 'Unavailable'
        suffix = 'pinned' if obj.version_policy == obj.VERSION_PINNED else 'latest compatible'
        return f'{resolved.name} v{resolved.version} ({suffix})'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'product_definition':
            kwargs['queryset'] = OriginationProductDefinition.objects.filter(
                lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
            ).order_by('name', '-version')
        elif db_field.name == 'template':
            kwargs['queryset'] = OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True,
                document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
                status=OriginationDocumentTemplate.STATUS_ACTIVE,
            ).order_by('name', '-version')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)
        OriginationProductDefinitionEvent.objects.create(
            product_definition=obj.product_definition,
            action='shared_document_assignment_updated' if change else 'shared_document_assigned',
            actor=request.user,
            metadata={
                'assignment_id': str(obj.pk), 'template_id': str(obj.template_id),
                'document_key': obj.document_key, 'inclusion_mode': obj.inclusion_mode,
                'version_policy': obj.version_policy,
            },
        )

    def delete_model(self, request, obj):
        product = obj.product_definition
        metadata = {'assignment_id': str(obj.pk), 'template_id': str(obj.template_id), 'document_key': obj.document_key}
        super().delete_model(request, obj)
        OriginationProductDefinitionEvent.objects.create(
            product_definition=product, action='shared_document_assignment_removed',
            actor=request.user, metadata=metadata,
        )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser and (obj is None or obj.product_definition.lifecycle_status == obj.product_definition.STATUS_DRAFT))

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_superuser and obj and obj.product_definition.lifecycle_status == obj.product_definition.STATUS_DRAFT)


@admin.register(OriginationProductDefinition)
class OriginationProductDefinitionAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    full_reset_confirmation = 'RESET ALL ORIGINATION DATA'
    form = OriginationProductDefinitionForm
    change_form_template = 'admin/core/originationproductdefinition/change_form.html'
    change_list_template = 'admin/core/originationproductdefinition/change_list.html'
    list_display = (
        'product_key', 'name', 'version_state', 'template_readiness',
        'version_history_link', 'updated_at',
    )
    list_filter = ('lifecycle_status', 'is_active', 'document_type')
    search_fields = ('product_key', 'name', 'document_type')
    actions = ('create_new_version',)
    readonly_fields = (
        'version', 'document_type', 'document_template_name', 'document_template_version',
        'document_template_sha256', 'lifecycle_status', 'is_active', 'supersedes',
        'created_by', 'published_by', 'published_at', 'created_at', 'updated_at',
    )


    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'canonical-field/create/',
                self.admin_site.admin_view(self.create_canonical_field_view),
                name='core_originationproductdefinition_create_canonical_field',
            ),
            path(
                'full-reset/',
                self.admin_site.admin_view(self.full_reset_view),
                name='core_origination_full_reset',
            ),
            path(
                '<path:object_id>/document-packet/add-shared/',
                self.admin_site.admin_view(self.add_shared_document_to_packet_view),
                name='core_originationproductdefinition_packet_add_shared',
            ),
            path(
                '<path:object_id>/document-packet/<path:assignment_id>/remove/',
                self.admin_site.admin_view(self.remove_shared_document_from_packet_view),
                name='core_originationproductdefinition_packet_remove_shared',
            ),
            path(
                '<path:object_id>/supporting-document/',
                self.admin_site.admin_view(self.supporting_document_setup_view),
                name='core_originationproductdefinition_supporting_document_setup',
            ),
            path(
                '<path:object_id>/create-next-version/',
                self.admin_site.admin_view(self.create_next_version_view),
                name='core_originationproductdefinition_create_next_version',
            ),
            path(
                '<path:object_id>/version-history/',
                self.admin_site.admin_view(self.version_history_view),
                name='core_originationproductdefinition_version_history',
            ),
        ]
        return custom + urls

    def create_canonical_field_view(self, request):
        """Create one governed input field without leaving an unsaved builder."""
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        if request.method != 'POST':
            response = JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
            response['Allow'] = 'POST'
            return response
        from core.services.origination_fields import (
            OriginationFieldError,
            create_data_field,
            serialize_data_field,
        )
        try:
            body = json.loads(request.body or b'{}')
            if not isinstance(body, dict):
                raise ValidationError('Request body must be an object.')
            data_field, replayed = create_data_field(payload=body, actor=request.user)
            if not data_field.active:
                raise ValidationError(
                    'That canonical key already exists but is inactive. Reactivate it in Origination data fields.',
                )
            if data_field.source_type != OriginationDataField.SOURCE_USER_INPUT:
                raise ValidationError(
                    'That canonical key belongs to a system-derived field and cannot be added as officer input.',
                )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'ok': False, 'error': 'Request body must be valid JSON.'}, status=400)
        except OriginationFieldError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        except ValidationError as exc:
            return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)
        return JsonResponse({
            'ok': True,
            'replayed': replayed,
            'field': serialize_data_field(data_field),
        })

    def full_reset_view(self, request):
        if (
            not getattr(settings, 'ORIGINATION_FULL_RESET_ENABLED', False)
            or not request.user.is_active
            or not request.user.is_superuser
        ):
            raise PermissionDenied

        from core.services.origination_god_mode import (
            OriginationGodModeError,
            preview_full_origination_reset,
            reset_all_origination_data,
        )

        error = ''
        reason = str(request.POST.get('reason') or '').strip()
        confirmation = str(request.POST.get('confirmation') or '').strip()
        request_id = re.sub(
            r'[^A-Za-z0-9._-]', '',
            str(request.POST.get('request_id') or uuid.uuid4()),
        )[:128] or str(uuid.uuid4())
        if request.method == 'POST':
            if confirmation != self.full_reset_confirmation:
                error = f'Type the exact confirmation phrase: {self.full_reset_confirmation}'
            elif not reason:
                error = 'Provide a reason for this permanent reset.'
            elif len(reason) > 500:
                error = 'The reset reason must be 500 characters or fewer.'
            else:
                try:
                    result = reset_all_origination_data(
                        actor=request.user,
                        reason=reason,
                    )
                except OriginationGodModeError as exc:
                    error = str(exc)
                except Exception:
                    logger.exception(
                        'Origination full reset failed: actor_id=%s request_id=%s',
                        request.user.pk,
                        request_id,
                    )
                    error = 'The Origination reset failed. No database changes were committed.'
                else:
                    deleted_total = result['before']['total']
                    logger.warning(
                        'Origination full reset completed: actor_id=%s request_id=%s '
                        'reason=%r before_counts=%s deleted=%s after_counts=%s '
                        'drive_files_untouched=true',
                        request.user.pk,
                        request_id,
                        reason,
                        result['before']['counts'],
                        result['deleted'],
                        result['after']['counts'],
                    )
                    self.message_user(
                        request,
                        f'Origination reset complete. Deleted {deleted_total} database '
                        'record(s); Google Drive files and other workflows were untouched.',
                        level=messages.WARNING,
                    )
                    return HttpResponseRedirect(reverse('admin:core_origination_full_reset'))
        elif request.method != 'GET':
            response = HttpResponse(status=405)
            response['Allow'] = 'GET, POST'
            return response

        preview = preview_full_origination_reset()
        return TemplateResponse(
            request,
            'admin/core/origination_god_mode/full_reset.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': 'Reset all Origination data',
                'preview': preview,
                'confirmation_phrase': self.full_reset_confirmation,
                'confirmation': confirmation,
                'reason': reason,
                'request_id': request_id,
                'error': error,
                'back_url': reverse('admin:core_originationproductdefinition_changelist'),
            },
        )

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            'created_by', 'published_by', 'supersedes',
        )
        resolver = getattr(request, 'resolver_match', None)
        if not resolver or resolver.url_name != 'core_originationproductdefinition_changelist':
            return queryset
        latest_version = (
            OriginationProductDefinition.objects.filter(
                product_key=models.OuterRef('product_key'),
            )
            .order_by('-version')
            .values('version')[:1]
        )
        live_version = (
            OriginationProductDefinition.objects.filter(
                product_key=models.OuterRef('product_key'), is_active=True,
            )
            .values('version')[:1]
        )
        return queryset.annotate(
            _latest_version=models.Subquery(latest_version),
            _live_version=models.Subquery(live_version),
        ).filter(version=models.F('_latest_version'))

    @admin.display(description='Version state', ordering='version')
    def version_state(self, obj):
        live_version = getattr(obj, '_live_version', None)
        if obj.lifecycle_status == obj.STATUS_DRAFT:
            return (
                f'Draft v{obj.version} · Live v{live_version}'
                if live_version else f'Draft v{obj.version} · Not published'
            )
        if obj.is_active:
            return f'Published v{obj.version}'
        return f'{obj.get_lifecycle_status_display()} v{obj.version}'

    @admin.display(description='Versions')
    def version_history_link(self, obj):
        return format_html(
            '<a href="{}">Version history</a>',
            reverse(
                'admin:core_originationproductdefinition_version_history',
                args=[obj.pk],
            ),
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            # These values are all derived when the first form version is
            # saved. Blank readonly rows make the builder look broken and,
            # on a vertical Unfold row, previously amplified label spacing.
            return ()
        return super().get_readonly_fields(request, obj)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        from core.services.loan_origination import SIGNER_ROLE_CATALOG
        from core.services.origination_fields import catalogue_for_product
        product = self.get_object(request, object_id) if object_id else None
        template = None
        failed_template = None
        existing_successor = None
        shared_assignments = []
        packet_readiness = []
        if product is not None:
            templates = product.document_templates.order_by('-created_at')
            template = templates.filter(status__in=[
                OriginationDocumentTemplate.STATUS_READY,
                OriginationDocumentTemplate.STATUS_ACTIVE,
            ], document_role=OriginationDocumentTemplate.ROLE_PRIMARY).first()
            failed_template = templates.filter(
                status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
            ).first()
            if product.lifecycle_status != product.STATUS_DRAFT:
                existing_successor = OriginationProductDefinition.objects.filter(
                    product_key=product.product_key,
                    lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
                ).order_by('-version').first()
            from core.services.origination_templates import resolve_assignment_template
            shared_assignments = [
                {'assignment': assignment, 'resolved_template': resolve_assignment_template(assignment)}
                for assignment in product.document_assignments.select_related(
                    'template', 'template__published_configuration_revision',
                ).order_by('display_order', 'document_key')
            ]
            packet_readiness.append({
                'label': 'Main LAF',
                'ready': bool(template and template.drive_file_id),
                'detail': 'Ready to align' if template and template.drive_file_id else 'Upload the primary LAF PDF',
            })
            packet_readiness.extend({
                'label': item['assignment'].name,
                'ready': bool(item['resolved_template']),
                'detail': (
                    f"Uses shared template v{item['resolved_template'].version}"
                    if item['resolved_template'] else 'No compatible published version is available'
                ),
            } for item in shared_assignments)
        context = {
            **(extra_context or {}),
            'origination_signer_roles': [
                {'key': key, 'label': label} for key, label in SIGNER_ROLE_CATALOG
            ],
            'origination_data_fields': catalogue_for_product(product),
            'origination_data_field_add_url': reverse(
                'admin:core_originationdatafield_add',
            ),
            'origination_data_field_create_url': reverse(
                'admin:core_originationproductdefinition_create_canonical_field',
            ),
            'origination_document_template': template,
            'origination_document_packet': list(
                templates.filter(status__in=[
                    OriginationDocumentTemplate.STATUS_READY,
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                ]).order_by('display_order', 'document_key')
            ) if product else [],
            'origination_shared_document_assignments': shared_assignments,
            'origination_available_shared_documents': list(
                OriginationDocumentTemplate.objects.filter(
                    product_definition__isnull=True,
                    document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
                    status=OriginationDocumentTemplate.STATUS_ACTIVE,
                    published_configuration_revision__isnull=False,
                ).exclude(
                    pk__in=[item['assignment'].template_id for item in shared_assignments],
                ).order_by('name', '-version')
            ) if product and product.lifecycle_status == product.STATUS_DRAFT else [],
            'origination_packet_readiness': packet_readiness,
            'origination_failed_template': failed_template,
            'origination_existing_successor': existing_successor,
            'origination_version_history_url': (
                reverse(
                    'admin:core_originationproductdefinition_version_history',
                    args=[product.pk],
                ) if product else ''
            ),
            'origination_create_next_version_url': (
                reverse(
                    'admin:core_originationproductdefinition_create_next_version',
                    args=[product.pk],
                ) if product and product.lifecycle_status == product.STATUS_PUBLISHED else ''
            ),
            'origination_calibration_url': (
                reverse(
                    'admin:core_originationdocumenttemplate_calibrate',
                    args=[template.pk],
                )
                if template and template.drive_file_id else ''
            ),
            'origination_template_change_url': (
                reverse(
                    'admin:core_originationdocumenttemplate_change',
                    args=[template.pk],
                )
                if template else ''
            ),
            'origination_document_add_url': (
                reverse('admin:core_originationdocumenttemplate_add')
                + f'?product_definition={product.pk}' if product else ''
            ),
            'origination_supporting_document_setup_url': (
                reverse(
                    'admin:core_originationproductdefinition_supporting_document_setup',
                    args=[product.pk],
                ) if product and product.lifecycle_status == product.STATUS_DRAFT else ''
            ),
            'origination_packet_add_shared_url': (
                reverse(
                    'admin:core_originationproductdefinition_packet_add_shared',
                    args=[product.pk],
                ) if product and product.lifecycle_status == product.STATUS_DRAFT else ''
            ),
            'origination_assignment_add_url': (
                reverse('admin:core_originationproductdocumentassignment_add')
                + f'?product_definition={product.pk}' if product and product.lifecycle_status == product.STATUS_DRAFT else ''
            ),
            'origination_shared_library_url': reverse('admin:core_originationdocumenttemplate_changelist') + '?product_definition__isnull=True',
        }
        return super().changeform_view(request, object_id, form_url, context)

    def _draft_packet_product(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        product = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not product:
            return None
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise ValidationError('Create an editable product version before changing its document packet.')
        return product

    @staticmethod
    def _packet_error_response(exc):
        from core.services.origination_templates import OriginationTemplateError
        if isinstance(exc, (OriginationTemplateError, ValidationError)):
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        logger.exception('Origination document-packet request failed.')
        return JsonResponse({'ok': False, 'error': 'The document-packet request could not be completed.'}, status=500)

    def add_shared_document_to_packet_view(self, request, object_id):
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            product = self._draft_packet_product(request, object_id)
            if not product:
                return JsonResponse({'ok': False, 'error': 'Product definition not found.'}, status=404)
            template = OriginationDocumentTemplate.objects.filter(
                pk=request.POST.get('template_id'), product_definition__isnull=True,
                document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
                status=OriginationDocumentTemplate.STATUS_ACTIVE,
                published_configuration_revision__isnull=False,
            ).first()
            if not template:
                raise ValidationError('Choose a published reusable supporting document.')
            next_order = (
                product.document_assignments.aggregate(models.Max('display_order'))['display_order__max']
                or 0
            ) + 10
            from core.services.origination_templates import attach_shared_supporting_template
            assignment = attach_shared_supporting_template(
                product_definition=product, template=template,
                inclusion_mode=template.inclusion_mode, display_order=next_order,
                officer_selectable=template.officer_selectable,
                default_selected=template.default_selected,
                applicability_rule=template.applicability_rule or {}, actor=request.user,
            )
        except PermissionDenied:
            raise
        except Exception as exc:
            return self._packet_error_response(exc)
        return JsonResponse({'ok': True, 'assignment_id': str(assignment.pk), 'name': assignment.name})

    def remove_shared_document_from_packet_view(self, request, object_id, assignment_id):
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            product = self._draft_packet_product(request, object_id)
            if not product:
                return JsonResponse({'ok': False, 'error': 'Product definition not found.'}, status=404)
            from core.services.origination_templates import remove_shared_supporting_template
            removed = remove_shared_supporting_template(
                product_definition=product, assignment_id=assignment_id, actor=request.user,
            )
        except PermissionDenied:
            raise
        except Exception as exc:
            return self._packet_error_response(exc)
        return JsonResponse({'ok': True, 'removed': removed})

    def supporting_document_setup_view(self, request, object_id):
        """Single product-first entry point for shared packet documents."""
        if not request.user.is_superuser:
            raise PermissionDenied
        product = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not product:
            return HttpResponse(status=404)
        product_url = reverse('admin:core_originationproductdefinition_change', args=[product.pk])
        if product.lifecycle_status != product.STATUS_DRAFT:
            self.message_user(
                request, 'Published product versions are immutable. Create an editable next version first.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(product_url)
        form = ProductSupportingDocumentSetupForm(
            request.POST or None, request.FILES or None, product=product,
        )
        if request.method == 'POST' and form.is_valid():
            from core.services.origination_templates import (
                OriginationTemplateError, attach_shared_supporting_template,
                create_shared_supporting_template,
            )
            options = {
                'inclusion_mode': form.cleaned_data['inclusion_mode'],
                'display_order': form.cleaned_data['display_order'],
                'officer_selectable': form.cleaned_data['officer_selectable'],
                'default_selected': form.cleaned_data['default_selected'],
                'applicability_rule': form.cleaned_data['applicability_rule'],
            }
            try:
                if form.cleaned_data['mode'] == form.MODE_EXISTING:
                    assignment = attach_shared_supporting_template(
                        product_definition=product, template=form.cleaned_data['template'],
                        actor=request.user, **options,
                    )
                    self.message_user(
                        request,
                        f'{assignment.name} is now in this product document packet. '
                        'New applications will resolve the latest compatible published version.',
                        level=messages.SUCCESS,
                    )
                    return HttpResponseRedirect(product_url)
                template = create_shared_supporting_template(
                    pdf_file=form.cleaned_data['pdf_file'], name=form.cleaned_data['name'],
                    document_key=form.cleaned_data['document_key'],
                    form_schema=form.cleaned_data['form_schema'] or {},
                    signer_rules=form.cleaned_data['signer_rules'] or [], actor=request.user,
                )
            except OriginationTemplateError as exc:
                form.add_error(None, str(exc))
            else:
                if template.status == template.STATUS_UPLOAD_FAILED or not template.drive_file_id:
                    form.add_error(
                        'pdf_file',
                        template.upload_error or 'The PDF could not be stored. No document was attached.',
                    )
                else:
                    pending = request.session.get('origination_supporting_document_attachments', {})
                    pending[str(template.pk)] = {
                        'product_id': str(product.pk), **options,
                    }
                    request.session['origination_supporting_document_attachments'] = pending
                    request.session.modified = True
                    self.message_user(
                        request,
                        'PDF uploaded. Draw its fields, then use Publish & attach to finish the packet.',
                        level=messages.SUCCESS,
                    )
                    return HttpResponseRedirect(reverse(
                        'admin:core_originationdocumenttemplate_calibrate', args=[template.pk],
                    ))
        from core.services.loan_origination import SIGNER_ROLE_CATALOG
        from core.services.origination_fields import catalogue_for_product
        return TemplateResponse(request, 'admin/core/originationproductdefinition/supporting_document_setup.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Add supporting document: {product}',
            'product': product,
            'product_url': product_url,
            'form': form,
            'origination_signer_roles': [
                {'key': key, 'label': label} for key, label in SIGNER_ROLE_CATALOG
            ],
            'origination_data_fields': catalogue_for_product(product),
            'origination_data_field_add_url': reverse('admin:core_originationdatafield_add'),
            'origination_data_field_create_url': reverse(
                'admin:core_originationproductdefinition_create_canonical_field',
            ),
        })

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None and obj.lifecycle_status != obj.STATUS_DRAFT:
            kwargs['form'] = forms.modelform_factory(OriginationProductDefinition, fields=())
        return super().get_form(request, obj, **kwargs)

    @admin.display(description='Template')
    def template_readiness(self, obj):
        template = obj.document_templates.filter(status__in=[
            OriginationDocumentTemplate.STATUS_READY,
            OriginationDocumentTemplate.STATUS_ACTIVE,
        ], document_role=OriginationDocumentTemplate.ROLE_PRIMARY).order_by('-created_at').first()
        if not template:
            failed = obj.document_templates.filter(
                status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
            ).exists()
            if failed:
                return 'Upload failed'
            return 'PDF required'
        if obj.is_active and template.status == template.STATUS_ACTIVE:
            return 'Published'
        if template.published_configuration_revision_id:
            return 'Ready to publish'
        if template.events.filter(action='version_inherited').exists():
            return 'Alignment copied'
        return 'Calibration required'

    def save_model(self, request, obj, form, change):
        if change and obj.lifecycle_status != obj.STATUS_DRAFT:
            raise PermissionDenied
        if not change:
            if obj.product_version_id:
                obj.product_key = obj.product_version.product.code
                obj.name = obj.product_version.product.name
            if OriginationProductDefinition.objects.filter(product_key=obj.product_key).exists():
                raise ValidationError('This product key already exists. Create a new version from its existing record.')
            obj.version = 1
            obj.document_type = obj.product_key
            obj.document_template_version = obj.version
            obj.lifecycle_status = obj.STATUS_DRAFT
            obj.is_active = False
        if not obj.created_by_id:
            obj.created_by = request.user
        from core.services.loan_origination import validate_product_form_contract
        validate_product_form_contract(obj.form_schema, obj.signer_rules)
        super().save_model(request, obj, form, change)
        from core.services.origination_fields import bind_compatible_schema_fields
        bind_compatible_schema_fields(obj, create_issues=True)
        OriginationProductDefinitionEvent.objects.create(
            product_definition=obj, action='draft_updated' if change else 'created',
            actor=request.user, metadata={'version': obj.version},
        )
        laf_pdf = form.cleaned_data.get('laf_pdf')
        if laf_pdf:
            from core.services.origination_templates import (
                create_template, replace_draft_template,
            )
            current_template = obj.document_templates.filter(status__in=[
                OriginationDocumentTemplate.STATUS_READY,
                OriginationDocumentTemplate.STATUS_ACTIVE,
            ], document_role=OriginationDocumentTemplate.ROLE_PRIMARY).order_by('-created_at').first()
            creator = replace_draft_template if current_template else create_template
            template = creator(
                pdf_file=laf_pdf, product_definition=obj,
                name=f'{obj.name} LAF v{obj.version}', actor=request.user,
            )
            obj._uploaded_laf_template_id = template.pk
            if template.status == OriginationDocumentTemplate.STATUS_UPLOAD_FAILED:
                messages.error(request, template.upload_error)
            else:
                messages.success(
                    request,
                    'Replacement LAF uploaded; the previous PDF remains in version history.'
                    if current_template else
                    'LAF uploaded. Assign each form variable and signer slot on the PDF.',
                )

    def _uploaded_laf_response(self, obj):
        template_id = getattr(obj, '_uploaded_laf_template_id', None)
        if not template_id:
            return None
        template = OriginationDocumentTemplate.objects.get(pk=template_id)
        if template.drive_file_id and template.status != template.STATUS_UPLOAD_FAILED:
            return HttpResponseRedirect(reverse(
                'admin:core_originationdocumenttemplate_calibrate', args=[template.pk],
            ))
        return HttpResponseRedirect(reverse(
            'admin:core_originationproductdefinition_change', args=[obj.pk],
        ))

    def response_add(self, request, obj, post_url_continue=None):
        return self._uploaded_laf_response(obj) or super().response_add(
            request, obj, post_url_continue,
        )

    def response_change(self, request, obj):
        return self._uploaded_laf_response(obj) or super().response_change(request, obj)

    @admin.action(description='Create editable next version')
    def create_new_version(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one product.', level=messages.ERROR)
            return None
        from core.services.origination_templates import clone_product_version
        clone = clone_product_version(queryset.first(), actor=request.user)
        self.message_user(request, f'Product version {clone.version} is ready to edit.', level=messages.SUCCESS)
        return self._successor_response(clone)

    def _successor_response(self, successor):
        template = successor.document_templates.filter(
            status=OriginationDocumentTemplate.STATUS_READY,
            drive_file_id__gt='',
        ).order_by('-created_at').first()
        if template:
            return HttpResponseRedirect(reverse(
                'admin:core_originationdocumenttemplate_calibrate', args=[template.pk],
            ))
        return HttpResponseRedirect(reverse(
            'admin:core_originationproductdefinition_change', args=[successor.pk],
        ))

    def create_next_version_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.method != 'POST':
            response = HttpResponse(status=405)
            response['Allow'] = 'POST'
            return response
        source = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not source:
            return HttpResponse(status=404)
        if source.lifecycle_status != source.STATUS_PUBLISHED:
            self.message_user(
                request, 'Only a published product can create a successor.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse(
                'admin:core_originationproductdefinition_change', args=[source.pk],
            ))
        from core.services.origination_templates import clone_product_version
        successor = clone_product_version(source, actor=request.user)
        self.message_user(
            request,
            f'Editable version {successor.version} is ready with the existing PDF and alignment.',
            level=messages.SUCCESS,
        )
        return self._successor_response(successor)

    def version_history_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        selected = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not selected:
            return HttpResponse(status=404)
        versions = list(
            OriginationProductDefinition.objects.filter(
                product_key=selected.product_key,
            ).select_related(
                'created_by', 'published_by', 'supersedes',
            ).prefetch_related('document_templates').order_by('-version')
        )
        rows = []
        for version in versions:
            templates = sorted(
                version.document_templates.all(),
                key=lambda candidate: candidate.created_at,
                reverse=True,
            )
            template = next((
                item for item in templates
                if item.status in [
                    OriginationDocumentTemplate.STATUS_READY,
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                ]
            ), None)
            rows.append({
                'version': version,
                'template': template,
                'templates': [{
                    'template': item,
                    'change_url': reverse(
                        'admin:core_originationdocumenttemplate_change',
                        args=[item.pk],
                    ),
                } for item in templates],
                'change_url': reverse(
                    'admin:core_originationproductdefinition_change', args=[version.pk],
                ),
                'calibration_url': (
                    reverse(
                        'admin:core_originationdocumenttemplate_calibrate',
                        args=[template.pk],
                    )
                    if template and version.lifecycle_status == version.STATUS_DRAFT
                    else ''
                ),
            })
        return TemplateResponse(
            request,
            'admin/core/originationproductdefinition/version_history.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': f'{selected.name} version history',
                'selected': selected,
                'rows': rows,
                'changelist_url': reverse(
                    'admin:core_originationproductdefinition_changelist',
                ),
            },
        )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OriginationDocumentTemplate)
class OriginationDocumentTemplateAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    form = OriginationDocumentTemplateForm
    change_form_template = 'admin/core/originationdocumenttemplate/change_form.html'
    change_list_template = 'admin/core/originationdocumenttemplate/change_list.html'
    list_display = ('name', 'product_definition', 'document_role', 'inclusion_mode', 'display_order', 'status', 'calibrate_link', 'page_count', 'updated_at')
    list_filter = ('status', 'document_role', 'inclusion_mode', 'document_type', 'product_definition')
    search_fields = ('name', 'document_type', 'source_filename', 'source_sha256')
    actions = ('activate_selected_templates',)
    readonly_fields = (
        'product_definition', 'document_key', 'name', 'document_role', 'inclusion_mode',
        'display_order', 'officer_selectable', 'default_selected', 'applicability_summary',
        'configuration_summary', 'document_type', 'version', 'status', 'source_filename', 'source_sha256',
        'source_byte_size', 'page_count', 'calibration_link', 'drive_link',
        'published_configuration_revision', 'upload_error', 'created_by', 'activated_by',
        'activated_at', 'created_at', 'updated_at',
    )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            # Values below are derived only after the PDF has been validated
            # and uploaded. Rendering all of them as blank readonly rows made
            # the add screen both misleading and unnecessarily tall.
            return ()
        return super().get_readonly_fields(request, obj)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return ((
                'Upload PDF template',
                {
                    'description': (
                        'Select the draft loan form that defines the fields for this PDF. '
                        'After upload, the visual calibration screen opens automatically.'
                    ),
                    'fields': (
                        'product_definition', ('document_key', 'name'),
                        ('document_role', 'inclusion_mode', 'display_order'),
                        ('officer_selectable', 'default_selected'),
                        ('condition_field', 'condition_operator'), 'condition_value',
                        'applicability_rule', 'form_schema', 'signer_rules', 'pdf_file',
                    ),
                },
            ),)
        return (
            ('Template', {
                'fields': (
                    'product_definition', ('document_key', 'name'),
                    ('document_role', 'inclusion_mode', 'display_order'),
                    ('officer_selectable', 'default_selected'),
                    'applicability_summary', 'configuration_summary',
                    ('document_type', 'version', 'status'),
                    'calibration_link',
                ),
            }),
            ('Source PDF', {
                'fields': (
                    'source_filename', ('source_byte_size', 'page_count'),
                    'source_sha256', 'drive_link', 'upload_error',
                ),
            }),
            ('Published calibration', {
                'description': 'Field positions, formatting, and signer slots are managed in the visual calibration builder.',
                'fields': ('published_configuration_revision',),
                'classes': ('collapse',),
            }),
            ('Audit', {
                'fields': (
                    ('created_by', 'created_at'),
                    ('activated_by', 'activated_at'), 'updated_at',
                ),
                'classes': ('collapse',),
            }),
        )

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = {**(extra_context or {})}
        from core.services.loan_origination import SIGNER_ROLE_CATALOG
        from core.services.origination_fields import catalogue_for_product
        selected_product_id = request.POST.get('product_definition') or request.GET.get('product_definition')
        selected_product = OriginationProductDefinition.objects.filter(
            pk=selected_product_id,
        ).first() if selected_product_id else None
        context.update({
            'origination_signer_roles': [
                {'key': key, 'label': label} for key, label in SIGNER_ROLE_CATALOG
            ],
            'origination_data_fields': catalogue_for_product(selected_product),
            'origination_data_field_add_url': reverse('admin:core_originationdatafield_add'),
            'origination_condition_fields_by_product': {
                str(item.pk): _product_condition_fields(item)
                for item in OriginationProductDefinition.objects.filter(
                    lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
                )
            },
        })
        if object_id is None:
            eligible_definitions = OriginationDocumentTemplateForm.eligible_product_definitions()
            context.update({
                'has_eligible_product_definitions': eligible_definitions.exists(),
                'create_product_definition_url': reverse(
                    'admin:core_originationproductdefinition_add',
                ),
                'manage_product_definitions_url': reverse(
                    'admin:core_originationproductdefinition_changelist',
                ),
            })
        else:
            original = self.get_object(request, object_id)
            if (
                original
                and original.product_definition_id is None
                and original.document_role == original.ROLE_SUPPORTING
            ):
                context['origination_next_family_version_url'] = (
                    reverse('admin:core_originationdocumenttemplate_add') + '?' + urlencode({
                        'document_key': original.document_key,
                        'document_role': original.document_role,
                        'inclusion_mode': original.inclusion_mode,
                        'display_order': original.display_order,
                        'officer_selectable': int(original.officer_selectable),
                        'default_selected': int(original.default_selected),
                        'name': original.name,
                    })
                )
        return super().changeform_view(request, object_id, form_url, context)

    @admin.display(description='Inclusion condition')
    def applicability_summary(self, obj):
        rule = _simple_document_condition(obj.applicability_rule)
        if not rule:
            return 'Always included' if not obj.applicability_rule else 'Legacy multi-part condition retained'
        operator = dict(DOCUMENT_CONDITION_OPERATORS).get(rule['operator'], rule['operator'])
        value = '' if rule['operator'] in {'truthy', 'falsy'} else f' {rule.get("value", "")}'
        return f"{rule['field'].replace('_', ' ').title()} {operator}{value}"

    @admin.display(description='Configured fields and signers')
    def configuration_summary(self, obj):
        schema = obj.form_schema if isinstance(obj.form_schema, dict) else {}
        fields = schema.get('fields') if isinstance(schema.get('fields'), list) else []
        sections = schema.get('sections') if isinstance(schema.get('sections'), list) else []
        signers = obj.signer_rules if isinstance(obj.signer_rules, list) else []
        return f'{len(fields)} field(s) in {len(sections)} section(s); {len(signers)} signer role(s).'

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None:
            kwargs['form'] = forms.modelform_factory(
                OriginationDocumentTemplate, fields=(),
            )
        return super().get_form(request, obj, **kwargs)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('<path:object_id>/calibrate/', self.admin_site.admin_view(self.calibrate_view), name='core_originationdocumenttemplate_calibrate'),
            path('<path:object_id>/calibration-state/', self.admin_site.admin_view(self.calibration_state_view), name='core_originationdocumenttemplate_calibration_state'),
            path('<path:object_id>/calibration-page/', self.admin_site.admin_view(self.calibration_page_view), name='core_originationdocumenttemplate_calibration_page'),
            path('<path:object_id>/calibration-preview/', self.admin_site.admin_view(self.calibration_preview_view), name='core_originationdocumenttemplate_calibration_preview'),
            path('<path:object_id>/calibration-save/', self.admin_site.admin_view(self.calibration_save_view), name='core_originationdocumenttemplate_calibration_save'),
            path('<path:object_id>/calibration-field/', self.admin_site.admin_view(self.calibration_field_view), name='core_originationdocumenttemplate_calibration_field'),
            path('<path:object_id>/calibration-publish/', self.admin_site.admin_view(self.calibration_publish_view), name='core_originationdocumenttemplate_calibration_publish'),
        ]
        return custom + urls

    def _calibration_template(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        obj = self.get_object(request, object_id)
        if not obj:
            raise PermissionDenied
        return obj

    @admin.display(description='Alignment')
    def calibrate_link(self, obj):
        if not obj.drive_file_id:
            return 'Unavailable'
        url = reverse('admin:core_originationdocumenttemplate_calibrate', args=[obj.pk])
        return format_html('<a href="{}">Calibrate fields</a>', url)

    @admin.display(description='Visual alignment editor')
    def calibration_link(self, obj):
        if not obj or not obj.pk or not obj.drive_file_id:
            return 'Available after the PDF is uploaded to Drive.'
        url = reverse('admin:core_originationdocumenttemplate_calibrate', args=[obj.pk])
        return format_html(
            '<a class="button" style="display:inline-flex;background:#2563eb;color:#fff;'
            'padding:8px 14px;border-radius:7px;font-weight:700" href="{}">'
            'Open visual calibration</a>', url,
        )

    @staticmethod
    def _pending_supporting_attachment(request, template):
        """Read the short-lived product-wizard hand-off for this template only."""
        raw = (request.session.get('origination_supporting_document_attachments') or {}).get(str(template.pk))
        if not isinstance(raw, dict):
            return None
        product_id = raw.get('product_id')
        product = OriginationProductDefinition.objects.filter(
            pk=product_id, lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
        ).first()
        if not product or template.product_definition_id or template.document_role != template.ROLE_SUPPORTING:
            return None
        return {'product': product, 'options': {
            'inclusion_mode': raw.get('inclusion_mode', OriginationDocumentTemplate.INCLUDE_REQUIRED),
            'display_order': raw.get('display_order', 10),
            'officer_selectable': bool(raw.get('officer_selectable')),
            'default_selected': bool(raw.get('default_selected')),
            'applicability_rule': raw.get('applicability_rule') or {},
        }}

    @staticmethod
    def _clear_pending_supporting_attachment(request, template):
        pending = dict(request.session.get('origination_supporting_document_attachments') or {})
        if str(template.pk) in pending:
            pending.pop(str(template.pk), None)
            request.session['origination_supporting_document_attachments'] = pending
            request.session.modified = True

    def calibrate_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        pending_attachment = self._pending_supporting_attachment(request, obj)
        product = pending_attachment['product'] if pending_attachment else None
        return TemplateResponse(request, 'admin/core/originationdocumenttemplate/calibrate.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Calibrate fields: {obj}', 'template_record': obj,
            'calibration_attach_product': product,
            'calibration_back_url': reverse(
                'admin:core_originationproductdefinition_change', args=[product.pk],
            ) if product else reverse('admin:core_originationdocumenttemplate_changelist'),
        })

    def calibration_state_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        latest = obj.configuration_revisions.order_by('-revision').first()
        config = latest.configuration if latest else obj.placement_config
        from pypdf import PdfReader
        from io import BytesIO
        from core.services.origination_templates import load_template_source
        reader = PdfReader(BytesIO(load_template_source(obj)))
        page_sizes = [{'page_number': i + 1, 'width': float(page.mediabox.width), 'height': float(page.mediabox.height)} for i, page in enumerate(reader.pages)]
        product = obj.product_definition or OriginationProductDefinition.objects.filter(
            document_type=obj.document_type, is_active=True,
        ).order_by('-version').first()
        from core.services.origination_fields import (
            catalogue_for_product, product_schema_revision, template_schema_revision,
        )
        fields = (
            obj.form_schema
            if obj.document_role == obj.ROLE_SUPPORTING and obj.form_schema
            else product.form_schema if product else {}
        )
        presentations = {
            str(item.get('key') or ''): item
            for item in (fields.get('fields') or [])
            if isinstance(item, dict) and item.get('key')
        }
        context_keys = catalogue_for_product(product)
        for item in context_keys:
            presentation = presentations.get(str(item.get('key') or ''), {})
            if obj.document_role == obj.ROLE_SUPPORTING:
                item['attached'] = bool(presentation)
            item['required'] = bool(presentation.get('required', False))
            item['section_key'] = str(presentation.get('section_key') or '')
        from core.services.origination_templates import _expected_signature_slots
        return JsonResponse({
            'ok': True,
            'revision': latest.revision if latest else 0,
            'published': bool(latest and latest.is_published),
            'product_published': bool(product and product.is_active),
            'configuration': config,
            'page_sizes': page_sizes,
            'context_keys': context_keys,
            'schema_revision': template_schema_revision(obj) if obj.document_role == obj.ROLE_SUPPORTING else product_schema_revision(product) if product else 0,
            'form_sections': list(fields.get('sections') or []),
            'signature_slots': list(_expected_signature_slots(product, obj).values()),
        })

    def calibration_page_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        from core.services.origination_templates import load_template_source
        from core.services.partnership_laf_preview import render_pdf_page
        try:
            content, total = render_pdf_page(load_template_source(obj), page_number=int(request.GET.get('page') or 1), scale=2)
        except Exception as exc:
            return self._calibration_error_response(exc)
        response = HttpResponse(content, content_type='image/jpeg')
        response['X-Preview-Page-Count'] = str(total)
        response['Cache-Control'] = 'private, no-store'
        return response

    def _json_body(self, request):
        try:
            return json.loads(request.body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValidationError('Invalid JSON request.')

    def _calibration_error_response(self, exc):
        from core.services.origination_templates import OriginationTemplateError
        from core.services.origination_fields import OriginationFieldError
        if isinstance(exc, (OriginationTemplateError, OriginationFieldError, ValidationError)):
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        logger.exception('Origination template calibration request failed.')
        return JsonResponse({'ok': False, 'error': 'The calibration request could not be completed.'}, status=500)

    def calibration_preview_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from core.services.origination_templates import load_template_source, validate_template_configuration
            from core.services.partnership_laf_preview import render_pdf_page, render_template
            body = self._json_body(request)
            config = validate_template_configuration(
                body.get('configuration'), template=obj, require_complete=False,
            )
            sample_context = dict(config.get('sample_context') or {})
            sample_context['_show_signature_slots'] = True
            pdf = render_template(load_template_source(obj), config, sample_context)
            content, total = render_pdf_page(pdf, page_number=int(body.get('page') or 1), scale=2)
        except Exception as exc:
            return self._calibration_error_response(exc)
        response = HttpResponse(content, content_type='image/jpeg')
        response['X-Preview-Page-Count'] = str(total)
        response['Cache-Control'] = 'private, no-store'
        return response

    def calibration_save_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from core.services.origination_templates import save_calibration_draft
            body = self._json_body(request)
            request_id = str(body.get('client_request_id') or request.headers.get('Idempotency-Key') or '')
            saved = save_calibration_draft(
                template=obj, configuration=body.get('configuration'), actor=request.user,
                expected_revision=int(body.get('revision')),
                client_request_id=request_id,
            )
        except Exception as exc:
            return self._calibration_error_response(exc)
        return JsonResponse({'ok': True, 'revision': saved.revision})

    def calibration_field_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from core.services.origination_fields import (
                attach_data_field, attach_data_field_to_template, catalogue_for_product,
                create_data_field, product_schema_revision, template_schema_revision,
            )
            body = self._json_body(request)
            with transaction.atomic():
                create_payload = body.get('create_field')
                if create_payload:
                    data_field, _replayed = create_data_field(
                        payload=create_payload, actor=request.user,
                    )
                else:
                    data_field = OriginationDataField.objects.filter(
                        pk=body.get('data_field_id'), active=True,
                    ).first()
                    if not data_field:
                        raise ValidationError('Choose an active canonical data field.')
                if obj.document_role == obj.ROLE_SUPPORTING:
                    obj, replayed = attach_data_field_to_template(
                        template=obj, data_field=data_field,
                        presentation=body.get('presentation') or {}, actor=request.user,
                        expected_schema_revision=int(body.get('schema_revision') or 0),
                    )
                    product = obj.product_definition
                elif obj.product_definition_id:
                    product, replayed = attach_data_field(
                        product=obj.product_definition, data_field=data_field,
                        presentation=body.get('presentation') or {}, actor=request.user,
                        expected_schema_revision=int(body.get('schema_revision') or 0),
                    )
                else:
                    raise ValidationError('A primary template must be linked to an editable product form.')
        except Exception as exc:
            return self._calibration_error_response(exc)
        context_keys = catalogue_for_product(product)
        presentations = {
            str(item.get('key') or ''): item
            for item in (((obj.form_schema if obj.document_role == obj.ROLE_SUPPORTING else product.form_schema) or {}).get('fields') or [])
            if isinstance(item, dict) and item.get('key')
        }
        for item in context_keys:
            presentation = presentations.get(str(item.get('key') or ''), {})
            if obj.document_role == obj.ROLE_SUPPORTING:
                item['attached'] = bool(presentation)
            item['required'] = bool(presentation.get('required', False))
            item['section_key'] = str(presentation.get('section_key') or '')
        return JsonResponse({
            'ok': True, 'field': next(
                item for item in context_keys if item['key'] == data_field.key
            ),
            'context_keys': context_keys,
            'schema_revision': template_schema_revision(obj) if obj.document_role == obj.ROLE_SUPPORTING else product_schema_revision(product),
            'form_sections': list(((obj.form_schema if obj.document_role == obj.ROLE_SUPPORTING else product.form_schema) or {}).get('sections') or []),
            'replayed': replayed,
        })

    def calibration_publish_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from core.services.origination_templates import (
                publish_and_attach_shared_supporting_template, publish_product_template,
            )
            body = self._json_body(request)
            request_id = str(body.get('client_request_id') or request.headers.get('Idempotency-Key') or '')
            pending_attachment = self._pending_supporting_attachment(request, obj)
            assignment = None
            if pending_attachment:
                _template, published, assignment = publish_and_attach_shared_supporting_template(
                    product_definition=pending_attachment['product'], template=obj,
                    revision=int(body.get('revision')), actor=request.user,
                    client_request_id=request_id, assignment_options=pending_attachment['options'],
                )
                product = pending_attachment['product']
                self._clear_pending_supporting_attachment(request, obj)
            else:
                product, _template, published = publish_product_template(
                    template=obj, revision=int(body.get('revision')), actor=request.user,
                    client_request_id=request_id,
                )
        except Exception as exc:
            return self._calibration_error_response(exc)
        return JsonResponse({
            'ok': True,
            'revision': published.revision,
            'product_key': product.product_key if product else '',
            'product_name': product.name if product else '',
            'product_version': product.version if product else None,
            'template_name': obj.name,
            'assignment_name': assignment.name if assignment else '',
        })

    @admin.display(description='Drive file')
    def drive_link(self, obj):
        if not obj or not obj.drive_url:
            return 'Not uploaded'
        return format_html('<a href="{}" target="_blank" rel="noopener">Open approved PDF</a>', obj.drive_url)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            return
        obj.created_by = request.user
        obj.status = OriginationDocumentTemplate.STATUS_READY
        obj.full_clean()
        super().save_model(request, obj, form, change)
        OriginationDocumentTemplateEvent.objects.create(
            template=obj, action='created', actor=request.user,
            metadata={
                'sha256': obj.source_sha256,
                'byte_size': obj.source_byte_size,
                'page_count': obj.page_count,
            },
        )
        from core.services.origination_templates import upload_template_record
        upload_template_record(obj, pdf_data=form._pdf_data, actor=request.user)
        if obj.status == OriginationDocumentTemplate.STATUS_UPLOAD_FAILED:
            messages.error(request, obj.upload_error)
        else:
            messages.success(request, 'Template uploaded to Drive. Calibrate its fields and publish the product.')

    def response_add(self, request, obj, post_url_continue=None):
        if obj.drive_file_id and obj.status != OriginationDocumentTemplate.STATUS_UPLOAD_FAILED:
            return HttpResponseRedirect(reverse('admin:core_originationdocumenttemplate_calibrate', args=[obj.pk]))
        return super().response_add(request, obj, post_url_continue)

    @admin.action(description='Activate selected template')
    def activate_selected_templates(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one template to activate.', level=messages.ERROR)
            return
        selected = queryset.first()
        if selected.product_definition_id:
            self.message_user(
                request,
                'Open Calibrate fields and use Publish product; it validates and activates the product in one action.',
                level=messages.ERROR,
            )
            return
        from core.services.origination_templates import OriginationTemplateError, activate_template
        try:
            template = activate_template(selected, actor=request.user)
        except OriginationTemplateError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, f'{template} is now active.', level=messages.SUCCESS)


@admin.register(LoanOriginationApplication)
class LoanOriginationApplicationAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    list_display = ('reference_number', 'product_definition', 'officer', 'branch', 'status', 'revision', 'updated_at')
    list_filter = ('status', 'branch', 'product_definition')
    search_fields = ('reference_number', 'officer__username')
    readonly_fields = tuple(field.name for field in LoanOriginationApplication._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _AppendOnlyOriginationAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        excluded = set(self.exclude or ())
        return tuple(field.name for field in self.model._meta.fields if field.name not in excluded)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OriginationDataFieldEvent)
class OriginationDataFieldEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('data_field', 'action', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('data_field__key', 'data_field__label')

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(OriginationDocumentTemplateEvent)
class OriginationDocumentTemplateEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('template', 'action', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('template__name', 'template__document_type')


@admin.register(OriginationProductDefinitionEvent)
class OriginationProductDefinitionEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('product_definition', 'action', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('product_definition__product_key', 'product_definition__name')


@admin.register(OriginationTemplateConfigurationRevision)
class OriginationTemplateConfigurationRevisionAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('template', 'revision', 'is_published', 'created_by', 'created_at', 'published_at')
    list_filter = ('is_published', 'template__document_type')
    search_fields = ('template__name', 'template__document_type')


@admin.register(OriginationApplicationEvent)
class OriginationApplicationEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'action', 'revision', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('application__reference_number', 'request_id')


@admin.register(OriginationApplicationDocument)
class OriginationApplicationDocumentAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'application', 'document_key', 'document_role', 'selected',
        'applicable', 'previewed_application_revision', 'updated_at',
    )
    list_filter = ('document_role', 'inclusion_mode', 'selected', 'applicable')
    search_fields = ('application__reference_number', 'document_key', 'name')


@admin.register(OriginationCorrectionRequest)
class OriginationCorrectionRequestAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'application_revision', 'reviewer', 'status', 'created_at', 'addressed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('application__reference_number', 'summary', 'reviewer__username')


@admin.register(OriginationCorrectionItem)
class OriginationCorrectionItemAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('correction_request', 'target_type', 'target_label', 'created_at')
    list_filter = ('target_type',)
    search_fields = ('correction_request__application__reference_number', 'target_key', 'target_label')


@admin.register(OriginationRequirementEvidence)
class OriginationRequirementEvidenceAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'requirement_label', 'original_filename', 'status', 'uploaded_by', 'created_at')
    list_filter = ('status', 'mime_type', 'requirement_key')
    search_fields = ('application__reference_number', 'requirement_label', 'original_filename', 'content_sha256')


@admin.register(OriginationSigningPackage)
class OriginationSigningPackageAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('external_reference', 'application', 'application_revision', 'status', 'archive_status', 'updated_at')
    list_filter = ('status', 'archive_status', 'document_type')
    search_fields = ('external_reference', 'application__reference_number')
    exclude = ('pending_signed_document',)


@admin.register(OriginationSignerSession)
class OriginationSignerSessionAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'package', 'signer_role', 'status', 'access_mode', 'masked_phone',
        'shared_phone_approved_by', 'verified_at', 'created_at',
    )
    list_filter = ('status', 'access_mode', 'signer_role', 'is_active')
    search_fields = ('package__external_reference', 'package__application__reference_number', 'phone_last4')
    exclude = ('token_hash', 'phone_normalized', 'phone_hash', 'signature_capture')

    @admin.display(description='Phone')
    def masked_phone(self, obj):
        return f'+254•••••{obj.phone_last4}' if obj.phone_last4 else '—'


@admin.register(OriginationOtpChallenge)
class OriginationOtpChallengeAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'session', 'send_sequence', 'delivery_status', 'attempts_remaining',
        'expires_at', 'verified_at', 'created_at',
    )
    list_filter = ('delivery_status', 'verified_at', 'created_at')
    search_fields = ('session__package__external_reference', 'provider_message_id')
    exclude = ('code_hash', 'source_ip_hash', 'binding_sha256')


@admin.register(OriginationSigningRequestEvent)
class OriginationSigningRequestEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('session', 'action', 'request_id', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('session__package__external_reference',)
    exclude = ('token_hash', 'source_ip_hash', 'payload_digest')


class OriginationStampAssetAdminForm(forms.ModelForm):
    image_upload = forms.FileField(
        label='Transparent PNG stamp', required=False,
        help_text='PNG only, at most 2 MB. Create a new version to replace an active stamp.',
    )

    class Meta:
        model = OriginationStampAsset
        fields = ('name', 'branch', 'environment', 'active')

    def clean_image_upload(self):
        upload = self.cleaned_data.get('image_upload')
        if not upload:
            if not self.instance.pk:
                raise ValidationError('Choose the approved PNG stamp image.')
            return None
        if self.instance.pk:
            raise ValidationError('Stamp image bytes are immutable. Add a new stamp version instead.')
        if int(getattr(upload, 'size', 0) or 0) > 2 * 1024 * 1024:
            raise ValidationError('The stamp PNG must not exceed 2 MB.')
        data = upload.read()
        upload.seek(0)
        try:
            from io import BytesIO
            from PIL import Image
            image = Image.open(BytesIO(data))
            image.verify()
            if image.format != 'PNG':
                raise ValueError('not png')
            if image.width > 2000 or image.height > 2000:
                raise ValidationError('The stamp image must be no larger than 2000 × 2000 pixels.')
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError('Choose a genuine, readable PNG stamp image.') from exc
        upload._validated_stamp_bytes = data
        return upload


@admin.register(OriginationStampAsset)
class OriginationStampAssetAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    form = OriginationStampAssetAdminForm
    list_display = ('name', 'branch', 'environment', 'version', 'active', 'activated_at')
    list_filter = ('environment', 'active', 'branch')
    search_fields = ('name', 'content_sha256', 'branch__name')
    readonly_fields = (
        'version', 'content_sha256', 'byte_size', 'created_by',
        'activated_by', 'activated_at', 'created_at',
    )

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def save_model(self, request, obj, form, change):
        upload = form.cleaned_data.get('image_upload')
        if not change:
            import hashlib
            data = bytes(upload._validated_stamp_bytes)
            obj.image_png = data
            obj.content_sha256 = hashlib.sha256(data).hexdigest()
            obj.byte_size = len(data)
            obj.created_by = request.user
            obj.version = (
                OriginationStampAsset.objects.filter(
                    name__iexact=obj.name, branch=obj.branch,
                    environment=obj.environment,
                ).aggregate(models.Max('version'))['version__max'] or 0
            ) + 1
        if obj.active:
            OriginationStampAsset.objects.filter(
                name__iexact=obj.name, branch=obj.branch,
                environment=obj.environment, active=True,
            ).exclude(pk=obj.pk).update(active=False)
            obj.activated_by = request.user
            obj.activated_at = timezone.now()
        super().save_model(request, obj, form, change)
        self.message_user(
            request,
            f'{obj} saved. Test stamps remain unusable for production signing.',
            level=messages.SUCCESS,
        )


@admin.register(OriginationSigningAction)
class OriginationSigningActionAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'package', 'document_key', 'slot_key', 'signer_role',
        'action_type', 'mode', 'actor', 'signer_session', 'created_at',
    )
    list_filter = ('mode', 'action_type', 'signer_role')
    search_fields = ('package__external_reference', 'document_key', 'slot_key', 'request_id')
    exclude = ('metadata',)


@admin.register(OriginationReportingValue)
class OriginationReportingValueAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'field_key', 'value_type', 'sensitivity', 'projected_at')
    list_filter = ('value_type', 'sensitivity', 'reporting_use', 'export_allowed')
    search_fields = ('application__reference_number', 'field_key', 'data_field__key')


try:
    admin.site.unregister(get_user_model())
except admin.sites.NotRegistered:
    pass
admin.site.register(get_user_model(), UnfoldUserAdmin)

try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass
admin.site.register(Group, UnfoldGroupAdmin)


from core.admin_utils import auto_register_unregistered_models


AUTO_REGISTERED_MODELS = auto_register_unregistered_models()
