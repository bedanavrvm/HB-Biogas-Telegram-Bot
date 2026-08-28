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

from core.models import (
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    Product,
    ProductAvailability,
    ProductVersion,
    ProductVersionEvent,
)
from core.origination_setup_forms import (
    AttributeFormSet,
    FeeFormSet,
    RequirementFormSet,
    SetupDocumentForm,
    SetupFormContractForm,
    SetupIdentityForm,
    SetupTermsForm,
)
from core.services.origination_setup import (
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
            'admin:core_origination_setup_step', args=[definition.pk, step_key],
        )
    return reverse('admin:core_origination_setup_workspace', args=[definition.pk])


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
    for code in OriginationProductDefinition.objects.values_list(
        'product_key', flat=True,
    ).distinct():
        latest = OriginationProductDefinition.objects.filter(
            product_key=code,
        ).order_by('-version').values_list('pk', flat=True).first()
        if latest:
            latest_ids.append(latest)
    published = OriginationProductDefinition.objects.filter(
        pk__in=latest_ids,
        lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
    ).select_related('product_version__product').order_by('name')
    return TemplateResponse(request, 'admin/core/origination_setup/dashboard.html', {
        **model_admin.admin_site.each_context(request),
        'opts': model_admin.model._meta,
        'title': 'Origination product setup',
        'draft_rows': draft_rows,
        'published_products': published,
        'start_form': SetupIdentityForm(),
        'request_id': str(uuid.uuid4()),
        'start_url': reverse('admin:core_origination_setup_start'),
        'advanced_url': reverse('admin:core_originationproductdefinition_changelist'),
        'laf_library_url': reverse('admin:core_originationdocumenttemplate_changelist'),
    })


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
        from core.services.origination_commercial_terms import (
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
        'start_url': reverse('admin:core_origination_setup_start'),
        'advanced_url': reverse('admin:core_originationproductdefinition_changelist'),
        'laf_library_url': reverse('admin:core_originationdocumenttemplate_changelist'),
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
        from core.services.origination_templates import clone_product_version
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
        return HttpResponseRedirect(reverse('admin:core_origination_setup_dashboard'))
    messages.success(request, f'Editable version {successor.version} is ready.')
    return HttpResponseRedirect(_workspace_url(successor))


def _sync_availability(product, branches):
    selected = {str(item.pk) for item in branches}
    existing = product.availability_assignments.filter(workflow='loan_origination')
    existing.exclude(branch_id__in=selected).update(active=False)
    for branch in branches:
        ProductAvailability.objects.update_or_create(
            product=product,
            scope_signature=f'branch:{branch.pk}|workflow:loan_origination|channel:telegram',
            defaults={
                'branch': branch, 'workflow': 'loan_origination',
                'channel': 'telegram', 'active': True,
            },
        )


def _base_context(model_admin, request, definition, step_key):
    rows = setup_readiness(definition)
    return {
        **model_admin.admin_site.each_context(request),
        'opts': model_admin.model._meta,
        'title': f'Set up {definition.name}',
        'definition': definition,
        'step_key': step_key,
        'step_label': dict(SETUP_STEPS)[step_key],
        'steps': [
            {**row, 'url': _workspace_url(definition, row['key'])}
            for row in rows
        ],
        'expected_tokens': json.dumps(step_tokens(definition), sort_keys=True),
        'workspace_token': state_token(definition),
        'request_id': str(uuid.uuid4()),
        'dashboard_url': reverse('admin:core_origination_setup_dashboard'),
        'advanced_url': reverse(
            'admin:core_originationproductdefinition_change', args=[definition.pk],
        ),
        'published_readonly': definition.lifecycle_status != definition.STATUS_DRAFT,
    }


def step_view(model_admin, request, object_id, step_key):
    _guard(request)
    if step_key not in dict(SETUP_STEPS):
        return HttpResponse(status=404)
    definition = _definition(object_id)
    if not definition:
        return HttpResponse(status=404)
    if request.method == 'POST' and definition.lifecycle_status != definition.STATUS_DRAFT:
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
                keys = [key for key, _label in SETUP_STEPS]
                next_key = keys[keys.index(step_key) + 1] if step_key != 'publish' else ''
                return HttpResponseRedirect(
                    _workspace_url(definition, next_key)
                    if next_key else reverse('admin:core_origination_setup_dashboard')
                )
        current_step = next(item for item in context['steps'] if item['key'] == step_key)
        if request.method == 'POST' and current_step['status'] == 'blocked':
            raise ValidationError('Complete the preceding required setup step first.')
        response = handler(model_admin, request, definition, context)
    except OriginationSetupConflict as exc:
        labels = dict(SETUP_STEPS)
        context['conflict'] = {
            'changed': [labels[key] for key in exc.changed_steps],
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


def _check_locked(definition, request):
    locked = _definition(definition.pk, lock=True)
    assert_expected_state(definition=locked, expected_tokens=_expected_tokens(request))
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
        definition = _check_locked(definition, request)
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
    return HttpResponseRedirect(_workspace_url(definition, 'terms'))


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
        definition = _check_locked(definition, request)
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
    return HttpResponseRedirect(_workspace_url(definition, 'terms_publish'))


def _step_terms_publish(model_admin, request, definition, context):
    context['terms_summary'] = definition.product_version
    if request.method != 'POST':
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request)
        from core.services.product_catalog import publish_product_version
        publish_product_version(version=definition.product_version, actor=request.user)
        definition.refresh_from_db()
        record_step_completion(
            definition=definition, step_key='terms_publish', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, 'Commercial terms published and locked.')
    return HttpResponseRedirect(_workspace_url(definition, 'form'))


def _step_form(model_admin, request, definition, context):
    from core.services.loan_origination import SIGNER_ROLE_CATALOG, validate_product_form_contract
    from core.services.origination_fields import catalogue_for_product
    form = SetupFormContractForm(request.POST or None, instance=definition)
    context.update({
        'form': form,
        'origination_signer_roles': [
            {'key': key, 'label': label} for key, label in SIGNER_ROLE_CATALOG
        ],
        'origination_data_fields': catalogue_for_product(definition),
        'origination_data_field_add_url': reverse('admin:core_originationdatafield_add'),
        'origination_data_field_create_url': reverse(
            'admin:core_originationproductdefinition_create_canonical_field',
        ),
    })
    if request.method != 'POST':
        return None
    if not form.is_valid():
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request)
        form = SetupFormContractForm(request.POST, instance=definition)
        if not form.is_valid():
            context['form'] = form
            return None
        from core.services.origination_commercial_terms import (
            ensure_commercial_catalogue, merge_commercial_contract,
        )
        definition.form_schema = merge_commercial_contract(
            form.cleaned_data['form_schema'],
            fields=ensure_commercial_catalogue(actor=request.user),
        )
        definition.signer_rules = form.cleaned_data['signer_rules']
        validate_product_form_contract(definition.form_schema, definition.signer_rules)
        definition.save(update_fields=['form_schema', 'signer_rules', 'updated_at'])
        from core.services.origination_fields import bind_compatible_schema_fields
        bind_compatible_schema_fields(definition, create_issues=True)
        OriginationProductDefinitionEvent.objects.create(
            product_definition=definition, action='draft_updated', actor=request.user,
            metadata={'request_id': request_id, 'source': 'guided_setup', 'step': 'form'},
        )
        record_step_completion(
            definition=definition, step_key='form', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, 'Form and signing roles saved.')
    return HttpResponseRedirect(_workspace_url(definition, 'documents'))


