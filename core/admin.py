from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    CaseUpdate,
    GroupSheetConfiguration,
    MediaAttachment,
    OrderApprovalUpdate,
    RawMessage,
    ProcessedMessage,
    ParsedMessage,
)


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
        'drive_file_id', 'drive_url',
    ]
    readonly_fields = ['id', 'created_at']


@admin.register(GroupSheetConfiguration)
class GroupSheetConfigurationAdmin(admin.ModelAdmin):
    list_display = [
        'display_label', 'group_id', 'enabled', 'sheet_name',
        'sheet_link', 'updated_at',
    ]
    list_filter = ['enabled', 'sheet_name', 'updated_at']
    search_fields = ['group_id', 'display_name', 'sheet_id', 'sheet_name']
    readonly_fields = [
        'created_at', 'updated_at', 'sheet_link', 'sheet_analyzer_link',
    ]
    fieldsets = (
        ('Group Routing', {
            'fields': (
                'enabled', 'group_id', 'display_name', 'sheet_id',
                'sheet_name', 'sheet_link', 'sheet_analyzer_link',
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
                'Optional JSON mapping from canonical case fields to this '
                'sheet\'s column headers.'
            ),
        }),
        ('Workflow And Parser Rules', {
            'fields': ('workflow', 'parser_rules'),
            'description': (
                'Optional per-group workflow and parser settings. Keep empty '
                'to use the default complaint/status rules.'
            ),
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
