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
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connections, models, transaction
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from django.utils.text import slugify
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
from core.services.tat_responsibilities import (
    assignment_snapshot,
    canonical_stage_role,
    configuration_issues,
    eligible_responsibility_users,
    stage_catalog,
)
from core.services.telegram_launchers import MINI_APP_LAUNCHER_CHOICES, default_launcher_keys
from core.services.access_policies import (
    branch_choices, product_choices, role_choices, role_workflow_map,
    validate_access_scope,
)

from .models import (
    ComplaintCaseEvidence,
    ComplaintCaseControl,
    ComplaintCaseEvent,
    ComplaintCaseImportBatch,
    ComplaintCaseImportItem,
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
    OriginationCommercialException,
    OriginationReportingValue,
    OriginationApplicationEvent,
    OriginationCorrectionItem,
    OriginationCorrectionRequest,
    OriginationRequirementEvidence,
    OriginationApplicationDocument,
    OriginationProductDocumentAssignment,
    OriginationConsentPolicyVersion,
    OriginationSigningPackage,
    OriginationSigningAction,
    OriginationSigningActionInvalidation,
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
    TatResponsibilityAssignment,
    TatResponsibilityBackup,
    TatResponsibilityEvent,
    TatPrivateAlertConnection,
    TatActionTask,
    TatActionTaskRecipient,
    TatActionTaskLocator,
    TatTaskRerouteEvent,
    TatResponsibilityChangePlan,
    TatConfigurationEvent,
    TatGroupExceptionStatus,
    TatNotificationProcessorRun,
    TatRepairJob,
    WorkflowDataModeEvent,
    WorkflowDataModeState,
    WorkflowPilotFormulaReadiness,
    WorkflowPilotPurgeRun,
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
    StaffLifecycleChangePlan,
    TelegramStaffActivation,
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
    MiniAppDiagnosticSession,
    MiniAppDiagnosticEvent,
    MiniAppDiagnosticDailyAggregate,
)

logger = logging.getLogger(__name__)


class WorkflowDataModeStateForm(forms.ModelForm):
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Required whenever SPIN or TAT mode changes. Stored in immutable audit history.',
    )

    class Meta:
        model = WorkflowDataModeState
        fields = ('spin_mode', 'tat_mode')

    def clean(self):
        cleaned = super().clean()
        changed_fields = [
            field for field in ('spin_mode', 'tat_mode')
            if cleaned.get(field) != self.initial.get(field)
        ]
        changed = bool(changed_fields)
        if changed and not str(cleaned.get('reason') or '').strip():
            self.add_error('reason', 'Explain why the workflow mode is changing.')
        if self.instance.pk:
            current = WorkflowDataModeState.objects.filter(pk=self.instance.pk).first()
            if current:
                for field in changed_fields:
                    prefix = 'spin' if field == 'spin_mode' else 'tat'
                    if getattr(current, f'active_{prefix}_purge_id'):
                        self.add_error(
                            field,
                            'Finish the active pilot purge before changing this workflow mode.',
                        )
        return cleaned


class OriginationProductDefinitionForm(forms.ModelForm):
    LAF_SOURCE_LIBRARY = 'library'
    LAF_SOURCE_UPLOAD = 'upload'
    LAF_SOURCE_LATER = 'later'
    LAF_SOURCE_CHOICES = (
        (LAF_SOURCE_LIBRARY, 'Choose from reusable library'),
        (LAF_SOURCE_UPLOAD, 'Upload a new PDF'),
        (LAF_SOURCE_LATER, 'Configure later'),
    )

    product_version = forms.ModelChoiceField(
        queryset=ProductVersion.objects.none(), required=False,
        help_text='Global product terms version used by this form and LAF.',
        widget=UnfoldAdminSelectWidget,
    )
    product_key = forms.SlugField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(required=False, widget=forms.HiddenInput)
    form_schema = forms.JSONField(widget=forms.HiddenInput)
    signer_rules = forms.JSONField(widget=forms.HiddenInput)
    main_laf_source = forms.ChoiceField(
        choices=LAF_SOURCE_CHOICES, required=False, initial=LAF_SOURCE_LIBRARY,
        label='Main LAF source', widget=forms.RadioSelect,
        help_text='Reuse an approved LAF, upload a new one, or save an incomplete draft and finish the document packet later.',
    )
    reusable_primary_template = forms.ModelChoiceField(
        queryset=OriginationDocumentTemplate.objects.none(), required=False,
        empty_label='Choose a published reusable primary LAF',
        label='Reusable primary LAF', widget=UnfoldAdminSelectWidget,
        help_text='The selected version is pinned to this product version. A later LAF upgrade must be selected explicitly.',
    )
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
            'product_version', 'main_laf_source', 'reusable_primary_template',
            'laf_pdf', 'product_key', 'name',
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
        self.fields['reusable_primary_template'].queryset = (
            OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True,
                document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                status=OriginationDocumentTemplate.STATUS_ACTIVE,
                published_configuration_revision__isnull=False,
            )
            .select_related('published_configuration_revision')
            .order_by('name', '-version')
        )
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
            assigned_primary = self.instance.document_assignments.filter(
                template__document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
            ).select_related('template').first()
            owned_primary = self.instance.document_templates.filter(
                document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                status__in=[
                    OriginationDocumentTemplate.STATUS_READY,
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                ],
            ).exists()
            if assigned_primary and not self.fields['reusable_primary_template'].queryset.filter(
                pk=assigned_primary.template_id,
            ).exists():
                self.fields['reusable_primary_template'].queryset = (
                    OriginationDocumentTemplate.objects.filter(
                        models.Q(pk=assigned_primary.template_id)
                        | models.Q(
                            product_definition__isnull=True,
                            document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                            status=OriginationDocumentTemplate.STATUS_ACTIVE,
                            published_configuration_revision__isnull=False,
                        )
                    ).order_by('name', '-version')
                )
            if not self.is_bound:
                if assigned_primary:
                    self.initial['main_laf_source'] = self.LAF_SOURCE_LIBRARY
                    self.initial['reusable_primary_template'] = assigned_primary.template_id
                elif owned_primary:
                    self.initial['main_laf_source'] = self.LAF_SOURCE_UPLOAD
                else:
                    self.initial['main_laf_source'] = self.LAF_SOURCE_LATER

    def clean(self):
        cleaned = super().clean()
        schema = cleaned.get('form_schema')
        signer_rules = cleaned.get('signer_rules')
        product_version = cleaned.get('product_version')
        laf_pdf = cleaned.get('laf_pdf')
        laf_source = str(cleaned.get('main_laf_source') or '').strip()
        reusable_primary = cleaned.get('reusable_primary_template')
        if not laf_source:
            # Cached Admin forms from before the library picker remain safe.
            laf_source = self.LAF_SOURCE_UPLOAD if laf_pdf else self.LAF_SOURCE_LATER
            cleaned['main_laf_source'] = laf_source
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
        existing_primary = None
        owned_primary = False
        if self.instance.pk:
            existing_primary = self.instance.document_assignments.filter(
                template__document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
            ).select_related('template').first()
            owned_primary = self.instance.document_templates.filter(
                document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                status__in=[
                    OriginationDocumentTemplate.STATUS_READY,
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                ],
            ).exists()
        if laf_source == self.LAF_SOURCE_LIBRARY:
            if not reusable_primary:
                self.add_error('reusable_primary_template', 'Choose a published reusable primary LAF.')
            elif owned_primary:
                self.add_error(
                    'reusable_primary_template',
                    'Remove or retire the product-owned primary LAF before selecting a reusable one.',
                )
            elif existing_primary and existing_primary.template_id != reusable_primary.pk:
                self.add_error(
                    'reusable_primary_template',
                    'Remove the primary LAF already attached to this product before selecting another.',
                )
            else:
                from core.services.origination_templates import (
                    OriginationTemplateError, _merge_shared_primary_contract,
                )
                self.instance.form_schema = schema or {}
                self.instance.signer_rules = signer_rules or []
                try:
                    schema, signer_rules = _merge_shared_primary_contract(
                        product=self.instance, template=reusable_primary,
                    )
                except OriginationTemplateError as exc:
                    self.add_error('reusable_primary_template', str(exc))
                else:
                    cleaned['form_schema'] = schema
                    cleaned['signer_rules'] = signer_rules
        elif laf_source == self.LAF_SOURCE_UPLOAD:
            if existing_primary:
                self.add_error(
                    'laf_pdf',
                    'Remove the reusable primary LAF from the document packet before uploading a product-owned replacement.',
                )
            elif not laf_pdf and not owned_primary:
                self.add_error('laf_pdf', 'Choose a PDF or select Configure later.')
        elif laf_source != self.LAF_SOURCE_LATER:
            self.add_error('main_laf_source', 'Choose how this product will get its main LAF.')
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
    SCHEMA_PRESET_GENERIC_JAWABU_LAF = 'generic_jawabu_laf'

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
        empty_label='Reusable template library (not tied to one product)',
        label='Draft product (optional)',
        help_text=(
            'Choose a draft product only when this PDF belongs exclusively to it. '
            'Leave blank for a reusable LAF or supporting document that several products can share.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    reusable_family = forms.ChoiceField(
        required=False,
        label='Reusable template family',
        help_text=(
            'For a replacement PDF, choose the existing family so it becomes the next version. '
            'For a new reusable document, leave this on Create new family.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    schema_preset = forms.ChoiceField(
        required=False,
        label='Field setup',
        choices=(
            ('', 'Build fields visually after upload'),
            (SCHEMA_PRESET_GENERIC_JAWABU_LAF, 'Generic Jawabu LAF - reviewed two-page field set'),
        ),
        help_text=(
            'The reviewed preset creates or updates the canonical fields and signer roles automatically. '
            'No JSON or code entry is required.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    pdf_file = forms.FileField(
        help_text='Approved PDF. It is stored in the configured restricted Drive folder.',
        widget=UnfoldAdminFileFieldWidget,
    )
    native_consent_policy = forms.ModelChoiceField(
        queryset=OriginationConsentPolicyVersion.objects.none(), required=False,
        label='Consent clause embedded in this PDF',
        help_text=(
            'Select only when compliance has verified that this exact source PDF visibly contains '
            'the complete clause. Otherwise the governed notice page is prepended automatically.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    native_consent_attestation_reference = forms.CharField(
        required=False, max_length=160, label='Native-clause attestation reference',
        help_text='Required when an embedded consent policy is selected.',
    )

    class Meta:
        model = OriginationDocumentTemplate
        fields = (
            'product_definition', 'reusable_family', 'schema_preset',
            'document_key', 'name', 'document_role',
            'inclusion_mode', 'display_order', 'officer_selectable',
            'default_selected', 'applicability_rule', 'form_schema',
            'signer_rules', 'pdf_file', 'native_consent_policy',
            'native_consent_attestation_reference',
        )
        widgets = {
            # These remain the audited storage format, but are authored through
            # the visual builder below rather than as hand-written JSON.
            'applicability_rule': forms.HiddenInput,
            'form_schema': forms.HiddenInput,
            'signer_rules': forms.HiddenInput,
            'document_key': forms.HiddenInput,
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
        self.fields['native_consent_policy'].queryset = OriginationConsentPolicyVersion.objects.filter(
            status=OriginationConsentPolicyVersion.STATUS_ACTIVE,
        ).order_by('-approved_at')
        reusable_families = []
        seen_families = set()
        family_templates = OriginationDocumentTemplate.objects.filter(
            product_definition__isnull=True,
        ).exclude(
            status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
        ).order_by('document_type', '-version')
        for template in family_templates:
            if template.document_type in seen_families:
                continue
            seen_families.add(template.document_type)
            reusable_families.append((
                template.document_type,
                f'{template.name} - {template.get_document_role_display()} (current v{template.version})',
            ))
        self.fields['reusable_family'].choices = [
            ('', 'Create a new reusable family from the document name'),
            *reusable_families,
        ]
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
                if key in self.fields:
                    self.fields[key].initial = value
        for key in defaults:
            if key in self.fields:
                self.fields[key].required = False
        self._configure_condition_editor()

    @staticmethod
    def _derived_family_key(name, role):
        key = slugify(str(name or '')).strip('-')[:80]
        if key:
            return key
        return 'shared-primary' if role == OriginationDocumentTemplate.ROLE_PRIMARY else 'shared-document'

    def clean(self):
        cleaned = super().clean()
        pdf_file = cleaned.get('pdf_file')
        product = cleaned.get('product_definition')
        reusable_family = str(cleaned.get('reusable_family') or '').strip()
        schema_preset = str(cleaned.get('schema_preset') or '').strip()
        if not pdf_file:
            return cleaned
        cleaned['document_role'] = cleaned.get('document_role') or OriginationDocumentTemplate.ROLE_PRIMARY
        cleaned['inclusion_mode'] = cleaned.get('inclusion_mode') or OriginationDocumentTemplate.INCLUDE_REQUIRED
        cleaned['display_order'] = cleaned.get('display_order') or 0
        cleaned['officer_selectable'] = bool(cleaned.get('officer_selectable'))
        cleaned['default_selected'] = bool(cleaned.get('default_selected'))
        cleaned['applicability_rule'] = self._clean_condition_rule(cleaned)
        cleaned['form_schema'] = cleaned.get('form_schema') or {}
        cleaned['signer_rules'] = cleaned.get('signer_rules') or []
        native_policy = cleaned.get('native_consent_policy')
        native_reference = str(cleaned.get('native_consent_attestation_reference') or '').strip()
        if bool(native_policy) != bool(native_reference):
            self.add_error(
                'native_consent_attestation_reference',
                'Select the embedded consent policy and provide its attestation reference together.',
            )
        if not str(pdf_file.name).lower().endswith('.pdf'):
            self.add_error('pdf_file', 'Upload a PDF file.')
            return cleaned
        family_template = None
        if product and reusable_family:
            self.add_error('reusable_family', 'A product-owned PDF cannot also be placed in a reusable family.')
        if product and schema_preset:
            self.add_error(
                'schema_preset',
                'The Generic Jawabu LAF preset creates a reusable primary LAF. Leave Draft product blank.',
            )
        if reusable_family:
            family_template = OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True,
                document_type=reusable_family,
            ).exclude(
                status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
            ).order_by('-version').first()
            if not family_template:
                self.add_error('reusable_family', 'Choose an existing reusable template family.')

        role = cleaned['document_role']
        name = str(cleaned.get('name') or '').strip()
        if schema_preset == self.SCHEMA_PRESET_GENERIC_JAWABU_LAF:
            from core.services.generic_jawabu_laf_seed import (
                DOCUMENT_NAME, DOCUMENT_TYPE, GenericJawabuLafSeedError,
                validate_catalogue_contract,
            )
            if reusable_family and reusable_family != DOCUMENT_TYPE:
                self.add_error('reusable_family', 'The reviewed preset belongs to the Generic Jawabu LAF family.')
            try:
                validate_catalogue_contract()
            except GenericJawabuLafSeedError as exc:
                self.add_error('schema_preset', str(exc))
            role = OriginationDocumentTemplate.ROLE_PRIMARY
            name = name or DOCUMENT_NAME
            document_type = DOCUMENT_TYPE
            family_template = OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True, document_type=DOCUMENT_TYPE,
            ).exclude(status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED).order_by('-version').first()
        elif family_template:
            role = family_template.document_role
            name = name or family_template.name
            document_type = family_template.document_type
        elif product:
            document_type = product.document_type if role == OriginationDocumentTemplate.ROLE_PRIMARY else ''
        else:
            document_type = self._derived_family_key(name, role)
            if OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True,
                document_type=document_type,
            ).exclude(status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED).exists():
                self.add_error(
                    'reusable_family',
                    'A reusable family with this name already exists. Select it above to upload its next version.',
                )

        if not name:
            self.add_error('name', 'Enter a clear document name.')
        if role == OriginationDocumentTemplate.ROLE_PRIMARY:
            document_key = 'primary'
        elif family_template:
            document_key = family_template.document_key
        else:
            document_key = self._derived_family_key(name, role)
        if product and role == OriginationDocumentTemplate.ROLE_SUPPORTING:
            document_type = f'{product.product_key}-{document_key}'[:80]
        cleaned.update({
            'name': name,
            'document_key': document_key,
            'document_role': role,
        })
        for key, value in cleaned.items():
            if key in self.fields:
                setattr(self.instance, key, value)
        if product and product.document_templates.exclude(
            status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
        ).filter(document_key=document_key).exists():
            self.add_error('product_definition', 'This draft product already has this document. Open its existing template instead.')
            return cleaned
        from core.services.origination_templates import (
            OriginationTemplateError, initial_template_configuration, sample_context_for_schema,
            validate_template_pdf,
        )
        pdf_data = pdf_file.read()
        pdf_file.seek(0)
        try:
            digest, page_count = validate_template_pdf(pdf_data)
        except OriginationTemplateError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if schema_preset == self.SCHEMA_PRESET_GENERIC_JAWABU_LAF and page_count != 2:
            self.add_error(
                'pdf_file',
                f'The reviewed Generic Jawabu LAF preset expects the two-page form; this PDF has {page_count} page(s).',
            )
        self.instance.product_definition = product
        self.instance.name = name
        self.instance.document_key = document_key
        self.instance.document_role = role
        self.instance.document_type = document_type
        self.instance.version = (
            product.version if product else
            (OriginationDocumentTemplate.objects.filter(document_type=self.instance.document_type)
             .aggregate(models.Max('version'))['version__max'] or 0) + 1
        )
        self.instance.source_filename = str(pdf_file.name)[:255]
        self.instance.source_sha256 = digest
        self.instance.source_byte_size = len(pdf_data)
        self.instance.page_count = page_count
        inherited_schema = family_template.form_schema if family_template else {}
        inherited_signers = family_template.signer_rules if family_template else []
        self.instance.placement_config = initial_template_configuration(
            product, form_schema=inherited_schema or None,
        )
        self.instance.placement_config['version'] = self.instance.version
        self.instance.placement_config['document_type'] = self.instance.document_type
        # Product-owned primaries use their product contract. Reusable family
        # successors inherit the family's governed schema and signer roles.
        self.instance.form_schema = (
            product.form_schema if role == OriginationDocumentTemplate.ROLE_PRIMARY and product
            else inherited_schema or cleaned.get('form_schema') or {}
        )
        self.instance.signer_rules = (
            product.signer_rules if role == OriginationDocumentTemplate.ROLE_PRIMARY and product
            else inherited_signers or cleaned.get('signer_rules') or []
        )
        sample_context = self.instance.placement_config.setdefault('sample_context', {})
        generated_samples = sample_context_for_schema(self.instance.form_schema)
        generated_canonical = generated_samples.pop('_canonical_values', {})
        for key, value in generated_samples.items():
            sample_context.setdefault(key, value)
        if generated_canonical:
            canonical_values = sample_context.setdefault('_canonical_values', {})
            for key, value in generated_canonical.items():
                canonical_values.setdefault(key, value)
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
        if 'product_definition' in self.fields:
            self.fields['product_definition'].help_text = (
                'Choose an editable Draft product. Published products must first be opened as an '
                'editable product version.'
            )
        if 'template' in self.fields:
            self.fields['template'].help_text = (
                'The document must already be published. Selecting a newer version of the same '
                'Main LAF family upgrades the draft; a different Main LAF must first be removed '
                'from the product Document packet.'
            )

    def clean(self):
        cleaned = super().clean()
        cleaned['applicability_rule'] = self._clean_condition_rule(cleaned)
        template = cleaned.get('template')
        product = cleaned.get('product_definition')
        if template:
            # A product assignment chooses a governed document family. It must
            # not create another, typo-prone key and name for that same form.
            self.instance.document_key = template.document_key
            self.instance.name = template.name
            if template.document_role == template.ROLE_PRIMARY:
                cleaned.update({
                    'version_policy': OriginationProductDocumentAssignment.VERSION_PINNED,
                    'inclusion_mode': template.INCLUDE_REQUIRED,
                    'display_order': 0,
                    'officer_selectable': False,
                    'default_selected': False,
                    'applicability_rule': {},
                })
                for key in (
                    'version_policy', 'inclusion_mode', 'display_order', 'officer_selectable',
                    'default_selected', 'applicability_rule',
                ):
                    setattr(self.instance, key, cleaned[key])
                if product and self.instance._state.adding:
                    owned_primary = product.document_templates.filter(
                        document_role=template.ROLE_PRIMARY,
                        status__in=[template.STATUS_READY, template.STATUS_ACTIVE],
                    ).exists()
                    assigned_primary = product.document_assignments.filter(
                        template__document_role=template.ROLE_PRIMARY,
                    ).select_related('template').first()
                    if owned_primary:
                        self.add_error(
                            'template',
                            'This draft already has a product-owned Main LAF. Remove or retire '
                            'it from the product Document packet before selecting a reusable LAF.',
                        )
                    elif assigned_primary and assigned_primary.template_id != template.pk:
                        baseline = assigned_primary.template
                        if baseline.document_type != template.document_type:
                            self.add_error(
                                'template',
                                f'This draft already uses {baseline.name} as its Main LAF. '
                                'Remove it from the product Document packet before selecting a '
                                'different LAF family.',
                            )
                        else:
                            from core.services.origination_templates import (
                                assignment_template_compatibility_errors,
                            )
                            compatibility_errors = assignment_template_compatibility_errors(
                                baseline, template,
                            )
                            if compatibility_errors:
                                self.add_error(
                                    'template',
                                    'This version cannot upgrade the current Main LAF because '
                                    + '; '.join(compatibility_errors)
                                    + '.',
                                )
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


from core.services.product_availability import PRODUCT_WORKFLOW_CHOICES as _PRODUCT_WORKFLOW_CHOICES

PRODUCT_WORKFLOW_CHOICES = [('', 'All workflows'), *_PRODUCT_WORKFLOW_CHOICES]

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


@admin.register(Product)
class ProductAdmin(CompactModelAdmin):
    """Canonical identity shared by every workflow and external adapter."""

    list_display = ('name', 'code', 'category', 'active', 'current_terms', 'sort_order', 'updated_at')
    list_filter = ('active', 'category')
    search_fields = ('name', 'code', 'aliases__alias')
    ordering = ('sort_order', 'name')
    readonly_fields = ('created_at', 'updated_at', 'terms_link', 'availability_link')
    inlines = (ProductAliasInline,)
    fieldsets = (
        ('Global identity', {'fields': (('name', 'code'), ('category', 'active'), 'description', 'sort_order')}),
        ('Commercial terms', {'fields': ('terms_link',)}),
        ('Availability', {'fields': ('availability_link',)}),
        ('Audit', {'fields': (('created_at', 'updated_at'),), 'classes': ('collapse',)}),
    )

    def get_urls(self):
        return [
            path(
                '<path:object_id>/availability/',
                self.admin_site.admin_view(self.availability_workspace_view),
                name='core_product_availability',
            ),
        ] + super().get_urls()

    def availability_workspace_view(self, request, object_id):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        product = Product.objects.filter(pk=object_id).first()
        if not product:
            return HttpResponse(status=404)
        error = ''
        if request.method == 'POST':
            from core.services.product_availability import (
                add_product_coverage, deactivate_product_coverage,
            )
            try:
                action = str(request.POST.get('action') or '')
                if action == 'add':
                    result = add_product_coverage(
                        product=product,
                        branch_ids=request.POST.getlist('branches'),
                        workflows=request.POST.getlist('workflows'),
                        actor=request.user,
                        request_id=request.POST.get('request_id') or '',
                    )
                    self.message_user(
                        request,
                        f"Coverage saved: {result['created_count']} added and "
                        f"{result['reactivated_count']} reactivated.",
                        level=messages.SUCCESS,
                    )
                elif action == 'deactivate':
                    count = deactivate_product_coverage(
                        product=product,
                        assignment_ids=request.POST.getlist('assignments'),
                        actor=request.user,
                        request_id=request.POST.get('request_id') or '',
                    )
                    self.message_user(
                        request, f'{count} coverage assignment(s) deactivated.',
                        level=messages.SUCCESS,
                    )
                else:
                    raise ValidationError('Choose a supported availability action.')
                return HttpResponseRedirect(reverse(
                    'admin:core_product_availability', args=[product.pk],
                ))
            except ValidationError as exc:
                error = '; '.join(exc.messages)
        from core.services.product_availability import (
            CANONICAL_PRODUCT_CHANNEL, PRODUCT_WORKFLOW_CHOICES,
        )
        workflow_labels = dict(PRODUCT_WORKFLOW_CHOICES)
        canonical = list(product.availability_assignments.select_related('branch').filter(
            active=True, channel=CANONICAL_PRODUCT_CHANNEL,
            workflow__in=workflow_labels,
        ).order_by('workflow', 'branch__sort_order', 'branch__name'))
        for assignment in canonical:
            assignment.workflow_label = workflow_labels.get(
                assignment.workflow, assignment.workflow,
            )
        compatibility = list(product.availability_assignments.select_related('branch').filter(
            active=True,
        ).exclude(
            channel=CANONICAL_PRODUCT_CHANNEL, workflow__in=workflow_labels,
        ).order_by('workflow', 'channel', 'branch__name'))
        return TemplateResponse(request, 'admin/core/product/availability.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Manage {product.name} availability',
            'product': product,
            'branches': OperationalLocation.objects.filter(
                location_type='branch', active=True,
            ).order_by('sort_order', 'name'),
            'workflows': PRODUCT_WORKFLOW_CHOICES,
            'canonical_assignments': canonical,
            'compatibility_assignments': compatibility,
            'request_id': str(uuid.uuid4()),
            'error': error,
            'product_change_url': reverse('admin:core_product_change', args=[product.pk]),
        }, status=400 if error else 200)

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

    @admin.display(description='Product availability')
    def availability_link(self, obj):
        if not obj.pk:
            return 'Save the product before configuring availability.'
        count = obj.availability_assignments.filter(active=True, channel='portal').count()
        url = reverse('admin:core_product_availability', args=[obj.pk])
        return format_html(
            '<a class="button" href="{}">Manage availability</a> '
            '<span>{} active branch/workflow assignment(s)</span>',
            url, count,
        )

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


