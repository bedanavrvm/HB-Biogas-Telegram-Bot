"""Admin views for the guided Origination product setup workspace."""

from __future__ import annotations

import json
import re
import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse

from origination.models import (
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
)
from core.models import Product, ProductAvailability, ProductVersion, ProductVersionEvent
from origination.origination_setup_forms import (
    AttributeFormSet,
    FeeFormSet,
    RequirementFormSet,
    SetupIdentityForm,
    SetupTermsForm,
    SetupCatalogueSelectionForm,
    SetupCatalogueUploadForm,
)
from origination.services.origination_setup import (
    SETUP_STEPS,
    OriginationSetupConflict,
    assert_expected_state,
    completed_request,
    make_return_token,
    record_step_completion,
    resume_step,
    setup_readiness,
    state_token,
    step_tokens,
)


def _guard(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied


def _request_id(request) -> str:
    value = re.sub(
        r'[^A-Za-z0-9._-]', '',
        str(request.POST.get('request_id') or uuid.uuid4()),
    )[:128]
    return value or str(uuid.uuid4())


def _expected_tokens(request) -> dict[str, str]:
    try:
        value = json.loads(request.POST.get('expected_tokens') or '{}')
    except (TypeError, ValueError):
        raise ValidationError('Reload this setup before saving; its concurrency token is invalid.')
    if not isinstance(value, dict) or not value:
        raise ValidationError('Reload this setup before saving; its concurrency token is missing.')
    return {str(key): str(token) for key, token in value.items()}


def _workspace_url(definition, step_key=None):
    if step_key:
        return reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, step_key],
        )
    return reverse('admin:origination_origination_setup_workspace', args=[definition.pk])


def _definition(object_id, *, lock=False):
    if lock:
        # Lock nullable relations explicitly. PostgreSQL rejects FOR UPDATE on
        # the nullable side of a select_related() outer join.
        definition = OriginationProductDefinition.objects.select_for_update().filter(
            pk=object_id,
        ).first()
        if not definition:
            return None
        if definition.product_version_id:
            version = ProductVersion.objects.select_for_update().select_related(
                'product',
            ).get(pk=definition.product_version_id)
            Product.objects.select_for_update().get(pk=version.product_id)
            list(version.fees.select_for_update())
            list(version.requirements.select_for_update())
            list(version.custom_attributes.select_for_update())
            list(version.product.availability_assignments.select_for_update().filter(
                workflow='loan_origination',
            ))
            definition._state.fields_cache['product_version'] = version
        return definition
    return OriginationProductDefinition.objects.select_related(
        'product_version__product', 'created_by', 'published_by',
    ).filter(pk=object_id).first()


def dashboard_view(model_admin, request):
    _guard(request)
    drafts = list(
        OriginationProductDefinition.objects.filter(
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
        ).select_related('product_version__product', 'created_by').order_by('-updated_at')
    )
    draft_rows = [
        {
            'definition': item,
            'readiness': setup_readiness(item),
            'resume_url': _workspace_url(item),
            'resume_label': dict(SETUP_STEPS).get(resume_step(item), 'Resume setup'),
        }
        for item in drafts
    ]
    latest_ids = []
    for code in OriginationProductDefinition.objects.filter(
        lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
    ).values_list(
        'product_key', flat=True,
    ).distinct():
        latest = OriginationProductDefinition.objects.filter(
            product_key=code,
            lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
        ).order_by('-version').values_list('pk', flat=True).first()
        if latest:
            latest_ids.append(latest)
    published = OriginationProductDefinition.objects.filter(
        pk__in=latest_ids,
        lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
    ).select_related('product_version__product').order_by('name')
    from origination.services.origination_document_catalogue import catalogue_for_product, catalogue_revision
    current_catalogue_revision = catalogue_revision()
    published_product_rows = [
        {
            'definition': item,
            'catalogue': catalogue_for_product(item, revision=current_catalogue_revision),
        }
        for item in published
    ]
    return TemplateResponse(request, 'admin/core/origination_setup/dashboard.html', {
        **model_admin.admin_site.each_context(request),
        'opts': model_admin.model._meta,
        'title': 'Origination product setup',
        'draft_rows': draft_rows,
        'published_products': published,
        'published_product_rows': published_product_rows,
        'start_form': SetupIdentityForm(),
        'request_id': str(uuid.uuid4()),
        'start_url': reverse('admin:origination_origination_setup_start'),
        'advanced_url': reverse('admin:origination_originationproductdefinition_changelist'),
        'laf_library_url': reverse('admin:origination_originationdocumenttemplate_changelist'),
    })


