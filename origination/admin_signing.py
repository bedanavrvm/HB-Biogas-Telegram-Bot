"""Guided signer editing; writes cross the same audited plan seam as tests."""
from django import forms
from django.contrib.auth import get_user_model
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.template.response import TemplateResponse
from django.core.exceptions import PermissionDenied
from uuid import uuid4
from unfold.widgets import UnfoldAdminSelect2Widget

from origination.services.origination_signing_plans import candidates, configure_plan, enabled
from origination.services.loan_origination import OriginationError, OriginationConflict


class ApplicationSignersForm(forms.Form):
    revision = forms.IntegerField(widget=forms.HiddenInput)
    plan_revision = forms.IntegerField(widget=forms.HiddenInput)
    request_id = forms.CharField(max_length=128, widget=forms.HiddenInput)

    def __init__(self, *args, application, **kwargs):
        super().__init__(*args, **kwargs)
        from origination.services.origination_esign import STAFF_SIGNER_ROLES, authorize_staff_signer
        self.rows = []
        current = {row.participant_key: row for row in application.signing_participants.filter(
            pk__in=application.signing_plan.get('participants', []))}
        self.initial.update(revision=application.revision, plan_revision=application.signing_plan_revision, request_id=str(uuid4()))
        for index, (key, config) in enumerate(sorted(candidates(application).items(), key=lambda item: item[1]['role'] in STAFF_SIGNER_ROLES)):
            checked = f'participant_{index}'
            assigned = f'assigned_{index}'
            label = str(config.get('label') or config['role']).replace('_', ' ').title()
            person = (config.get('identity') or {}).get('name', '')
            mandatory = bool(config.get('required') or any(slot.get('required') for slot in config.get('slots', [])))
            self.fields[checked] = forms.BooleanField(required=False, label=label,
                initial=key in current or mandatory, disabled=mandatory,
                widget=forms.CheckboxInput(attrs={'aria-label': f'Require {label}'}))
            staff = config['role'] in STAFF_SIGNER_ROLES
            if staff:
                allowed = []
                for user in get_user_model().objects.filter(is_active=True).order_by('username'):
                    try:
                        authorize_staff_signer(actor=user, application=application, signer_role=config['role'])
                        if config['role'] == 'officer' and user.pk != application.officer_id:
                            continue
                        allowed.append(user.pk)
                    except OriginationError:
                        continue
                self.fields[assigned] = forms.ModelChoiceField(required=config['role']=='officer',
                    queryset=get_user_model().objects.filter(pk__in=allowed).order_by('username'),
                    label=f'{label} assigned to', empty_label=f'Any eligible {label.lower()}',
                    widget=UnfoldAdminSelect2Widget,
                    initial=current[key].staff_user_id if key in current else application.officer_id if config['role'] == 'officer' else None)
                self.fields[assigned].widget.attrs.update({'aria-label': f'{label} assigned to'})
                self.fields[assigned].label_from_instance = lambda user: user.get_full_name() or user.get_username()
            self.rows.append({'key': key, 'selected': self[checked],
                'assigned': self[assigned] if staff else None, 'label': label, 'name': person,
                'staff': staff, 'required': mandatory,
                'documents': list(dict.fromkeys(slot.get('document_key', 'primary') for slot in config.get('slots', [])))})

    def choices(self):
        return [{'participant_key': row['key'],
                 'staff_user_id': self.cleaned_data[row['assigned'].name].pk
                 if row['assigned'] and self.cleaned_data.get(row['assigned'].name) else None}
                for row in self.rows if self.cleaned_data.get(row['selected'].name)]


def application_signers_view(model_admin, request, object_id):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    application = model_admin.get_object(request, object_id)
    if application is None or not enabled(application):
        return JsonResponse({'ok': False, 'error': 'This application retains its original signing policy.'}, status=404)
    editable = application.status == 'draft'
    form = ApplicationSignersForm(request.POST if request.method == 'POST' else None, application=application)
    error = ''
    status = 200
    if request.method == 'POST':
        if form.is_valid():
            try:
                application = configure_plan(application_id=application.pk, actor=request.user,
                    choices=form.choices(), expected_revision=form.cleaned_data['revision'],
                    expected_plan_revision=form.cleaned_data['plan_revision'], request_id=form.cleaned_data['request_id'])
                if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
                    return HttpResponseRedirect(reverse('admin:origination_application_signers', args=[application.pk]))
                return JsonResponse({'ok': True, 'message': 'Saved', 'revision': application.revision,
                    'plan_revision': application.signing_plan_revision})
            except OriginationConflict as exc:
                error, status = str(exc), 409
            except OriginationError as exc:
                error, status = str(exc), 400
        else:
            error, status = 'Check the highlighted signer fields.', 400
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': error, 'errors': form.errors.get_json_data()}, status=status)
    context = {**model_admin.admin_site.each_context(request), 'opts': model_admin.model._meta,
        'original': application, 'title': f'Signers · {application.reference_number}',
        'form': form, 'editable': editable, 'error': error}
    return TemplateResponse(request, 'admin/origination/application_signers.html', context, status=status)
