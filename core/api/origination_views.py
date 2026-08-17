"""Portal HTTP boundary for product-neutral field loan origination."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import (
    LoanOriginationApplication,
    OriginationProductDefinition,
    OriginationRequirementEvidence,
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
)


logger = logging.getLogger(__name__)


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
    farmer = None
    error = _portal_capability_error(request, capability, farmer)
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
        'product_definition', 'product_version__product', 'officer',
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
            LoanOriginationApplication.objects.select_related('product_definition', 'officer'),
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
            queryset = queryset.filter(reference_number__icontains=query[:80])
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