def detail_view(model_admin, request, object_id):
    """Read-only, family-wide view of an Origination product contract."""

    _guard(request)
    selected = _definition(object_id)
    if not selected or not selected.product_version_id:
        return HttpResponse(status=404)
    product = selected.product_version.product
    from origination.services.origination_document_catalogue import catalogue_for_product
    document_catalogue = catalogue_for_product(selected)
    from origination.services.origination_templates import resolve_assignment_template
    from core.services.product_availability import (
        CANONICAL_PRODUCT_CHANNEL, PRODUCT_WORKFLOW_CHOICES,
    )
    workflow_labels = dict(PRODUCT_WORKFLOW_CHOICES)
    availability = list(product.availability_assignments.select_related('branch').filter(
        active=True, channel=CANONICAL_PRODUCT_CHANNEL,
        workflow__in=workflow_labels,
    ).order_by('workflow', 'branch__sort_order', 'branch__name'))
    for assignment in availability:
        assignment.workflow_label = workflow_labels.get(
            assignment.workflow, assignment.workflow or 'All workflows',
        )
    versions = list(OriginationProductDefinition.objects.filter(
        product_key=selected.product_key,
    ).select_related(
        'product_version', 'created_by', 'published_by', 'supersedes',
    ).prefetch_related(
        'product_version__fees', 'product_version__requirements',
        'product_version__custom_attributes', 'document_templates',
        'document_assignments__template__published_configuration_revision',
    ).order_by('-version'))
    rows = []
    for definition in versions:
        schema = definition.form_schema if isinstance(definition.form_schema, dict) else {}
        sections = {
            str(item.get('key') or ''): str(item.get('label') or item.get('key') or '')
            for item in schema.get('sections', []) if isinstance(item, dict)
        }
        fields = []
        for item in schema.get('fields', []):
            if not isinstance(item, dict):
                continue
            fields.append({
                'key': str(item.get('key') or ''),
                'label': str(item.get('label') or item.get('key') or ''),
                'type': str(item.get('type') or item.get('control') or 'text'),
                'required': bool(item.get('required')),
                'width': str(item.get('width') or ''),
                'section': sections.get(
                    str(item.get('section_key') or ''),
                    str(item.get('section_key') or 'Unsectioned'),
                ),
            })
        signers = []
        for item in definition.signer_rules if isinstance(definition.signer_rules, list) else []:
            if not isinstance(item, dict):
                continue
            signers.append({
                'role': str(item.get('label') or item.get('role') or ''),
                'required': bool(item.get('required')),
                'slots': [
                    str(slot.get('label') or slot.get('key') or '')
                    for slot in item.get('slots', []) if isinstance(slot, dict)
                ],
            })
        documents = []
        for template in definition.document_templates.all():
            documents.append({
                'name': template.name,
                'source': 'Product-owned',
                'role': template.get_document_role_display(),
                'inclusion': template.get_inclusion_mode_display(),
                'version_policy': f'Pinned to v{template.version}',
                'resolved': template,
                'calibrated': bool(template.published_configuration_revision_id),
                'detail_url': reverse(
                    'admin:origination_originationdocumenttemplate_change', args=[template.pk],
                ),
                'calibration_url': reverse(
                    'admin:origination_originationdocumenttemplate_calibrate', args=[template.pk],
                ) if template.drive_file_id else '',
            })
        for assignment in definition.document_assignments.all():
            resolved = resolve_assignment_template(assignment)
            documents.append({
                'name': assignment.name,
                'source': 'Reusable library',
                'role': assignment.template.get_document_role_display(),
                'inclusion': assignment.get_inclusion_mode_display(),
                'version_policy': assignment.get_version_policy_display(),
                'resolved': resolved,
                'calibrated': bool(
                    resolved and resolved.published_configuration_revision_id
                ),
                'detail_url': reverse(
                    'admin:origination_originationdocumenttemplate_change',
                    args=[resolved.pk if resolved else assignment.template_id],
                ),
                'calibration_url': reverse(
                    'admin:origination_originationdocumenttemplate_calibrate',
                    args=[resolved.pk],
                ) if resolved and resolved.drive_file_id else '',
            })
        rows.append({
            'definition': definition,
            'terms': definition.product_version,
            'fields': fields,
            'sections': list(sections.values()),
            'signers': signers,
            'documents': sorted(
                documents,
                key=lambda item: (item['role'] != 'Primary LAF', item['name']),
            ),
            'readiness': setup_readiness(definition),
            'advanced_url': reverse(
                'admin:origination_originationproductdefinition_change', args=[definition.pk],
            ),
        })
    return TemplateResponse(
        request, 'admin/core/origination_setup/detail.html', {
            **model_admin.admin_site.each_context(request),
            'opts': model_admin.model._meta,
            'title': f'{selected.name} product overview',
            'selected': selected,
            'product': product,
            'availability': availability,
            'document_catalogue': document_catalogue,
            'document_catalogue_url': reverse('admin:origination_originationdocumenttemplate_changelist'),
            'version_rows': rows,
            'dashboard_url': reverse('admin:origination_origination_setup_dashboard'),
            'availability_url': reverse(
                'admin:core_product_availability', args=[product.pk],
            ),
            'version_history_url': reverse(
                'admin:origination_originationproductdefinition_version_history',
                args=[selected.pk],
            ),
            'revise_url': reverse(
                'admin:origination_origination_setup_revise', args=[selected.pk],
            ),
            'request_id': str(uuid.uuid4()),
        },
    )


