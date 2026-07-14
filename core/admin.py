from django import forms
from django.contrib import admin
from django.contrib import messages
from django.conf import settings
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from urllib.parse import urlencode

from core.services.workflow_presets import (
    MANUAL_PRESET,
    build_workflow_from_preset,
    defaults_for_preset,
    get_preset,
    preset_choices,
    preset_for_workflow,
)

from .models import (
    CaseUpdate,
    FcaImportRecord,
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    JawabuFarmerUploadBatch,
    JawabuVisitRecord,
    LiveSheetRecordChange,
    MediaAttachment,
    OrderApprovalUpdate,
    RawMessage,
    ProcessedMessage,
    ParsedMessage,
    RequisitionBatch,
    RequisitionTemplate,
    SpinCreditRequest,
    TatTrackerCase,
    TatTrackerEvent,
    TatTrackerStaffMember,
)


class ReadOnlyAuditAdmin(admin.ModelAdmin):
    """Prevent admin edits that would not be written back to the live sheet."""

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

    class Meta:
        model = GroupSheetConfiguration
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workflow = getattr(self.instance, 'workflow', None) or {}
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
        if preset_key == 'jawabu_homebiogas':
            self.fields['workflow_preset'].initial = 'jawabu_homebiogas'
            defaults = defaults_for_preset('jawabu_homebiogas')['workflow']
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

    def order_approval_tabs(self) -> list[str]:
        raw = self.cleaned_data.get('order_approval_search_tabs', '')
        return [
            tab.strip()
            for tab in str(raw or '').split(',')
            if tab.strip()
        ]

    def generated_workflow(self) -> dict | None:
        preset_key = self.cleaned_data.get('workflow_preset') or MANUAL_PRESET
        return build_workflow_from_preset(
            preset_key,
            overrides={
                'case_header_row': self.cleaned_data.get('case_header_row'),
                'search_sheet_names': self.order_approval_tabs(),
                'match_field': self.cleaned_data.get('order_approval_match_field'),
                'media_field': self.cleaned_data.get('order_approval_media_field'),
                'header_row': self.cleaned_data.get('order_approval_header_row'),
                'legacy_batch_sheet_name': self.cleaned_data.get('spin_legacy_batch_sheet_name'),
                'spin_header_row': self.cleaned_data.get('spin_header_row'),
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
            },
        )

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



@admin.register(TatTrackerCase)
class TatTrackerCaseAdmin(TestDataDeleteAdmin):
    list_display = ['case_id', 'group_id', 'product_label', 'client_name', 'branch', 'status', 'current_stage', 'updated_at']
    list_filter = ['group_id', 'product_key', 'branch', 'status', 'current_stage']
    search_fields = ['case_id', 'client_name', 'bro_name', 'branch']


@admin.register(TatTrackerEvent)
class TatTrackerEventAdmin(ReadOnlyAuditAdmin):
    list_display = ['case', 'stage_label', 'actor_name', 'source', 'synced_to_sheet', 'created_at']
    list_filter = ['group_id', 'source', 'stage_key', 'synced_to_sheet', 'created_at']
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
        'business_key_value', 'group_id', 'file_type', 'original_filename',
        'storage_provider', 'upload_status', 'created_at',
    ]
    list_filter = [
        'group_id', 'file_type', 'storage_provider', 'upload_status', 'created_at',
    ]
    search_fields = [
        'business_key_value', 'telegram_file_id', 'original_filename',
        'drive_file_id', 'drive_url', 'content_hash',
    ]
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
        'source_filename', 'group_id', 'status', 'total_rows',
        'review_needed', 'committed_count', 'skipped_count', 'sender', 'created_at',
    ]
    list_filter = ['status', 'group_id', 'created_at', 'committed_at']
    search_fields = ['source_filename', 'group_id', 'sender', 'telegram_message_id', 'error']
    readonly_fields = ['id', 'created_at', 'updated_at', 'committed_at']
