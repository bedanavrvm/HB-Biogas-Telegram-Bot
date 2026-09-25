import io
import logging
import os
import re
import uuid
from xml.sax.saxutils import escape

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.text import slugify
from unfold.admin import ModelAdmin

from core.models import AccessGrant, GroupSheetConfiguration
from core.services.order_approval import GoogleDriveMediaStorage
from .models import TestCase, TestCycle, TestEvidence, TestRun
from .services import WORKFLOWS, allowed_cycles, attach_screenshot, can_create_cycle, cycle_summary, record_result, require_cycle

logger = logging.getLogger(__name__)


def _qa_staff(user):
    return bool(user.is_active and user.is_staff and (
        user.is_superuser or AccessGrant.objects.filter(user=user, active=True, role__iexact='IT', workflow__in=set(WORKFLOWS.values())).exists()
    ))


class QaAdmin(ModelAdmin):
    def has_module_permission(self, request):
        return _qa_staff(request.user)

    def has_view_permission(self, request, obj=None):
        return _qa_staff(request.user)

    def has_add_permission(self, request):
        return _qa_staff(request.user)

    def has_change_permission(self, request, obj=None):
        return _qa_staff(request.user)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TestCase)
class TestCaseAdmin(QaAdmin):
    list_display = ('id', 'app', 'journey', 'description', 'priority', 'automation_gap', 'active')
    list_filter = ('app', 'journey', 'priority', 'automation_gap', 'active')
    search_fields = ('id', 'description', 'journey')
    readonly_fields = ('id', 'created_at')

    def get_readonly_fields(self, request, obj=None):
        return ('id', 'app', 'created_at') if obj else ('created_at',)

class CycleForm(forms.ModelForm):
    class Meta:
        model = TestCycle
        fields = ('app', 'release', 'environment', 'build_commit', 'group_configuration', 'branch', 'product')
        widgets = {'app': forms.Select(choices=[(key, key.replace('_', ' ').title()) for key in WORKFLOWS])}