def start_view(model_admin, request):
    _guard(request)
    if request.method != 'POST':
        response = HttpResponse(status=405)
        response['Allow'] = 'POST'
        return response
    request_id = _request_id(request)
    replay = ProductVersionEvent.objects.filter(
        action='setup_started', metadata__request_id=request_id,
    ).select_related('product_version').first()
    if replay:
        definition = replay.product_version.origination_definitions.order_by('-version').first()
        if definition:
            return HttpResponseRedirect(_workspace_url(definition))
    form = SetupIdentityForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Check the highlighted product details and try again.')
        return _dashboard_with_form(model_admin, request, form)
    with transaction.atomic():
        product = form.save(commit=False)
        product.active = False
        product.save()
        version = ProductVersion.objects.create(
            product=product, version=1, created_by=request.user,
        )
        _sync_availability(product, form.cleaned_data['branches'])
        from origination.services.origination_commercial_terms import (
            ensure_commercial_catalogue, merge_commercial_contract,
        )
        schema = merge_commercial_contract(
            {'_revision': 0, 'sections': [], 'fields': []},
            fields=ensure_commercial_catalogue(actor=request.user),
        )
        definition = OriginationProductDefinition.objects.create(
            product_version=version, product_key=product.code, name=product.name,
            version=1, form_schema=schema, signer_rules=[],
            document_type=product.code, document_template_version=1,
            created_by=request.user,
        )
        ProductVersionEvent.objects.create(
            product_version=version, action='setup_started', actor=request.user,
            metadata={'request_id': request_id, 'definition_id': str(definition.pk)},
        )
        OriginationProductDefinitionEvent.objects.create(
            product_definition=definition, action='created', actor=request.user,
            metadata={'request_id': request_id, 'source': 'guided_setup'},
        )
        record_step_completion(
            definition=definition, step_key='identity', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, 'Product draft created. Add its commercial terms next.')
    return HttpResponseRedirect(_workspace_url(definition, 'terms'))


def _dashboard_with_form(model_admin, request, form):
    return TemplateResponse(request, 'admin/core/origination_setup/dashboard.html', {
        **model_admin.admin_site.each_context(request),
        'opts': model_admin.model._meta,
        'title': 'Origination product setup', 'start_form': form,
        'draft_rows': [], 'published_products': [],
        'request_id': request.POST.get('request_id') or str(uuid.uuid4()),
        'start_url': reverse('admin:origination_origination_setup_start'),
        'advanced_url': reverse('admin:origination_originationproductdefinition_changelist'),
        'laf_library_url': reverse('admin:origination_originationdocumenttemplate_changelist'),
    }, status=400)


