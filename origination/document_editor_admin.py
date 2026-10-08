"""Superuser-only independent document workspace, reusing catalogue records."""
import json
import uuid
from django import forms
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from origination.models import OriginationDocumentTemplate, OriginationDocumentProductEligibility
from core.models import Product
from origination.services.document_editor import require_editor, readiness, save_signers, copy_document, authoring_products


def editor_data(document):
    from origination.services.origination_setup_documents import shared_review
    from origination.services.origination_templates import _expected_signature_slots
    from origination.services.origination_fields import catalogue_for_product
    data = readiness(document)
    presentations = {f['key']:f for f in data['form_schema'].get('fields', [])}
    catalogue = catalogue_for_product(None)
    for field in catalogue:
        presentation = presentations.get(field['key'], {})
        field.update(attached=bool(presentation), required=bool(presentation.get('required')),
            label=presentation.get('label') or field['label'], section_key=presentation.get('section_key',''))
        for key in ('value_contract', 'source_type', 'help_text', 'width'):
            if key in presentation:
                field[key] = presentation[key]
    latest = document.configuration_revisions.order_by('-revision').first()
    return {'ok':True, 'readiness':data, 'schema_revision':data['schema_revision'], 'revision':data['revision'],
        'signers':data['signers'], 'context_keys':catalogue,
        'signature_slots':list(_expected_signature_slots(document.product_definition, document).values()),
        'form_sections':data['form_schema'].get('sections', []), 'shared_review':shared_review(document),
        'configuration':latest.configuration if latest else document.placement_config,
        'details':{'name':document.name,'products':[str(pk) for pk in document.eligible_products.values_list('pk',flat=True)],
                   'shared_values':data['form_schema'].get('value_contract_version') == 2}}


def write_view(admin, request, object_id):
    require_editor(request.user)
    if request.method != 'POST':
        return JsonResponse({'ok':False,'error':'POST required.'}, status=405)
    document = admin._calibration_template(request, object_id)
    try:
        body = admin._json_body(request)
        document = save_signers(document=document, rules=body.get('signers'), actor=request.user,
            schema_revision=int(body.get('schema_revision',0)), revision=int(body.get('revision',0)),
            configuration=body.get('configuration'), request_id=str(body.get('client_request_id') or ''),
            details=body.get('details'), field_pack=body.get('field_pack',''))
        return JsonResponse(editor_data(document))
    except Exception as exc:
        return admin._calibration_error_response(exc)


def readiness_view(admin, request, object_id):
    require_editor(request.user)
    return JsonResponse(editor_data(admin._calibration_template(request, object_id)))


def edit_view(admin, request, object_id):
    require_editor(request.user)
    document = admin._calibration_template(request, object_id)
    if document.status == 'ready' and not document.product_definition_id:
        return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[document.pk]))
    from origination.services.origination_templates import clone_reusable_template_version
    if request.method == 'POST':
        try:
            if request.POST.get('mode') == 'copy':
                if not request.POST.get('product'):
                    raise ValidationError('Choose the product for this copy.')
                document = copy_document(source=document, actor=request.user,
                    request_id=request.POST.get('request_id'), product_id=request.POST.get('product') or None,
                    replace=bool(request.POST.get('product')))
            elif request.POST.get('mode') == 'shared':
                document, _ = clone_reusable_template_version(document, actor=request.user)
            else:
                raise ValidationError('Choose who this change is for.')
            return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[document.pk]))
        except (ValidationError, ValueError) as exc:
            error = str(exc)
    else:
        error = ''
    return TemplateResponse(request, 'admin/origination/document_edit_choice.html', {
        **admin.admin_site.each_context(request), 'opts':admin.model._meta, 'title':'Edit document',
        'document':document, 'products':document.eligible_products.order_by('name'),
        'selected_product':request.POST.get('product') or request.GET.get('product',''),
        'request_id':request.POST.get('request_id') or str(uuid.uuid4()), 'error':error})


class NewDocumentForm(forms.Form):
    source = forms.ModelChoiceField(queryset=OriginationDocumentTemplate.objects.none(), required=False,
                                    label='Start from an existing document')
    name = forms.CharField(max_length=180, label='Document name')
    role = forms.ChoiceField(choices=OriginationDocumentTemplate.ROLE_CHOICES, label='Purpose')
    products = forms.ModelMultipleChoiceField(queryset=Product.objects.none(), required=False,
                                               widget=forms.CheckboxSelectMultiple, label='Used by products')
    pdf = forms.FileField(required=False, label='PDF', widget=forms.FileInput(attrs={'accept':'application/pdf'}))
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source'].queryset = OriginationDocumentTemplate.objects.filter(status__in=['ready', 'active']).order_by('name')
        self.fields['products'].queryset = authoring_products().order_by('name')
        self.initial.setdefault('role','primary')
    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('source') and not cleaned.get('pdf'):
            self.add_error('pdf','Choose an existing document or upload a PDF.')
        if cleaned.get('source') and cleaned.get('pdf'):
            self.add_error('source','Choose a copy or upload a new PDF, not both.')
        return cleaned


def new_view(admin, request):
    require_editor(request.user)
    form = NewDocumentForm(request.POST or None, request.FILES or None,
        initial={'source':request.GET.get('source'), 'products':[request.GET['product']] if request.GET.get('product') else []})
    error = ''
    request_id = request.POST.get('request_id') or str(uuid.uuid4())
    if request.method == 'POST' and form.is_valid():
        try:
            from origination.services.document_editor import create_document
            document = create_document(actor=request.user, request_id=request_id, **form.cleaned_data)
            if document.status == 'upload_failed':
                raise ValidationError(document.upload_error or 'Could not upload. Try again.')
            return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[document.pk]))
        except (ValidationError, ValueError) as exc:
            error = str(exc)
    return TemplateResponse(request, 'admin/origination/document_new.html', {
        **admin.admin_site.each_context(request), 'opts':admin.model._meta, 'title':'New document',
        'form':form, 'error':error, 'request_id':request_id})