@admin.register(TestCycle)
class TestCycleAdmin(QaAdmin):
    form = CycleForm
    list_display = ('app', 'release', 'environment', 'group_configuration', 'branch', 'product', 'created_at', 'run_link', 'report_link')
    list_filter = ('app', 'environment', 'group_configuration')
    search_fields = ('release', 'build_commit')
    readonly_fields = ('created_by', 'created_at')

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        configured_release = str(getattr(settings, 'APP_RELEASE', '') or '').strip()
        render_commit = str(os.environ.get('RENDER_GIT_COMMIT', '') or '').strip()
        commit = render_commit if re.fullmatch(r'[0-9a-fA-F]{7,40}', render_commit) else ''
        if not commit and re.fullmatch(r'[0-9a-fA-F]{7,40}', configured_release):
            commit = configured_release
        release = configured_release if 0 < len(configured_release) <= 80 else commit
        environment = str(getattr(settings, 'RELEASE_ENVIRONMENT', '') or '').strip().lower()
        if release:
            initial.setdefault('release', release)
        if commit:
            initial.setdefault('build_commit', commit)
        if environment in dict(TestCycle._meta.get_field('environment').choices):
            initial.setdefault('environment', environment)
        return initial

    def get_queryset(self, request):
        return allowed_cycles(request.user).select_related('group_configuration')

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in TestCycle._meta.fields) if obj else self.readonly_fields

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'group_configuration' and not request.user.is_superuser:
            grants = AccessGrant.objects.filter(user=request.user, active=True, role__iexact='IT', workflow__in=set(WORKFLOWS.values()))
            if not grants.filter(group_configuration__isnull=True).exists():
                kwargs['queryset'] = GroupSheetConfiguration.objects.filter(pk__in=grants.values_list('group_configuration_id', flat=True))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if change:
            raise PermissionDenied
        if not can_create_cycle(request.user, obj):
            raise PermissionDenied
        obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description='Checklist')
    def run_link(self, obj):
        return format_html('<a href="{}">Run checklist</a>', reverse('admin:qa_tracker_cycle_run', args=[obj.pk]))

    @admin.display(description='Report')
    def report_link(self, obj):
        return format_html('<a href="{}">Download PDF</a>', reverse('admin:qa_tracker_cycle_report', args=[obj.pk]))

    def get_urls(self):
        return [
            path('<uuid:cycle_id>/run/', self.admin_site.admin_view(self.run_view), name='qa_tracker_cycle_run'),
            path('<uuid:cycle_id>/report/', self.admin_site.admin_view(self.report_view), name='qa_tracker_cycle_report'),
            path('<uuid:cycle_id>/evidence/<uuid:evidence_id>/', self.admin_site.admin_view(self.evidence_view), name='qa_tracker_cycle_evidence'),
            path('<uuid:cycle_id>/runs/<uuid:run_id>/evidence/', self.admin_site.admin_view(self.add_evidence_view), name='qa_tracker_add_evidence'),
        ] + super().get_urls()

    def _cycle(self, request, cycle_id):
        return get_object_or_404(allowed_cycles(request.user), pk=cycle_id)

    def run_view(self, request, cycle_id):
        cycle = self._cycle(request, cycle_id)
        if request.method == 'POST':
            try:
                case = get_object_or_404(TestCase, pk=request.POST.get('test_case_id'), app=cycle.app)
                run = record_result(
                    cycle, case, request.user, result=request.POST.get('result', ''),
                    severity=request.POST.get('severity', ''), bug_reference=request.POST.get('bug_reference', ''),
                    notes=request.POST.get('notes', ''), request_key=request.POST.get('request_key', ''),
                )
                upload = request.FILES.get('screenshot')
                if upload:
                    try:
                        if run.evidence.count() >= 5:
                            raise ValidationError('This result already has five screenshots.')
                        attach_screenshot(run, upload)
                    except ValidationError as exc:
                        messages.warning(request, f'Result saved, but the screenshot was not attached: {exc}')
                    except Exception:
                        logger.exception('QA screenshot upload failed: run_id=%s', run.pk)
                        messages.warning(request, 'Result saved, but the screenshot could not be stored. Try attaching it again.')
                    else:
                        messages.success(request, f'{case.pk}: result and screenshot saved.')
                else:
                    messages.success(request, f'{case.pk}: result saved.')
            except (ValidationError, ValueError, TypeError) as exc:
                messages.error(request, f'Result not saved: {exc}')
            return redirect('admin:qa_tracker_cycle_run', cycle_id=cycle.pk)
        summary = cycle_summary(cycle)
        for row in summary['rows']:
            row['request_key'] = uuid.uuid4()
            row['evidence'] = list(row['run'].evidence.all()) if row['run'] else []
        context = {
            **self.admin_site.each_context(request), 'title': f'QA checklist · {cycle.release}',
            'cycle': cycle, 'summary': summary, 'opts': self.model._meta,
            'run_url': reverse('admin:qa_tracker_cycle_run', args=[cycle.pk]),
            'report_url': reverse('admin:qa_tracker_cycle_report', args=[cycle.pk]),
        }
        return TemplateResponse(request, 'admin/qa_tracker/checklist.html', context)

    def add_evidence_view(self, request, cycle_id, run_id):
        cycle = self._cycle(request, cycle_id)
        if request.method != 'POST':
            raise Http404
        run = get_object_or_404(TestRun, pk=run_id, cycle=cycle)
        upload = request.FILES.get('screenshot')
        if not upload:
            messages.error(request, 'Choose a screenshot to attach.')
        else:
            try:
                if run.evidence.count() >= 5:
                    raise ValidationError('This result already has five screenshots.')
                attach_screenshot(run, upload)
            except ValidationError as exc:
                messages.error(request, f'Screenshot not attached: {exc}')
            except Exception:
                logger.exception('QA screenshot upload failed: run_id=%s', run.pk)
                messages.error(request, 'Screenshot could not be stored. Try again.')
            else:
                messages.success(request, 'Screenshot attached.')
        return redirect('admin:qa_tracker_cycle_run', cycle_id=cycle.pk)

    def evidence_view(self, request, cycle_id, evidence_id):
        cycle = self._cycle(request, cycle_id)
        evidence = get_object_or_404(TestEvidence, pk=evidence_id, run__cycle=cycle)
        data = GoogleDriveMediaStorage().download(evidence.drive_file_id)
        response = HttpResponse(data, content_type=evidence.mime_type)
        response['Content-Disposition'] = f'inline; filename="{evidence.filename}"'
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    def report_view(self, request, cycle_id):
        cycle = self._cycle(request, cycle_id)
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
        from PIL import Image as PillowImage

        summary = cycle_summary(cycle)
        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = [Paragraph(f'QA report: {escape(cycle.app)} · {escape(cycle.release)}', styles['Title']),
                 Paragraph(f'{escape(cycle.environment)} · Group {cycle.group_configuration_id} · Branch {escape(cycle.branch or "All")} · Product {escape(cycle.product or "All")}', styles['Normal']),
                 Paragraph(f'Build: {escape(cycle.build_commit or "Not recorded")}', styles['Normal']), Spacer(1, 12)]
        counts = summary['counts']
        metrics = [['Active', 'Tested', 'Pass', 'Fail', 'Blocked', 'Untested', 'Regressions'],
                   [counts['total'], counts['tested'], counts['pass'], counts['fail'], counts['blocked'], counts['untested'], counts['regressions']]]
        table = Table(metrics, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8eef5')),
                                   ('GRID', (0, 0), (-1, -1), 0.3, colors.grey), ('PADDING', (0, 0), (-1, -1), 5)]))
        story.extend([table, Spacer(1, 14)])
        for row in summary['rows']:
            case, run = row['case'], row['run']
            status = run.get_result_display() if run else 'Untested'
            heading = f'{escape(case.pk)} · {escape(status)} · {escape(case.description)}'
            section = [Paragraph(heading, styles['Heading3'])]
            if row['change']:
                section.append(Paragraph(f'Change: {escape(row["change"])}', styles['Normal']))
            if run:
                section.append(Paragraph(f'Tester: {escape(run.tester.get_username() if run.tester else "Former user")} · {run.created_at:%d-%m-%Y %H:%M %Z}', styles['Normal']))
                if run.severity or run.bug_reference:
                    section.append(Paragraph(f'Severity: {escape(run.severity or "—")} · Bug: {escape(run.bug_reference or "—")}', styles['Normal']))
                if run.notes:
                    section.append(Paragraph(escape(run.notes).replace('\n', '<br/>'), styles['Normal']))
                for evidence in run.evidence.all()[:5]:
                    try:
                        data = GoogleDriveMediaStorage().download(evidence.drive_file_id)
                        with PillowImage.open(io.BytesIO(data)) as img:
                            width, height = img.size
                        scale = min(500 / width, 420 / height, 1)
                        section.append(Image(io.BytesIO(data), width=width * scale, height=height * scale))
                    except Exception:
                        section.append(Paragraph(f'Screenshot unavailable: {escape(str(evidence.pk))}', styles['Normal']))
            section.append(Spacer(1, 8))
            story.extend(section)
        doc.build(story)
        response = HttpResponse(output.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="qa-{cycle.app}-{slugify(cycle.release)[:40] or "release"}.pdf"'
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


@admin.register(TestRun)
class TestRunAdmin(QaAdmin):
    list_display = ('test_case', 'cycle', 'result', 'severity', 'tester', 'created_at')
    list_filter = ('result', 'severity', 'cycle__app', 'cycle__environment')
    search_fields = ('test_case__id', 'cycle__release', 'bug_reference')
    readonly_fields = tuple(field.name for field in TestRun._meta.fields)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(cycle__in=allowed_cycles(request.user))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)