def workspace_view(model_admin, request, object_id):
    _guard(request)
    definition = _definition(object_id)
    if not definition:
        return HttpResponse(status=404)
    return HttpResponseRedirect(_workspace_url(definition, resume_step(definition)))


def revise_view(model_admin, request, object_id):
    _guard(request)
    if request.method != 'POST':
        response = HttpResponse(status=405)
        response['Allow'] = 'POST'
        return response
    source = _definition(object_id)
    if not source:
        return HttpResponse(status=404)
    try:
        request_id = _request_id(request)
        from origination.services.origination_templates import clone_product_version
        successor = clone_product_version(source, actor=request.user)
        if source.product_version_id:
            from core.services.product_catalog import clone_product_version as clone_terms
            draft_terms = clone_terms(source.product_version, actor=request.user)
            if successor.product_version_id != draft_terms.pk:
                successor.product_version = draft_terms
                successor.product_key = draft_terms.product.code
                successor.name = draft_terms.product.name
                successor.save(update_fields=[
                    'product_version', 'product_key', 'name', 'updated_at',
                ])
        ProductVersionEvent.objects.get_or_create(
            product_version=successor.product_version,
            action='setup_started', metadata__request_id=request_id,
            defaults={
                'actor': request.user,
                'metadata': {
                    'request_id': request_id, 'definition_id': str(successor.pk),
                    'maintenance_successor': True,
                },
            },
        )
        OriginationProductDefinitionEvent.objects.get_or_create(
            product_definition=successor,
            action='setup_started', metadata__request_id=request_id,
            defaults={
                'actor': request.user,
                'metadata': {
                    'request_id': request_id, 'source_id': str(source.pk),
                    'maintenance_successor': True,
                },
            },
        )
        record_step_completion(
            definition=successor, step_key='identity', actor=request.user,
            request_id=request_id,
        )
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(reverse('admin:origination_origination_setup_dashboard'))
    messages.success(request, f'Editable version {successor.version} is ready.')
    return HttpResponseRedirect(_workspace_url(successor))


def _sync_availability(product, branches):
    selected = {item.pk for item in branches}
    existing = product.availability_assignments.filter(workflow='loan_origination')
    existing.exclude(channel='portal').update(active=False)
    existing.filter(channel='portal').exclude(branch_id__in=selected).update(active=False)
    for branch in branches:
        ProductAvailability.objects.update_or_create(
            product=product,
            scope_signature=f'branch:{branch.pk}|workflow:loan_origination|channel:portal',
            defaults={
                'branch': branch, 'workflow': 'loan_origination',
                'channel': 'portal', 'active': True,
            },
        )


def _base_context(model_admin, request, definition, step_key):
    rows = setup_readiness(definition)
    keys = [key for key, _label in SETUP_STEPS]
    return {
        **model_admin.admin_site.each_context(request),
        'opts': model_admin.model._meta,
        'title': f'Set up {definition.name}',
        'definition': definition,
        'step_key': step_key,
        'step_label': dict(SETUP_STEPS)[step_key],
        'previous_url': _workspace_url(definition, keys[keys.index(step_key) - 1]) if keys.index(step_key) else '',
        'steps': [
            {**row, 'url': _workspace_url(definition, row['key'])}
            for row in rows
        ],
        'expected_tokens': json.dumps(step_tokens(definition), sort_keys=True),
        'workspace_token': state_token(definition),
        'request_id': str(uuid.uuid4()),
        'dashboard_url': reverse('admin:origination_origination_setup_dashboard'),
        'advanced_url': reverse(
            'admin:origination_originationproductdefinition_change', args=[definition.pk],
        ),
        'published_readonly': definition.lifecycle_status != definition.STATUS_DRAFT,
    }