def _reusable_primaries():
    return OriginationDocumentTemplate.objects.filter(
        product_definition__isnull=True,
        document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        status=OriginationDocumentTemplate.STATUS_ACTIVE,
        published_configuration_revision__isnull=False,
    ).order_by('name', '-version')


def _step_documents(model_admin, request, definition, context):
    from core.services.origination_templates import resolve_assignment_template
    owned = list(definition.document_templates.exclude(
        status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
    ).order_by('display_order', 'name'))
    assignments = list(definition.document_assignments.select_related(
        'template', 'template__published_configuration_revision',
    ).order_by('display_order', 'name'))
    context.update({
        'documents': owned,
        'assignments': [
            {'assignment': item, 'resolved': resolve_assignment_template(item)}
            for item in assignments
        ],
        'supporting_url': reverse(
            'admin:core_originationproductdefinition_supporting_document_setup',
            args=[definition.pk],
        ) + '?setup_return=' + make_return_token(
            definition_id=definition.pk, step_key='documents',
        ),
        'library_url': reverse('admin:core_originationdocumenttemplate_changelist'),
    })
    form = SetupDocumentForm(
        request.POST or None, request.FILES or None,
        reusable_queryset=_reusable_primaries(),
    )
    context['form'] = form
    if request.method != 'POST':
        return None
    if request.POST.get('action') == 'confirm_existing':
        request_id = _request_id(request)
        with transaction.atomic():
            definition = _check_locked(definition, request)
            record_step_completion(
                definition=definition, step_key='documents', actor=request.user,
                request_id=request_id,
            )
        return HttpResponseRedirect(_workspace_url(definition, 'calibration'))
    if not form.is_valid():
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request)
        from core.services.origination_templates import (
            attach_shared_document_template, create_template, replace_draft_template,
        )
        if form.cleaned_data['source'] == SetupDocumentForm.SOURCE_EXISTING:
            attach_shared_document_template(
                product_definition=definition,
                template=form.cleaned_data['reusable_template'],
                inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
                display_order=0, officer_selectable=False, default_selected=False,
                applicability_rule={}, actor=request.user,
                version_policy='pinned',
            )
            template = form.cleaned_data['reusable_template']
        else:
            current = definition.document_templates.filter(
                document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                status__in=[OriginationDocumentTemplate.STATUS_READY, OriginationDocumentTemplate.STATUS_ACTIVE],
            ).order_by('-created_at').first()
            creator = replace_draft_template if current else create_template
            template = creator(
                pdf_file=form.cleaned_data['pdf_file'], product_definition=definition,
                name=f'{definition.name} LAF v{definition.version}', actor=request.user,
            )
            if template.status == template.STATUS_UPLOAD_FAILED:
                raise ValidationError(template.upload_error or 'The PDF upload failed.')
        record_step_completion(
            definition=definition, step_key='documents', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, 'Main LAF saved in this document packet.')
    if template.product_definition_id:
        return HttpResponseRedirect(
            reverse('admin:core_originationdocumenttemplate_calibrate', args=[template.pk])
            + '?setup_return=' + make_return_token(definition_id=definition.pk)
        )
    return HttpResponseRedirect(_workspace_url(definition, 'calibration'))


