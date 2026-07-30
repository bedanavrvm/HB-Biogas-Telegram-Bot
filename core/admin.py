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
from django.db import DatabaseError, connections, transaction
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from unfold.admin import ModelAdmin, StackedInline, TabularInline
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
    CaseUpdate,
    FcaImportRecord,
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    JawabuCustomer,
    JawabuCustomerPhoneHistory,
    JawabuCustomerFieldProvenance,
    JawabuPipelineEvent,
    BusinessCalendarHoliday,
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
    OperationalLocation,
    OperationalProduct,
    OrderApprovalUpdate,
    InvoiceUploadBatch,
    ParsedInvoice,
    PaymentDocument,
    PaymentDocumentTemplate,
    RawMessage,
    ProcessedMessage,
    ParsedMessage,
    RequisitionBatch,
    RequisitionTemplate,
    SpinCreditRequest,
    SpinBatchReviewItem,
    TatTrackerCase,
    TatTrackerEvent,
    TatRepairJob,
    UserProfile,
    AccessGrant,
    WorkflowRoleCapability,
    WorkflowRoleCapabilityAuditEvent,
    AccessControlChangeRequest,
    AccessControlPolicySnapshot,
    EmergencyAccessGrant,
    AccessControlNotification,
    CapabilityUsageDaily,
    DocumentSignoffPolicy,
    DocumentPhysicalSignoff,
    DocumentPhysicalSignoffEvent,
)

logger = logging.getLogger(__name__)


class CompactModelAdmin(ModelAdmin):
    """Shared dense layout for editable operational records."""

    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True


@admin.register(OperationalLocation)
class OperationalLocationAdmin(CompactModelAdmin):
    """Central editable list used by Portal, forms, parsers, and grants."""

    list_display = ('location_type', 'name', 'code', 'active', 'sort_order', 'updated_at')
    list_filter = ('location_type', 'active')
    search_fields = ('name', 'code')
    list_editable = ('active', 'sort_order')
    ordering = ('location_type', 'sort_order', 'name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Location', {
            'fields': (
                ('location_type', 'name'),
                ('code', 'sort_order'),
                'active',
            ),
        }),
        ('Audit', {
            'fields': (('created_at', 'updated_at'),),
            'classes': ('collapse',),
        }),
    )


@admin.register(OperationalProduct)
class OperationalProductAdmin(CompactModelAdmin):
    """Controlled product names accepted from system exports."""

    list_display = ('name', 'code', 'active', 'sort_order', 'updated_at')
    list_filter = ('active',)
    search_fields = ('name', 'code')
    list_editable = ('active', 'sort_order')
    ordering = ('sort_order', 'name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Product', {'fields': (('name', 'code'), ('active', 'sort_order'))}),
        ('Audit', {'fields': (('created_at', 'updated_at'),), 'classes': ('collapse',)}),
    )


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