def step_view(model_admin, request, object_id, step_key):
    _guard(request)
    if step_key in {'form', 'calibration'}:
        return HttpResponseRedirect(reverse(
            'admin:origination_origination_setup_step', args=[object_id, 'documents'],
        ))
    if step_key == 'terms_publish':
        definition = _definition(object_id)
        if not definition:
            return HttpResponse(status=404)
        messages.info(request, 'Financial terms are published with the product at final review.')
        return HttpResponseRedirect(_workspace_url(definition, 'publish'))
    if step_key not in dict(SETUP_STEPS):
        return HttpResponse(status=404)
    definition = _definition(object_id)
    if not definition:
        return HttpResponse(status=404)
    if not definition.product_version_id:
        messages.warning(request, 'Connect this legacy product to its commercial terms before guided setup.')
        return HttpResponseRedirect(reverse('admin:origination_origination_setup_detail', args=[definition.pk]))
    if (request.method == 'POST' and step_key != 'documents' and definition.lifecycle_status != definition.STATUS_DRAFT
            and not completed_request(definition=definition, step_key=step_key, request_id=_request_id(request))):
        messages.error(request, 'Published versions are immutable. Create an editable successor.')
        return HttpResponseRedirect(_workspace_url(definition, step_key))
    context = _base_context(model_admin, request, definition, step_key)
    handler = globals()[f'_step_{step_key}']
    try:
        if request.method == 'POST':
            posted_request_id = _request_id(request)
            if completed_request(
                definition=definition, step_key=step_key,
                request_id=posted_request_id,
            ):
                if step_key == 'documents' and request.POST.get('action') == 'upload':
                    uploaded = definition.events.filter(action='setup_pdf_uploaded',
                        metadata__request_id=posted_request_id).first()
                    if uploaded:
                        return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate',
                            args=[uploaded.metadata['template_id']]) + '?setup_return=' + make_return_token(
                                definition_id=definition.pk, step_key='documents'))
                if request.POST.get('intent') == 'stay':
                    return HttpResponseRedirect(_workspace_url(definition, step_key))
                keys = [key for key, _label in SETUP_STEPS]
                next_key = keys[keys.index(step_key) + 1] if step_key != 'publish' else ''
                return HttpResponseRedirect(
                    _workspace_url(definition, next_key)
                    if next_key else reverse('admin:origination_origination_setup_dashboard')
                )
        response = handler(model_admin, request, definition, context)
    except OriginationSetupConflict as exc:
        labels = dict(SETUP_STEPS)
        context['conflict'] = {
            'changed': list(dict.fromkeys(labels.get(key, 'Documents') for key in exc.changed_steps)),
            'submitted': request.POST,
        }
        context['form'] = context.get('form') or SetupIdentityForm(
            request.POST, instance=definition.product_version.product,
        )
        return TemplateResponse(
            request, 'admin/core/origination_setup/workspace.html', context, status=409,
        )
    except (ValidationError, ValueError) as exc:
        context['step_error'] = (
            '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        )
        return TemplateResponse(
            request, 'admin/core/origination_setup/workspace.html', context, status=400,
        )
    return response or TemplateResponse(
        request, 'admin/core/origination_setup/workspace.html', context,
    )


def _check_locked(definition, request, step_key=None):
    locked = _definition(definition.pk, lock=True)
    if (locked.lifecycle_status != locked.STATUS_DRAFT
            and not (step_key == 'documents' and locked.lifecycle_status == locked.STATUS_PUBLISHED)
            and not (step_key == 'publish' and completed_request(
                definition=locked, step_key='publish', request_id=_request_id(request)))):
        raise ValidationError('This version was published. Create an editable successor to make changes.')
    assert_expected_state(definition=locked, expected_tokens=_expected_tokens(request), step_key=step_key)
    return locked


def _step_identity(model_admin, request, definition, context):
    product = definition.product_version.product
    form = SetupIdentityForm(request.POST or None, instance=product)
    context['form'] = form
    if request.method != 'POST':
        return None
    if not form.is_valid():
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request, 'identity')
        product = definition.product_version.product
        posted = SetupIdentityForm(request.POST, instance=product)
        if not posted.is_valid():
            context['form'] = posted
            return None
        posted.save()
        _sync_availability(product, posted.cleaned_data['branches'])
        record_step_completion(
            definition=definition, step_key='identity', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, 'Product and branch availability saved.')
    return HttpResponseRedirect(_workspace_url(definition, 'identity' if request.POST.get('intent') == 'stay' else 'terms'))


def _terms_forms(request, version):
    bound = request.POST if request.method == 'POST' else None
    return (
        SetupTermsForm(bound, instance=version),
        FeeFormSet(bound, instance=version, prefix='fees'),
        RequirementFormSet(bound, instance=version, prefix='requirements'),
        AttributeFormSet(bound, instance=version, prefix='attributes'),
    )


