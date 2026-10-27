"""Same-origin native browser delivery; no test hosts or synthetic data."""
import base64
from functools import lru_cache
import hashlib
import json
from email.utils import parseaddr
from pathlib import Path
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_GET

ASSET_PREFIX = '/staff/assets/'
ENTRY = 'complaints-operations.html'
TYPES = {'.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.txt':'text/plain'}


@lru_cache(maxsize=1)
def load_build():
    root = Path(settings.BASE_DIR)
    directory = root / 'browser/dist-production'
    try:
        lock = json.dumps(json.loads((root/'browser/package-lock.json').read_bytes()),sort_keys=True,separators=(',',':'))
        if directory.is_symlink() or (directory/'build-manifest.json').is_symlink(): raise ValueError
        manifest = json.loads((directory / 'build-manifest.json').read_bytes())
        if (manifest.get('schemaVersion') != 1 or manifest.get('mode') != 'production'
                or manifest.get('demoOnly') is not False or manifest.get('localComplaintsDemo') is not False
                or manifest.get('closedAuthentication') is not True
                or manifest.get('closedComplaintOperations') is not True
                or manifest.get('productionBrowser') is not True or manifest.get('assetPrefix') != ASSET_PREFIX
                or manifest.get('dependencyLock') != hashlib.sha256(lock.encode()).hexdigest()):
            raise ValueError
        for row in manifest['sources']:
            name = row['path']
            if not name.startswith('browser/src/') or '..' in Path(name).parts:
                raise ValueError
            source = root/name
            if source.is_symlink() or not source.resolve().is_relative_to((root/'browser/src').resolve()):
                raise ValueError
            if hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest() != row['sha256']:
                raise ValueError
        routes, total = {}, 0
        for row in manifest['files']:
            name = row['name']
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.(html|js|css|txt)',name):
                raise ValueError
            source = directory/name
            if source.is_symlink() or source.resolve().parent != directory.resolve():
                raise ValueError
            raw = source.read_bytes()
            total += len(raw)
            if total > 25_000_000 or len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256'] or name in routes:
                raise ValueError
            routes[name] = raw, TYPES[source.suffix]
        if ENTRY not in routes or 'THIRD_PARTY_NOTICES.txt' not in routes or not manifest['sources']:
            raise ValueError
        hashes = []
        for attributes, body in re.findall(rb'<script\b([^>]*)>(.*?)</script>',routes[ENTRY][0],re.I|re.S):
            if re.search(rb'\bsrc\s*=',attributes):
                if body.strip(): raise ValueError
                continue
            if not body.strip(): continue
            if not re.search(rb'\btype\s*=\s*(?:[\"\']importmap[\"\']|importmap(?:\s|$))',attributes,re.I):
                raise ValueError
            imports = json.loads(body)
            if set(imports) != {'imports'} or not isinstance(imports['imports'],dict): raise ValueError
            if any(not isinstance(value,str) or not value.startswith(ASSET_PREFIX) or value[len(ASSET_PREFIX):] not in routes
                   for value in imports['imports'].values()): raise ValueError
            hashes.append("'sha256-"+base64.b64encode(hashlib.sha256(body).digest()).decode('ascii')+"'")
        return routes, ' '.join(sorted(set(hashes)))
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        raise ImproperlyConfigured('Build and verify the native production Complaints browser artifact before activation.') from None


def release_errors(config):
    if not getattr(config,'STAFF_BROWSER_AUTH_ENABLED',False): return []
    errors = []
    try: load_build()
    except ImproperlyConfigured as exc: errors.append(('staff_auth.E006',str(exc)))
    origin = urlsplit(getattr(config,'APP_BASE_URL',''))
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.path not in ('','/') or origin.query or origin.fragment):
        errors.append(('staff_auth.E010','Browser access requires APP_BASE_URL to be its exact HTTPS origin.'))
    sender=getattr(config,'STAFF_BROWSER_EMAIL_FROM','')
    try: validate_email(parseaddr(sender)[1])
    except ValidationError: sender=''
    if (not getattr(config,'STAFF_BROWSER_INVITATIONS_ENABLED',False) or not sender or not getattr(config,'RESEND_API_KEY','')):
        errors.append(('staff_auth.E011','Configure the browser invitation sender and enable its reviewed delivery before activation.'))
    if (config.DATABASES['default']['ENGINE']!='django.db.backends.postgresql'
            or config.CACHES.get('default',{}).get('BACKEND')!='staff_auth.security_cache.PostgresSecurityCache'):
        errors.append(('staff_auth.E012','Production browser access requires PostgreSQL native security state (ADR 0074).'))
    return errors


def _enabled():
    if not settings.STAFF_BROWSER_AUTH_ENABLED or not settings.STAFF_BROWSER_COMPLAINTS_ENABLED:
        raise Http404


@require_GET
def entry(request):
    _enabled()
    return _response(ENTRY)


@require_GET
def asset(request,filename):
    _enabled()
    if filename.endswith('.html') or request.GET: raise Http404
    return _response(filename)


def _response(filename):
    routes, hashes = load_build()
    if filename not in routes: raise Http404
    raw, kind = routes[filename]
    response = HttpResponse(raw,content_type=kind+'; charset=utf-8')
    response['Cache-Control']='no-store, private'
    response['Referrer-Policy']='no-referrer'
    response['X-Content-Type-Options']='nosniff'
    response['Content-Security-Policy']=(
        "default-src 'none'; script-src 'self' "+hashes+"; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src blob: data:; frame-src blob:; font-src 'none'; "
        "form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


@require_GET
def home(request):
    _enabled()
    return HttpResponseRedirect('/staff/app/complaints/')
