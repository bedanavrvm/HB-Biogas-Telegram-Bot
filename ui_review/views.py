import json
import logging
from functools import wraps
from html import escape

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Subquery
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from core.services.telegram_identity import TelegramAuthenticationError
from . import services
from .catalog import APPS, PATTERNS, ROLES, STATES, current_manifest, digest, inventory
from .models import ReviewRevision, StandardRelease
from .scenes import scene_html

logger = logging.getLogger(__name__)


def ui_review_auth_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not settings.UI_DESIGN_LAB_ENABLED:
            raise Http404
        raw = request.headers.get('X-Telegram-Init-Data')
        if raw:
            try:
                actor = authenticate(request, init_data=raw)
            except TelegramAuthenticationError:
                actor = None
        else:
            actor = request.user
        if not actor or not actor.is_authenticated or not actor.is_active or not actor.is_superuser:
            return JsonResponse({'ok': False, 'error': 'Design Lab requires an active Superuser account.'}, status=403)
        if not raw and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            failure = CsrfViewMiddleware(lambda req: HttpResponse()).process_view(request, lambda req: None, (), {})
            if failure:
                return failure
        request.design_actor = actor
        try:
            response = view(request, *args, **kwargs)
        except (ValidationError, ValueError, TypeError, KeyError) as error:
            message = ' '.join(error.messages) if isinstance(error, ValidationError) else 'Invalid review request. Refresh and try again.'
            response = JsonResponse({'ok': False, 'error': message}, status=400)
        response['Cache-Control'] = 'no-store, private'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    # Cookie writes are checked above; only cryptographically verified Telegram
    # identity can use the non-cookie path. No debug/auth bypass exists.
    return csrf_exempt(wrapped)


@require_GET
@ensure_csrf_cookie
def index(request):
    if not settings.UI_DESIGN_LAB_ENABLED:
        raise Http404
    # Anonymous bootstrap has no source catalogue, evidence or review data.
    response = render(request, 'ui_review/index.html')
    response['Cache-Control'] = 'no-store, private'
    response['Content-Security-Policy'] = "frame-ancestors 'self' https://web.telegram.org"
    response.xframe_options_exempt = True
    return response


def revision_data(revision):
    manifest = revision.manifest
    return {'id': str(revision.pk), 'pattern': revision.pattern, 'fingerprint': revision.fingerprint,
            'current': manifest['source_fingerprint'] == digest(current_manifest(revision.pattern)),
            'evidence': [{**{key: value for key, value in item.items() if key not in ('drive_file_id',)},
                          'url': f'/ui-lab/api/revisions/{revision.pk}/evidence/{index}/'}
                         for index, item in enumerate(manifest['evidence'])],
            'decisions': [{'id': str(event.pk), 'decision': event.decision, 'payload': event.payload,
                           'at': event.created_at.isoformat(), 'actor_id': event.actor_id}
                          for event in revision.decisions.all()]}


@require_GET
@ui_review_auth_required
def catalogue(request):
    patterns = inventory()
    latest = {}
    latest_id = ReviewRevision.objects.filter(pattern=OuterRef('pattern')).values('pk')[:1]
    for revision in ReviewRevision.objects.filter(pk=Subquery(latest_id)).prefetch_related('decisions'):
        latest.setdefault(revision.pattern, revision)
    for item in patterns:
        revision = latest.get(item['key'])
        event = next((event for event in revision.decisions.all() if event.decision != 'device'), None) if revision else None
        item['review_status'] = ('stale' if revision and revision.manifest['source_fingerprint'] != item['fingerprint']
                                 else {'adopt':'approved','approve':'approved','changes':'changes','decline':'declined','defer':'deferred'}.get(event.decision if event else '', 'unreviewed'))
    return JsonResponse({'ok': True, 'patterns': patterns, 'apps': {key: value['label'] for key, value in APPS.items()},
                         'states': STATES, 'roles': ROLES, 'phase_6': 'Not authorised',
                         'releases': [{'version': item.version, 'id': str(item.pk)} for item in StandardRelease.objects.all()[:10]]})