def _step_terms(model_admin, request, definition, context):
    version = definition.product_version
    context['terms_readonly'] = version.status != ProductVersion.STATUS_DRAFT
    if context['terms_readonly']:
        context['terms_summary'] = version
        return None
    form, fees, requirements, attributes = _terms_forms(request, version)
    context.update({
        'form': form, 'fees': fees, 'requirements': requirements,
        'attributes': attributes,
    })
    if request.method != 'POST':
        return None
    if not all(item.is_valid() for item in (form, fees, requirements, attributes)):
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request, 'terms')
        if definition.product_version.status != ProductVersion.STATUS_DRAFT:
            raise ValidationError('These financial terms were published. Create an editable successor to change them.')
        form, fees, requirements, attributes = _terms_forms(request, definition.product_version)
        if not all(item.is_valid() for item in (form, fees, requirements, attributes)):
            context.update({'form': form, 'fees': fees, 'requirements': requirements, 'attributes': attributes})
            return None
        form.save()
        fees.save()
        requirements.save()
        attributes.save()
        record_step_completion(
            definition=definition, step_key='terms', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, 'Commercial terms saved as a draft.')
    return HttpResponseRedirect(_workspace_url(definition, 'terms' if request.POST.get('intent') == 'stay' else 'documents'))




def _step_documents(model_admin, request, definition, context):
    from origination.services.origination_setup_documents import (
        create_setup_document, document_readiness, prepare_document_profile,
        select_documents, selected_documents,
        stage_change, prepare_edit, replace_pdf, cancel_changes, apply_changes,
        maintenance_impact, pending_changes,
    )
    uploading = request.method == 'POST' and request.POST.get('action') == 'upload'
    selection = SetupCatalogueSelectionForm(
        request.POST if request.method == 'POST' and not uploading else None, definition=definition,
    )
    upload = SetupCatalogueUploadForm(request.POST if uploading else None, request.FILES if uploading else None)
    token = make_return_token(definition_id=definition.pk, step_key='documents')
    templates, errors = document_readiness(definition)
    impact = maintenance_impact(definition)
    context.update({'form': selection, 'upload_form': upload, 'document_errors': errors,
                    'maintenance': impact,
                    'replacement_options': selection.fields['templates'].queryset,
                    'documents': [{
                        'template': item,
                        'url': reverse('admin:origination_originationdocumenttemplate_calibrate', args=[item.pk])
                               + '?setup_return=' + token,
                    } for item in templates]})
    if request.method != 'POST':
        return None
    action = request.POST.get('action')
    if action in {'edit', 'remove', 'switch', 'replace_pdf', 'cancel_changes'}:
        request_id = _request_id(request)
        with transaction.atomic():
            definition = _check_locked(definition, request, 'documents')
            if action == 'cancel_changes':
                cancel_changes(definition=definition, actor=request.user, request_id=request_id)
                return HttpResponseRedirect(_workspace_url(definition, 'documents'))
            source = OriginationDocumentTemplate.objects.filter(pk=request.POST.get('source')).first()
            if not source:
                raise ValidationError('This document is unavailable. Refresh the list.')
            if action == 'edit':
                target = prepare_edit(definition=definition, source=source, actor=request.user, request_id=request_id)
                return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[target.pk])
                    + '?setup_return=' + token)
            if action == 'remove':
                stage_change(definition=definition, action='remove', source=source, actor=request.user, request_id=request_id)
            if action == 'switch':
                target = selection.fields['templates'].queryset.filter(pk=request.POST.get('replacement')).first()
                if not target:
                    raise ValidationError('Choose an available replacement document.')
                stage_change(definition=definition, action='replace', source=source, target=target, actor=request.user, request_id=request_id)
        if action == 'replace_pdf':
            pdf = request.FILES.get('pdf_file')
            if not pdf:
                raise ValidationError('Choose the replacement PDF.')
            target = replace_pdf(definition=definition, source=source, pdf_file=pdf, actor=request.user, request_id=request_id)
            if target.status == 'upload_failed':
                context['step_error'] = target.upload_error
                context['request_id'] = request_id
                context['expected_tokens'] = json.dumps(step_tokens(definition), sort_keys=True)
                return None
            if target.pk == source.pk:
                messages.info(request, 'This is the same PDF. Fields and alignment were kept.')
                return HttpResponseRedirect(_workspace_url(definition, 'documents'))
            return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[target.pk])
                + '?setup_return=' + token)
        return HttpResponseRedirect(_workspace_url(definition, 'publish'))
    form = upload if uploading else selection
    if not form.is_valid():
        return None
    request_id = _request_id(request)
    if uploading:
        with transaction.atomic():
            definition = _check_locked(definition, request, 'documents')
        uploaded_template = create_setup_document(definition=definition, actor=request.user,
            request_id=request_id, **upload.cleaned_data)
        if uploaded_template.status == uploaded_template.STATUS_UPLOAD_FAILED:
            context['step_error'] = uploaded_template.upload_error or 'Upload failed. Please try again.'
            context['request_id'] = request_id
            context['expected_tokens'] = json.dumps(step_tokens(definition), sort_keys=True)
            return None
    with transaction.atomic():
        definition = _check_locked(definition, request, 'documents')
        if uploading:
            template = uploaded_template
            if template.status == template.STATUS_UPLOAD_FAILED:
                # Keep the failed upload checkpoint; retry does not claim success.
                context['step_error'] = template.upload_error or 'Upload failed. Please try again.'
                return None
            OriginationProductDefinitionEvent.objects.create(
                product_definition=definition, action='setup_pdf_uploaded', actor=request.user,
                metadata={'request_id': request_id, 'template_id': str(template.pk)},
            )
            chosen = list(selected_documents(definition)) + [template]
        else:
            chosen = list(selection.cleaned_data['templates'])
            if definition.lifecycle_status == definition.STATUS_DRAFT:
                approval_mode = selection.cleaned_data.get('approval_mode')
                modes = {'independent': [], 'bm': ['branch_manager'],
                         'management': ['branch_manager', 'management_approver']}
                if approval_mode in modes:
                    definition.approval_roles = modes[approval_mode]
                    definition.save(update_fields=['approval_roles', 'updated_at'])
        chosen = select_documents(definition=definition, templates=chosen,
                                  actor=request.user, request_id=request_id)
        if definition.lifecycle_status == definition.STATUS_DRAFT and any(item.document_role == item.ROLE_PRIMARY for item in chosen):
            prepare_document_profile(definition=definition, templates=chosen)
        record_step_completion(definition=definition, step_key='documents', actor=request.user, request_id=request_id)
        if request.POST.get('action') == 'enable_documents' and definition.lifecycle_status == definition.STATUS_PUBLISHED:
            from origination.services.origination_setup_documents import publish_setup_documents
            if pending_changes(definition):
                apply_changes(definition=definition, actor=request.user, request_id=request_id,
                    expected_impact=request.POST.get('maintenance_token'),
                    allow_unavailable=request.POST.get('allow_unavailable') == 'yes')
            else:
                publish_setup_documents(definition=definition, actor=request.user, request_id=request_id)
            messages.success(request, 'Document changes applied. Existing product terms and applications were kept.')
            return HttpResponseRedirect(reverse('admin:origination_origination_setup_dashboard'))
    messages.success(request, 'Document choices saved.' if not uploading else 'PDF uploaded. Set up its fields and alignment.')
    if uploading:
        return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[template.pk])
                                    + '?setup_return=' + token)
    return HttpResponseRedirect(_workspace_url(definition, 'documents' if request.POST.get('intent') == 'stay' else 'publish'))


