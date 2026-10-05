import uuid

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from django.db.models import F
from unfold.admin import ModelAdmin

from .models import ApprovedRecipient, ReportDelivery, ReportSchedule
from .services import (allowed_configurations, can_manage, next_occurrence, preview_report,
                       queue_schedule, require_manage, retry_delivery, validate_recipient)


class ScopedForm(forms.ModelForm):
    actor = None

    def clean(self):
        values = super().clean()
        if not all(key in values for key in ('group_configuration', 'branch', 'product')):
            return values
        for key in ('group_configuration', 'branch', 'product'):
            setattr(self.instance, key, values[key])
        if not can_manage(self.actor, self.instance):
            raise ValidationError('Your Portal IT grant does not cover this entire report scope.')
        return values


class ScheduleForm(ScopedForm):
    recipients = forms.ModelMultipleChoiceField(queryset=ApprovedRecipient.objects.none(), required=False)
    class Meta:
        model = ReportSchedule
        fields = '__all__'
        widgets = {'send_time': forms.TimeInput(attrs={'type': 'time'})}

    def clean(self):
        values = super().clean()
        if len(values.get('recipients', [])) > 50:
            raise ValidationError('Use up to 50 approved recipients per schedule.')
        for recipient in values.get('recipients', []):
            try:
                validate_recipient(self.instance, recipient)
            except PermissionDenied:
                raise ValidationError('A recipient’s approving IT access is no longer valid.')
        if values.get('active') and not values.get('recipients'):
            raise ValidationError('Add at least one approved recipient before enabling this schedule.')
        return values


class RecipientForm(ScopedForm):
    class Meta:
        model = ApprovedRecipient
        fields = '__all__'

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()


class ScopedAdmin(ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_staff and can_manage(request.user)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and can_manage(request.user, obj)

    has_change_permission = has_view_permission

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return allowed_configurations(request.user, self.model)

    def get_form(self, request, obj=None, **kwargs):
        base = super().get_form(request, obj, **kwargs)
        class ActorForm(base):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                self.actor = request.user
                if 'recipients' in self.fields:
                    self.fields['recipients'].queryset = allowed_configurations(request.user, ApprovedRecipient).filter(active=True, suppressed=False)
        return ActorForm

    def save_model(self, request, obj, form, change):
        require_manage(request.user, obj)
        obj.authorized_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ApprovedRecipient)
class RecipientAdmin(ScopedAdmin):
    form = RecipientForm
    list_display = ('email', 'group_configuration', 'branch', 'product', 'active', 'suppressed')
    list_filter = ('active', 'suppressed', 'group_configuration')
    search_fields = ('email',)
    readonly_fields = ('authorized_by', 'suppression_reason', 'created_at', 'updated_at')


