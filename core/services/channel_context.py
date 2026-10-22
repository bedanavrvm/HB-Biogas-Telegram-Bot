"""Request attribution only. This module never authenticates or authorizes."""
from contextvars import ContextVar
from dataclasses import dataclass, replace
import logging
import re
from time import monotonic
from uuid import UUID, uuid4

from django.conf import settings

_current = ContextVar('workflow_request_channel', default=None)
logger = logging.getLogger('core.channel_requests')
ROUTES = (
    ('/api/staff/complaints/', 'browser', 'complaint_cases'),
    ('/api/staff/auth/', 'browser', 'staff_access'),
    ('/api/staff/workspace/', 'browser', 'staff_access'),
    ('/api/complaints/', 'telegram', 'complaint_cases'),
    ('/api/tat-tracker/', 'telegram', 'tat_tracker'),
    ('/api/portal/', 'telegram', 'jawabu_portal'),
    ('/api/origination/', 'telegram', 'loan_origination'),
)


def _label(value):
    value = str(value or '')
    return value if re.fullmatch(r'[A-Za-z0-9._-]{1,64}', value) else ''


@dataclass(frozen=True)
class ChannelContext:
    request_id: str
    attempted_channel: str = 'unknown'
    channel: str = 'unknown'
    workflow: str = ''
    authentication: str = ''
    server_release: str = ''
    client_build: str = ''


def bind_verified_channel(channel, authentication):
    """Called only by the owning, successful authentication implementation."""
    current = _current.get()
    if current is not None and channel in {'browser', 'telegram', 'system'}:
        _current.set(replace(current, channel=channel, authentication=authentication))


def audit_context():
    current = _current.get()
    if current is None:
        return {}
    return {'channel': current.channel, 'attempted_channel': current.attempted_channel,
            'request_id': current.request_id, 'workflow': current.workflow,
            'authentication': current.authentication, 'server_release': current.server_release,
            'client_build': current.client_build}


class ChannelRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            request_id = str(UUID(request.headers.get('X-Correlation-ID', '')))
        except (ValueError, TypeError, AttributeError):
            request_id = str(uuid4())
        attempted, workflow = next(((channel, workflow) for prefix, channel, workflow in ROUTES
                                    if request.path.startswith(prefix)), ('unknown', ''))
        release = _label(getattr(settings, 'APP_RELEASE', ''))
        # Never log arbitrary client header contents (they may contain PII or
        # secrets). Only a known deployment label can survive as a client claim.
        supplied_build = request.headers.get('X-Client-Build', '')
        known_build = release
        token = _current.set(ChannelContext(request_id, attempted_channel=attempted, workflow=workflow,
            server_release=release,
            client_build=known_build if known_build and supplied_build == known_build else ''))
        started = monotonic()
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
            response['X-Correlation-ID'] = request_id
            response['X-Request-Channel'] = _current.get().channel
            return response
        finally:
            context = audit_context()
            if workflow:
                match = getattr(request, 'resolver_match', None)
                route = str(getattr(match, 'url_name', '') or getattr(getattr(match, 'func', None), '__name__', 'unresolved'))
                logger.info('Workflow request: channel=%s attempted_channel=%s workflow=%s route=%s status=%s duration_ms=%.1f correlation=%s release=%s client_build=%s',
                    context['channel'], attempted, workflow, route, status, (monotonic() - started) * 1000,
                    request_id, context['server_release'], context['client_build'])
            _current.reset(token)