class TatResponsibilityAssignmentForm(forms.ModelForm):
    branch = forms.ChoiceField(choices=(), required=True)
    role = forms.ChoiceField(choices=(), required=True)
    product_key = forms.ChoiceField(choices=(), required=False, label='Product')
    stage_key = forms.ChoiceField(choices=(), required=False, label='Stage')
    change_reason = forms.CharField(
        required=True, label='Reason for change',
        widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Required. The responsibility change is recorded in append-only audit history.',
    )

    class Meta:
        model = TatResponsibilityAssignment
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        def selected_value(name):
            if self.is_bound:
                return str(self.data.get(self.add_prefix(name), '') or '').strip()
            if name in self.initial:
                return str(self.initial.get(name) or '').strip()
            return str(getattr(self.instance, name, '') or '').strip()

        branches = set(global_branch_choices())
        workflows = list(GroupSheetConfiguration.objects.filter(
            workflow__type='tat_tracker', enabled=True,
        ).values_list('workflow', flat=True))
        product_configs = {product.key: product for product in PRODUCTS.values()}
        for workflow in workflows:
            branches.update(configured_workflow_branches(workflow or {}, default=[]))
            for product in configured_products(workflow or {}):
                product_configs[product.key] = product
        if self.instance and self.instance.pk and self.instance.branch:
            branches.add(self.instance.branch)
        self.fields['branch'].choices = [(value, value) for value in sorted(branches)]
        roles = {str(stage.role or '').strip().upper() for product in product_configs.values() for stage in product.stages}
        if self.instance and self.instance.pk and self.instance.role:
            roles.add(self.instance.role)
        roles = sorted(roles)
        self.fields['role'].choices = [(value, value.replace('_', ' ').title()) for value in roles]
        self.fields['role'].help_text = 'Used for a role roster. A selected stage derives and locks its canonical role.'
        product_choices = [('', 'All products')] + [
            (product.key, product.label) for product in product_configs.values()
        ]
        product_values = {value for value, _label in product_choices}
        if self.instance and self.instance.pk and self.instance.product_key not in product_values:
            product_choices.append((self.instance.product_key, self.instance.product_key))
        self.fields['product_key'].choices = product_choices
        stage_labels = {}
        stage_roles = {}
        selected_product = selected_value('product_key').lower()
        visible_products = [
            product for product in product_configs.values()
            if not selected_product or product.key.casefold() == selected_product.casefold()
        ]
        for product in visible_products:
            for stage in product.stages:
                role = str(stage.role or '').strip().upper()
                stage_labels.setdefault(stage.key, stage.label)
                stage_roles.setdefault(stage.key, set()).add(role)
        if self.instance and self.instance.pk and self.instance.stage_key:
            stage_labels.setdefault(self.instance.stage_key, self.instance.stage_key)
        self.fields['stage_key'].choices = [('', 'All stages for this role')] + sorted([
            (key, f"{label} — {', '.join(sorted(stage_roles.get(key) or []))}")
            for key, label in stage_labels.items()
        ], key=lambda row: row[1])
        self.fields['stage_key'].widget.attrs['data-stage-role-map'] = json.dumps({
            key: next(iter(values)) for key, values in stage_roles.items() if len(values) == 1
        })
        selected_group_id = selected_value('group_configuration')
        selected_branch = selected_value('branch')
        selected_role = selected_value('role').upper()
        selected_stage = selected_value('stage_key')
        if selected_stage and selected_group_id:
            try:
                group = GroupSheetConfiguration.objects.get(pk=selected_group_id)
                selected_role = canonical_stage_role(
                    stage_key=selected_stage,
                    product_key=selected_product,
                    workflow=group.workflow,
                )
            except (GroupSheetConfiguration.DoesNotExist, ValidationError):
                pass
            else:
                self.fields['role'].choices = [(selected_role, selected_role.replace('_', ' ').title())]
                self.fields['role'].initial = selected_role
                self.fields['role'].disabled = True
                self.fields['role'].help_text = 'Derived automatically from the selected canonical TAT stage.'

        selected_group = (
            GroupSheetConfiguration.objects.filter(pk=selected_group_id).first()
            if selected_group_id else None
        )
        eligible_users = eligible_responsibility_users(
            group_configuration=selected_group,
            branch=selected_branch,
            role=selected_role,
            product_key=selected_product,
        )
        primary_queryset = eligible_users
        if self.instance and self.instance.pk and self.instance.primary_user_id:
            # Keep an invalid historical selection visible while requiring the
            # administrator to replace it before a successful save.
            primary_queryset = get_user_model().objects.filter(
                models.Q(pk__in=eligible_users.values('pk'))
                | models.Q(pk=self.instance.primary_user_id)
            ).distinct().order_by('first_name', 'last_name', 'username')
        self.fields['primary_user'].queryset = primary_queryset
        primary_widget = self.fields['primary_user'].widget
        primary_native_widget = getattr(primary_widget, 'widget', primary_widget)
        primary_native_widget.attrs['data-eligible-users-url'] = reverse(
            'admin:core_tatresponsibilityassignment_eligible_users',
        )
        if selected_group and selected_branch and selected_role:
            count = eligible_users.count()
            eligibility_message = (
                f'{count} eligible active user{"s" if count != 1 else ""} match this exact TAT scope.'
                if count else
                'No eligible users match this TAT role and scope. Add or correct an active AccessGrant, then retry.'
            )
        else:
            eligibility_message = 'Choose the workflow group, branch, and role to load eligible users.'
        self.fields['primary_user'].help_text = format_html(
            '<span id="tat-eligible-users-help">{}</span> '
            '<a href="{}">Manage user access grants</a>',
            eligibility_message,
            reverse('admin:auth_user_changelist'),
        )

    def clean(self):
        cleaned = super().clean()
        stage_key = cleaned.get('stage_key')
        group = cleaned.get('group_configuration')
        if stage_key and group:
            cleaned['role'] = canonical_stage_role(
                stage_key=stage_key,
                product_key=cleaned.get('product_key') or '',
                workflow=group.workflow,
            )
            self.instance.role = cleaned['role']
        return cleaned

    class Media:
        js = ('admin/js/tat_responsibility.js',)


