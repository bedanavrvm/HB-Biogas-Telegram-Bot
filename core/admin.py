from django import forms
from django.contrib import admin
from django.contrib import messages
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
    GroupSheetConfiguration,
    MediaAttachment,
    OrderApprovalUpdate,
    RawMessage,
    ProcessedMessage,
    ParsedMessage,
)


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

    class Meta:
        model = GroupSheetConfiguration
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workflow = getattr(self.instance, 'workflow', None) or {}
        preset_key = preset_for_workflow(workflow)
        self.fields['workflow_preset'].initial = preset_key
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
                'search_sheet_names': self.order_approval_tabs(),
                'match_field': self.cleaned_data.get('order_approval_match_field'),
                'media_field': self.cleaned_data.get('order_approval_media_field'),
                'header_row': self.cleaned_data.get('order_approval_header_row'),
                'media_root_folder': self.cleaned_data.get(
                    'order_approval_media_root_folder'
                ),
            },
        )

    def apply_preset_defaults(self, obj):
        preset_key = self.cleaned_data.get('workflow_preset') or MANUAL_PRESET
        defaults = defaults_for_preset(preset_key)
        if defaults.get('sheet_name') and not obj.sheet_name:
            obj.sheet_name = defaults['sheet_name']
        if defaults.get('sheet_schema') is not None and not obj.sheet_schema:
            obj.sheet_schema = defaults['sheet_schema']
        if defaults.get('parser_rules') is not None and not obj.parser_rules:
            obj.parser_rules = defaults['parser_rules']


@admin.register(RawMessage)
class RawMessageAdmin(admin.ModelAdmin):
    list_display = ['sender', 'received_at', 'has_image', 'created_at']
    list_filter = ['has_image', 'received_at']
    search_fields = ['sender', 'content']
    readonly_fields = ['id', 'created_at']


@admin.register(ProcessedMessage)
class ProcessedMessageAdmin(admin.ModelAdmin):
    list_display = ['message_hash', 'status', 'processed_at']
    list_filter = ['status', 'processed_at']
    search_fields = ['message_hash']
    readonly_fields = ['id', 'processed_at']


@admin.register(ParsedMessage)
class ParsedMessageAdmin(admin.ModelAdmin):
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
class CaseUpdateAdmin(admin.ModelAdmin):
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
class OrderApprovalUpdateAdmin(admin.ModelAdmin):
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
class MediaAttachmentAdmin(admin.ModelAdmin):
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


@admin.register(GroupSheetConfiguration)
class GroupSheetConfigurationAdmin(admin.ModelAdmin):
    form = GroupSheetConfigurationAdminForm
    list_display = [
        'display_label', 'group_id', 'enabled', 'sheet_name',
        'sheet_link', 'data_records_link', 'media_records_link', 'updated_at',
    ]
    list_filter = ['enabled', 'sheet_name', 'updated_at']
    search_fields = ['group_id', 'display_name', 'sheet_id', 'sheet_name']
    readonly_fields = [
        'created_at', 'updated_at', 'sheet_link', 'sheet_analyzer_link',
        'data_records_link', 'media_records_link',
    ]
    fieldsets = (
        ('Group Routing', {
            'fields': (
                'enabled', 'group_id', 'display_name', 'sheet_id',
                'sheet_name', 'sheet_link', 'data_records_link',
                'media_records_link', 'sheet_analyzer_link',
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
            'fields': (
                'workflow_preset',
                'order_approval_search_tabs',
                'order_approval_match_field',
                'order_approval_media_field',
                'order_approval_header_row',
                'order_approval_media_root_folder',
            ),
            'description': (
                'Select Case / Complaints for the existing complaint intake '
                'workflow, Order Approval for BRO updates, or Manual JSON for '
                'a custom workflow. The workflow JSON below will be generated '
                'automatically where a preset applies.'
            ),
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
        ]
        return custom_urls + urls

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

    def save_model(self, request, obj, form, change):
        apply_defaults = getattr(form, 'apply_preset_defaults', None)
        if apply_defaults:
            apply_defaults(obj)
        generated_workflow = getattr(form, 'generated_workflow', lambda: None)()
        if generated_workflow:
            obj.workflow = generated_workflow
        super().save_model(request, obj, form, change)
        self._clear_runtime_config_cache()
        self.message_user(
            request,
            'Configuration saved. Runtime group routing cache was refreshed.',
        )

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