@admin.register(ReportSchedule)
class ScheduleAdmin(ScopedAdmin):
    form = ScheduleForm
    list_display = ('title', 'preset', 'group_configuration', 'frequency', 'active', 'next_run_at', 'controls')
    list_filter = ('preset', 'frequency', 'active', 'group_configuration')
    readonly_fields = ('authorized_by', 'revision', 'next_run_at', 'skipped_occurrences', 'created_at', 'updated_at', 'controls')

    def save_model(self, request, obj, form, change):
        if change:
            obj.revision += 1
        obj.next_run_at = next_occurrence(obj, timezone.now()) if obj.active else None
        super().save_model(request, obj, form, change)

    @admin.display(description='Delivery controls')
    def controls(self, obj):
        if not obj.pk:
            return 'Save to preview or send.'
        return format_html('<a href="{}">Preview / Send / Pause</a>', reverse('admin:report_schedule_controls', args=[obj.pk]))

    def get_urls(self):
        return [path('<uuid:schedule_id>/delivery/', self.admin_site.admin_view(self.control_view), name='report_schedule_controls')] + super().get_urls()

    def control_view(self, request, schedule_id):
        schedule = get_object_or_404(allowed_configurations(request.user, ReportSchedule), pk=schedule_id)
        if request.method == 'POST':
            action = request.POST.get('action')
            try:
                if action == 'preview':
                    from .rendering import report_pdf
                    response = HttpResponse(report_pdf(preview_report(schedule, request.user)), content_type='application/pdf')
                    response['Cache-Control'] = 'no-store'
                    response['Content-Disposition'] = 'inline; filename="portal-report-preview.pdf"'
                    return response
                elif action in {'send', 'test'}:
                    recipient_id = request.POST.get('recipient') if action == 'test' else None
                    if action == 'test' and not recipient_id:
                        raise ValidationError('Choose an approved test recipient.')
                    result = queue_schedule(schedule.pk, actor=request.user, request_key=request.POST.get('request_key'), recipient_id=recipient_id)
                    messages.success(request, f'{len(result)} recipient delivery(s) queued. The report runner sends them in the background.')
                    self.log_change(request, schedule, 'Queued report delivery: ' + action)
                elif action == 'pause':
                    require_manage(request.user, schedule)
                    ReportSchedule.objects.filter(pk=schedule.pk).update(active=False, next_run_at=None, revision=F('revision') + 1)
                    self.log_change(request, schedule, 'Paused report delivery')
                    messages.success(request, 'Schedule paused.')
                else:
                    raise ValidationError('Choose a valid delivery action.')
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
            return redirect('admin:report_schedule_controls', schedule.pk)
        return TemplateResponse(request, 'admin/report_delivery/controls.html', {
            **self.admin_site.each_context(request), 'title': schedule.title,
            'schedule': schedule, 'recipients': schedule.recipients.filter(active=True, suppressed=False),
            'deliveries': schedule.deliveries.select_related('recipient')[:20], 'request_key': str(uuid.uuid4()),
            'opts': self.model._meta,
        })


@admin.register(ReportDelivery)
class DeliveryAdmin(ModelAdmin):
    list_display = ('id', 'schedule', 'recipient', 'status', 'attempts', 'next_attempt_at', 'issue', 'retry_link')
    list_filter = ('status',)
    # Customer-bearing snapshots/attachments are never exposed as raw admin JSON.
    fields = ('schedule', 'recipient', 'occurrence', 'status', 'attempts', 'provider_id', 'payload_hash', 'first_attempt_at', 'next_attempt_at', 'last_event_at', 'issue', 'error_code', 'created_at', 'updated_at', 'retry_link')
    readonly_fields = fields

    def has_module_permission(self, request):
        return request.user.is_staff and can_manage(request.user)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and (obj is None or can_manage(request.user, obj.schedule))

    has_change_permission = has_view_permission

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return ReportDelivery.objects.filter(schedule__in=allowed_configurations(request.user, ReportSchedule)).select_related('schedule', 'recipient')

    @admin.display(description='Retry')
    def retry_link(self, obj):
        return format_html('<a href="{}">Review retry</a>', reverse('admin:report_delivery_retry', args=[obj.pk])) if obj.status in {'failed', 'blocked'} else '—'

    def get_urls(self):
        return [path('<uuid:delivery_id>/retry/', self.admin_site.admin_view(self.retry_view), name='report_delivery_retry')] + super().get_urls()

    def retry_view(self, request, delivery_id):
        delivery = get_object_or_404(self.get_queryset(request), pk=delivery_id)
        if request.method == 'POST':
            try:
                retry_delivery(delivery.pk, request.user)
                self.log_change(request, delivery, 'Retried unaccepted report delivery')
                messages.success(request, 'Delivery queued for retry.')
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
            return redirect('admin:report_delivery_reportdelivery_change', delivery.pk)
        return TemplateResponse(request, 'admin/report_delivery/retry.html', {
            **self.admin_site.each_context(request), 'title': 'Retry report delivery', 'delivery': delivery, 'opts': self.model._meta,
        })