def _step_publish(model_admin, request, definition, context):
    from origination.services.origination_document_catalogue import catalogue_for_product
    context['document_catalogue'] = catalogue_for_product(definition)
    context['terms_summary'] = definition.product_version
    from origination.services.origination_setup_documents import document_readiness, maintenance_impact
    templates, document_errors = document_readiness(definition)
    context['document_errors'] = document_errors
    context['selected_documents'] = templates
    context['maintenance'] = maintenance_impact(definition)
    if context['maintenance']['changes']:
        context['affected_products'] = context['maintenance']['affected_products']
    context['branches'] = definition.product_version.product.availability_assignments.filter(
        workflow='loan_origination', active=True,
    ).select_related('branch')
    context['signer_labels'] = [rule.get('label') or rule.get('role', '').replace('_', ' ').title()
                                for rule in definition.signer_rules if isinstance(rule, dict)]
    main = next((item for item in templates if item.document_role == item.ROLE_PRIMARY), None)
    if main:
        from origination.services.origination_fields import template_form_contract
        schema, _signers = template_form_contract(main)
        context['applicant_fields'] = schema.get('fields', [])
    context['document_previews'] = [{
        'template': item,
        'configuration': (item.published_configuration_revision if item.status == item.STATUS_ACTIVE
                          else item.configuration_revisions.order_by('-revision').first()).configuration,
        'url': reverse('admin:origination_originationdocumenttemplate_calibration_preview', args=[item.pk]),
    } for item in templates if item.published_configuration_revision_id or item.configuration_revisions.exists()]
    context['can_enable'] = not document_errors
    context['documents_url'] = _workspace_url(definition, 'documents')
    context['affected_products'] = sorted({name for item in templates if item.status == item.STATUS_READY
        for name in item.eligible_products.exclude(pk=definition.product_version.product_id).values_list('name', flat=True)})
    if context['maintenance']['changes']:
        context['affected_products'] = context['maintenance']['affected_products']
    terms = definition.product_version
    context['term_changes'] = []
    if terms.supersedes_id:
        labels = {'min_amount':'Minimum amount', 'max_amount':'Maximum amount', 'currency':'Currency',
                  'min_tenor':'Minimum tenor', 'max_tenor':'Maximum tenor', 'tenor_unit':'Tenor unit',
                  'interest_rate':'Interest rate', 'interest_method':'Interest method',
                  'interest_rate_period':'Rate period', 'repayment_frequency':'Repayment frequency',
                  'effective_from':'Start date', 'effective_to':'End date'}
        for name, label in labels.items():
            before, after = getattr(terms.supersedes, name), getattr(terms, name)
            if before != after:
                display = f'get_{name}_display'
                context['term_changes'].append({'label':label,
                    'before':getattr(terms.supersedes, display)() if hasattr(terms, display) else before,
                    'after':getattr(terms, display)() if hasattr(terms, display) else after})
    context['same_day_replacement'] = bool(
        terms and terms.supersedes_id
        and terms.status == ProductVersion.STATUS_DRAFT
        and terms.effective_from == terms.supersedes.effective_from
        and terms.supersedes.status in {ProductVersion.STATUS_PUBLISHED, ProductVersion.STATUS_SCHEDULED}
    )
    context['review_rows'] = [{**row, 'url': _workspace_url(definition, row['key'])}
                              for row in setup_readiness(definition)]
    if request.method != 'POST':
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request, 'publish')
        if completed_request(definition=definition, step_key='publish', request_id=request_id):
            return HttpResponseRedirect(reverse('admin:origination_origination_setup_dashboard'))
        readiness = setup_readiness(definition)
        blockers = [
            item for item in readiness[:-1]
            if not item['valid']
        ]
        if blockers:
            raise ValidationError([f"{item['label']}: {item['detail']}" for item in blockers])
        from core.services.product_catalog import publish_product_version
        publish_product_version(
            version=definition.product_version, actor=request.user,
            allow_same_day_replacement=True,
        )
        definition.refresh_from_db()
        from origination.services.origination_setup_documents import publish_setup_documents, pending_changes, apply_changes
        if pending_changes(definition):
            apply_changes(definition=definition, actor=request.user, request_id=request_id,
                expected_impact=request.POST.get('maintenance_token'))
        else:
            publish_setup_documents(definition=definition, actor=request.user, request_id=request_id)
        if not catalogue_for_product(definition)['ready']:
            raise ValidationError('Documents are not ready for applications. Review the document step.')
        from origination.services.origination_setup import publish_product_profile
        published = publish_product_profile(definition=definition, actor=request.user)
        for key in ('identity', 'terms', 'documents'):
            record_step_completion(definition=published, step_key=key,
                                   actor=request.user, request_id=request_id)
        record_step_completion(
            definition=published, step_key='publish', actor=request.user,
            request_id=request_id,
        )
    messages.success(
        request,
        f'{published.name} is ready for applications.' if published.product_version.status == ProductVersion.STATUS_PUBLISHED
        else f'{published.name} is enabled from {published.product_version.effective_from}.',
    )
    return HttpResponseRedirect(reverse('admin:origination_origination_setup_dashboard'))
