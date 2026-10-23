"""Opt-in real React/native-session Complaints operations; synthetic only."""
import json
import os
from pathlib import Path
import subprocess
from datetime import timedelta
from unittest import skipUnless

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from core.models import AccessGrant, BranchServiceArea, CaseUpdate, ComplaintCategory, OperationalLocation, ParsedMessage
from core.services.complaint_cases import ensure_case_control
from core.services.compliance_audit import record_event
from core.tests_browser_complaints import synthetic_case
from . import tests_complaints_transport as transport
from .tests import PASSWORD


@skipUnless(os.environ.get('RUN_STAFF_BROWSER_E2E') == '1', 'Opt-in isolated browser integration.')
@override_settings(ROOT_URLCONF='staff_auth.complaints_operations_test_urls',
                   STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints-operations',
                   STAFF_BROWSER_COMPLAINTS_ENABLED=True)
class ComplaintsOperationsTransportTests(transport.ComplaintsTransportTests):
    def setUp(self):
        super().setUp()
        # Keep short resolutions on their intended Nairobi reporting day even
        # when this suite runs after 20:00 EAT. Otherwise 4h crosses midnight
        # and merges with the zero-hour fixture's daily median.
        now = timezone.now().replace(hour=6, minute=0, second=0, microsecond=0)
        for case, days in zip(self.cases, (1, 3, 5, 8, 15, 20, 35)):
            case.timestamp = now - timedelta(days=days)
            case.save(update_fields=['timestamp'])
            ensure_case_control(case)
        self.closed.timestamp = now - timedelta(days=12)
        self.closed.date_resolved = now - timedelta(days=4)
        self.closed.save(update_fields=['timestamp', 'date_resolved'])
        control = ensure_case_control(self.closed)
        control.sla_target_hours = 72
        control.save(update_fields=['sla_target_hours'])
        for index, hours, target in ((9, 0.25, 72), (10, 4, 72), (11, 0, 72)):
            start = now - timedelta(days=1 if index == 11 else 2)
            case = synthetic_case(self.group, index, timestamp=start,
                complaint_status='Closed', date_resolved=start + timedelta(hours=hours))
            control = ensure_case_control(case)
            control.sla_target_hours = target
            control.save(update_fields=['sla_target_hours'])
        response = CaseUpdate.objects.create(parsed_message=self.cases[2], group_id=self.group.group_id,
            old_status='Open', new_status='Open', source='mini_app_comment',
            resolution_text='Synthetic recorded first response.', updated_by='Synthetic HB officer')
        CaseUpdate.objects.filter(pk=response.pk).update(created_at=self.cases[2].timestamp + timedelta(hours=12))
        record_event(workflow='complaint_cases', action='case.updated', subject_type='complaint',
            subject_id=str(self.cases[2].pk), source_model='CaseUpdate', source_event_id=str(response.pk),
            deduplication_key=f'operations-response-{response.pk}', metadata={'actor_affiliation': 'HB'})
        event = CaseUpdate.objects.create(parsed_message=self.cases[3], group_id=self.group.group_id,
            old_status='Closed', new_status='Reopened', source='mini_app', updated_by='Synthetic manager')
        CaseUpdate.objects.filter(pk=event.pk).update(created_at=now - timedelta(days=1))
        self.cases[3].complaint_status = 'Reopened'
        self.cases[3].save(update_fields=['complaint_status'])
        OperationalLocation.objects.create(location_type='branch', code='BROWSER-FIXTURE', name='Synthetic Other Branch')
        branch = OperationalLocation.objects.get(code='BROWSER-FIXTURE')
        county = OperationalLocation.objects.create(location_type='county', code='RECOVERY-COUNTY', name='Synthetic County')
        OperationalLocation.objects.create(location_type='sub_county', code='RECOVERY-AREA', name='Synthetic Constituency', parent=county)
        BranchServiceArea.objects.create(branch=branch, area=county)
        ComplaintCategory.objects.create(key='synthetic-recovery', label='Synthetic service issue')
        for index in range(61):
            CaseUpdate.objects.create(parsed_message=self.cases[1], group_id=self.group.group_id,
                old_status='Open', new_status='Open', source='mini_app_comment', updated_by='Synthetic history author',
                resolution_text=f'Synthetic older note {index:03d}')

    def test_native_authenticated_complaints_workspace(self):
        from .transport_test_urls import assets
        assets(operations=True)
        AccessGrant.objects.create(user=self.user, workflow='complaint_cases', role='IT', group_configuration=self.group)
        root = Path(settings.BASE_DIR)
        result = subprocess.run([os.environ.get('STAFF_BROWSER_TEST_NODE', 'node'),
            str(root / 'scripts/test_complaints_operations_transport.js')],
            input=json.dumps({'origin': self.live_server_url, 'username': self.user.username,
                'password': PASSWORD,
                'code': self.codes[0], 'resume_code': self.codes[1], 'group': str(self.group.pk), 'build': settings.STAFF_BROWSER_TRANSPORT_BUILD,
                'preferences_only': os.environ.get('COMPLAINTS_BROWSER_PREFERENCES_ONLY') == '1',
                'month_start': timezone.localdate().replace(day=1).isoformat()}),
            cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=240)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        report = json.loads(result.stdout)
        self.assertTrue(report['passed'], report)
        if os.environ.get('COMPLAINTS_BROWSER_PREFERENCES_ONLY') != '1':
            self.assertEqual(CaseUpdate.objects.filter(resolution_text='Synthetic browser follow-up.').count(), 1)
            self.assertEqual(ParsedMessage.objects.filter(customer_name__iexact='Synthetic confirmed creation').count(), 1)
        checks = 'preferences checks' if os.environ.get('COMPLAINTS_BROWSER_PREFERENCES_ONLY') == '1' else 'comment/draft/export/history/preferences checks'
        print(f"Closed operations: {report['captures']} captures, native {checks} passed")


