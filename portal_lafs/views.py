import json
from functools import wraps

from django.http import HttpResponse, JsonResponse
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import JawabuFarmerMaster
from core.api.portal_views import portal_auth_required, _portal_request_id
from origination.services.loan_origination import OriginationError
from . import services


def response_guard(fn):
    @wraps(fn)
    def wrapped(request, *args, **kwargs):
        try:
            result = fn(request, *args, **kwargs)
        except (services.LafError, OriginationError) as exc:
            from core.services.miniapp_messages import miniapp_error_response

            result = miniapp_error_response(
                request,
                "portal_laf_blocked",
                workflow="portal",
                user_message=str(exc),
                errors=getattr(exc, "errors", {}),
                status=getattr(exc, "status", 400),
            )
        except (ValueError, TypeError, KeyError):
            result = JsonResponse({"ok": False, "error": "Check the LAF request and try again."}, status=400)
        except PermissionDenied:
            result = JsonResponse(
                {
                    "ok": False,
                    "code": "permission_denied",
                    "message": "This LAF action is outside your current access scope.",
                    "error": "This LAF action is outside your current access scope.",
                },
                status=403,
            )
        result["Cache-Control"] = "private, no-store"
        result["X-Content-Type-Options"] = "nosniff"
        result["Referrer-Policy"] = "no-referrer"
        return result

    return wrapped


def payload(request):
    if len(request.body) > 512 * 1024:
        raise services.LafError("The LAF request is too large.", status=413)
    value = json.loads(request.body or "{}")
    if not isinstance(value, dict):
        raise services.LafError("Expected LAF data.")
    return value


@csrf_exempt
@portal_auth_required
@require_http_methods(["GET", "POST"])
@response_guard
def case_laf(request, farmer_id):
    case = get_object_or_404(JawabuFarmerMaster, pk=farmer_id)
    actor, access = getattr(request, "portal_user", None), getattr(request, "portal_access", None)
    services.authorize(case, actor, access)
    if request.method == "POST":
        posted = payload(request)
        if posted.get("action") == "signature_preview":
            from origination.services.signature_appearance import preview_capture

            return JsonResponse({"ok": True, **preview_capture(posted.get("name", ""), posted.get("font", "caveat"))})
        result = services.mutate(case.pk, actor, access, posted, _portal_request_id(request, posted))
    else:
        result = services.serialize(case, actor, access)
    return JsonResponse({"ok": True, **result})


def pdf_response(version, page):
    data = bytes(version.pdf)
    if not data or services.sha(data) != version.digest:
        raise services.LafError("Preview this LAF before opening it.")
    if page is not None:
        if not 1 <= page <= version.template.page_count:
            raise services.LafError("Choose a valid page.")
        import base64
        import re
        from django.core.cache import cache
        from core.services.secure_media_preview import pdf_preview_html

        cache_key = f"portal-laf-page:{version.pk}:{version.digest}:{page}"
        image = cache.get(cache_key)
        if image is None:
            markup = pdf_preview_html(data, "Biogas LAF", start_page=page, page_limit=1, show_filename=False)
            match = re.search(rb'<img src="data:image/jpeg;base64,([A-Za-z0-9+/=]+)"', markup)
            if not match:
                raise services.LafError("This LAF page could not be prepared. Retry preview.", status=503)
            image = base64.b64decode(match[1], validate=True)
            cache.set(cache_key, image, 300)
        return HttpResponse(image, content_type="image/jpeg")
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Biogas LAF.pdf"'
    return response


@portal_auth_required
@require_http_methods(["GET"])
@response_guard
def document(request, farmer_id, version_id, page=None):
    case = get_object_or_404(JawabuFarmerMaster, pk=farmer_id)
    services.authorize(case, getattr(request, "portal_user", None), getattr(request, "portal_access", None))
    from .models import PortalLafVersion, PortalLafRequest

    version = get_object_or_404(PortalLafVersion, pk=version_id, laf__case=case)
    response = pdf_response(version, page)
    if page is None and request.GET.get("preview") == "1":
        from core.services.secure_media_preview import pdf_preview_html

        response = HttpResponse(pdf_preview_html(bytes(version.pdf), "Biogas LAF"), content_type="text/html")
    PortalLafRequest.objects.get_or_create(
        laf=version.laf,
        key=f"read:{request.portal_request_id or __import__('uuid').uuid4()}",
        defaults={
            "digest": services.sha([str(request.portal_user.pk), str(version.pk), page]),
            "result": {
                "action": "document_read",
                "actor_id": str(request.portal_user.pk),
                "version_id": str(version.pk),
                "page": page,
                "page_digest": version.digest,
            },
        },
    )
    return response
