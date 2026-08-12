"""Portal HTTP boundary for product-neutral field loan origination."""

from __future__ import annotations

import json

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import LoanOriginationApplication, OriginationProductDefinition
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    create_application,
    prepare_signing_package,
    review_application,
    save_application_fields,
    serialize_application,
    submit_for_review,
)


@require_http_methods(['GET', 'HEAD'])
def origination_app(request):
    """Standalone Telegram Mini App shell; authenticated APIs load its data."""
    return render(request, 'loan_origination/app.html')


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
    return LoanOriginationApplication.objects.select_related('product_definition', 'officer').filter(pk=application_id).first()


def _branch_creation_error(request, branch: str):
    access = getattr(request, 'portal_access', None)
    user = getattr(request, 'portal_user', None)
    if access is None or getattr(user, 'is_superuser', False):
        return None
    allowed = {str(value).strip().casefold() for value in access.get('branches', []) if str(value).strip()}
    if allowed and str(branch or '').strip().casefold() not in allowed:
        return JsonResponse({'ok': False, 'error': 'Choose a branch within your authorized scope.'}, status=403)
    return None


@csrf_exempt
@require_http_methods(['GET'])
def portal_origination_products(request):
    error = _capability_error(request, 'portal.origination.view')
    if error:
        return error
    products = OriginationProductDefinition.objects.filter(is_active=True).order_by('name')
    return JsonResponse({'ok': True, 'products': [{
        'product_key': item.product_key, 'name': item.name, 'version': item.version,
        'form_schema': item.form_schema, 'signer_rules': item.signer_rules,
        'document_type': item.document_type,
        'document_template_name': item.document_template_name,
        'document_template_version': item.document_template_version,
    } for item in products]})


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
        queryset = LoanOriginationApplication.objects.select_related('product_definition').all()
        access = getattr(request, 'portal_access', None)
        if access is not None and not user.is_superuser:
            branches = [str(value).strip() for value in access.get('branches', []) if str(value).strip()]
            if branches:
                scope = Q()
                for branch in branches:
                    scope |= Q(branch__iexact=branch)
                queryset = queryset.filter(scope)
        return JsonResponse({'ok': True, 'applications': [
            serialize_application(item, include_payload=False) for item in queryset[:100]
        ]})
    try:
        body = _body(request)
        branch_error = _branch_creation_error(request, body.get('branch'))
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
    if request.method == 'GET':
        return JsonResponse({'ok': True, 'application': serialize_application(application)})
    try:
        body = _body(request)
        saved = save_application_fields(
            application_id=application.pk, actor=request.portal_user,
            payload=body.get('form_payload', {}), expected_revision=int(body.get('revision')),
            request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
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
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'application': serialize_application(submitted)})


@csrf_exempt
@require_http_methods(['POST'])
def portal_origination_review(request, application_id: str):
    application = _application(application_id)
    if not application:
        return JsonResponse({'ok': False, 'error': 'Application not found.'}, status=404)
    error = _capability_error(request, 'portal.origination.review', application)
    if error:
        return error
    try:
        body = _body(request)
        reviewed = review_application(
            application_id=application.pk, actor=request.portal_user,
            expected_revision=int(body.get('revision')), request_id=_request_id(request, body),
            decision=body.get('decision'), reason=body.get('reason', ''),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
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
    try:
        body = _body(request)
        package, replayed = prepare_signing_package(
            application_id=application.pk, actor=request.portal_user,
            expected_revision=int(body.get('revision')), request_id=_request_id(request, body),
        )
    except OriginationConflict as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (OriginationError, TypeError, ValueError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True, 'replayed': replayed,
        'signing_package': {'id': str(package.pk), 'reference': package.external_reference, 'status': package.status},
    }, status=200 if replayed else 201)
