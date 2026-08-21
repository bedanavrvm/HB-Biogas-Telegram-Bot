"""Portal HTTP boundary for product-neutral field loan origination."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import (
    LoanOriginationApplication,
    OriginationProductDefinition,
    OriginationRequirementEvidence,
    OriginationSignerSession,
    OriginationSigningPackage,
    OperationalLocation,
)
from core.services.origination_access import (
    DENIED,
    MASKED,
    application_presentation_mode,
    authorized_branches,
    queue_capabilities,
    scope_application_queryset,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    create_application,
    prepare_signing_package,
    render_application_preview,
    review_application,
    save_application_fields,
    save_signing_requirements,
    serialize_application,
    submit_for_review,
    take_over_correction_review,
)
from core.services.origination_documents import (
    mark_document_previewed,
    render_document,
    render_packet,
    save_document_fields,
    select_documents,
)
from core.services.origination_signing import render_test_package, simulate_slot


logger = logging.getLogger(__name__)


def _public_signing_token(request) -> str:
    authorization = str(request.headers.get('Authorization') or '')
    scheme, separator, value = authorization.partition(' ')
    if not separator or scheme.casefold() != 'bearer' or not value.strip():
        raise OriginationError('This signing link is invalid or incomplete.')
    return value.strip()[:256]


@require_http_methods(['GET', 'HEAD'])
def origination_app(request):
    """Standalone Telegram Mini App shell; authenticated APIs load its data."""
    response = render(request, 'loan_origination/app.html')
    # Telegram WebViews can retain the HTML shell between launches.  The shell
    # contains the versioned static URLs, so caching it also prevents a newly
    # deployed CSS/JS version from ever being requested.
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


def _body(request) -> dict:
    try:
        value = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OriginationError('Request body must be valid JSON.') from exc
    if not isinstance(value, dict):
        raise OriginationError('Request body must be an object.')
    return value


def _capability_error(request, capability: str, application=None):
    from core.api.portal_views import _portal_capability_error
    error = _portal_capability_error(request, capability, None)
    if error or application is None:
        return error
    access = getattr(request, 'portal_access', None)
    user = getattr(request, 'portal_user', None)
    if access is None or getattr(user, 'is_superuser', False):
        return None
    branches = {str(value).strip().casefold() for value in access.get('branches', []) if str(value).strip()}
    if branches and str(application.branch or '').strip().casefold() not in branches:
        return JsonResponse({'ok': False, 'error': 'This application is outside your authorized branch scope.'}, status=403)
    return None


def _request_id(request, body: dict) -> str:
    return str(
        request.headers.get('Idempotency-Key')
        or request.headers.get('X-Request-ID')
        or body.get('client_request_id')
        or body.get('request_id')
        or ''
    ).strip()[:128]


def _application(application_id: str):
    return LoanOriginationApplication.objects.select_related(
        'product_definition', 'product_version__product', 'officer', 'recheck_assigned_to',
    ).prefetch_related(
        'requirement_evidence_files', 'correction_requests__items',
    ).filter(pk=application_id).first()


def _application_access_error(request, application, *, require_full: bool = True):
    mode = application_presentation_mode(
        application, user=getattr(request, 'portal_user', None),
        access=getattr(request, 'portal_access', None),
    )
    if mode == DENIED or (require_full and mode == MASKED):
        return JsonResponse(
            {'ok': False, 'error': 'This application is outside your authorized origination scope.'},
            status=403,
        )
    return None


def _safe_error(exc: Exception) -> dict:
    payload = {'ok': False, 'error': str(exc)}
    errors = getattr(exc, 'errors', None)
    if errors:
        payload['errors'] = errors
    return payload


def _branch_creation_error(request, branch: str, product_key: str = ''):
    access = getattr(request, 'portal_access', None)
    user = getattr(request, 'portal_user', None)
    if access is not None and not getattr(user, 'is_superuser', False):
        from core.services.portal_permissions import portal_access_decision

        if not portal_access_decision(
            user, 'portal.origination.create', access=access,
            branch=branch, product=product_key,
        ).allowed:
            return JsonResponse({'ok': False, 'error': 'Choose a branch within your authorized scope.'}, status=403)
    canonical = {
        value.casefold(): value
        for value in authorized_branches(user, access)
    }
    if str(branch or '').strip().casefold() not in canonical:
        return JsonResponse({'ok': False, 'error': 'Choose an active branch from the approved list.'}, status=400)
    return None


@csrf_exempt
@require_http_methods(['GET'])
def portal_origination_products(request):
    error = _capability_error(request, 'portal.origination.view')
    if error:
        return error
    user = getattr(request, 'portal_user', None)
    access = getattr(request, 'portal_access', None)
    branches = authorized_branches(user, access)
    from core.services.location_catalog import location_catalog_manifest
    location_catalog = location_catalog_manifest()
    allowed_branch_names = {item.casefold() for item in branches}
    location_catalog['branches'] = [
        item for item in location_catalog['branches']
        if item['name'].casefold() in allowed_branch_names
    ]
    selected_branch = str(request.GET.get('branch') or '').strip()
    branch_record = None
    if selected_branch:
        branch_lookup = {item.casefold(): item for item in branches}
        if selected_branch.casefold() not in branch_lookup:
            return JsonResponse({'ok': False, 'error': 'Choose a branch within your authorized scope.'}, status=403)
        selected_branch = branch_lookup[selected_branch.casefold()]
        branch_record = OperationalLocation.objects.filter(
            location_type='branch', name__iexact=selected_branch, active=True,
        ).first()
    products = OriginationProductDefinition.objects.filter(is_active=True).select_related(
        'product_version__product',
    ).order_by('name')
    from core.services.product_catalog import (
        active_product_version, product_is_available, product_is_selectable,
        serialize_product_version,
    )
    from core.services.origination_templates import resolve_assignment_template
    payload = []
    for item in products:
        if item.product_version_id:
            current = active_product_version(item.product_version.product)
            if current is None or current.pk != item.product_version_id:
                continue
            if not product_is_selectable(
                product=item.product_version.product,
                workflow='loan_origination', channel='portal',
            ):
                continue
            if selected_branch and not product_is_available(
                item.product_version.product, branch=branch_record,
                workflow='loan_origination', channel='portal',
            ):
                continue
        assignment_documents = []
        for assignment in item.document_assignments.select_related(
            'template', 'template__published_configuration_revision',
        ).order_by('display_order', 'document_key'):
            resolved_template = resolve_assignment_template(assignment)
            assignment_documents.append({
                'key': assignment.document_key,
                'name': assignment.name,
                'role': 'supporting',
                'order': assignment.display_order,
                'inclusion_mode': assignment.inclusion_mode,
                'default_selected': assignment.default_selected,
                'version_policy': assignment.version_policy,
                'template_version': resolved_template.version if resolved_template else None,
                'template_ready': bool(resolved_template),
            })
        payload.append({
            'id': item.product_version.product_id if item.product_version_id else None,
            'product_key': item.product_key, 'name': item.name, 'version': item.version,
            'global_product_version_id': str(item.product_version_id or ''),
            'terms': serialize_product_version(item.product_version) if item.product_version_id else {},
            'form_schema': item.form_schema, 'signer_rules': item.signer_rules,
            'lifecycle_status': item.lifecycle_status,
            'document_type': item.document_type,
            'document_template_name': item.document_template_name,
            'document_template_version': item.document_template_version,
            'template_ready': bool(item.document_template_sha256),
            'document_packet': [
                {
                    'key': template.document_key,
                    'name': template.name,
                    'role': template.document_role,
                    'order': template.display_order,
                    'inclusion_mode': template.inclusion_mode,
                    'default_selected': template.default_selected,
                }
                for template in item.document_templates.filter(status='active').order_by(
                    'display_order', 'document_key',
                )
                if template.document_role == template.ROLE_PRIMARY
            ] + assignment_documents,
        })
    return JsonResponse({
        'ok': True,
        'branches': branches,
        'location_catalog': location_catalog,
        'selected_branch': selected_branch,
        'products': payload,
        'capabilities': queue_capabilities(user=user, access=access),
    })


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def portal_origination_applications(request):
    capability = 'portal.origination.create' if request.method == 'POST' else 'portal.origination.view'
    error = _capability_error(request, capability)
    if error:
        return error
    user = getattr(request, 'portal_user', None)
    if not user:
        return JsonResponse({'ok': False, 'error': 'A resolved Portal staff identity is required.'}, status=401)
    if request.method == 'GET':
        access = getattr(request, 'portal_access', None)
        queryset = scope_application_queryset(
            LoanOriginationApplication.objects.select_related(
                'product_definition', 'officer', 'recheck_assigned_to',
            ),
            user=user, access=access,
        )
        capabilities = queue_capabilities(user=user, access=access)
        scoped = queryset
        status_counts = {
            key: scoped.filter(status=key).count()
            for key, _label in LoanOriginationApplication.STATUS_CHOICES
        }
        queue_name = str(request.GET.get('queue') or '').strip()
        if queue_name == 'mine':
            queryset = queryset.filter(officer=user)
        elif queue_name == 'corrections':
            queryset = queryset.filter(
                officer=user, status=LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
            )
        elif queue_name == 'review':
            if not capabilities['can_review']:
                queryset = queryset.none()
            else:
                queryset = queryset.filter(status=LoanOriginationApplication.STATUS_READY_FOR_REVIEW)
        elif queue_name == 'signing':
            if not capabilities['can_start_signing']:
                queryset = queryset.none()
            else:
                queryset = queryset.filter(status__in=[
                    LoanOriginationApplication.STATUS_REVIEWED,
                    LoanOriginationApplication.STATUS_SIGNING_PENDING,
                    LoanOriginationApplication.STATUS_PARTIALLY_SIGNED,
                ])
        status_filter = str(request.GET.get('status') or '').strip()
        if status_filter:
            allowed_statuses = {key for key, _label in LoanOriginationApplication.STATUS_CHOICES}
            if status_filter not in allowed_statuses:
                return JsonResponse({'ok': False, 'error': 'Choose a valid application status.'}, status=400)
            queryset = queryset.filter(status=status_filter)
        product_key = str(request.GET.get('product_key') or '').strip()
        if product_key:
            queryset = queryset.filter(product_definition__product_key=product_key)
        officer_id = str(request.GET.get('officer') or '').strip()
        if officer_id and capabilities['can_review']:
            queryset = queryset.filter(officer_id=officer_id)
        query = str(request.GET.get('q') or '').strip()
        if query:
            term = query[:80]
            queryset = queryset.filter(
                Q(reference_number__icontains=term)
                | Q(identity_snapshot__name__icontains=term)
                | Q(identity_snapshot__national_id__icontains=term)
                | Q(identity_snapshot__phone__icontains=term)
                # Historical applications may predate the identity snapshot.
                # Keep their approved legacy keys searchable during cutover.
                | Q(form_payload__applicant_full_name__icontains=term)
                | Q(form_payload__borrower_full_name__icontains=term)
                | Q(form_payload__customer_name__icontains=term)
                | Q(form_payload__applicant_id_number__icontains=term)
                | Q(form_payload__applicant_national_id__icontains=term)
                | Q(form_payload__national_id__icontains=term)
                | Q(form_payload__applicant_phone__icontains=term)
                | Q(form_payload__applicant_primary_phone__icontains=term)
                | Q(form_payload__primary_phone__icontains=term)
            )
        try:
            page = max(1, int(request.GET.get('page') or 1))
            page_size = min(100, max(1, int(request.GET.get('page_size') or 25)))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'Pagination values must be whole numbers.'}, status=400)
        total = queryset.count()
        pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        items = queryset.order_by('-updated_at', '-created_at')[start:start + page_size]
        return JsonResponse({
            'ok': True,
            'applications': [serialize_application(item, include_payload=False) for item in items],
            'counts': status_counts,
            'capabilities': capabilities,
            'queue': queue_name,
            'pagination': {
                'page': page, 'page_size': page_size, 'total': total, 'pages': pages,
            },
        })
    try:
        body = _body(request)
        branch_error = _branch_creation_error(
            request, body.get('branch'), str(body.get('product_key') or '').strip(),
        )
        if branch_error:
            return branch_error
        request_id = _request_id(request, body)
        application, replayed = create_application(
            product_key=str(body.get('product_key') or '').strip(), officer=user,
            branch=str(body.get('branch') or '').strip(), client_request_id=request_id,
        )
    except OriginationError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'replayed': replayed, 'application': serialize_application(application)}, status=200 if replayed else 201)


@csrf_exempt
@require_http_methods(['GET', 'PATCH'])
def portal_origination_application_detail(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    capability = 'portal.origination.create' if request.method == 'PATCH' else 'portal.origination.view'
    error = _capability_error(request, capability, application)
    if error:
        return error
    access_error = _application_access_error(
        request, application, require_full=request.method == 'PATCH',
    )
    if access_error:
        return access_error
    if request.method == 'GET':
        mode = application_presentation_mode(
            application, user=request.portal_user,
            access=getattr(request, 'portal_access', None),
        )
        return JsonResponse({
            'ok': True,
            'application': serialize_application(application, presentation=mode),
        })
    try:
        body = _body(request)
        saved = save_application_fields(
            application_id=application.pk, actor=request.portal_user,
            payload=body.get('form_payload', {}), expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body),
            requirement_evidence=body.get('product_requirement_evidence'),
            custom_values=body.get('product_custom_values'),
            selected_fee_keys=body.get('product_selected_fee_keys'),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(saved)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_submit(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.create', application)
    if error:
        return error
    access_error = _application_access_error(request, application)
    if access_error:
        return access_error
    try:
        body = _body(request)
        submitted = submit_for_review(
            application_id=application.pk, actor=request.portal_user,
            expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(submitted)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_preview(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.view', application)
    if error:
        return error
    access_error = _application_access_error(request, application)
    if access_error:
        return access_error
    try:
        body = _body(request)
        if int(body.get('revision')) != application.revision:
            raise OriginationConflict('This application changed. Refresh before previewing it.')
        preview = render_application_preview(application)
        preview_format = str(body.get('preview_format') or 'pdf').strip().lower()
        request_id = _request_id(request, body)
        if request_id and not application.events.filter(request_id=request_id).exists():
            from core.services.loan_origination import _record_event
            _record_event(application, 'document_previewed', actor=request.portal_user, request_id=request_id)
        if application.primary_previewed_revision != application.revision:
            application.primary_previewed_revision = application.revision
            application.save(update_fields=['primary_previewed_revision', 'updated_at'])
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    if preview_format == 'image':
        try:
            from core.services.partnership_laf_preview import PartnershipLafPreviewError, render_pdf_page
            page_number = int(body.get('page') or 1)
            rendered, total_pages = render_pdf_page(preview, page_number=page_number)
        except (OriginationError, PartnershipLafPreviewError, TypeError, ValueError) as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        response = HttpResponse(rendered, content_type='image/jpeg')
        response['Content-Disposition'] = f'inline; filename="{application.reference_number}-page-{page_number}.jpg"'
        response['X-Preview-Page-Count'] = str(total_pages)
    else:
        response = HttpResponse(preview, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{application.reference_number}-preview.pdf"'
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    response['X-Application-Revision'] = str(application.revision)
    return response


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_review(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.review', application)
    if error:
        return error
    access_error = _application_access_error(request, application)
    if access_error:
        return access_error
    try:
        body = _body(request)
        reviewed = review_application(
            application_id=application.pk, actor=request.portal_user,
            expected_revision=int(body.get('revision')), request_id=_request_id(request, body),
            decision=body.get('decision'), reason=body.get('reason', ''),
            correction_items=body.get('correction_items'),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(reviewed)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_correction_takeover(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.review', application)):
        return error
    if (access_error := _application_access_error(request, application)):
        return access_error
    try:
        body = _body(request)
        application = take_over_correction_review(
            application_id=application.pk, actor=request.portal_user,
            expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body), reason=body.get('reason', ''),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(application)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_prepare_signing(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.signing.start', application)
    if error:
        return error
    access_error = _application_access_error(request, application)
    if access_error:
        return access_error
    try:
        body = _body(request)
        package, replayed = prepare_signing_package(
            application_id=application.pk, actor=request.portal_user,
            expected_revision=int(body.get('revision')), request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({
        'ok': True, 'replayed': replayed,
        'signing_package': {'id': str(package.pk), 'reference': package.external_reference, 'status': package.status},
    }, status=200 if replayed else 201)


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_signing_requirements(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.signing.start', application)
    if error:
        return error
    access_error = _application_access_error(request, application)
    if access_error:
        return access_error
    try:
        body = _body(request)
        saved = save_signing_requirements(
            application_id=application.pk, actor=request.portal_user,
            requirement_evidence=body.get('product_requirement_evidence'),
            expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(saved)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_evidence_upload(request, application_id: str, requirement_key: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    signing_stage = application.status == LoanOriginationApplication.STATUS_REVIEWED
    capability = 'portal.origination.signing.start' if signing_stage else 'portal.origination.create'
    error = _capability_error(request, capability, application)
    if error:
        return error
    access_error = _application_access_error(request, application)
    if access_error:
        return access_error
    try:
        from core.services.origination_evidence import serialize_evidence, upload_requirement_evidence
        item, replayed = upload_requirement_evidence(
            application_id=application.pk,
            actor=request.portal_user,
            requirement_key=requirement_key,
            expected_revision=int(request.POST.get('revision')),
            request_id=(
                request.headers.get('Idempotency-Key')
                or request.headers.get('X-Request-ID')
                or request.POST.get('request_id')
                or ''
            ),
            file_obj=request.FILES.get('file'),
            allow_signing_actor=signing_stage,
        )
        refreshed = _application(application_id)
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    if item.status == item.STATUS_FAILED:
        return JsonResponse({
            'ok': False, 'error': item.upload_error,
            'evidence': serialize_evidence(item),
            'application': serialize_application(refreshed),
        }, status=502)
    return JsonResponse({
        'ok': True, 'replayed': replayed,
        'evidence': serialize_evidence(item),
        'application': serialize_application(refreshed),
    }, status=200 if replayed else 201)


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_test_signing_action(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.signing.start', application)):
        return error
    if (access_error := _application_access_error(request, application)):
        return access_error
    try:
        body = _body(request)
        package, replayed = simulate_slot(
            package_id=body.get('package_id'), actor=request.portal_user,
            document_key=str(body.get('document_key') or ''),
            slot_key=str(body.get('slot_key') or ''),
            signer_role=str(body.get('signer_role') or ''),
            stamp_asset_id=str(body.get('stamp_asset_id') or ''),
            signature_capture=body.get('signature_capture'),
            expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body),
        )
    except OriginationSigningPackage.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Signing package not found.'}, status=404)
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    application = _application(application.pk)
    return JsonResponse({
        'ok': True, 'replayed': replayed,
        'application': serialize_application(application),
    }, status=200 if replayed else 201)


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_test_signing_preview(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.signing.start', application)):
        return error
    if (access_error := _application_access_error(request, application)):
        return access_error
    try:
        body = _body(request)
        if int(body.get('revision')) != application.revision:
            raise OriginationConflict('This application changed. Refresh before previewing test signing.')
        package = application.signing_packages.get(pk=body.get('package_id'))
        content = render_test_package(package)
        preview_format = str(body.get('preview_format') or 'pdf').strip().lower()
        if preview_format == 'image':
            from core.services.partnership_laf_preview import render_pdf_page
            page_number = int(body.get('page') or 1)
            content, total_pages = render_pdf_page(content, page_number=page_number)
    except OriginationSigningPackage.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Signing package not found.'}, status=404)
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, RuntimeError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    if preview_format == 'image':
        response = HttpResponse(content, content_type='image/jpeg')
        response['X-Preview-Page-Count'] = str(total_pages)
    else:
        response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{application.reference_number}-TEST-signing.{"jpg" if preview_format == "image" else "pdf"}"'
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt  # Opaque signer token is the non-cookie credential; no session cookie authorizes this route.
@require_http_methods(['GET'])
def origination_signer_session(request):
    from core.services.origination_esign import resolve_session, serialize_public_session
    try:
        session = resolve_session(_public_signing_token(request))
    except OriginationError as exc:
        return JsonResponse(_safe_error(exc), status=404)
    return JsonResponse({'ok': True, 'session': serialize_public_session(session)})


@csrf_exempt  # Opaque signer token is the non-cookie credential.
@require_http_methods(['GET'])
def origination_signer_packet_preview(request):
    from core.services.origination_esign import resolve_session
    try:
        session = resolve_session(_public_signing_token(request))
        content, _manifest = render_packet(session.package.application)
        import hashlib
        if hashlib.sha256(content).hexdigest() != session.package.unsigned_document_hash:
            raise OriginationError('The document packet no longer matches its frozen signing hash.')
        from core.services.partnership_laf_preview import render_pdf_page
        image, page_count = render_pdf_page(content, page_number=int(request.GET.get('page') or 1))
    except OriginationError as exc:
        return JsonResponse(_safe_error(exc), status=400)
    except (RuntimeError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    response = HttpResponse(image, content_type='image/jpeg')
    response['X-Preview-Page-Count'] = str(page_count)
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _public_signing_error(exc: Exception):
    from core.services.origination_esign import OriginationSigningRateLimited
    if isinstance(exc, OriginationSigningRateLimited):
        response = JsonResponse(_safe_error(exc), status=429)
        response['Retry-After'] = str(exc.retry_after)
        return response
    return JsonResponse(_safe_error(exc), status=400)


@csrf_exempt  # Opaque signer token is the non-cookie credential.
@require_http_methods(['POST'])
def origination_signer_consent(request):
    from core.services.origination_esign import (
        client_ip_hash, record_consent_and_signature, serialize_public_session,
    )
    try:
        body = _body(request)
        session = record_consent_and_signature(
            raw_token=_public_signing_token(request), signature_capture=body.get('signature_capture'),
            consent=body.get('consent') is True,
            access_mode=str(body.get('access_mode') or ''), ip_hash=client_ip_hash(request),
            reviewed_pages=body.get('reviewed_pages'),
            request_id=_request_id(request, body),
        )
    except (OriginationError, TypeError, ValueError) as exc:
        return _public_signing_error(exc)
    return JsonResponse({'ok': True, 'session': serialize_public_session(session)})


@csrf_exempt  # Opaque signer token is the non-cookie credential.
@require_http_methods(['POST'])
def origination_signer_otp(request):
    from core.services.external_resilience import ExternalOperationError
    from core.services.origination_esign import client_ip_hash, dispatch_otp, issue_otp, serialize_public_session
    try:
        body = _body(request)
        challenge, code, replayed = issue_otp(
            raw_token=_public_signing_token(request), request_id=_request_id(request, body), ip_hash=client_ip_hash(request),
        )
        if not replayed:
            challenge = dispatch_otp(challenge, code)
        session = challenge.session
    except ExternalOperationError:
        return JsonResponse({'ok': False, 'error': 'The SMS provider did not confirm this code. Wait 60 seconds before requesting another.'}, status=502)
    except (OriginationError, TypeError, ValueError) as exc:
        return _public_signing_error(exc)
    return JsonResponse({
        'ok': True, 'replayed': replayed,
        'session': serialize_public_session(session),
    }, status=200 if replayed else 201)


@csrf_exempt  # Opaque signer token is the non-cookie credential.
@require_http_methods(['POST'])
def origination_signer_verify(request):
    from core.services.origination_esign import client_ip_hash, serialize_public_session, verify_otp
    try:
        body = _body(request)
        session = verify_otp(
            raw_token=_public_signing_token(request), code=str(body.get('code') or ''),
            request_id=_request_id(request, body), ip_hash=client_ip_hash(request),
        )
    except (OriginationError, TypeError, ValueError) as exc:
        return _public_signing_error(exc)
    return JsonResponse({'ok': True, 'session': serialize_public_session(session)})


@csrf_exempt  # Provider receipt is informational only and cannot advance signing state.
@require_http_methods(['POST'])
def origination_africastalking_delivery_report(request):
    """Accept an idempotent Africa's Talking delivery receipt."""
    from core.services.origination_esign import record_delivery_report
    try:
        if request.content_type == 'application/json':
            payload = _body(request)
        else:
            payload = request.POST
        message_id = payload.get('id') or payload.get('messageId') or payload.get('message_id')
        status = payload.get('status') or payload.get('deliveryStatus') or ''
        matched = record_delivery_report(
            provider_message_id=message_id, provider_status=status,
        )
    except (OriginationError, TypeError, ValueError):
        # Keep the provider retry contract stable without exposing internals.
        return JsonResponse({'ok': False, 'error': 'Invalid delivery report.'}, status=400)
    return JsonResponse({'ok': True, 'matched': matched})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_signer_session(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.signing.start', application)):
        return error
    if (error := _application_access_error(request, application)):
        return error
    try:
        from core.services.external_resilience import ExternalOperationError
        from core.services.origination_esign import create_signer_session, send_signing_invitation, signing_url
        body = _body(request)
        package = application.signing_packages.get(pk=body.get('package_id'))
        session, raw_token, replayed = create_signer_session(
            package_id=package.pk, signer_role=str(body.get('signer_role') or ''),
            actor=request.portal_user, request_id=_request_id(request, body),
            access_mode=str(body.get('access_mode') or 'self_service'),
            shared_phone_override_reason=str(body.get('shared_phone_override_reason') or ''),
        )
        invitation = {}
        if not replayed and session.access_mode == OriginationSignerSession.MODE_SELF_SERVICE:
            invitation = send_signing_invitation(session, raw_token, request_id=_request_id(request, body))
        url = signing_url(raw_token)
    except OriginationSigningPackage.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Signing package not found.'}, status=404)
    except ExternalOperationError:
        return JsonResponse({'ok': False, 'error': 'The signer session was created, but the invitation SMS was not confirmed. Reissue it after checking the provider.'}, status=502)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({
        'ok': True, 'replayed': replayed,
        'signer_session': {'id': str(session.pk), 'role': session.signer_role, 'status': session.status, 'url': url},
        'invitation': invitation,
    }, status=200 if replayed else 201)


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_reset_signer_session(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.signing.start', application)):
        return error
    if (error := _application_access_error(request, application)):
        return error
    try:
        from core.services.external_resilience import ExternalOperationError
        from core.services.origination_esign import reset_signer_session, send_signing_invitation, signing_url
        body = _body(request)
        old_session = OriginationSignerSession.objects.filter(
            pk=body.get('session_id'), package__application=application,
        ).first()
        if not old_session:
            return JsonResponse({'ok': False, 'error': 'Signer session not found.'}, status=404)
        session, raw_token = reset_signer_session(
            session_id=old_session.pk, actor=request.portal_user,
            reason=str(body.get('reason') or ''), request_id=_request_id(request, body),
        )
        invitation = {}
        if session.access_mode == OriginationSignerSession.MODE_SELF_SERVICE:
            invitation = send_signing_invitation(
                session, raw_token, request_id=_request_id(request, body),
            )
        url = signing_url(raw_token)
    except ExternalOperationError:
        return JsonResponse({
            'ok': False,
            'error': 'The signer session was reset, but the invitation SMS was not confirmed. Reissue it after checking the provider.',
        }, status=502)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({
        'ok': True,
        'signer_session': {
            'id': str(session.pk), 'role': session.signer_role,
            'status': session.status, 'url': url,
        },
        'invitation': invitation,
    }, status=201)


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_staff_signature(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.signing.start', application)):
        return error
    if (error := _application_access_error(request, application)):
        return error
    try:
        from core.services.origination_esign import complete_staff_signatures
        body = _body(request)
        if not application.signing_packages.filter(pk=body.get('package_id')).exists():
            return JsonResponse({'ok': False, 'error': 'Signing package not found.'}, status=404)
        package = complete_staff_signatures(
            package_id=body.get('package_id'), signer_role=str(body.get('signer_role') or ''),
            actor=request.portal_user, signature_capture=body.get('signature_capture'),
            expected_revision=int(body.get('revision')), request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(package.application)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_production_stamp(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.signing.start', application)):
        return error
    if (error := _application_access_error(request, application)):
        return error
    try:
        from core.services.origination_esign import apply_production_stamp
        body = _body(request)
        if not application.signing_packages.filter(pk=body.get('package_id')).exists():
            return JsonResponse({'ok': False, 'error': 'Signing package not found.'}, status=404)
        package = apply_production_stamp(
            package_id=body.get('package_id'), document_key=str(body.get('document_key') or ''),
            slot_key=str(body.get('slot_key') or ''), signer_role=str(body.get('signer_role') or ''),
            stamp_asset_id=body.get('stamp_asset_id'), actor=request.portal_user,
            expected_revision=int(body.get('revision')), request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(package.application)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_archive_signed(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    if (error := _capability_error(request, 'portal.origination.signing.start', application)):
        return error
    if (error := _application_access_error(request, application)):
        return error
    try:
        from core.services.origination_esign import archive_signed_package
        body = _body(request)
        if not application.signing_packages.filter(pk=body.get('package_id')).exists():
            return JsonResponse({'ok': False, 'error': 'Signing package not found.'}, status=404)
        package = archive_signed_package(
            package_id=body.get('package_id'), actor=request.portal_user,
            request_id=_request_id(request, body),
        )
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'archive_status': package.archive_status})


@require_http_methods(['GET', 'HEAD'])
def origination_signing_app(request):
    """Public signer shell; the opaque URL token is the sole session credential."""
    response = render(request, 'loan_origination/sign.html')
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_evidence_remove(request, evidence_id: str):
    item = OriginationRequirementEvidence.objects.select_related('application').filter(pk=evidence_id).first()
    if not item:
        return JsonResponse({'ok': False, 'error': 'Evidence not found.'}, status=404)
    signing_stage = item.application.status == LoanOriginationApplication.STATUS_REVIEWED
    capability = 'portal.origination.signing.start' if signing_stage else 'portal.origination.create'
    error = _capability_error(request, capability, item.application)
    if error:
        return error
    access_error = _application_access_error(request, item.application)
    if access_error:
        return access_error
    try:
        body = _body(request)
        from core.services.origination_evidence import remove_requirement_evidence
        remove_requirement_evidence(
            evidence_id=item.pk, actor=request.portal_user,
            expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body),
            allow_signing_actor=signing_stage,
        )
        application = _application(item.application_id)
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(application)})


@require_http_methods(['GET'])
def portal_origination_evidence_download(request, evidence_id: str):
    item = OriginationRequirementEvidence.objects.select_related(
        'application__officer', 'application__product_definition',
    ).filter(pk=evidence_id, status=OriginationRequirementEvidence.STATUS_UPLOADED).first()
    if not item:
        return JsonResponse({'ok': False, 'error': 'Evidence not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.view', item.application)
    if error:
        return error
    access_error = _application_access_error(request, item.application)
    if access_error:
        return access_error
    try:
        from core.services.loan_origination import _record_event
        from core.services.order_approval import GoogleDriveMediaStorage
        content = GoogleDriveMediaStorage().download(item.drive_file_id)
        request_id = str(request.headers.get('X-Request-ID') or '').strip()[:128]
        if not request_id or not item.application.events.filter(request_id=request_id).exists():
            _record_event(
                item.application, 'evidence_downloaded', actor=request.portal_user,
                request_id=request_id,
                after={'evidence_id': str(item.pk), 'requirement_key': item.requirement_key},
            )
    except Exception:
        logger.exception('Origination evidence download failed for evidence %s.', item.pk)
        return JsonResponse(
            {'ok': False, 'error': 'The evidence file could not be retrieved. Try again.'},
            status=502,
        )
    filename = Path(item.original_filename).name.replace('"', '')
    response = HttpResponse(content, content_type=item.mime_type)
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_document_selection(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.create', application)
    if error:
        return error
    if (access_error := _application_access_error(request, application)):
        return access_error
    try:
        body = _body(request)
        saved = select_documents(
            application_id=application.pk, actor=request.portal_user,
            selected_keys=body.get('selected_keys'), expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(saved)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_document_fields(request, application_id: str, document_key: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.create', application)
    if error:
        return error
    if (access_error := _application_access_error(request, application)):
        return access_error
    try:
        body = _body(request)
        saved = save_document_fields(
            application_id=application.pk, document_key=document_key,
            actor=request.portal_user, payload=body.get('payload'),
            expected_revision=int(body.get('revision')), request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(saved)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_document_preview(request, application_id: str, document_key: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.view', application)
    if error:
        return error
    if (access_error := _application_access_error(request, application)):
        return access_error
    try:
        body = _body(request)
        if int(body.get('revision')) != application.revision:
            raise OriginationConflict('This application changed. Refresh before previewing it.')
        content = render_document(application, document_key)
        preview_format = str(body.get('preview_format') or 'pdf').strip().lower()
        mark_document_previewed(application, document_key)
        request_id = _request_id(request, body)
        if request_id and not application.events.filter(request_id=request_id).exists():
            from core.services.loan_origination import _record_event
            _record_event(
                application, 'supporting_document_previewed', actor=request.portal_user,
                request_id=request_id, after={'document_key': document_key},
            )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    if preview_format == 'image':
        try:
            from core.services.partnership_laf_preview import PartnershipLafPreviewError, render_pdf_page
            page_number = int(body.get('page') or 1)
            content, total_pages = render_pdf_page(content, page_number=page_number)
        except (OriginationError, PartnershipLafPreviewError, TypeError, ValueError) as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        response = HttpResponse(content, content_type='image/jpeg')
        response['Content-Disposition'] = f'inline; filename="{application.reference_number}-{document_key}-page-{page_number}.jpg"'
        response['X-Preview-Page-Count'] = str(total_pages)
    else:
        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{application.reference_number}-{document_key}.pdf"'
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_packet_preview(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.view', application)
    if error:
        return error
    if (access_error := _application_access_error(request, application)):
        return access_error
    try:
        body = _body(request)
        if int(body.get('revision')) != application.revision:
            raise OriginationConflict('This application changed. Refresh before previewing the packet.')
        content, manifest = render_packet(application)
        preview_format = str(body.get('preview_format') or 'pdf').strip().lower()
        if preview_format == 'image':
            from core.services.partnership_laf_preview import render_pdf_page
            page_number = int(body.get('page') or 1)
            content, total_pages = render_pdf_page(content, page_number=page_number)
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, RuntimeError, TypeError, ValueError) as exc:
        return JsonResponse(_safe_error(exc), status=400)
    if preview_format == 'image':
        response = HttpResponse(content, content_type='image/jpeg')
        response['Content-Disposition'] = f'inline; filename="{application.reference_number}-packet-page-{page_number}.jpg"'
        response['X-Preview-Page-Count'] = str(total_pages)
    else:
        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{application.reference_number}-packet.pdf"'
    response['X-Document-Count'] = str(len(manifest))
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