@override_settings(STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints-operations-development')
class ComplaintsOperationsDevelopmentTransportTests(ComplaintsOperationsTransportTests):
    """Same native workflow under development and React StrictMode."""


class ComplaintsResponsiveTransportTests(ComplaintsOperationsTransportTests):
    """Dedicated native-session visual checks; do not extend the human review host."""
    test_native_authenticated_complaints_workspace = None

    def test_responsive_controls_with_native_authentication(self):
        from .transport_test_urls import assets
        assets(operations=True)
        AccessGrant.objects.create(user=self.user, workflow='complaint_cases', role='IT', group_configuration=self.group)
        case = synthetic_case(self.group, 991, complaint_category='Synthetic additional type')
        ensure_case_control(case)
        root = Path(settings.BASE_DIR)
        environment = {**os.environ, 'COMPLAINTS_REVIEW_ORIGIN': self.live_server_url,
            'COMPLAINTS_REVIEW_BUILD': settings.STAFF_BROWSER_TRANSPORT_BUILD,
            'COMPLAINTS_REVIEW_USERNAME': self.user.username,
            'COMPLAINTS_REVIEW_PASSWORD': PASSWORD, 'COMPLAINTS_REVIEW_CODE': self.codes[0]}
        result = subprocess.run([os.environ.get('STAFF_BROWSER_TEST_NODE', 'node'),
            str(root / 'node_modules/playwright/cli.js'), 'test',
            'core/tests_browser/complaints_responsive.spec.js', '--workers=1', '--reporter=line',
            '--output=' + str(root / 'test-results/complaints-responsive' / settings.STAFF_BROWSER_TRANSPORT_BUILD)],
            cwd=root, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=200)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-5000:])
        print('Responsive Complaints: native MFA, viewports, autosave, export, charts and media passed')


@override_settings(STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints-operations-development')
class ComplaintsResponsiveDevelopmentTransportTests(ComplaintsResponsiveTransportTests):
    """Responsive controls under development and React StrictMode."""