def _step_calibration(model_admin, request, definition, context):
    from core.services.origination_templates import resolve_assignment_template
    token = make_return_token(definition_id=definition.pk)
    items = []
    for template in definition.document_templates.exclude(status=template_status_failed()):
        items.append({
            'name': template.name, 'template': template,
            'ready': bool(template.configuration_revisions.exists()),
            'published': bool(template.published_configuration_revision_id),
            'url': reverse('admin:core_originationdocumenttemplate_calibrate', args=[template.pk])
                   + '?setup_return=' + token,
        })
    for assignment in definition.document_assignments.select_related('template'):
        template = resolve_assignment_template(assignment)
        if template:
            items.append({
                'name': assignment.name, 'template': template, 'ready': True,
                'published': True,
                'url': reverse('admin:core_originationdocumenttemplate_calibrate', args=[template.pk])
                       + '?setup_return=' + token,
            })
    context['calibration_items'] = items
    if request.method != 'POST':
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request)
        row = next(item for item in setup_readiness(definition) if item['key'] == 'calibration')
        if row['status'] not in {'complete', 'stale'} and 'complete alignment' not in row['detail']:
            raise ValidationError(row['detail'])
        record_step_completion(
            definition=definition, step_key='calibration', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, 'PDF alignment reviewed.')
    return HttpResponseRedirect(_workspace_url(definition, 'publish'))


def template_status_failed():
    return OriginationDocumentTemplate.STATUS_UPLOAD_FAILED


def _step_publish(model_admin, request, definition, context):
    from core.services.origination_templates import resolve_assignment_template
    owned = list(definition.document_templates.filter(
        document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        status__in=[OriginationDocumentTemplate.STATUS_READY, OriginationDocumentTemplate.STATUS_ACTIVE],
    ))
    assigned = [
        resolve_assignment_template(item)
        for item in definition.document_assignments.select_related('template').filter(
            template__document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        )
    ]
    primaries = owned + [item for item in assigned if item]
    context['primary_template'] = primaries[0] if len(primaries) == 1 else None
    context['review_rows'] = setup_readiness(definition)
    if request.method != 'POST':
        return None
    request_id = _request_id(request)
    with transaction.atomic():
        definition = _check_locked(definition, request)
        readiness = setup_readiness(definition)
        blockers = [
            item for item in readiness[:-1]
            if item['status'] not in {'complete', 'published'}
        ]
        if blockers:
            raise ValidationError('Resolve every stale, incomplete, or blocked setup step before publishing.')
        owned = list(definition.document_templates.filter(
            document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
            status__in=[OriginationDocumentTemplate.STATUS_READY, OriginationDocumentTemplate.STATUS_ACTIVE],
        ))
        assignments = list(definition.document_assignments.select_related(
            'template', 'template__published_configuration_revision',
        ).filter(template__document_role=OriginationDocumentTemplate.ROLE_PRIMARY))
        from core.services.origination_templates import publish_product_template, resolve_assignment_template
        primary = owned[0] if len(owned) == 1 and not assignments else (
            resolve_assignment_template(assignments[0])
            if len(assignments) == 1 and not owned else None
        )
        if not primary:
            raise ValidationError('Attach exactly one main LAF before publishing.')
        revision = (
            primary.published_configuration_revision.revision
            if primary.product_definition_id is None
            else primary.configuration_revisions.order_by('-revision').values_list('revision', flat=True).first()
        )
        if not revision:
            raise ValidationError('Save and review the main LAF alignment before publishing.')
        published, _template, _revision = publish_product_template(
            template=primary, revision=revision, product_definition=definition,
            actor=request.user, client_request_id=request_id,
        )
        record_step_completion(
            definition=published, step_key='publish', actor=request.user,
            request_id=request_id,
        )
    messages.success(request, f'{published.name} v{published.version} is published for Origination.')
    return HttpResponseRedirect(reverse('admin:core_origination_setup_dashboard'))