class TatResponsibilityBackupForm(forms.ModelForm):
    threshold_percent = forms.ChoiceField(choices=(), label='SLA escalation threshold')

    class Meta:
        model = TatResponsibilityBackup
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        thresholds = sorted(set(TatEscalationRule.objects.filter(active=True).values_list('threshold_percent', flat=True)))
        if self.instance and self.instance.pk and self.instance.threshold_percent:
            thresholds = sorted(set(thresholds) | {self.instance.threshold_percent})
        self.fields['threshold_percent'].choices = [
            (value, f'{value}%') for value in thresholds
        ]
        grants = AccessGrant.objects.filter(workflow='tat_tracker', active=True)
        assignment = getattr(self.instance, 'assignment', None)
        if assignment and assignment.pk:
            users = eligible_responsibility_users(
                group_configuration=assignment.group_configuration,
                branch=assignment.branch,
                role=assignment.role,
                product_key=assignment.product_key,
            )
            if self.instance.user_id:
                users = get_user_model().objects.filter(
                    models.Q(pk__in=users.values('pk')) | models.Q(pk=self.instance.user_id)
                ).distinct().order_by('first_name', 'last_name', 'username')
            self.fields['user'].queryset = users
            if self.instance.user_id:
                native_widget = getattr(self.fields['user'].widget, 'widget', self.fields['user'].widget)
                native_widget.attrs['data-initial-user-id'] = str(self.instance.user_id)
        else:
            self.fields['user'].queryset = get_user_model().objects.filter(
                access_grants__in=grants, is_active=True,
            ).distinct().order_by('first_name', 'last_name', 'username')


class TatResponsibilityBackupInline(TabularInline):
    model = TatResponsibilityBackup
    form = TatResponsibilityBackupForm
    extra = 1
    fields = ('rank', 'user', 'threshold_percent', 'active')


