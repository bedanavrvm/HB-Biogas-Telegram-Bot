from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from unfold.admin import ModelAdmin

from core.models import GroupSheetConfiguration
from core.services.group_config import GroupConfig
from core.services.complaint_cases import ComplaintCaseError, staff_actor_for_user, is_complaint_workflow, actor_can
from .models import UploadAttempt, UploadFile
from .services import attention, is_it, retry_case


for model in (UploadAttempt, UploadFile):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


@admin.register(UploadFile)
class UploadFileAdmin(ModelAdmin):
    list_display = ['id', 'filename', 'size', 'received_at', 'published_at', 'operation']
    exclude = ['content', 'resumable_uri']
    actions = ['retry_publication']
    list_filter = ['operation__status']
    change_list_template = 'admin/complaint_publications/uploadfile/change_list.html'

    def get_urls(self):
        return [path('needs-attention/', self.admin_site.admin_view(self.attention_view),
            name='complaint_publications_attention'), *super().get_urls()]

    def attention_view(self, request):
        if not self.has_module_permission(request):
            raise PermissionDenied
        groups = GroupSheetConfiguration.objects.filter(pk__in=self.allowed_groups(request))
        if request.method == 'POST':
            from core.models import ParsedMessage
            from uuid import UUID
            row = next((group for group in groups if str(group.pk) == request.POST.get('group')), None)
            try:
                key = UUID(request.POST.get('case', ''))
            except (ValueError, AttributeError):
                raise PermissionDenied from None
            case = ParsedMessage.objects.filter(pk=key, group_id=row.group_id).first() if row else None
            if not case:
                raise PermissionDenied
            group = GroupConfig(**row.as_group_config_kwargs())
            retry_case(group, staff_actor_for_user(group, request.user), case)
            self.message_user(request, 'Reviewed publication retries are queued. The failure history is retained.')
            return redirect('admin:complaint_publications_attention')
        rows = []
        for row in groups:
            group = GroupConfig(**row.as_group_config_kwargs())
            rows.append({'key': row.pk, 'label': row.display_name,
                'items': attention(group, staff_actor_for_user(group, request.user))})
        return TemplateResponse(request, 'admin/complaint_publications/attention.html', {
            **self.admin_site.each_context(request), 'title': 'Complaint publications needing attention',
            'groups': rows, 'opts': self.model._meta,
        })

    def allowed_groups(self, request):
        groups = []
        for row in GroupSheetConfiguration.objects.filter(enabled=True):
            if not is_complaint_workflow(row):
                continue
            try:
                group = GroupConfig(**row.as_group_config_kwargs())
                actor = staff_actor_for_user(group, request.user)
                if is_it(actor) and actor_can(group, actor, 'complaint.queue.view') and actor_can(group, actor, 'complaint.case.evidence.view'):
                    groups.append(row.pk)
            except (ComplaintCaseError, ValueError):
                continue
        return groups

    def get_queryset(self, request):
        return super().get_queryset(request).defer('content', 'resumable_uri').filter(attempt__group_id__in=self.allowed_groups(request))

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_staff and self.allowed_groups(request))

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and (obj is None or obj.attempt.group_id in self.allowed_groups(request))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields if field.name not in self.exclude]

    @admin.action(description='Retry failed publication for selected Complaint cases', permissions=['view'])
    def retry_publication(self, request, queryset):
        handled = set()
        for file in queryset.select_related('attempt__group', 'evidence__parsed_message'):
            if not file.evidence_id or file.evidence.parsed_message_id in handled:
                continue
            handled.add(file.evidence.parsed_message_id)
            group = GroupConfig(**file.attempt.group.as_group_config_kwargs())
            retry_case(group, staff_actor_for_user(group, request.user), file.evidence.parsed_message)
        self.message_user(request, 'Reviewed publication retries are queued. Saved complaint records are retained.')
