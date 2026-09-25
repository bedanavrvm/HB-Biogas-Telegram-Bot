import hashlib
import io
import uuid
import logging

from PIL import Image, UnidentifiedImageError
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from core.models import AccessGrant
from core.services.order_approval import GoogleDriveMediaStorage
from .models import TestCase, TestCycle, TestEvidence, TestRun


WORKFLOWS = {
    'portal': 'jawabu_portal',
    'tat_tracker': 'tat_tracker',
    'complaints': 'complaint_cases',
    'spin': 'spin_credit_analysis',
    'origination': 'jawabu_portal',
}
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
logger = logging.getLogger(__name__)


def allowed_cycles(user):
    """Do not combine group, branch and product from separate IT grants."""
    qs = TestCycle.objects.all()
    if not user.is_active or not user.is_staff:
        return qs.none()
    if user.is_superuser:
        return qs
    grants = list(AccessGrant.objects.filter(user=user, active=True, role__iexact='IT'))
    scope = Q(pk__in=[])
    for grant in grants:
        for app, workflow in WORKFLOWS.items():
            if grant.workflow != workflow:
                continue
            clause = Q(app=app)
            if grant.group_configuration_id:
                clause &= Q(group_configuration_id=grant.group_configuration_id)
            if grant.branch:
                clause &= Q(branch__iexact=grant.branch)
            if grant.product:
                clause &= Q(product__iexact=grant.product)
            scope |= clause
    return qs.filter(scope)


def can_create_cycle(user, cycle):
    if not user.is_active or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    if cycle.app not in WORKFLOWS:
        return False
    grants = AccessGrant.objects.filter(user=user, active=True, role__iexact='IT', workflow=WORKFLOWS[cycle.app])
    for grant in grants:
        if grant.group_configuration_id and grant.group_configuration_id != cycle.group_configuration_id:
            continue
        if grant.branch and grant.branch.casefold() != cycle.branch.casefold():
            continue
        if grant.product and grant.product.casefold() != cycle.product.casefold():
            continue
        return True
    return False


def require_cycle(user, cycle):
    if not allowed_cycles(user).filter(pk=cycle.pk).exists():
        raise PermissionDenied


def latest_runs(cycle):
    result = {}
    for run in TestRun.objects.filter(cycle=cycle).select_related('tester').order_by('-created_at', '-pk'):
        result.setdefault(run.test_case_id, run)
    return result


def cycle_summary(cycle):
    cases = list(TestCase.objects.filter(app=cycle.app, pk__in=cycle.case_ids))
    current = latest_runs(cycle)
    previous_cycle = TestCycle.objects.filter(
        app=cycle.app, environment=cycle.environment,
        group_configuration=cycle.group_configuration, branch=cycle.branch,
        product=cycle.product, created_at__lt=cycle.created_at,
    ).order_by('-created_at').first()
    previous = latest_runs(previous_cycle) if previous_cycle else {}
    counts = {'total': len(cases), 'tested': 0, 'untested': 0, 'pass': 0, 'fail': 0,
              'blocked': 0, 'regressions': 0, 'persistent_failures': 0, 'newly_fixed': 0,
              'blocker_regressions': 0}
    rows = []
    for case in cases:
        run, prior = current.get(case.pk), previous.get(case.pk)
        if run:
            counts['tested'] += 1
            counts[run.result] += 1
        else:
            counts['untested'] += 1
        change = ''
        if run and prior:
            if prior.result == 'pass' and run.result == 'fail':
                change = 'Regression'
                counts['regressions'] += 1
                if run.severity == 'blocker':
                    counts['blocker_regressions'] += 1
            elif prior.result == 'fail' and run.result == 'fail':
                change = 'Still failing'
                counts['persistent_failures'] += 1
            elif prior.result == 'fail' and run.result == 'pass':
                change = 'Fixed'
                counts['newly_fixed'] += 1
        rows.append({'case': case, 'run': run, 'prior': prior, 'change': change})
    return {'counts': counts, 'rows': rows, 'previous_cycle': previous_cycle}


def validate_screenshot(upload):
    if upload.size > MAX_SCREENSHOT_BYTES or upload.size == 0:
        raise ValidationError('Screenshot must be a non-empty PNG or JPEG under 5 MB.')
    content = upload.read()
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > 40_000_000:
                raise ValidationError('Screenshot dimensions are too large.')
            mime = Image.MIME.get(image.format)
            if mime not in ('image/png', 'image/jpeg'):
                raise ValidationError('Screenshot must be a PNG or JPEG image.')
            # Re-encode pixels so EXIF and other embedded source metadata do not
            # leave the browser in QA evidence.
            clean = io.BytesIO()
            if mime == 'image/jpeg':
                image.convert('RGB').save(clean, format='JPEG', quality=90)
            else:
                image.convert('RGBA').save(clean, format='PNG')
            content = clean.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError('Screenshot must be a valid PNG or JPEG image.') from exc
    if len(content) > MAX_SCREENSHOT_BYTES:
        raise ValidationError('Screenshot is too large after processing.')
    return content, mime, hashlib.sha256(content).hexdigest()


def attach_screenshot(run, upload):
    content, mime, digest = validate_screenshot(upload)
    existing = TestEvidence.objects.filter(run=run, sha256=digest).first()
    if existing:
        return existing
    name = f'qa-{run.pk}-{digest[:12]}.{ "png" if mime == "image/png" else "jpg" }'
    file_id, _ = GoogleDriveMediaStorage().upload(
        content, name, mime, str(run.pk), timezone.now(),
        workflow_key='qa_tracker', record_type=run.cycle.app,
        record_key=str(run.cycle.pk),
    )
    return TestEvidence.objects.create(
        run=run, drive_file_id=file_id, filename=name, mime_type=mime,
        size_bytes=len(content), sha256=digest,
    )


def record_result(cycle, case, user, *, result, severity='', bug_reference='', notes='', request_key):
    require_cycle(user, cycle)
    if case.app != cycle.app or case.pk not in cycle.case_ids:
        raise ValidationError('This test is not in the selected release checklist.')
    if result not in dict(TestRun.RESULT_CHOICES):
        raise ValidationError('Choose Pass, Fail, or Blocked.')
    if result != 'fail':
        severity = ''
    elif severity not in ('blocker', 'major', 'minor'):
        raise ValidationError('Choose a severity for a failed test.')
    request_key = uuid.UUID(str(request_key))
    run, _ = TestRun.objects.get_or_create(
        request_key=request_key,
        defaults={'cycle': cycle, 'test_case': case, 'test_description': case.description,
                  'test_steps': case.steps, 'test_expected': case.expected,
                  'tester': user, 'result': result, 'severity': severity,
                  'bug_reference': bug_reference[:100], 'notes': notes[:4000]},
    )
    if (run.cycle_id != cycle.pk or run.test_case_id != case.pk or run.tester_id != user.pk
            or run.result != result or run.severity != severity or run.bug_reference != bug_reference[:100]
            or run.notes != notes[:4000]):
        raise ValidationError('This submission key belongs to another result.')
    return run