@admin.register(JawabuFarmerMaster)
class JawabuFarmerMasterAdmin(admin.ModelAdmin):
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
                'customer_name', 'national_id', 'primary_phone',
                'secondary_phone', 'external_id', 'status',
            ),
        }),
        ('Location', {
            'fields': (
                'county', 'sub_county', 'ward', 'village', 'landmark',
                'branch', 'gps_link', 'latitude', 'longitude',
            ),
        }),
        ('Farmers Source Fields', {
            'fields': (
                'hbg_contract_name', 'lead_source', 'contract_type',
                'installation_status', 'actual_receipts_currency',
                'actual_receipts', 'hb_sales_person', 'sign_date',
                'created_date', 'comments',
            ),
        }),
        ('Stage 2 â€” JBL Visit', {
            'fields': (
                'jbl_visit_date', 'jbl_officer',
                'jbl_visit_status', 'jbl_visit_comment',
            ),
            'description': 'Logged by the JBL BRO after visiting the farmer.',
        }),
        ('Stage 3 â€” Credit Decision', {
            'fields': (
                'credit_decision', 'credit_decided_by', 'credit_decided_at',
            ),
            'description': (
                'Set by the credit analyst. Only when Credit Decision = Approved '
                'can a requisition date and order number be assigned.'
            ),
        }),
        ('Stage 4 â€” Requisition', {
            'fields': ('requisition_date', 'order_number'),
            'description': 'Filled by admin once credit is approved. Gate enforced by the portal.',
        }),
        ('Stage 7 â€” Invoice', {
            'fields': (
                'invoice_number', 'invoice_date',
                'invoice_amount', 'discount', 'payment', 'balance_due',
            ),
            'description': (
                'Populated automatically when a combined invoice PDF is uploaded '
                'via the portal Batches tab. Can also be set manually.'
            ),
        }),
        ('Import / Cleaning', {
            'fields': (
                'cleaning_notes', 'duplicate_key', 'source', 'source_name',
                'source_row_number', 'source_fingerprint', 'last_imported_at',
                'raw_data', 'created_at', 'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
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


class TatTrackerStaffMemberAdminForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        choices=TatTrackerStaffMember.ROLE_CHOICES,
        required=True,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select every role this staff member can perform.',
    )
    branches = forms.MultipleChoiceField(
        choices=TatTrackerStaffMember.BRANCH_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Leave empty or choose All branches for unrestricted branch access.',
    )
    products = forms.MultipleChoiceField(
        choices=TatTrackerStaffMember.PRODUCT_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Leave empty or choose All products for unrestricted product access.',
    )

    class Meta:
        model = TatTrackerStaffMember
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['roles'].initial = self._split(self.instance.roles)
            self.fields['branches'].initial = self._split(self.instance.branches)
            self.fields['products'].initial = self._split(self.instance.products)
        else:
            self.fields['roles'].initial = ['BRO']
            self.fields['branches'].initial = ['ALL']
            self.fields['products'].initial = ['ALL']

    def clean_roles(self):
        return ','.join(self.cleaned_data.get('roles') or ['BRO'])

    def clean_branches(self):
        selected = self.cleaned_data.get('branches') or ['ALL']
        return 'ALL' if 'ALL' in selected else ','.join(selected)

    def clean_products(self):
        selected = self.cleaned_data.get('products') or ['ALL']
        return 'ALL' if 'ALL' in selected else ','.join(selected)

    @staticmethod
    def _split(value):
        return [part.strip() for part in str(value or '').split(',') if part.strip()]


class TatTrackerStaffMemberInline(admin.StackedInline):
    model = TatTrackerStaffMember
    form = TatTrackerStaffMemberAdminForm
    extra = 1
    fields = (
        'active', 'name', 'telegram_user_id', 'telegram_username',
        'roles', 'branches', 'products', 'notes',
    )
    verbose_name = 'TAT tracker staff member'
    verbose_name_plural = 'TAT tracker staff GUI'

@admin.register(GroupSheetConfiguration)
class GroupSheetConfigurationAdmin(admin.ModelAdmin):
    form = GroupSheetConfigurationAdminForm
    inlines = [TatTrackerStaffMemberInline]
    list_display = [
        'display_label', 'group_id', 'enabled', 'sheet_name',
        'sheet_link', 'live_records_link', 'data_records_link',
        'media_records_link', 'updated_at',
    ]
    list_filter = ['enabled', 'sheet_name', 'updated_at']
    search_fields = ['group_id', 'display_name', 'sheet_id', 'sheet_name']
    readonly_fields = [
        'created_at', 'updated_at', 'sheet_link', 'sheet_analyzer_link',
        'live_records_link', 'data_records_link', 'media_records_link',
        'reset_group_data_link',
    ]
    fieldsets = (
        ('Group Routing', {
            'fields': (
                'enabled', 'group_id', 'display_name', 'sheet_id',
                'sheet_name', 'sheet_link', 'live_records_link', 'data_records_link',
                'media_records_link', 'sheet_analyzer_link', 'reset_group_data_link',
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
            'classes': ('collapse', 'preset-section', 'preset-case'),
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
            'classes': ('collapse', 'preset-section', 'preset-order_approval'),
        }),
        ('SPIN / CRB Settings', {
            'fields': (
                'spin_header_row',
                'spin_legacy_batch_sheet_name',
            ),
            'description': 'Header and legacy batch tab settings for the SPIN / CRB workflow.',
            'classes': ('collapse', 'preset-section', 'preset-spin_credit_analysis'),
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
            ),
            'description': 'Master Data sync plus optional downstream internal Order Sheet sync for the Jawabu HomeBiogas workflow.',
            'classes': ('collapse', 'preset-section', 'preset-jawabu_homebiogas'),
        }),
        ('Advanced Workflow And Parser Rules', {
            'fields': ('workflow', 'parser_rules'),
            'description': (
                'Optional per-group workflow and parser settings. Use a '
                'preset where possible; custom workflows can define their own '
                'JSON here.'
            ),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    class Media:
        js = ('admin/js/workflow_preset_toggle.js',)

    def get_inline_instances(self, request, obj=None):
        workflow_type = str(((obj.workflow if obj else {}) or {}).get('type') or '')
        if workflow_type != 'tat_tracker':
            return []
        return super().get_inline_instances(request, obj)

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
                '<path:object_id>/analyze-sheet/',
                self.admin_site.admin_view(self.analyze_sheet_view),
                name='core_groupsheetconfiguration_analyze',
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
            include_spin_legacy_batch = request.POST.get('include_spin_legacy_batch') == 'yes'
            result = reset_group_data(
                config.group_id,
                include_farmer_uploads=include_farmer_uploads,
                include_all_farmer_master=include_all_farmer_master,
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
            delete_live_sheet_row,
            load_live_sheet_table,
            update_live_sheet_row,
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
            if not self.has_change_permission(request, config):
                messages.error(request, 'You do not have permission to change live sheet rows.')
                return HttpResponseRedirect(request.path)
            try:
                if action == 'update':
                    submitted = {
                        int(key[4:]): value
                        for key, value in request.POST.items()
                        if key.startswith('col_') and key[4:].isdigit()
                    }
                    result = update_live_sheet_row(
                        config,
                        selected_tab,
                        edit_row,
                        submitted,
                    )
                    if result.get('changed'):
                        self._audit_live_sheet_change(
                            config=config,
                            request=request,
                            action='update',
                            result=result,
                        )
                        mirror_result = self._sync_case_mirror(config)
                        messages.success(
                            request,
                            f"Updated live sheet row {edit_row}.",
                        )
                        self._warn_on_mirror_failure(request, mirror_result)
                    else:
                        messages.info(request, 'No sheet values changed.')
                else:
                    if request.POST.get('confirm_delete') != 'yes':
                        raise LiveSheetRecordError(
                            'Confirm the deletion before removing the live sheet row.'
                        )
                    result = delete_live_sheet_row(config, selected_tab, edit_row)
                    self._audit_live_sheet_change(
                        config=config,
                        request=request,
                        action='delete',
                        result=result,
                    )
                    mirror_result = self._sync_case_mirror(config)
                    messages.success(
                        request,
                        f"Deleted live sheet row {edit_row}.",
                    )
                    self._warn_on_mirror_failure(request, mirror_result)
                return HttpResponseRedirect(
                    f"{request.path}?{urlencode({'sheet_tab': selected_tab})}"
                )
            except LiveSheetRecordError as exc:
                self._audit_live_sheet_failure(
                    config=config,
                    request=request,
                    action=action,
                    sheet_tab=selected_tab,
                    row_number=edit_row,
                    error=str(exc),
                )
                messages.error(request, str(exc))

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
            'has_change_permission': self.has_change_permission(request, config),
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
        workflow_type = str((config.workflow or {}).get('type') or 'case')
        if workflow_type != 'case':
            return None
        from core.services.sheet_sync import sync_group_from_sheet
        return sync_group_from_sheet(group_id=config.group_id, delete_missing=True)

    @staticmethod
    def _warn_on_mirror_failure(request, result):
        if result and result.get('status') != 'success':
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


@admin.register(TatTrackerStaffMember)
class TatTrackerStaffMemberAdmin(admin.ModelAdmin):
    form = TatTrackerStaffMemberAdminForm
    list_display = [
        'name', 'group_configuration', 'active', 'telegram_user_id',
        'telegram_username', 'roles', 'branches', 'products', 'updated_at',
    ]
    list_filter = ['active', 'group_configuration', 'roles', 'branches', 'products']
    search_fields = [
        'name', 'telegram_user_id', 'telegram_username',
        'group_configuration__group_id', 'group_configuration__display_name',
    ]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        GroupSheetConfigurationAdmin._clear_runtime_config_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        GroupSheetConfigurationAdmin._clear_runtime_config_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        GroupSheetConfigurationAdmin._clear_runtime_config_cache()

@admin.register(RequisitionTemplate)
class RequisitionTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'file', 'created_at', 'updated_at')
    list_editable = ('is_active',)
    search_fields = ('name',)


@admin.register(RequisitionBatch)
class RequisitionBatchAdmin(ReadOnlyAuditAdmin):
    list_display = (
        'order_number', 'requisition_date', 'farmer_count', 'status',
        'generated_by', 'created_at', 'updated_at',
    )
    list_filter = ('status', 'requisition_date', 'created_at')
    search_fields = ('order_number', 'generated_by', 'filename')

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