@admin.register(TatResponsibilityAssignment)
class TatResponsibilityAssignmentAdmin(CompactModelAdmin):
    """Superuser-managed routing; matching AccessGrants remain authoritative."""

    form = TatResponsibilityAssignmentForm
    change_list_template = 'admin/core/tatresponsibilityassignment/change_list.html'
    list_display = (
        'group_configuration', 'branch', 'role', 'product_key', 'stage_key',
        'primary_user', 'active', 'effective_from', 'effective_until',
    )
    list_filter = ('active', 'group_configuration', 'role', 'branch', 'product_key', 'stage_key')
    search_fields = (
        'primary_user__username', 'primary_user__first_name', 'primary_user__last_name',
        'group_configuration__display_name', 'branch', 'role', 'product_key', 'stage_key',
    )
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    inlines = (TatResponsibilityBackupInline,)
    fieldsets = (
        ('Responsibility scope', {
            'fields': (
                'group_configuration', ('branch', 'role'),
                ('product_key', 'stage_key'), 'primary_user',
                'change_reason',
            ),
            'description': 'Assignment routes alerts only. Every actor still needs a matching TAT AccessGrant.',
        }),
        ('Availability', {
            'fields': (('active', 'effective_from', 'effective_until'),),
            'classes': ('tat-responsibility-availability',),
        }),
        ('Audit', {'fields': (('created_by', 'created_at', 'updated_at'),), 'classes': ('collapse',)}),
    )

    def get_urls(self):
        return [
            path(
                'eligible-users/',
                self.admin_site.admin_view(self.eligible_users_view),
                name='core_tatresponsibilityassignment_eligible_users',
            ),
            path(
                'control-center/<int:group_id>/',
                self.admin_site.admin_view(self.control_center_view),
                name='core_tat_control_center',
            ),
            path(
                'control-center/<int:group_id>/stages/<uuid:version_id>/',
                self.admin_site.admin_view(self.stage_designer_view),
                name='core_tat_stage_designer',
            ),
            path(
                'control-center/<int:group_id>/register/',
                self.admin_site.admin_view(self.register_view),
                name='core_tat_register',
            ),
            path(
                'control-center/<int:group_id>/register/export/',
                self.admin_site.admin_view(self.register_export_view),
                name='core_tat_register_export',
            ),
            path(
                'control-center/task/<uuid:task_id>/reroute/',
                self.admin_site.admin_view(self.reroute_task_view),
                name='core_tat_task_reroute',
            ),
            path(
                'control-center/case/<uuid:case_id>/resolve-configuration/',
                self.admin_site.admin_view(self.resolve_case_configuration_view),
                name='core_tat_case_configuration_resolve',
            ),
        ] + super().get_urls()

    def _control_group(self, group_id):
        group = GroupSheetConfiguration.objects.filter(pk=group_id, enabled=True).first()
        if not group or str((group.workflow or {}).get('type') or '') != 'tat_tracker':
            raise PermissionDenied('Choose an enabled TAT Tracker group.')
        return group

    def control_center_view(self, request, group_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        from core.services.tat_setup import (
            TatSetupError, disable_sheet_projection, enable_sheet_projection,
            setup_readiness, sheet_cutover_readiness,
        )
        group = self._control_group(group_id)
        if request.method == 'POST' and request.POST.get('action') in {'disable_projection', 'enable_projection'}:
            try:
                operation = disable_sheet_projection if request.POST.get('action') == 'disable_projection' else enable_sheet_projection
                operation(
                    group=group, actor=request.user,
                    reason=request.POST.get('reason'), request_id=request.POST.get('request_id'),
                )
            except TatSetupError as exc:
                messages.error(request, str(exc))
            else:
                from core.services.group_config import GroupRegistry
                from core.services.sheets import GoogleSheetsService
                GroupRegistry._instance = None
                GoogleSheetsService.clear_instances()
                state = 'disabled' if request.POST.get('action') == 'disable_projection' else 'enabled'
                messages.success(request, f'Google Sheet projection {state}. Django remains the TAT source of truth.')
            return HttpResponseRedirect(reverse('admin:core_tat_control_center', args=[group.pk]))
        readiness = setup_readiness(group)
        allowed_product_keys = [item.key for item in configured_products(group.workflow)]
        versions = list(ProductVersion.objects.select_related('product').filter(
            tat_configuration__isnull=False, product__code__in=allowed_product_keys,
        ).order_by('product__sort_order', 'product__name', '-version'))
        products = {}
        for version in versions:
            row = products.setdefault(version.product_id, {
                'product': version.product, 'versions': [], 'selected': None,
            })
            row['versions'].append(version)
            if row['selected'] is None or version.status == ProductVersion.STATUS_DRAFT:
                row['selected'] = version
        for row in products.values():
            selected = row['selected']
            row['designer_url'] = reverse(
                'admin:core_tat_stage_designer', args=[group.pk, selected.pk],
            )
            row['version_admin_url'] = reverse('admin:core_productversion_change', args=[selected.pk])
        return TemplateResponse(request, 'admin/core/tatresponsibilityassignment/control_center.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'TAT Control Center - {group.display_name or group.group_id}',
            'group': group, 'readiness': readiness, 'products': list(products.values()),
            'cutover': sheet_cutover_readiness(group),
            'register_url': reverse('admin:core_tat_register', args=[group.pk]),
            'responsibilities_url': f"{reverse('admin:core_tatresponsibilityassignment_changelist')}?workspace_group={group.pk}",
            'users_url': reverse('admin:auth_user_changelist'),
            'request_id': str(uuid.uuid4()),
        })

    def stage_designer_view(self, request, group_id, version_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        from core.services.tat_setup import TatSetupError, save_stage_design, stage_editor_rows
        group = self._control_group(group_id)
        version = ProductVersion.objects.select_related('product').filter(pk=version_id).first()
        allowed_keys = {item.key for item in configured_products(group.workflow)}
        if not version or not hasattr(version, 'tat_configuration') or version.product.code not in allowed_keys:
            return HttpResponse(status=404)
        request_id = str(request.POST.get('request_id') or uuid.uuid4())
        if request.method == 'POST':
            try:
                stages = json.loads(request.POST.get('stages_json') or '[]')
                saved = save_stage_design(
                    version=version, stages=stages, actor=request.user,
                    expected_updated_at=request.POST.get('expected_updated_at'),
                    reason=request.POST.get('reason'), request_id=request_id,
                )
            except (json.JSONDecodeError, TatSetupError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f'Stage design saved to editable {saved.product.name} version {saved.version}.')
                return HttpResponseRedirect(reverse(
                    'admin:core_tat_stage_designer', args=[group.pk, saved.pk],
                ))
        return TemplateResponse(request, 'admin/core/tatresponsibilityassignment/stage_designer.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'{version.product.name} TAT stage designer', 'group': group,
            'version': version, 'stages_json': json.dumps(stage_editor_rows(version)),
            'request_id': request_id,
            'back_url': reverse('admin:core_tat_control_center', args=[group.pk]),
        })

    def register_view(self, request, group_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        from core.services.tat_register import register_data, version_timeline
        group = self._control_group(group_id)
        filters = {key: str(request.GET.get(key) or '').strip() for key in (
            'search', 'branch', 'product', 'version', 'stage', 'owner', 'status',
        )}
        data = register_data(
            group=group, filters=filters, page=request.GET.get('page') or 1,
            page_size=request.GET.get('page_size') or 25,
        )
        branches = sorted(set(TatTrackerCase.objects.filter(
            group_id=group.group_id, is_deleted=False,
        ).exclude(branch='').values_list('branch', flat=True)))
        version_options = ProductVersion.objects.select_related('product').filter(
            tat_configuration__isnull=False,
        ).order_by('product__name', '-version')
        selected_version = version_options.filter(pk=filters.get('version')).first() if filters.get('version') else None
        return TemplateResponse(request, 'admin/core/tatresponsibilityassignment/register.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'TAT Register - {group.display_name or group.group_id}',
            'group': group, 'filters': filters, 'register': data, 'branches': branches,
            'status_choices': TatTrackerCase.STATUS_CHOICES,
            'version_options': version_options, 'selected_version': selected_version,
            'timeline': version_timeline(group=group, version=selected_version),
            'products': configured_products(group.workflow),
            'export_url': reverse('admin:core_tat_register_export', args=[group.pk]),
            'control_center_url': reverse('admin:core_tat_control_center', args=[group.pk]),
            'request_id': str(uuid.uuid4()),
        })

    def register_export_view(self, request, group_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        if request.method != 'POST':
            response = HttpResponse(status=405)
            response['Allow'] = 'POST'
            return response
        from core.services.tat_register import export_xlsx
        group = self._control_group(group_id)
        filters = {key: str(request.POST.get(key) or '').strip() for key in (
            'search', 'branch', 'product', 'version', 'stage', 'owner', 'status',
        )}
        request_id = str(request.POST.get('request_id') or '').strip()
        if not request_id:
            messages.error(request, 'The export request expired. Reload the register and try again.')
            return HttpResponseRedirect(reverse('admin:core_tat_register', args=[group.pk]))
        content = export_xlsx(group=group, actor=request.user, request_id=request_id, filters=filters)
        response = HttpResponse(
            content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="tat-register-{timezone.localdate().isoformat()}.xlsx"'
        return response

    def reroute_task_view(self, request, task_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        task = TatActionTask.objects.select_related('case', 'group_configuration').filter(pk=task_id).first()
        if not task:
            return HttpResponse(status=404)
        if request.method == 'POST':
            from core.services.tat_notifications import reroute_pending_task
            try:
                reroute_pending_task(
                    task=task, actor=request.user, reason=request.POST.get('reason'),
                    request_id=request.POST.get('request_id'),
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, 'The open task was rerouted to the current approved responsibility roster.')
            return HttpResponseRedirect(reverse(
                'admin:core_tat_register', args=[task.group_configuration_id],
            ))
        return TemplateResponse(request, 'admin/core/tatresponsibilityassignment/reroute.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Reroute {task.case.case_id}', 'task': task,
            'request_id': str(uuid.uuid4()),
            'back_url': reverse('admin:core_tat_register', args=[task.group_configuration_id]),
        })

    def resolve_case_configuration_view(self, request, case_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        case = TatTrackerCase.objects.select_related('product', 'product_version').filter(pk=case_id).first()
        if not case:
            return HttpResponse(status=404)
        group = GroupSheetConfiguration.objects.filter(group_id=case.group_id).first()
        versions = ProductVersion.objects.select_related('product').filter(tat_configuration__isnull=False)
        versions = (
            versions.filter(product_id=case.product_id)
            if case.product_id else versions.filter(product__code=case.product_key)
        )
        request_id = str(request.POST.get('request_id') or uuid.uuid4())
        if request.method == 'POST':
            from core.services.tat_configuration import TatConfigurationError, resolve_case_configuration
            version = versions.filter(pk=request.POST.get('product_version')).first()
            if not version:
                messages.error(request, 'Choose a matching governed product version.')
            else:
                try:
                    resolve_case_configuration(
                        case=case, version=version, actor=request.user,
                        reason=request.POST.get('reason'), request_id=request_id,
                    )
                except TatConfigurationError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, 'The case is now bound to the selected immutable TAT configuration.')
                    return HttpResponseRedirect(reverse('admin:core_tat_register', args=[group.pk]))
        return TemplateResponse(request, 'admin/core/tatresponsibilityassignment/resolve_case.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Resolve configuration for {case.case_id}', 'case': case,
            'versions': versions.order_by('-version'), 'request_id': request_id,
            'back_url': reverse('admin:core_tat_register', args=[group.pk]) if group else reverse('admin:core_tatresponsibilityassignment_changelist'),
        })

    def eligible_users_view(self, request):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        if request.method != 'GET':
            return JsonResponse({'ok': False, 'error': 'GET required.'}, status=405)

        group_id = str(request.GET.get('group_configuration') or '').strip()
        branch = str(request.GET.get('branch') or '').strip()
        role = str(request.GET.get('role') or '').strip().upper()
        product_key = str(request.GET.get('product_key') or '').strip().lower()
        missing = [
            label for label, value in (
                ('workflow group', group_id), ('branch', branch), ('role', role),
            ) if not value
        ]
        if missing:
            return JsonResponse({
                'ok': True,
                'users': [],
                'message': f'Choose {", ".join(missing)} to load eligible users.',
            })

        group = GroupSheetConfiguration.objects.filter(pk=group_id, enabled=True).first()
        if not group or str((group.workflow or {}).get('type') or '') != 'tat_tracker':
            return JsonResponse({
                'ok': False,
                'users': [],
                'error': 'Choose an enabled TAT workflow group.',
            }, status=400)

        users = list(eligible_responsibility_users(
            group_configuration=group,
            branch=branch,
            role=role,
            product_key=product_key,
        ))
        payload = []
        for user in users:
            full_name = user.get_full_name().strip()
            payload.append({
                'id': str(user.pk),
                'label': f'{full_name} ({user.get_username()})' if full_name else user.get_username(),
            })
        scope = f'{role} / {branch} / {product_key or "all products"}'
        return JsonResponse({
            'ok': True,
            'users': payload,
            'message': (
                f'{len(payload)} eligible active user{"s" if len(payload) != 1 else ""} match {scope}.'
                if payload else
                f'No eligible users match {scope}. Add or correct an active TAT AccessGrant, then retry.'
            ),
        })

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            raise PermissionDenied
        if not obj.created_by_id:
            obj.created_by = request.user
        obj._responsibility_before = (
            assignment_snapshot(type(obj).objects.get(pk=obj.pk)) if change else {}
        )
        obj._responsibility_reason = form.cleaned_data['change_reason']
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        TatResponsibilityEvent.objects.create(
            assignment=obj,
            assignment_id_snapshot=obj.pk,
            action=(TatResponsibilityEvent.ACTION_UPDATED if change else TatResponsibilityEvent.ACTION_CREATED),
            actor=request.user,
            reason=getattr(obj, '_responsibility_reason', ''),
            before_snapshot=getattr(obj, '_responsibility_before', {}),
            after_snapshot=assignment_snapshot(obj),
        )

    def delete_model(self, request, obj):
        snapshot = assignment_snapshot(obj)
        event = TatResponsibilityEvent.objects.create(
            assignment=obj, assignment_id_snapshot=obj.pk,
            action=TatResponsibilityEvent.ACTION_DELETED,
            actor=request.user,
            reason='Deleted through Django Admin by a technical Superuser.',
            before_snapshot=snapshot,
        )
        super().delete_model(request, obj)
        event.refresh_from_db()

    def delete_queryset(self, request, queryset):
        for obj in queryset.prefetch_related('backups'):
            self.delete_model(request, obj)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        for key in ('group_configuration', 'branch', 'product_key', 'stage_key', 'role'):
            if request.GET.get(key) is not None:
                initial[key] = request.GET[key]
        return initial

    def changelist_view(self, request, extra_context=None):
        groups = list(GroupSheetConfiguration.objects.filter(
            workflow__type='tat_tracker', enabled=True,
        ).order_by('display_name', 'group_id'))
        selected_group_id = (
            request.GET.get('workspace_group')
            or request.GET.get('group_configuration_id__exact')
            or (str(groups[0].pk) if groups else '')
        )
        selected_group = next((item for item in groups if str(item.pk) == selected_group_id), None)
        products = configured_products(selected_group.workflow if selected_group else {})
        product_key = str(request.GET.get('workspace_product') or '').strip().lower()
        branches = sorted(set(
            configured_workflow_branches(selected_group.workflow or {}, default=[])
            if selected_group else global_branch_choices()
        ))
        branch = str(request.GET.get('workspace_branch') or (branches[0] if branches else '')).strip()
        catalogue = stage_catalog(selected_group.workflow if selected_group else {})
        if product_key:
            catalogue = [row for row in catalogue if row['product_key'] == product_key]
        assignments = TatResponsibilityAssignment.objects.none()
        if selected_group:
            assignments = TatResponsibilityAssignment.objects.filter(
                group_configuration=selected_group,
            ).select_related('group_configuration', 'primary_user').prefetch_related('backups__user')
        scoped_assignments = [row for row in assignments if not branch or row.branch.casefold() == branch.casefold()]
        workspace_now = timezone.now()
        current_assignments = [
            row for row in scoped_assignments
            if row.active
            and row.effective_from <= workspace_now
            and (row.effective_until is None or row.effective_until > workspace_now)
        ]
        role_rosters = {
            (row.role, row.product_key): row for row in current_assignments
            if not row.stage_key
        }
        stage_overrides = {
            (row.stage_key, row.product_key): row for row in current_assignments
            if row.stage_key
        }
        role_rows = []
        for role in sorted({row['role'] for row in catalogue}):
            roster = role_rosters.get((role, product_key)) or role_rosters.get((role, ''))
            params = {
                'group_configuration': selected_group_id,
                'branch': branch,
                'product_key': product_key,
                'role': role,
            }
            role_rows.append({
                'role': role,
                'roster': roster,
                'add_url': f"{reverse('admin:core_tatresponsibilityassignment_add')}?{urlencode(params)}",
            })
        for row in catalogue:
            override = stage_overrides.get((row['stage_key'], product_key)) or stage_overrides.get((row['stage_key'], ''))
            params = {
                'group_configuration': selected_group_id,
                'branch': branch,
                'product_key': product_key,
                'stage_key': row['stage_key'],
                'role': row['role'],
            }
            row['override'] = override
            row['add_url'] = f"{reverse('admin:core_tatresponsibilityassignment_add')}?{urlencode(params)}"

        scoped_grants = AccessGrant.objects.filter(workflow='tat_tracker', active=True, user__is_active=True)
        if selected_group:
            scoped_grants = scoped_grants.filter(
                models.Q(group_configuration__isnull=True)
                | models.Q(group_configuration=selected_group)
            )
        if branch:
            scoped_grants = scoped_grants.filter(models.Q(branch='') | models.Q(branch__iexact=branch))
        if product_key:
            scoped_grants = scoped_grants.filter(models.Q(product='') | models.Q(product__iexact=product_key))
        else:
            scoped_grants = scoped_grants.filter(product='')
        scoped_grants = scoped_grants.select_related('user', 'group_configuration').order_by(
            'role', 'user__first_name', 'user__last_name', 'user__username',
        )
        connections = {
            row.user_id: row.status for row in TatPrivateAlertConnection.objects.filter(
                user_id__in=[grant.user_id for grant in scoped_grants]
            )
        }
        grant_rows = [{
            'grant': grant,
            'connection_status': connections.get(grant.user_id, TatPrivateAlertConnection.STATUS_UNKNOWN),
        } for grant in scoped_grants]
        issues = configuration_issues(assignments)
        context = {
            **(extra_context or {}),
            'workspace_groups': groups,
            'workspace_group': selected_group,
            'workspace_group_id': selected_group_id,
            'workspace_branches': branches,
            'workspace_branch': branch,
            'workspace_products': products,
            'workspace_product': product_key,
            'responsibility_role_rows': role_rows,
            'responsibility_stage_rows': catalogue,
            'responsibility_grant_rows': grant_rows,
            'responsibility_assignments': scoped_assignments,
            'responsibility_issues': issues,
            'responsibility_issue_count': sum(len(rows) for rows in issues.values()),
            'capability_matrix_url': reverse('admin:core_workflowrolecapability_matrix'),
            'users_url': reverse('admin:auth_user_changelist'),
            'control_center_url': (
                reverse('admin:core_tat_control_center', args=[selected_group.pk])
                if selected_group else ''
            ),
            'register_url': (
                reverse('admin:core_tat_register', args=[selected_group.pk])
                if selected_group else ''
            ),
        }
        # Workspace selectors are presentation controls, not ORM field
        # lookups. Remove them before Django's ChangeList parses query params.
        changelist_query = request.GET.copy()
        for key in ('workspace_group', 'workspace_branch', 'workspace_product'):
            changelist_query.pop(key, None)
        request.GET = changelist_query
        return super().changelist_view(request, extra_context=context)

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


@admin.register(TatResponsibilityEvent)
class TatResponsibilityEventAdmin(GovernedConfigurationAuditAdmin):
    list_display = ('assignment_id_snapshot', 'action', 'actor', 'reason', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('assignment_id_snapshot', 'actor__username', 'reason')
    readonly_fields = [field.name for field in TatResponsibilityEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TatActionTaskRecipientInline(TabularInline):
    model = TatActionTaskRecipient
    extra = 0
    can_delete = False
    fields = (
        'user', 'kind', 'rank', 'threshold_percent', 'inbox_status',
        'routing_generation', 'delivery_state', 'deliver_after', 'delivery_attempts', 'delivered_at',
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TatActionTask)
class TatActionTaskAdmin(GovernedConfigurationAuditAdmin):
    list_display = (
        'case', 'stage_label', 'responsible_role', 'case_revision', 'status',
        'assignment', 'acted_by', 'created_at',
    )
    list_filter = ('status', 'responsible_role', 'stage_key', 'group_configuration', 'created_at')
    search_fields = ('case__case_id', 'case__client_name', 'stage_label', 'responsible_role')
    readonly_fields = [field.name for field in TatActionTask._meta.fields]
    inlines = (TatActionTaskRecipientInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TatTaskRerouteEvent)
class TatTaskRerouteEventAdmin(GovernedConfigurationAuditAdmin):
    list_display = ('task', 'generation_before', 'generation_after', 'actor', 'reason', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('task__case__case_id', 'actor__username', 'reason', 'request_id')
    readonly_fields = [field.name for field in TatTaskRerouteEvent._meta.fields]
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(TatResponsibilityChangePlan)
class TatResponsibilityChangePlanAdmin(GovernedConfigurationAuditAdmin):
    list_display = ('assignment', 'status', 'effective_at', 'created_by', 'created_at', 'applied_at')
    list_filter = ('status', 'effective_at')
    readonly_fields = [field.name for field in TatResponsibilityChangePlan._meta.fields]
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(TatConfigurationEvent)
class TatConfigurationEventAdmin(GovernedConfigurationAuditAdmin):
    list_display = ('action', 'group_configuration', 'actor', 'reason', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('action', 'request_id', 'reason', 'actor__username')
    readonly_fields = [field.name for field in TatConfigurationEvent._meta.fields]
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(TatPrivateAlertConnection)
class TatPrivateAlertConnectionAdmin(GovernedConfigurationAuditAdmin):
    list_display = ('user', 'status', 'connected_at', 'last_success_at', 'last_failure_at', 'updated_at')
    list_filter = ('status', 'updated_at')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    readonly_fields = [field.name for field in TatPrivateAlertConnection._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TatGroupExceptionStatus)
class TatGroupExceptionStatusAdmin(GovernedConfigurationAuditAdmin):
    list_display = (
        'group_configuration', 'responsible_role', 'unresolved_count', 'oldest_task_at',
        'active', 'last_attempt_at',
    )
    list_filter = ('active', 'responsible_role', 'group_configuration')
    search_fields = ('group_configuration__display_name', 'group_configuration__group_id', 'responsible_role')
    readonly_fields = [field.name for field in TatGroupExceptionStatus._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TatNotificationProcessorRun)
class TatNotificationProcessorRunAdmin(GovernedConfigurationAuditAdmin):
    list_display = (
        'started_at', 'status', 'completed_at', 'processed_task_count',
        'retry_recipient_count', 'overdue_recipient_count',
        'unreachable_recipient_count', 'error_code',
    )
    list_filter = ('status', 'started_at', 'completed_at')
    readonly_fields = [field.name for field in TatNotificationProcessorRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TatActionTaskLocator)
class TatActionTaskLocatorAdmin(GovernedConfigurationAuditAdmin):
    list_display = ('task', 'recipient', 'expires_at', 'revoked_at', 'created_at')
    list_filter = ('expires_at', 'revoked_at')
    search_fields = ('task__case__case_id', 'recipient__username')
    exclude = ('token_hash',)
    readonly_fields = [
        field.name for field in TatActionTaskLocator._meta.fields
        if field.name != 'token_hash'
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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

    tat_notification_mode = forms.ChoiceField(
        choices=(
            ('group', 'Existing group alerts'),
            ('shadow', 'Shadow inbox (no Telegram delivery)'),
            ('hybrid', 'Private inbox and Telegram alerts'),
        ),
        required=False,
        initial='group',
        label='TAT notification delivery',
        help_text='Use Shadow to validate responsibility routing before private delivery.',
    )
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
            self.fields['tat_notification_mode'].initial = workflow.get('tat_notification_mode') or 'group'
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
                workflow['tat_notification_mode'] = self.cleaned_data.get('tat_notification_mode') or 'group'
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
                'tat_notification_mode': self.cleaned_data.get('tat_notification_mode') or 'group',
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


@admin.register(WorkflowDataModeState)
class WorkflowDataModeStateAdmin(ModelAdmin):
    """Superuser-only switchboard and entry point for verified pilot cleanup."""

    form = WorkflowDataModeStateForm
    change_form_template = 'admin/core/workflowdatamodestate/change_form.html'
    fieldsets = (
        ('Current creation modes', {'fields': (('spin_mode', 'tat_mode'), 'reason')}),
        ('Protected active cycles', {
            'fields': (
                ('spin_pilot_cycle_id', 'spin_mode_version'),
                ('tat_pilot_cycle_id', 'tat_mode_version'),
                ('active_spin_purge_id', 'active_tat_purge_id'),
                ('updated_by', 'updated_at'),
            ),
        }),
    )
    readonly_fields = (
        'spin_pilot_cycle_id', 'spin_mode_version', 'tat_pilot_cycle_id',
        'tat_mode_version', 'active_spin_purge_id', 'active_tat_purge_id',
        'updated_by', 'updated_at',
    )

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request) and not WorkflowDataModeState.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from core.services.workflow_data_mode import WORKFLOW_SPIN, WORKFLOW_TAT, change_mode

        if not change:
            obj.updated_by = request.user
            super().save_model(request, obj, form, change)
            return
        current = WorkflowDataModeState.objects.get(pk=obj.pk)
        reason = str(form.cleaned_data.get('reason') or '').strip()
        request_base = str(request.headers.get('X-Request-ID') or uuid.uuid4())
        for workflow, field in ((WORKFLOW_SPIN, 'spin_mode'), (WORKFLOW_TAT, 'tat_mode')):
            desired = form.cleaned_data[field]
            if getattr(current, field) != desired:
                change_mode(
                    workflow, desired, actor=request.user, reason=reason,
                    request_id=f'{request_base}:{workflow}',
                )
        obj.refresh_from_db()

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Convert a rare mode-change race into a safe Admin message, never a 500."""
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as exc:
            detail = '; '.join(exc.messages)
            self.message_user(request, detail, messages.ERROR)
            target = request.path if object_id else reverse(
                'admin:core_workflowdatamodestate_changelist'
            )
            return HttpResponseRedirect(target)

    def get_urls(self):
        return [
            path(
                '<path:object_id>/rotate/<str:workflow>/',
                self.admin_site.admin_view(self.rotate_cycle_view),
                name='core_workflowdatamodestate_rotate',
            ),
            path(
                '<path:object_id>/pilot-purge/',
                self.admin_site.admin_view(self.pilot_purge_view),
                name='core_workflowdatamodestate_purge',
            ),
        ] + super().get_urls()

    def change_view(self, request, object_id, form_url='', extra_context=None):
        context = dict(extra_context or {})
        context.update({
            'rotate_spin_url': reverse('admin:core_workflowdatamodestate_rotate', args=[object_id, 'spin']),
            'rotate_tat_url': reverse('admin:core_workflowdatamodestate_rotate', args=[object_id, 'tat_tracker']),
            'pilot_purge_url': reverse('admin:core_workflowdatamodestate_purge', args=[object_id]),
        })
        return super().change_view(request, object_id, form_url, context)

    def rotate_cycle_view(self, request, object_id, workflow):
        if not self.has_module_permission(request):
            raise PermissionDenied
        if workflow not in {'spin', 'tat_tracker'}:
            raise PermissionDenied
        state = WorkflowDataModeState.objects.get(pk=object_id)
        if request.method == 'POST':
            from core.services.workflow_data_mode import rotate_pilot_cycle
            try:
                rotate_pilot_cycle(
                    workflow,
                    actor=request.user,
                    reason=request.POST.get('reason') or '',
                    request_id=str(request.POST.get('request_id') or uuid.uuid4()),
                )
            except ValidationError as exc:
                self.message_user(request, '; '.join(exc.messages), messages.ERROR)
            else:
                self.message_user(
                    request,
                    f'{workflow} now has a new active pilot cycle. The prior cycle is closed and purge-eligible.',
                    messages.SUCCESS,
                )
                return HttpResponseRedirect(reverse('admin:core_workflowdatamodestate_change', args=[state.pk]))
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'state': state,
            'workflow': workflow,
            'title': f'Rotate {workflow} pilot cycle',
            'request_id': str(uuid.uuid4()),
        }
        return TemplateResponse(request, 'admin/core/workflowdatamodestate/rotate.html', context)

    def pilot_purge_view(self, request, object_id):
        if not self.has_module_permission(request):
            raise PermissionDenied
        from core.services.workflow_pilot_purge import (
            acknowledge_sheet_readiness,
            inspect_sheet_readiness,
            preview_purge,
            process_purge,
            start_purge,
        )

        scope = str(request.POST.get('scope') or request.GET.get('scope') or 'spin')
        if scope not in {'spin', 'tat_tracker', 'both'}:
            scope = 'spin'
        if request.method == 'POST':
            action = str(request.POST.get('action') or '')
            try:
                if action == 'acknowledge':
                    acknowledge_sheet_readiness(
                        request.POST.get('workflow') or '',
                        request.POST.get('sheet_id') or '',
                        request.POST.get('sheet_tab') or '',
                        actor=request.user,
                        note=request.POST.get('note') or '',
                    )
                    self.message_user(request, 'Sheet formula/range readiness acknowledged.', messages.SUCCESS)
                elif action == 'start':
                    if str(request.POST.get('confirmation') or '').strip() != 'PURGE CLOSED PILOT DATA':
                        raise ValidationError('Type PURGE CLOSED PILOT DATA exactly to confirm.')
                    run, replayed = start_purge(
                        scope,
                        request.POST.get('manifest_hash') or '',
                        actor=request.user,
                        reason=request.POST.get('reason') or '',
                        request_id=str(request.POST.get('request_id') or uuid.uuid4()),
                    )
                    run = process_purge(run.pk)
                    level = messages.SUCCESS if run.status == 'completed' else messages.WARNING
                    self.message_user(
                        request,
                        f'Pilot purge {run.status}. Deleted {run.progress.get("deleted_records", 0)} database records.',
                        level,
                    )
                elif action == 'retry':
                    run = process_purge(request.POST.get('run_id'))
                    self.message_user(request, f'Purge retry finished with status {run.status}.', messages.SUCCESS if run.status == 'completed' else messages.WARNING)
            except (ValidationError, RuntimeError, ValueError) as exc:
                detail = '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
                self.message_user(request, detail, messages.ERROR)
            return HttpResponseRedirect(
                reverse('admin:core_workflowdatamodestate_purge', args=[object_id]) + f'?scope={scope}'
            )

        preview = preview_purge(scope)
        readiness = []
        for group in preview['sheet_groups']:
            try:
                readiness.append({**group, **inspect_sheet_readiness(
                    group['workflow'], group['sheet_id'], group['sheet_tab'],
                )})
            except RuntimeError as exc:
                readiness.append({**group, 'acknowledged': False, 'error': str(exc)})
        runs = WorkflowPilotPurgeRun.objects.filter(scope__in=[scope, 'both'] if scope != 'both' else ['spin', 'tat_tracker', 'both'])[:20]
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'state': WorkflowDataModeState.objects.get(pk=object_id),
            'title': 'SPIN/TAT pilot data cleanup',
            'scope': scope,
            'preview': preview,
            'readiness': readiness,
            'runs': runs,
            'request_id': str(uuid.uuid4()),
        }
        return TemplateResponse(request, 'admin/core/workflowdatamodestate/purge.html', context)


@admin.register(WorkflowDataModeEvent)
class WorkflowDataModeEventAdmin(ReadOnlyAuditAdmin):
    list_display = ('workflow', 'action', 'old_mode', 'new_mode', 'actor', 'created_at')
    list_filter = ('workflow', 'action', 'created_at')
    search_fields = ('request_id', 'reason')
    readonly_fields = [field.name for field in WorkflowDataModeEvent._meta.fields]


@admin.register(WorkflowPilotFormulaReadiness)
class WorkflowPilotFormulaReadinessAdmin(ReadOnlyAuditAdmin):
    list_display = ('workflow', 'sheet_tab', 'formula_fingerprint', 'acknowledged_by', 'acknowledged_at')
    list_filter = ('workflow', 'acknowledged_at')
    readonly_fields = [field.name for field in WorkflowPilotFormulaReadiness._meta.fields]


@admin.register(WorkflowPilotPurgeRun)
class WorkflowPilotPurgeRunAdmin(ReadOnlyAuditAdmin):
    list_display = ('id', 'scope', 'status', 'requested_by', 'cutoff_at', 'completed_at')
    list_filter = ('scope', 'status', 'created_at')
    readonly_fields = [field.name for field in WorkflowPilotPurgeRun._meta.fields]


@admin.register(TatTrackerCase)
class TatTrackerCaseAdmin(TestDataDeleteAdmin):
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = [
        'case_id', 'data_mode', 'group_id', 'product_label', 'client_name', 'branch',
        'status', 'current_stage', 'is_deleted', 'deleted_at', 'updated_at',
    ]
    list_filter = ['data_mode', 'pilot_cycle_id', 'is_deleted', 'group_id', 'product_key', 'branch', 'status', 'current_stage']
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
    list_display = ('label', 'key', 'active', 'updated_at')
    list_filter = ('active',)
    search_fields = ('label', 'key', 'aliases__alias')
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    exclude = ('default_priority', 'default_sla_hours')

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
    list_display = ('parsed_message', 'category', 'branch_ref', 'revision', 'sync_status')
    list_filter = ('sync_status', 'customer_match_status', 'category', 'branch_ref')
    search_fields = ('parsed_message__message_id', 'parsed_message__customer_name')
    readonly_fields = [field.name for field in ComplaintCaseControl._meta.fields]


@admin.register(ComplaintCaseEvent)
class ComplaintCaseEventAdmin(ReadOnlyAuditAdmin):
    list_display = ('case', 'revision', 'action', 'actor', 'request_id', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('case__parsed_message__message_id', 'actor_label', 'request_id', 'payload_hash')
    readonly_fields = [field.name for field in ComplaintCaseEvent._meta.fields]


@admin.register(ComplaintCaseImportBatch)
class ComplaintCaseImportBatchAdmin(ReadOnlyAuditAdmin):
    list_display = ('created_at', 'group_id', 'initiated_by', 'status', 'created_count', 'matched_count')
    list_filter = ('status', 'group_id', 'created_at')
    search_fields = ('source_telegram_message_id', 'actor_label', 'initiated_by__username')
    readonly_fields = [field.name for field in ComplaintCaseImportBatch._meta.fields]


@admin.register(ComplaintCaseImportItem)
class ComplaintCaseImportItemAdmin(ReadOnlyAuditAdmin):
    list_display = ('batch', 'source_index', 'parsed_message', 'created_at')
    search_fields = ('batch__source_telegram_message_id', 'parsed_message__message_id')
    readonly_fields = [field.name for field in ComplaintCaseImportItem._meta.fields]


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
        'display_label', 'group_id', 'enabled', 'tat_sheet_projection_enabled', 'sheet_name',
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
                ['tat_notification_mode'] + [field_name
                for _product_key, _product_label, field_names in TAT_TARGET_FIELD_GROUPS
                for field_name in field_names
                ]
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
        'request_datetime', 'data_mode', 'request_type', 'customer_name', 'national_id',
        'primary_phone', 'requested_amount', 'import_status', 'requested_by',
    )
    list_filter = ('data_mode', 'pilot_cycle_id', 'request_type', 'import_status', 'source_chat', 'created_at')
    search_fields = (
        'customer_name', 'national_id', 'primary_phone', 'secondary_phone',
        'requested_by', 'raw_message', 'source_message_hash',
    )


@admin.register(SpinBatchReviewItem)
class SpinBatchReviewItemAdmin(ReadOnlyAuditAdmin):
    list_display = ('category', 'data_mode', 'status', 'group_id', 'source_sender', 'source_received_at', 'reviewed_by')
    list_filter = ('data_mode', 'pilot_cycle_id', 'group_id', 'category', 'status', 'created_at')
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
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
    confirmation_phrase = forms.CharField(
        required=False,
        help_text='When establishing the first checker, type APPOINT FIRST CHECKER.',
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


class StaffLifecycleForm(forms.Form):
    action = forms.ChoiceField(choices=StaffLifecycleChangePlan.ACTION_CHOICES)
    target_user = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(), required=False,
        help_text='Required for every action except onboarding.',
    )
    display_name = forms.CharField(max_length=255, required=False)
    login_method = forms.ChoiceField(
        choices=StaffUserCreationForm.base_fields['login_method'].choices,
        required=False,
    )
    telegram_username = forms.CharField(max_length=100, required=False)
    django_username = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    replacement_user = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(), required=False,
        help_text='Required when active TAT responsibilities must move to another staff member.',
    )
    leave_until = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='Temporary leave may cover at most 14 days.',
    )
    leave_from = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='Leave starts immediately when blank, or at this future Nairobi time.',
    )
    delegation_gates = forms.MultipleChoiceField(
        required=False, choices=JawabuApprovalDelegation.GATE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    retire_grants = forms.ModelMultipleChoiceField(
        queryset=AccessGrant.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Selected permanent grants will be retired only after checker approval.',
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))
    request_key = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users = get_user_model().objects.filter(is_superuser=False).order_by('first_name', 'last_name', 'username')
        self.fields['target_user'].queryset = users
        self.fields['replacement_user'].queryset = users.filter(is_active=True)
        target_id = self.data.get('target_user') or self.initial.get('target_user')
        self.fields['retire_grants'].queryset = AccessGrant.objects.filter(user_id=target_id, active=True) if target_id else AccessGrant.objects.none()
        if not self.initial.get('request_key'):
            self.initial['request_key'] = f'lifecycle-{uuid.uuid4()}'

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get('action')
        target = cleaned.get('target_user')
        if action == StaffLifecycleChangePlan.ACTION_ONBOARD:
            if not str(cleaned.get('display_name') or '').strip():
                self.add_error('display_name', 'Enter the staff member’s full name.')
            method = cleaned.get('login_method')
            if method == StaffUserCreationForm.LOGIN_TELEGRAM:
                username = str(cleaned.get('telegram_username') or '').strip().lstrip('@').lower()
                cleaned['telegram_username'] = username
                if not username:
                    self.add_error('telegram_username', 'Enter the enrolled Telegram username.')
                elif UserProfile.objects.filter(telegram_username__iexact=username).exists():
                    self.add_error('telegram_username', 'That Telegram username is already enrolled.')
            elif method == StaffUserCreationForm.LOGIN_DJANGO:
                username = str(cleaned.get('django_username') or '').strip()
                if not username:
                    self.add_error('django_username', 'Enter a Django username.')
                elif get_user_model().objects.filter(username__iexact=username).exists():
                    self.add_error('django_username', 'That Django username already exists.')
                if not cleaned.get('password'):
                    self.add_error('password', 'Enter a password for this Django Admin account.')
            else:
                self.add_error('login_method', 'Choose how this staff member signs in.')
        elif target is None:
            self.add_error('target_user', 'Choose the staff member this plan changes.')
        if target and target.is_superuser:
            self.add_error('target_user', 'God-mode Superuser accounts are outside this workspace.')
        return cleaned


class StaffLifecycleGrantForm(forms.Form):
    include = forms.BooleanField(required=False, initial=False, label='Add this access scope')
    workflow = forms.ChoiceField(choices=AccessGrant.WORKFLOW_CHOICES, required=False)
    role = forms.ChoiceField(
        choices=role_choices(), required=False,
        widget=WorkflowScopedSelect(workflow_map=role_workflow_map()),
    )
    branch = forms.ChoiceField(choices=(('', 'All branches'),), required=False)
    product = forms.ChoiceField(choices=(('', 'All products'),), required=False)
    group_configuration = GroupConfigurationAccessField(
        queryset=GroupSheetConfiguration.objects.none(), required=False,
        empty_label='All compatible groups',
        widget=GroupConfigurationAccessSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configure_access_scope_fields(self)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('include'):
            return cleaned
        try:
            cleaned['role'] = validate_access_scope(
                workflow=cleaned.get('workflow'), role=cleaned.get('role'),
                branch=cleaned.get('branch', ''), product=cleaned.get('product', ''),
                group_configuration=cleaned.get('group_configuration'),
            )
        except ValidationError as exc:
            self.add_error(None, '; '.join(exc.messages))
        return cleaned

    class Media:
        js = ('admin/js/access_grant_inline.js',)


StaffLifecycleGrantFormSet = forms.formset_factory(StaffLifecycleGrantForm, extra=3, max_num=8)


class UnfoldUserAdmin(ModelAdmin, DjangoUserAdmin):
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True
    list_display = ('username', 'email', 'first_name', 'last_name', 'role_tags', 'is_staff', 'is_active')
    inlines = (UserProfileInline,)
    change_list_template = 'admin/auth/user/change_list.html'
    change_form_template = 'admin/auth/user/change_form.html'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('access_grants')

    def changelist_view(self, request, extra_context=None):
        from core.services.access_control import can_approve_access_change

        return super().changelist_view(request, extra_context={
            **(extra_context or {}),
            'can_review_lifecycle': can_approve_access_change(request.user),
        })

    def save_model(self, request, obj, form, change):
        # The lifecycle signal uses this transient actor for compliance
        # attribution and retires all effective access on active -> inactive.
        obj._access_retirement_actor = request.user
        return super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj:
            readonly.extend(['is_active', 'is_staff', 'is_superuser'])
        return tuple(dict.fromkeys(readonly))

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
        return HttpResponseRedirect(reverse('admin:auth_user_staff_lifecycle'))

    def get_urls(self):
        custom_urls = [
            path(
                'add-staff/',
                self.admin_site.admin_view(self.staff_lifecycle_view),
                name='auth_user_add_staff',
            ),
            path(
                'staff-lifecycle/', self.admin_site.admin_view(self.staff_lifecycle_view),
                name='auth_user_staff_lifecycle',
            ),
            path(
                'staff-lifecycle/<uuid:plan_id>/', self.admin_site.admin_view(self.staff_lifecycle_plan_view),
                name='auth_user_staff_lifecycle_plan',
            ),
            path(
                '<int:object_id>/telegram-activation/', self.admin_site.admin_view(self.telegram_activation_view),
                name='auth_user_telegram_activation',
            ),
            path('<int:object_id>/request-access/', self.admin_site.admin_view(self.request_access_view), name='auth_user_request_access'),
            path('<int:object_id>/emergency-access/', self.admin_site.admin_view(self.emergency_access_view), name='auth_user_emergency_access'),
            path('<int:object_id>/effective-access/', self.admin_site.admin_view(self.effective_access_view), name='auth_user_effective_access'),
            path('<int:object_id>/appoint-access-checker/', self.admin_site.admin_view(self.appoint_access_checker_view), name='auth_user_appoint_access_checker'),
            path('<int:object_id>/revoke-access-checker/', self.admin_site.admin_view(self.revoke_access_checker_view), name='auth_user_revoke_access_checker'),
        ]
        return custom_urls + super().get_urls()

    def staff_lifecycle_view(self, request):
        """Create one durable, independently reviewed staff lifecycle plan."""
        from core.services.access_control import approver_users, can_approve_access_change
        from core.services.staff_lifecycle import create_lifecycle_plan

        is_superuser = bool(request.user.is_active and request.user.is_superuser)
        is_checker = can_approve_access_change(request.user)
        if not request.user.is_active or not (is_superuser or is_checker):
            raise PermissionDenied
        if request.method == 'POST' and not is_superuser:
            raise PermissionDenied
        form = StaffLifecycleForm(
            request.POST or None, initial=request.GET.dict() if request.method == 'GET' else None,
        ) if is_superuser else None
        grant_formset = StaffLifecycleGrantFormSet(
            request.POST or None, prefix='grants',
        ) if is_superuser else None
        if request.method == 'POST' and form.is_valid() and grant_formset.is_valid():
            if not approver_users().exclude(pk=request.user.pk).exists():
                form.add_error(None, 'Appoint an independent Access Control Checker before submitting lifecycle changes.')
            else:
                data = form.cleaned_data
                target = data.get('target_user')
                new_grants = [
                    grant_form.cleaned_data for grant_form in grant_formset
                    if grant_form.cleaned_data and grant_form.cleaned_data.get('include')
                ]
                identity = {}
                try:
                    with transaction.atomic():
                        if data['action'] == StaffLifecycleChangePlan.ACTION_ONBOARD:
                            target, identity = self._create_pending_staff_shell(data)
                        retired_ids = {str(pk) for pk in data.get('retire_grants', []).values_list('pk', flat=True)}
                        desired = [
                            {
                                'workflow': row.workflow, 'role': row.role,
                                'branch': row.branch, 'product': row.product,
                                'group_configuration_id': row.group_configuration_id,
                            }
                            for row in AccessGrant.objects.filter(user=target, active=True)
                            if str(row.pk) not in retired_ids
                        ]
                        desired.extend(new_grants)
                        plan = create_lifecycle_plan(
                            requester=request.user, target_user=target, action=data['action'],
                            reason=data['reason'], desired_grants=desired,
                            replacement_user=data.get('replacement_user'), leave_until=data.get('leave_until'),
                            leave_from=data.get('leave_from'),
                            delegation_gates=data.get('delegation_gates'), request_key=data.get('request_key'),
                            identity=identity,
                        )
                except (PermissionDenied, ValidationError, IntegrityError) as exc:
                    form.add_error(None, '; '.join(getattr(exc, 'messages', [str(exc)])))
                else:
                    messages.success(request, 'Lifecycle plan submitted for independent checker approval.')
                    return HttpResponseRedirect(reverse('admin:auth_user_staff_lifecycle_plan', args=[plan.pk]))
        plans = StaffLifecycleChangePlan.objects.select_related('target_user', 'requested_by', 'reviewed_by')
        if not is_superuser:
            plans = plans.filter(status=StaffLifecycleChangePlan.STATUS_PENDING).exclude(
                models.Q(requested_by=request.user) | models.Q(target_user=request.user)
            )
        plans = plans[:50]
        return TemplateResponse(request, 'admin/auth/user/staff_lifecycle.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Staff lifecycle workspace', 'form': form,
            'grant_formset': grant_formset, 'plans': plans,
            'has_independent_checker': approver_users().exclude(pk=request.user.pk).exists(),
            'is_superuser_workspace': is_superuser,
        })

    @staticmethod
    def _create_pending_staff_shell(data):
        User = get_user_model()
        telegram_username = str(data.get('telegram_username') or '')
        login_method = data.get('login_method')
        if login_method == StaffUserCreationForm.LOGIN_TELEGRAM:
            safe_username = re.sub(r'[^a-z0-9_]', '_', telegram_username)[:100]
            username = f'tg_pending_{safe_username}'
            if User.objects.filter(username=username).exists():
                username = f'{username}_{uuid.uuid4().hex[:8]}'
        else:
            username = str(data.get('django_username') or '').strip()
        name_parts = str(data.get('display_name') or '').strip().split(None, 1)
        user = User(
            username=username, first_name=name_parts[0] if name_parts else '',
            last_name=name_parts[1] if len(name_parts) > 1 else '',
            email=data.get('email', ''), is_active=False, is_staff=False,
        )
        if login_method == StaffUserCreationForm.LOGIN_DJANGO:
            user.set_password(data['password'])
        else:
            user.set_unusable_password()
        user.save()
        UserProfile.objects.create(user=user, telegram_username=telegram_username)
        return user, {
            'login_method': login_method,
            'django_admin_login': login_method == StaffUserCreationForm.LOGIN_DJANGO,
            'telegram_username': telegram_username,
        }

    def staff_lifecycle_plan_view(self, request, plan_id):
        from core.services.access_control import can_approve_access_change
        from core.services.staff_lifecycle import approve_lifecycle_plan, reject_lifecycle_plan

        plan = StaffLifecycleChangePlan.objects.select_related(
            'target_user', 'requested_by', 'reviewed_by',
        ).filter(pk=plan_id).first()
        if plan is None or not (
            request.user.is_active and (request.user.is_superuser or can_approve_access_change(request.user))
        ):
            raise PermissionDenied
        if request.method == 'POST':
            try:
                if 'approve_plan' in request.POST:
                    plan = approve_lifecycle_plan(
                        plan_id=plan.pk, approver=request.user,
                        review_comment=str(request.POST.get('review_comment') or ''),
                    )
                    if plan.status == plan.STATUS_STALE:
                        messages.warning(request, 'The plan is stale because access or routing changed. Create a fresh plan.')
                    elif plan.status == plan.STATUS_SCHEDULED:
                        messages.success(request, 'The complete plan was approved and will apply at its scheduled start time after revalidation.')
                    else:
                        messages.success(request, 'The complete lifecycle plan was approved and applied atomically.')
                elif 'reject_plan' in request.POST:
                    plan = reject_lifecycle_plan(
                        plan_id=plan.pk, approver=request.user,
                        review_comment=str(request.POST.get('review_comment') or ''),
                    )
                    messages.info(request, 'The lifecycle plan was rejected without changing live access.')
            except (PermissionDenied, ValidationError, ValueError) as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            return HttpResponseRedirect(reverse('admin:auth_user_staff_lifecycle_plan', args=[plan.pk]))
        can_review = bool(
            plan.status == plan.STATUS_PENDING
            and can_approve_access_change(request.user)
            and plan.requested_by_id != request.user.pk
            and plan.target_user_id != request.user.pk
        )
        return TemplateResponse(request, 'admin/auth/user/staff_lifecycle_plan.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'{plan.get_action_display()}: {plan.target_user}',
            'plan': plan, 'can_review': can_review,
        })

    def telegram_activation_view(self, request, object_id):
        from core.services.staff_lifecycle import generate_telegram_activation

        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        user = self.get_object(request, object_id)
        if user is None:
            raise PermissionDenied
        activation_code = ''
        if request.method == 'POST':
            try:
                _challenge, activation_code = generate_telegram_activation(user=user, actor=request.user)
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                messages.warning(request, 'The activation code is shown once. Give it only to the intended staff member.')
        return TemplateResponse(request, 'admin/auth/user/telegram_activation.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Telegram activation: {user}', 'target_user': user,
            'activation_code': activation_code,
        })

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
                    confirmation_phrase=form.cleaned_data.get('confirmation_phrase', ''),
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
        try:
            return super().changeform_view(request, object_id, form_url, context)
        except Exception as exc:
            # Form.clean handles normal conflicts. This catches a packet change
            # racing with the final save so a recoverable configuration issue
            # is still shown as an Admin message rather than a server error.
            from core.services.origination_templates import OriginationTemplateError
            if not isinstance(exc, (OriginationTemplateError, ValidationError)):
                raise
            logger.warning(
                'Origination document assignment was rejected: %s', exc,
                extra={'user_id': request.user.pk, 'object_id': object_id},
            )
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

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
                status=OriginationDocumentTemplate.STATUS_ACTIVE,
                published_configuration_revision__isnull=False,
            ).order_by('name', '-version')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        if not change:
            from core.services.origination_templates import attach_shared_document_template
            assignment = attach_shared_document_template(
                product_definition=obj.product_definition,
                template=obj.template,
                inclusion_mode=obj.inclusion_mode,
                display_order=obj.display_order,
                officer_selectable=obj.officer_selectable,
                default_selected=obj.default_selected,
                applicability_rule=obj.applicability_rule or {},
                actor=request.user,
                version_policy=obj.version_policy,
            )
            obj.pk = assignment.pk
            obj._state.adding = False
            return
        obj.full_clean()
        super().save_model(request, obj, form, change)
        OriginationProductDefinitionEvent.objects.create(
            product_definition=obj.product_definition,
            action='shared_document_assignment_updated',
            actor=request.user,
            metadata={
                'assignment_id': str(obj.pk), 'template_id': str(obj.template_id),
                'document_key': obj.document_key, 'inclusion_mode': obj.inclusion_mode,
                'version_policy': obj.version_policy,
            },
        )

    def response_add(self, request, obj, post_url_continue=None):
        if request.GET.get('template') and obj.product_definition_id:
            self.message_user(
                request,
                'Document assignment saved. Review the product Document packet, then publish '
                'the product when its readiness checks are clear.',
                level=messages.SUCCESS,
            )
            return HttpResponseRedirect(reverse(
                'admin:core_originationproductdefinition_change',
                args=[obj.product_definition_id],
            ))
        return super().response_add(request, obj, post_url_continue)

    def delete_model(self, request, obj):
        product = obj.product_definition
        metadata = {'assignment_id': str(obj.pk), 'template_id': str(obj.template_id), 'document_key': obj.document_key}
        super().delete_model(request, obj)
        if obj.template.document_role == OriginationDocumentTemplate.ROLE_PRIMARY:
            product.document_template_name = ''
            product.document_template_sha256 = ''
            product.document_template_version = product.version
            product.save(update_fields=[
                'document_template_name', 'document_template_sha256',
                'document_template_version', 'updated_at',
            ])
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

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = dict(extra_context or {})
        obj = self.get_object(request, object_id) if object_id else None
        if (
            obj and request.user.is_active and request.user.is_superuser
            and getattr(settings, 'ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED', False)
        ):
            context['origination_product_family_purge_url'] = reverse(
                'admin:core_originationproductdefinition_family_purge',
                args=[obj.product_key],
            )
        return super().changeform_view(request, object_id, form_url, context)


    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'setup/',
                self.admin_site.admin_view(self.setup_dashboard_view),
                name='core_origination_setup_dashboard',
            ),
            path(
                'setup/start/',
                self.admin_site.admin_view(self.setup_start_view),
                name='core_origination_setup_start',
            ),
            path(
                'setup/<path:object_id>/overview/',
                self.admin_site.admin_view(self.setup_detail_view),
                name='core_origination_setup_detail',
            ),
            path(
                'setup/<path:object_id>/revise/',
                self.admin_site.admin_view(self.setup_revise_view),
                name='core_origination_setup_revise',
            ),
            path(
                'setup/<path:object_id>/<slug:step_key>/',
                self.admin_site.admin_view(self.setup_step_view),
                name='core_origination_setup_step',
            ),
            path(
                'setup/<path:object_id>/',
                self.admin_site.admin_view(self.setup_workspace_view),
                name='core_origination_setup_workspace',
            ),
            path(
                'product-family/<path:product_key>/god-mode-purge/',
                self.admin_site.admin_view(self.product_family_purge_view),
                name='core_originationproductdefinition_family_purge',
            ),
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
                '<path:object_id>/publish-assigned-primary/',
                self.admin_site.admin_view(self.publish_assigned_primary_view),
                name='core_originationproductdefinition_publish_assigned_primary',
            ),
            path(
                '<path:object_id>/upgrade-commercial-terms/',
                self.admin_site.admin_view(self.upgrade_commercial_terms_view),
                name='core_originationproductdefinition_upgrade_commercial_terms',
            ),
            path(
                '<path:object_id>/document-packet/<path:assignment_id>/remove/',
                self.admin_site.admin_view(self.remove_shared_document_from_packet_view),
                name='core_originationproductdefinition_packet_remove_shared',
            ),
            path(
                '<path:object_id>/document-packet/<path:assignment_id>/upgrade-primary/',
                self.admin_site.admin_view(self.upgrade_shared_primary_view),
                name='core_originationproductdefinition_packet_upgrade_primary',
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

    def setup_dashboard_view(self, request):
        from core.origination_setup_admin import dashboard_view
        return dashboard_view(self, request)

    def setup_start_view(self, request):
        from core.origination_setup_admin import start_view
        return start_view(self, request)

    def setup_detail_view(self, request, object_id):
        from core.origination_setup_admin import detail_view
        return detail_view(self, request, object_id)

    def setup_workspace_view(self, request, object_id):
        from core.origination_setup_admin import workspace_view
        return workspace_view(self, request, object_id)

    def setup_revise_view(self, request, object_id):
        from core.origination_setup_admin import revise_view
        return revise_view(self, request, object_id)

    def setup_step_view(self, request, object_id, step_key):
        from core.origination_setup_admin import step_view
        return step_view(self, request, object_id, step_key)

    def product_family_purge_view(self, request, product_key):
        if (
            not getattr(settings, 'ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED', False)
            or not request.user.is_active
            or not request.user.is_superuser
        ):
            raise PermissionDenied
        from core.services.origination_god_mode import (
            OriginationGodModeError,
            preview_product_family_purge,
            purge_origination_product_family,
        )
        family = OriginationProductDefinition.objects.filter(product_key=product_key).order_by('-version')
        latest = family.first()
        if not latest and request.method != 'POST':
            return HttpResponse(status=404)
        confirmation_text = f'PURGE PRODUCT FAMILY {product_key}'
        error = ''
        request_id = str(request.POST.get('request_id') or uuid.uuid4())
        if request.method == 'POST':
            if str(request.POST.get('confirmation') or '').strip() != confirmation_text:
                error = f'Type exactly: {confirmation_text}'
            elif not str(request.POST.get('reason') or '').strip():
                error = 'Provide a reason for this permanent purge.'
            else:
                try:
                    counts, replayed = purge_origination_product_family(
                        product_key=product_key,
                        actor=request.user,
                        reason=request.POST.get('reason') or '',
                        request_id=request_id,
                    )
                except OriginationGodModeError as exc:
                    error = str(exc)
                except Exception:
                    logger.exception('Origination product-family purge failed: key=%s actor_id=%s', product_key, request.user.pk)
                    error = 'The product-family purge failed. No database changes were committed.'
                else:
                    summary = ', '.join(f'{count} {label}' for label, count in counts.items()) or 'the product family'
                    self.message_user(
                        request,
                        f'{"Replayed" if replayed else "Completed"} Origination family purge: {summary}. Global Product records and Drive files were untouched.',
                        messages.WARNING,
                    )
                    return HttpResponseRedirect(reverse('admin:core_originationproductdefinition_changelist'))
        elif request.method != 'GET':
            response = HttpResponse(status=405)
            response['Allow'] = 'GET, POST'
            return response
        return TemplateResponse(request, 'admin/core/origination_god_mode/family_purge.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Purge Origination product family: {product_key}',
            'original': latest,
            'product_key': product_key,
            'confirmation_text': confirmation_text,
            'impact': preview_product_family_purge(product_key),
            'error': error,
            'request_id': request_id,
            'back_url': (
                reverse('admin:core_originationproductdefinition_change', args=[latest.pk])
                if latest else reverse('admin:core_originationproductdefinition_changelist')
            ),
        })

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
        if (
            product is not None
            and product.lifecycle_status != product.STATUS_DRAFT
            and request.method == 'POST'
        ):
            self.message_user(
                request,
                'Published product versions are read-only. Create or open the editable next version.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse(
                'admin:core_originationproductdefinition_change', args=[product.pk],
            ))
        template = None
        failed_template = None
        existing_successor = None
        shared_assignments = []
        shared_primary = None
        packet_readiness = []
        available_shared_documents = []
        shared_document_empty_reason = ''
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
            from core.services.origination_templates import (
                latest_compatible_assignment_template, resolve_assignment_template,
            )
            shared_assignments = [
                {
                    'assignment': assignment,
                    'resolved_template': resolve_assignment_template(assignment),
                    'upgrade_template': (
                        latest_compatible_assignment_template(assignment)
                        if assignment.template.document_role == OriginationDocumentTemplate.ROLE_PRIMARY
                        and assignment.version_policy == assignment.VERSION_PINNED
                        else None
                    ),
                }
                for assignment in product.document_assignments.select_related(
                    'template', 'template__published_configuration_revision',
                ).order_by('display_order', 'document_key')
            ]
            shared_primary = next((
                item['resolved_template'] for item in shared_assignments
                if item['resolved_template']
                and item['resolved_template'].document_role == OriginationDocumentTemplate.ROLE_PRIMARY
            ), None)
            if not template and shared_primary:
                template = shared_primary
            packet_readiness.append({
                'label': 'Main LAF',
                'ready': bool((template and template.drive_file_id) or shared_primary),
                'detail': (
                    f'Uses reusable {shared_primary.name} v{shared_primary.version}' if shared_primary
                    else 'Ready to align' if template and template.drive_file_id
                    else 'Upload or assign the primary LAF PDF'
                ),
            })
            packet_readiness.extend({
                'label': item['assignment'].name,
                'ready': bool(item['resolved_template']),
                'detail': (
                    f"Uses shared template v{item['resolved_template'].version}"
                    if item['resolved_template'] else 'No compatible published version is available'
                ),
            } for item in shared_assignments)
            if product.lifecycle_status == product.STATUS_DRAFT:
                attached_types = {
                    item['assignment'].template.document_type for item in shared_assignments
                }
                available_shared_documents = list(
                    OriginationDocumentTemplate.objects.filter(
                        product_definition__isnull=True,
                        status=OriginationDocumentTemplate.STATUS_ACTIVE,
                        published_configuration_revision__isnull=False,
                    ).exclude(document_type__in=attached_types).order_by('name', '-version')
                )
                if not available_shared_documents:
                    published_global = OriginationDocumentTemplate.objects.filter(
                        product_definition__isnull=True,
                        status=OriginationDocumentTemplate.STATUS_ACTIVE,
                        published_configuration_revision__isnull=False,
                    )
                    unpublished_global = OriginationDocumentTemplate.objects.filter(
                        product_definition__isnull=True,
                        status=OriginationDocumentTemplate.STATUS_READY,
                    )
                    if published_global.exists():
                        shared_document_empty_reason = (
                            'Every eligible reusable document is already attached to this product.'
                        )
                    elif unpublished_global.exists():
                        shared_document_empty_reason = (
                            'Reusable documents exist, but they must be calibrated and published before attachment.'
                        )
                    else:
                        shared_document_empty_reason = (
                            'No published reusable document is available yet. Create and publish one in the reusable library.'
                        )
            else:
                shared_document_empty_reason = (
                    'Published product versions are immutable. Create or open an editable next version to change this packet.'
                )
        commercial_contract_version = 0
        if product and product.product_version_id:
            from core.services.origination_commercial_terms import (
                commercial_contract_version as schema_commercial_contract_version,
            )
            commercial_contract_version = schema_commercial_contract_version(product.form_schema) or 1
        context = {
            **(extra_context or {}),
            **({
                'show_save': False,
                'show_save_and_continue': False,
                'show_save_and_add_another': False,
                'show_delete': False,
            } if product and product.lifecycle_status != product.STATUS_DRAFT else {}),
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
            'origination_available_shared_documents': available_shared_documents,
            'origination_shared_document_empty_reason': shared_document_empty_reason,
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
            'origination_publish_assigned_primary_url': (
                reverse(
                    'admin:core_originationproductdefinition_publish_assigned_primary',
                    args=[product.pk],
                ) if product and product.lifecycle_status == product.STATUS_DRAFT and shared_primary else ''
            ),
            'origination_commercial_contract_version': commercial_contract_version,
            'origination_upgrade_commercial_terms_url': (
                reverse(
                    'admin:core_originationproductdefinition_upgrade_commercial_terms',
                    args=[product.pk],
                )
                if product and product.product_version_id
                and product.lifecycle_status == product.STATUS_DRAFT
                and commercial_contract_version < 2
                else ''
            ),
            'origination_assignment_add_url': (
                reverse('admin:core_originationproductdocumentassignment_add')
                + f'?product_definition={product.pk}' if product and product.lifecycle_status == product.STATUS_DRAFT else ''
            ),
            'origination_shared_library_url': reverse('admin:core_originationdocumenttemplate_changelist') + '?product_definition__isnull=True',
        }
        return super().changeform_view(request, object_id, form_url, context)

    def upgrade_commercial_terms_view(self, request, object_id):
        if request.method != 'POST':
            response = HttpResponse(status=405)
            response['Allow'] = 'POST'
            return response
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        product_url = reverse('admin:core_originationproductdefinition_change', args=[object_id])
        try:
            with transaction.atomic():
                product = OriginationProductDefinition.objects.select_for_update().filter(pk=object_id).first()
                if not product:
                    return HttpResponse(status=404)
                if product.lifecycle_status != product.STATUS_DRAFT:
                    raise ValidationError('Published product versions require an editable successor before Commercial Terms can change.')
                if not product.product_version_id:
                    raise ValidationError('This product is not linked to a governed ProductVersion.')
                from core.services.origination_commercial_terms import (
                    COMMERCIAL_CONTRACT_VERSION, ensure_commercial_catalogue,
                    commercial_contract_version, merge_commercial_contract,
                )
                previous = commercial_contract_version(product.form_schema) or 1
                fields = ensure_commercial_catalogue(actor=request.user)
                upgraded = merge_commercial_contract(product.form_schema, fields=fields)
                if upgraded != product.form_schema:
                    product.form_schema = upgraded
                    product.save(update_fields=['form_schema', 'updated_at'])
                    product.document_templates.filter(
                        document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                        status__in=[OriginationDocumentTemplate.STATUS_READY, OriginationDocumentTemplate.STATUS_UPLOAD_FAILED],
                    ).update(form_schema=upgraded)
                    OriginationProductDefinitionEvent.objects.create(
                        product_definition=product, action='commercial_contract_upgraded',
                        actor=request.user, metadata={
                            'from_version': previous,
                            'contract_version': COMMERCIAL_CONTRACT_VERSION,
                            'source': 'django_admin',
                        },
                    )
        except (ValidationError, ValueError) as exc:
            error_message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            self.message_user(request, error_message, level=messages.ERROR)
        else:
            self.message_user(
                request,
                'Commercial Terms upgraded. Officers now enter only loan amount and repayment tenor; policy values remain calculated.',
                level=messages.SUCCESS,
            )
        return HttpResponseRedirect(product_url)

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
                status=OriginationDocumentTemplate.STATUS_ACTIVE,
                published_configuration_revision__isnull=False,
            ).first()
            if not template:
                raise ValidationError('Choose a published reusable document.')
            next_order = (
                product.document_assignments.aggregate(models.Max('display_order'))['display_order__max']
                or 0
            ) + 10
            from core.services.origination_templates import attach_shared_document_template
            assignment = attach_shared_document_template(
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
            from core.services.origination_templates import remove_shared_document_template
            removed = remove_shared_document_template(
                product_definition=product, assignment_id=assignment_id, actor=request.user,
            )
        except PermissionDenied:
            raise
        except Exception as exc:
            return self._packet_error_response(exc)
        return JsonResponse({'ok': True, 'removed': removed})

    def upgrade_shared_primary_view(self, request, object_id, assignment_id):
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            product = self._draft_packet_product(request, object_id)
            if not product:
                return JsonResponse({'ok': False, 'error': 'Product definition not found.'}, status=404)
            from core.services.origination_templates import upgrade_pinned_primary_assignment
            assignment, upgraded = upgrade_pinned_primary_assignment(
                product_definition=product, assignment_id=assignment_id, actor=request.user,
            )
        except PermissionDenied:
            raise
        except Exception as exc:
            return self._packet_error_response(exc)
        return JsonResponse({
            'ok': True, 'upgraded': upgraded,
            'assignment_id': str(assignment.pk),
            'version': assignment.template.version,
        })

    def publish_assigned_primary_view(self, request, object_id):
        if request.method != 'POST':
            response = JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
            response['Allow'] = 'POST'
            return response
        product_url = reverse('admin:core_originationproductdefinition_change', args=[object_id])
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        from core.services.origination_templates import OriginationTemplateError
        try:
            product = self._draft_packet_product(request, object_id)
            if not product:
                return HttpResponse(status=404)
            from core.services.origination_templates import (
                publish_product_template, resolve_assignment_template,
            )
            primary_assignments = list(product.document_assignments.select_related(
                'template', 'template__published_configuration_revision',
            ).filter(template__document_role=OriginationDocumentTemplate.ROLE_PRIMARY))
            if len(primary_assignments) != 1:
                raise ValidationError('Assign exactly one reusable primary LAF before publishing.')
            primary = resolve_assignment_template(primary_assignments[0])
            if not primary or not primary.published_configuration_revision_id:
                raise ValidationError('The reusable primary LAF must be calibrated and published first.')
            published_product, _template, _revision = publish_product_template(
                template=primary,
                revision=primary.published_configuration_revision.revision,
                product_definition=product,
                actor=request.user,
                client_request_id=str(request.POST.get('request_id') or ''),
            )
            published_product.refresh_from_db()
            if not (
                published_product.is_active
                and published_product.lifecycle_status == published_product.STATUS_PUBLISHED
            ):
                raise OriginationTemplateError(
                    'Publication did not activate the product. No success was reported; retry or inspect the audit log.',
                )
        except PermissionDenied:
            raise
        except Exception as exc:
            is_validation_error = isinstance(exc, (OriginationTemplateError, ValidationError))
            if is_validation_error:
                error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            else:
                logger.exception('Publishing product with assigned primary LAF failed.')
                error = 'The product could not be published. No partial publication was committed.'
            if is_ajax:
                return JsonResponse(
                    {'ok': False, 'error': error},
                    status=400 if is_validation_error else 500,
                )
            self.message_user(request, error, level=messages.ERROR)
            return HttpResponseRedirect(product_url)
        success = (
            f'{published_product.name} version {published_product.version} '
            'is published and active for new applications.'
        )
        self.message_user(request, success, level=messages.SUCCESS)
        if is_ajax:
            return JsonResponse({
                'ok': True,
                'message': success,
                'redirect_url': reverse('admin:core_originationproductdefinition_changelist'),
                'product_id': str(published_product.pk),
                'is_active': bool(published_product.is_active),
                'lifecycle_status': published_product.lifecycle_status,
            })
        return HttpResponseRedirect(product_url)

    def supporting_document_setup_view(self, request, object_id):
        """Single product-first entry point for shared packet documents."""
        if not request.user.is_superuser:
            raise PermissionDenied
        product = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not product:
            return HttpResponse(status=404)
        product_url = reverse('admin:core_originationproductdefinition_change', args=[product.pk])
        setup_token = str(
            request.POST.get('setup_return') or request.GET.get('setup_return') or ''
        ).strip()
        setup_return_url = ''
        if setup_token:
            try:
                from core.services.origination_setup import resolve_return_token
                setup_target = resolve_return_token(setup_token)
                if str(setup_target['definition_id']) != str(product.pk):
                    raise ValidationError('The return target belongs to another product.')
                setup_return_url = reverse(
                    'admin:core_origination_setup_step',
                    args=[product.pk, setup_target['step_key']],
                )
            except (signing.BadSignature, ValidationError, ValueError):
                setup_token = ''
                self.message_user(
                    request,
                    'The setup return link expired. You can still configure the document safely.',
                    level=messages.WARNING,
                )
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
                    return HttpResponseRedirect(setup_return_url or product_url)
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
                    calibration_url = reverse(
                        'admin:core_originationdocumenttemplate_calibrate', args=[template.pk],
                    )
                    if setup_token:
                        calibration_url += '?' + urlencode({'setup_return': setup_token})
                    return HttpResponseRedirect(calibration_url)
        from core.services.loan_origination import SIGNER_ROLE_CATALOG
        from core.services.origination_fields import catalogue_for_product
        return TemplateResponse(request, 'admin/core/originationproductdefinition/supporting_document_setup.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Add supporting document: {product}',
            'product': product,
            'product_url': product_url,
            'setup_return_url': setup_return_url,
            'setup_return_token': setup_token,
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
            from core.services.origination_templates import resolve_assignment_template
            assignment = obj.document_assignments.select_related(
                'template', 'template__published_configuration_revision',
            ).filter(template__document_role=OriginationDocumentTemplate.ROLE_PRIMARY).first()
            template = resolve_assignment_template(assignment) if assignment else None
            if (
                assignment
                and assignment.version_policy == assignment.VERSION_LATEST_COMPATIBLE
            ):
                return 'Review main LAF version policy'
        if not template:
            failed = obj.document_templates.filter(
                status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
            ).exists()
            if failed:
                return 'Upload failed'
            return 'Main LAF missing'
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
        if obj.product_version_id:
            from core.services.origination_commercial_terms import (
                ensure_commercial_catalogue, merge_commercial_contract,
            )
            commercial_fields = ensure_commercial_catalogue(actor=request.user)
            obj.form_schema = merge_commercial_contract(
                obj.form_schema, fields=commercial_fields,
            )
        from core.services.loan_origination import validate_product_form_contract
        validate_product_form_contract(obj.form_schema, obj.signer_rules)
        super().save_model(request, obj, form, change)
        from core.services.origination_fields import bind_compatible_schema_fields
        bind_compatible_schema_fields(obj, create_issues=True)
        OriginationProductDefinitionEvent.objects.create(
            product_definition=obj, action='draft_updated' if change else 'created',
            actor=request.user, metadata={'version': obj.version},
        )
        reusable_primary = form.cleaned_data.get('reusable_primary_template')
        if (
            form.cleaned_data.get('main_laf_source') == form.LAF_SOURCE_LIBRARY
            and reusable_primary
        ):
            from core.services.origination_templates import attach_shared_document_template
            assignment = attach_shared_document_template(
                product_definition=obj,
                template=reusable_primary,
                inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
                display_order=0,
                officer_selectable=False,
                default_selected=False,
                applicability_rule={},
                actor=request.user,
                version_policy=OriginationProductDocumentAssignment.VERSION_PINNED,
            )
            messages.success(
                request,
                f'{assignment.name} v{assignment.template.version} is pinned as this product version\'s main LAF.',
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
        from core.services.origination_templates import (
            OriginationTemplateError, clone_product_version,
        )
        try:
            clone = clone_product_version(queryset.first(), actor=request.user)
        except (OriginationTemplateError, ValidationError) as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return None
        except DatabaseError:
            logger.exception('Origination product successor creation failed.')
            self.message_user(
                request,
                'The editable version could not be created safely. Reload and try again.',
                level=messages.ERROR,
            )
            return None
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
        from core.services.origination_templates import (
            OriginationTemplateError, clone_product_version,
        )
        try:
            successor = clone_product_version(source, actor=request.user)
        except (OriginationTemplateError, ValidationError) as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(reverse(
                'admin:core_originationproductdefinition_change', args=[source.pk],
            ))
        except DatabaseError:
            logger.exception(
                'Origination product successor creation failed.',
                extra={'product_definition_id': str(source.pk), 'user_id': request.user.pk},
            )
            self.message_user(
                request,
                'The editable version could not be created safely. Reload and try again.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse(
                'admin:core_originationproductdefinition_change', args=[source.pk],
            ))
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
        'native_consent_policy', 'native_consent_attestation_reference',
        'native_consent_attested_by', 'native_consent_attested_at',
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
                        'Upload a product-owned PDF or add it to the reusable template library. '
                        'Choose the reviewed Generic Jawabu LAF field setup when applicable; '
                        'otherwise define fields visually after upload. The alignment builder opens automatically.'
                    ),
                    'fields': (
                        'product_definition', 'reusable_family', 'schema_preset',
                        ('name', 'document_role'),
                        ('inclusion_mode', 'display_order'),
                        ('officer_selectable', 'default_selected'),
                        ('condition_field', 'condition_operator'), 'condition_value',
                        'applicability_rule', 'form_schema', 'signer_rules', 'pdf_file',
                        'native_consent_policy', 'native_consent_attestation_reference',
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
            ('Consent clause', {
                'description': (
                    'If compliance attested that the governed clause is embedded in this exact source PDF, '
                    'conditional packets use it directly. Otherwise a governed first page is added before hashing.'
                ),
                'fields': (
                    'native_consent_policy', 'native_consent_attestation_reference',
                    ('native_consent_attested_by', 'native_consent_attested_at'),
                ),
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
            if original and original.product_definition_id is None:
                editable = OriginationDocumentTemplate.objects.filter(
                    product_definition__isnull=True,
                    document_type=original.document_type,
                    status=OriginationDocumentTemplate.STATUS_READY,
                    version__gt=original.version,
                ).order_by('-version').first()
                current = OriginationDocumentTemplate.objects.filter(
                    product_definition__isnull=True,
                    document_type=original.document_type,
                    status=OriginationDocumentTemplate.STATUS_ACTIVE,
                ).order_by('-version').first()
                context['origination_existing_editable_template'] = editable
                context['origination_current_family_template'] = current
                if original.status == original.STATUS_ACTIVE:
                    context['origination_create_editable_template_url'] = reverse(
                        'admin:core_originationdocumenttemplate_create_editable_version',
                        args=[original.pk],
                    )
                context['origination_next_family_version_url'] = (
                    reverse('admin:core_originationdocumenttemplate_add') + '?' + urlencode({
                        'reusable_family': original.document_type,
                        'name': original.name,
                    })
                )
                context['origination_attach_to_product_url'] = (
                    reverse('admin:core_originationproductdocumentassignment_add')
                    + '?' + urlencode({'template': original.pk})
                )
            elif original and original.product_definition_id:
                product = original.product_definition
                if product.lifecycle_status == product.STATUS_PUBLISHED:
                    context['origination_create_editable_product_url'] = reverse(
                        'admin:core_originationproductdefinition_create_next_version',
                        args=[product.pk],
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
            path(
                '<path:object_id>/create-editable-version/',
                self.admin_site.admin_view(self.create_editable_version_view),
                name='core_originationdocumenttemplate_create_editable_version',
            ),
            path('<path:object_id>/calibrate/', self.admin_site.admin_view(self.calibrate_view), name='core_originationdocumenttemplate_calibrate'),
            path('<path:object_id>/calibration-state/', self.admin_site.admin_view(self.calibration_state_view), name='core_originationdocumenttemplate_calibration_state'),
            path('<path:object_id>/calibration-page/', self.admin_site.admin_view(self.calibration_page_view), name='core_originationdocumenttemplate_calibration_page'),
            path('<path:object_id>/calibration-preview/', self.admin_site.admin_view(self.calibration_preview_view), name='core_originationdocumenttemplate_calibration_preview'),
            path('<path:object_id>/calibration-save/', self.admin_site.admin_view(self.calibration_save_view), name='core_originationdocumenttemplate_calibration_save'),
            path('<path:object_id>/calibration-field/', self.admin_site.admin_view(self.calibration_field_view), name='core_originationdocumenttemplate_calibration_field'),
            path('<path:object_id>/calibration-publish/', self.admin_site.admin_view(self.calibration_publish_view), name='core_originationdocumenttemplate_calibration_publish'),
        ]
        return custom + urls

    def create_editable_version_view(self, request, object_id):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        if request.method != 'POST':
            response = HttpResponse(status=405)
            response['Allow'] = 'POST'
            return response
        source = OriginationDocumentTemplate.objects.filter(pk=object_id).first()
        if not source:
            return HttpResponse(status=404)
        from core.services.origination_templates import (
            OriginationTemplateError, clone_reusable_template_version,
        )
        try:
            successor, replayed = clone_reusable_template_version(
                source, actor=request.user,
            )
        except OriginationTemplateError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(reverse(
                'admin:core_originationdocumenttemplate_change', args=[source.pk],
            ))
        except Exception:
            logger.exception('Creating an editable Origination template version failed.')
            self.message_user(
                request,
                'The editable version could not be created. No partial version was retained.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse(
                'admin:core_originationdocumenttemplate_change', args=[source.pk],
            ))
        self.message_user(
            request,
            (
                f'Opened existing editable version {successor.version}.'
                if replayed else
                f'Editable version {successor.version} is ready with the existing PDF, fields, and alignment.'
            ),
            level=messages.SUCCESS,
        )
        return HttpResponseRedirect(reverse(
            'admin:core_originationdocumenttemplate_calibrate', args=[successor.pk],
        ))

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
        setup_return_url = ''
        setup_return_warning = ''
        setup_token = str(request.GET.get('setup_return') or '').strip()
        if setup_token:
            try:
                from core.services.origination_setup import resolve_return_token
                setup_target = resolve_return_token(setup_token)
                setup_definition = OriginationProductDefinition.objects.filter(
                    pk=setup_target['definition_id'],
                    lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
                ).first()
                owns_template = bool(
                    setup_definition
                    and (
                        obj.product_definition_id == setup_definition.pk
                        or (product and product.pk == setup_definition.pk)
                        or setup_definition.document_assignments.filter(
                            template__document_type=obj.document_type,
                        ).exists()
                    )
                )
                if not owns_template:
                    raise ValidationError('The PDF does not belong to that setup workspace.')
                setup_return_url = reverse(
                    'admin:core_origination_setup_step',
                    args=[setup_definition.pk, setup_target['step_key']],
                )
            except (signing.BadSignature, ValidationError, ValueError):
                setup_return_url = reverse('admin:core_origination_setup_dashboard')
                setup_return_warning = (
                    'The setup return link is invalid or expired. Saving is still safe; '
                    'Back returns to the product setup dashboard.'
                )
        return TemplateResponse(request, 'admin/core/originationdocumenttemplate/calibrate.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Calibrate fields: {obj}', 'template_record': obj,
            'calibration_attach_product': product,
            'calibration_back_url': setup_return_url or (
                reverse('admin:core_originationproductdefinition_change', args=[product.pk])
                if product else reverse('admin:core_originationdocumenttemplate_changelist')
            ),
            'calibration_setup_return_url': setup_return_url,
            'calibration_setup_return_warning': setup_return_warning,
            'calibration_attach_product_url': (
                reverse('admin:core_originationproductdocumentassignment_add')
                + '?' + urlencode({'template': obj.pk})
                if obj.product_definition_id is None else ''
            ),
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
            catalogue_for_product, product_schema_revision, template_owns_form_schema,
            template_schema_revision,
        )
        owns_schema = template_owns_form_schema(obj)
        fields = (
            obj.form_schema
            if obj.form_schema and owns_schema
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
            if owns_schema:
                item['attached'] = bool(presentation)
            item['required'] = bool(presentation.get('required', False))
            item['section_key'] = str(presentation.get('section_key') or '')
            if item.get('type') == OriginationDataField.TYPE_CHOICE and presentation.get('options'):
                item['choice_options'] = list(presentation['options'])
        from core.services.origination_templates import _expected_signature_slots
        return JsonResponse({
            'ok': True,
            'revision': latest.revision if latest else 0,
            'published': bool(latest and latest.is_published),
            'product_published': bool(product and product.is_active),
            'configuration': config,
            'page_sizes': page_sizes,
            'context_keys': context_keys,
            'schema_revision': template_schema_revision(obj) if owns_schema else product_schema_revision(product) if product else 0,
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
                create_data_field, product_schema_revision, template_owns_form_schema,
                template_schema_revision,
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
                owns_schema = template_owns_form_schema(obj)
                if owns_schema:
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
            for item in (((obj.form_schema if owns_schema else product.form_schema) or {}).get('fields') or [])
            if isinstance(item, dict) and item.get('key')
        }
        for item in context_keys:
            presentation = presentations.get(str(item.get('key') or ''), {})
            if owns_schema:
                item['attached'] = bool(presentation)
            item['required'] = bool(presentation.get('required', False))
            item['section_key'] = str(presentation.get('section_key') or '')
            if item.get('type') == OriginationDataField.TYPE_CHOICE and presentation.get('options'):
                item['choice_options'] = list(presentation['options'])
        return JsonResponse({
            'ok': True, 'field': next(
                item for item in context_keys if item['key'] == data_field.key
            ),
            'context_keys': context_keys,
            'schema_revision': template_schema_revision(obj) if owns_schema else product_schema_revision(product),
            'form_sections': list(((obj.form_schema if owns_schema else product.form_schema) or {}).get('sections') or []),
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
        if obj.native_consent_policy_id:
            obj.native_consent_attested_by = request.user
            obj.native_consent_attested_at = timezone.now()
        schema_preset = str(form.cleaned_data.get('schema_preset') or '').strip()
        if schema_preset == OriginationDocumentTemplateForm.SCHEMA_PRESET_GENERIC_JAWABU_LAF:
            from core.services.generic_jawabu_laf_seed import (
                SIGNER_RULES, build_form_schema, ensure_catalogue,
            )
            from core.services.loan_origination import validate_product_form_contract
            from core.services.origination_templates import initial_template_configuration

            fields = ensure_catalogue(actor=request.user)
            obj.form_schema = build_form_schema(fields)
            obj.signer_rules = json.loads(json.dumps(SIGNER_RULES))
            validate_product_form_contract(obj.form_schema, obj.signer_rules)
            obj.placement_config = initial_template_configuration(
                None, form_schema=obj.form_schema,
            )
            obj.placement_config.update({
                'document_type': obj.document_type,
                'version': obj.version,
            })
        obj.full_clean()
        super().save_model(request, obj, form, change)
        OriginationDocumentTemplateEvent.objects.create(
            template=obj, action='created', actor=request.user,
            metadata={
                'sha256': obj.source_sha256,
                'byte_size': obj.source_byte_size,
                'page_count': obj.page_count,
                'reusable_family': obj.document_type if obj.product_definition_id is None else '',
                'schema_preset': schema_preset,
            },
        )
        from core.services.origination_templates import upload_template_record
        upload_template_record(obj, pdf_data=form._pdf_data, actor=request.user)
        if obj.status == OriginationDocumentTemplate.STATUS_UPLOAD_FAILED:
            messages.error(request, obj.upload_error)
        else:
            messages.success(
                request,
                'Template uploaded. Review its fields and align them in the visual builder before activation.',
            )

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


class OriginationCommercialExceptionForm(forms.ModelForm):
    class Meta:
        model = OriginationCommercialException
        fields = ('application', 'reason', 'approval_reference')
        widgets = {'reason': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['application'].queryset = LoanOriginationApplication.objects.filter(
            status__in=[
                LoanOriginationApplication.STATUS_DRAFT,
                LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
            ],
        ).select_related('product_version', 'product_definition').order_by('-updated_at')
        self.fields['application'].help_text = (
            'Choose the exact editable application revision. Any later edit invalidates this approval.'
        )

    def clean(self):
        cleaned = super().clean()
        application = cleaned.get('application')
        if not application:
            return cleaned
        from core.services.origination_commercial_terms import validate_commercial_terms
        validation = validate_commercial_terms(application)
        if not validation['enabled']:
            self.add_error('application', 'This application does not use the governed Commercial Terms contract.')
            return cleaned
        if any(not item['waivable'] for item in validation['blocking_findings']):
            self.add_error(
                'application',
                'Fix missing, invalid, or internally inconsistent values before approving a policy exception.',
            )
        elif not validation['policy_mismatch_codes']:
            self.add_error('application', 'This revision has no product-policy mismatch to approve.')
        elif OriginationCommercialException.objects.filter(
            application=application,
            application_revision=application.revision,
            entered_terms_sha256=validation['entered_terms_sha256'],
            expected_quote_sha256=validation['expected_quote_sha256'],
        ).exists():
            self.add_error('application', 'This exact revision already has a commercial exception.')
        self._commercial_validation = validation
        return cleaned


@admin.register(OriginationCommercialException)
class OriginationCommercialExceptionAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    form = OriginationCommercialExceptionForm
    list_display = (
        'application', 'application_revision', 'product_version',
        'approval_reference', 'approved_by', 'approved_at',
    )
    list_filter = ('approved_at', 'product_version__product')
    search_fields = (
        'application__reference_number', 'approval_reference',
        'approved_by__username',
    )
    readonly_fields = (
        'application_revision', 'product_version', 'entered_terms_sha256',
        'expected_quote_sha256', 'covered_mismatch_codes', 'approved_by', 'approved_at',
    )

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj else ()

    def get_fields(self, request, obj=None):
        if obj:
            return (
                'application', 'application_revision', 'product_version',
                'covered_mismatch_codes', 'reason', 'approval_reference',
                'entered_terms_sha256', 'expected_quote_sha256',
                'approved_by', 'approved_at',
            )
        return ('application', 'reason', 'approval_reference')

    def save_model(self, request, obj, form, change):
        if change or not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        validation = getattr(form, '_commercial_validation', None)
        if not validation:
            raise ValidationError('Commercial validation must complete before approval.')
        obj.application_revision = obj.application.revision
        obj.product_version = obj.application.product_version
        obj.entered_terms_sha256 = validation['entered_terms_sha256']
        obj.expected_quote_sha256 = validation['expected_quote_sha256']
        obj.covered_mismatch_codes = sorted(set(validation['policy_mismatch_codes']))
        obj.approved_by = request.user
        super().save_model(request, obj, form, change)
        OriginationApplicationEvent.objects.create(
            application=obj.application, action='commercial_exception_approved',
            revision=obj.application_revision, actor=request.user,
            after_values={
                'exception_id': str(obj.pk),
                'covered_mismatch_codes': obj.covered_mismatch_codes,
                'approval_reference': obj.approval_reference,
            },
            metadata={
                'entered_terms_sha256': obj.entered_terms_sha256,
                'expected_quote_sha256': obj.expected_quote_sha256,
            },
        )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return bool(obj is None and self.has_add_permission(request))

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
    exclude = ('frozen_unsigned_document', 'pending_signed_document')


@admin.register(OriginationConsentPolicyVersion)
class OriginationConsentPolicyVersionAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    list_display = (
        'version', 'status', 'approval_reference', 'approved_by', 'approved_at',
        'retired_by', 'retired_at', 'created_at',
    )
    list_filter = ('status', 'approved_at')
    search_fields = ('version', 'approval_reference', 'content_sha256')
    readonly_fields = (
        'status', 'content_sha256', 'created_by', 'approved_by', 'approved_at',
        'retired_by', 'retired_at', 'created_at',
    )
    actions = ('activate_selected_policy', 'retire_selected_policy')

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return False if obj else request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.created_by = request.user
        obj.status = obj.STATUS_DRAFT
        obj.full_clean()
        return super().save_model(request, obj, form, change)

    @admin.action(description='Activate selected compliance-approved consent policy')
    def activate_selected_policy(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one consent policy.', level=messages.ERROR)
            return
        policy_id = queryset.values_list('pk', flat=True).first()
        with transaction.atomic():
            policy = OriginationConsentPolicyVersion.objects.select_for_update().get(pk=policy_id)
            if policy.status != policy.STATUS_DRAFT:
                self.message_user(request, 'Only a draft consent policy can be activated.', level=messages.ERROR)
                return
            now = timezone.now()
            policy.status = policy.STATUS_ACTIVE
            policy.approved_by = request.user
            policy.approved_at = now
            OriginationConsentPolicyVersion.objects.select_for_update().filter(
                status=policy.STATUS_ACTIVE,
            ).exclude(pk=policy.pk).update(
                status=policy.STATUS_RETIRED, retired_by=request.user, retired_at=now,
            )
            policy.full_clean()
            OriginationConsentPolicyVersion.objects.filter(pk=policy.pk).update(
                status=policy.STATUS_ACTIVE, approved_by=request.user, approved_at=now,
            )
        self.message_user(
            request,
            f'Consent policy {policy.version} activated with approval reference {policy.approval_reference}.',
            level=messages.SUCCESS,
        )

    @admin.action(description='Retire selected active consent policy')
    def retire_selected_policy(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one consent policy.', level=messages.ERROR)
            return
        policy_id = queryset.values_list('pk', flat=True).first()
        with transaction.atomic():
            policy = OriginationConsentPolicyVersion.objects.select_for_update().get(pk=policy_id)
            if policy.status != policy.STATUS_ACTIVE:
                self.message_user(request, 'Only the active consent policy can be retired.', level=messages.ERROR)
                return
            now = timezone.now()
            OriginationConsentPolicyVersion.objects.filter(pk=policy.pk).update(
                status=policy.STATUS_RETIRED, retired_by=request.user, retired_at=now,
            )
        self.message_user(request, f'Consent policy {policy.version} retired.', level=messages.SUCCESS)


@admin.register(OriginationSigningActionInvalidation)
class OriginationSigningActionInvalidationAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('action', 'invalidated_by', 'reason', 'created_at')
    search_fields = ('action__package__external_reference', 'reason', 'request_id')


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


@admin.register(MiniAppDiagnosticSession)
class MiniAppDiagnosticSessionAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'surface', 'workflow', 'platform', 'classification', 'release',
        'network_bucket', 'last_signal_at', 'started_at',
    )
    list_filter = (
        'workflow', 'surface', 'platform', 'classification',
        'network_bucket', 'release', 'recovered_on_later_launch',
    )
    search_fields = ('client_session_uuid', 'events__request_id')
    date_hierarchy = 'started_at'


@admin.register(MiniAppDiagnosticEvent)
class MiniAppDiagnosticEventAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'session', 'event_type', 'action', 'visibility', 'online',
        'status_bucket', 'elapsed_ms', 'recorded_at',
    )
    list_filter = ('event_type', 'visibility', 'online', 'network_bucket', 'status_bucket')
    search_fields = ('client_event_uuid', 'session__client_session_uuid', 'request_id')
    date_hierarchy = 'recorded_at'


@admin.register(MiniAppDiagnosticDailyAggregate)
class MiniAppDiagnosticDailyAggregateAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'date', 'surface', 'platform', 'classification', 'network_bucket',
        'release', 'session_count',
    )
    list_filter = ('workflow', 'surface', 'platform', 'classification', 'network_bucket', 'release')
    date_hierarchy = 'date'


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