@admin.register(BusinessCalendarHoliday)
class BusinessCalendarHolidayAdmin(CompactModelAdmin):
    list_display = ('date', 'name', 'active', 'updated_at')
    list_filter = ('active',)
    search_fields = ('name',)
    list_editable = ('active',)
    ordering = ('date',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Holiday', {'fields': (('date', 'name'), 'active')}),
        ('Audit', {'fields': (('created_at', 'updated_at'),), 'classes': ('collapse',)}),
    )


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
        'review_needed', 'committed_count', 'skipped_count', 'sender', 'created_at',
    ]
    list_filter = ['import_kind', 'status', 'group_id', 'created_at', 'committed_at']
    search_fields = ['source_filename', 'group_id', 'sender', 'telegram_message_id', 'error']
    readonly_fields = ['id', 'created_at', 'updated_at', 'committed_at']
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
                if clean_errors:
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
                        f'Cleanup completed. Removed {removed} duplicate Sheet row(s); canonical Django case IDs were preserved.',
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

    list_display = ('document_type', 'approval_role', 'is_active', 'updated_at')
    list_filter = ('document_type', 'is_active')
    readonly_fields = ('document_type', 'workflow', 'approval_role', 'is_active', 'updated_at')
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
                    approval_role=str(request.POST.get('approval_role') or ''),
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
        choices=branch_choices(), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
            **{value: {'jawabu_portal', 'tat_tracker'} for value, _ in branch_choices() if value},
        }),
    )
    product = forms.ChoiceField(
        choices=product_choices(), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
            **{value: {'tat_tracker'} for value, _ in product_choices() if value},
        }),
    )
    group_configuration = GroupConfigurationAccessField(
        queryset=GroupSheetConfiguration.objects.filter(enabled=True),
        required=False,
        empty_label='All compatible groups',
        widget=GroupConfigurationAccessSelect,
    )

    class Meta:
        model = AccessGrant
        fields = ('active', 'workflow', 'role', 'branch', 'product', 'group_configuration')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.services.access_policies import branch_choices
        self.fields['branch'].choices = branch_choices()
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
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Explain the operational need. The grant will remain inactive until a different designated approver applies it.',
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
                    change_requests = [
                        create_capability_request(
                            requester=request.user, workflow=selected_workflow, role=target_role,
                            capability_keys=submitted, reason=str(request.POST.get('reason') or ''),
                        )
                        for target_role in target_roles
                    ]
                except ValidationError as exc:
                    messages.error(request, '; '.join(exc.messages))
                else:
                    messages.success(request, f'{len(change_requests)} change request(s) are pending independent approval. No live access changed.')
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
        'change_type', 'workflow', 'role', 'target_user', 'before_snapshot', 'proposed_snapshot',
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
        return bool(request.user.is_superuser or request.user.groups.filter(name='Access Policy Approvers').exists())

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
            from core.services.access_control import can_approve_access_change, request_diff
            change_request = AccessControlChangeRequest.objects.get(pk=object_id)
            extra_context = {**(extra_context or {}), 'request_diff': request_diff(change_request), 'can_approve_access_change': can_approve_access_change(request.user)}
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


@admin.register(EmergencyAccessGrant)
class EmergencyAccessGrantAdmin(CompactModelAdmin):
    list_display = ('user', 'workflow', 'role', 'activated_by', 'expires_at', 'revoked_at')
    list_filter = ('workflow',)
    search_fields = ('user__username', 'role', 'reason')
    readonly_fields = ('activated_by', 'activated_at', 'expires_at', 'revoked_at', 'revoked_by')

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


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
        choices=branch_choices(), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
            **{value: {'jawabu_portal', 'tat_tracker'} for value, _ in branch_choices() if value},
        }),
    )
    product = forms.ChoiceField(
        choices=product_choices(), required=False,
        widget=WorkflowScopedSelect(workflow_map={
            '': {'jawabu_portal', 'complaint_cases', 'tat_tracker'},
            **{value: {'tat_tracker'} for value, _ in product_choices() if value},
        }),
    )
    group_configuration = GroupConfigurationAccessField(
        queryset=GroupSheetConfiguration.objects.filter(enabled=True), required=False,
        empty_label='All compatible groups', widget=GroupConfigurationAccessSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.services.access_policies import branch_choices
        self.fields['branch'].choices = branch_choices()

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
            messages.success(request, f'{user.get_full_name() or user.get_username()} was created. Their initial workflow access is pending independent approval.')
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
        from core.services.access_control import create_grant_request
        create_grant_request(
            requester=requester, user=user, workflow=data['workflow'], role=data['role'],
            branch=data.get('branch', ''), product=data.get('product', ''),
            group_configuration=data.get('group_configuration'),
            reason='Initial workflow access for newly enrolled staff user.',
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
                reason=form.cleaned_data['reason'],
            )
            messages.success(request, 'Access request submitted for independent approval.')
            return HttpResponseRedirect(reverse('admin:core_accesscontrolchangerequest_change', args=[change_request.pk]))
        return TemplateResponse(request, 'admin/auth/user/access_request.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': f'Request Mini App access: {user.get_username()}', 'form': form, 'target_user': user,
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
        rows = []
        for workflow, label in AccessGrant.WORKFLOW_CHOICES:
            access = user_access(user, workflow)
            rows.append({'workflow': label, 'roles': access['roles'], 'branches': access['branches'], 'products': access['products'], 'capabilities': capabilities_payload(user, workflow, access=access), 'emergency': access.get('emergency_grants', [])})
        return TemplateResponse(request, 'admin/auth/user/effective_access.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': f'Effective Mini App access: {user.get_username()}', 'target_user': user, 'rows': rows,
        })


class UnfoldGroupAdmin(ModelAdmin, DjangoGroupAdmin):
    compressed_fields = True
    list_filter_submit = True
    list_fullwidth = True


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