@require_GET
@ui_review_auth_required
def pattern_detail(request, pattern):
    if pattern not in PATTERNS:
        raise Http404
    revisions = list(ReviewRevision.objects.filter(pattern=pattern).prefetch_related('decisions')[:30])
    return JsonResponse({'ok': True, 'manifest': current_manifest(pattern),
                         'revisions': [revision_data(item) for item in revisions]})


@require_POST
@ui_review_auth_required
def create_revision(request):
    body = json.loads(request.body)
    revision = services.snapshot(body['pattern'], body['fingerprint'], request.design_actor)
    return JsonResponse({'ok': True, 'revision': revision_data(revision)})


@require_POST
@ui_review_auth_required
def submit_decision(request, revision_id):
    body = json.loads(request.body)
    revision = get_object_or_404(ReviewRevision, pk=revision_id)
    event = services.decide(revision, request.design_actor, decision=body['decision'], payload=body.get('payload', {}), request_key=body['request_key'])
    return JsonResponse({'ok': True, 'id': str(event.pk), 'revision': revision_data(revision)})


@require_POST
@ui_review_auth_required
def upload_evidence(request, revision_id):
    revision = get_object_or_404(ReviewRevision, pk=revision_id)
    file = request.FILES.get('screenshot')
    if not file:
        raise ValidationError('Select a synthetic screenshot first.')
    if request.POST.get('synthetic_only') != 'true':
        raise ValidationError('Confirm that this capture contains synthetic data only.')
    try:
        result = services.attach_evidence(revision, request.design_actor, file, variant=request.POST.get('variant'),
            theme=request.POST.get('theme'), state=request.POST.get('state'), kind=request.POST.get('kind'),
            font_verified=request.POST.get('font_verified') == 'true')
    except ValidationError:
        raise
    except Exception:
        logger.exception('Design evidence storage failed: revision=%s', revision.pk)
        return JsonResponse({'ok': False, 'error': 'Screenshot could not be stored. Keep the file and retry; no approval was recorded.'}, status=503)
    return JsonResponse({'ok': True, 'revision': revision_data(result)})


@require_GET
@ui_review_auth_required
def evidence(request, revision_id, index):
    revision = get_object_or_404(ReviewRevision, pk=revision_id)
    try:
        content, item = services.read_evidence(revision, index)
    except ValidationError:
        raise
    except Exception:
        logger.exception('Design evidence retrieval failed: revision=%s', revision.pk)
        return JsonResponse({'ok': False, 'error': 'Screenshot unavailable. Retry or capture it again.'}, status=503)
    response = HttpResponse(content, content_type=item['mime'])
    response['Content-Disposition'] = f'inline; filename="{item["filename"]}"'
    return response


@require_POST
@ui_review_auth_required
def release(request):
    result = services.prepare_release(request.design_actor, json.loads(request.body)['request_key'])
    return JsonResponse({'ok': True, 'version': result.version, 'id': str(result.pk)})


@require_GET
@ui_review_auth_required
def export_release(request, release_id):
    item = get_object_or_404(StandardRelease, pk=release_id)
    response = JsonResponse({'version': item.version, 'fingerprint': item.fingerprint, 'manifest': item.manifest}, json_dumps_params={'indent': 2})
    response['Content-Disposition'] = f'attachment; filename="ui-standard-v{item.version}.json"'
    return response


@require_GET
@ui_review_auth_required
def scene(request, app, scene):
    state = request.GET.get('state', 'one')
    role = request.GET.get('role', 'manager')
    if app not in APPS or scene not in {item['scene'] for item in PATTERNS.values()} or state not in STATES or role not in ROLES:
        raise Http404
    origin = request.build_absolute_uri('/').rstrip('/')
    policy = (f"default-src 'none'; script-src {origin} data: 'unsafe-inline'; "
        f"style-src {origin} 'unsafe-inline' https://fonts.googleapis.com; font-src {origin} data: https://fonts.gstatic.com; "
        f"img-src {origin} data: blob:; connect-src 'none'; form-action 'none'; frame-src 'none'; base-uri {origin}")
    html = scene_html(app, scene, state, role).replace('<head>',
        '<head><meta http-equiv="Content-Security-Policy" content="'+escape(policy, quote=True)+'">', 1)
    response = HttpResponse(html)
    # Scripts run as an opaque sandbox and can only synthesize API responses.
    response['Content-Security-Policy'] = policy + "; frame-ancestors 'self'"
    response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response
