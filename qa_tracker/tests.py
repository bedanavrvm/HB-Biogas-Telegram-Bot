import io
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase as DjangoTestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import AccessGrant, GroupSheetConfiguration
from .models import TestCase, TestCycle, TestEvidence, TestRun
from .services import allowed_cycles, attach_screenshot, cycle_summary, record_result


class QaTrackerTests(DjangoTestCase):
    def test_other_miniapp_checklists_are_seeded(self):
        minimums = {
            'tat_tracker': 9, 'complaints': 9, 'spin': 6,
            'origination': 7, 'fca_review': 3,
            'farmers_review': 3, 'order_approval': 4,
        }
        for app, minimum in minimums.items():
            with self.subTest(app=app):
                self.assertGreaterEqual(TestCase.objects.filter(app=app, active=True).count(), minimum)

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(username='qa_root', email='qa@example.org', password='safe-test-pass')
        self.it = User.objects.create_user(username='qa_it', email='qa-it@example.org', password='safe-test-pass', is_staff=True)
        self.outsider = User.objects.create_user(username='qa_no', email='qa-no@example.org', password='safe-test-pass', is_staff=True)
        self.group = GroupSheetConfiguration.objects.create(group_id='-12345')
        self.other_group = GroupSheetConfiguration.objects.create(group_id='-54321')
        AccessGrant.objects.create(user=self.it, workflow='jawabu_portal', role='IT', active=True, group_configuration=self.group)
        self.case = TestCase.objects.create(id='QA-001', app='portal', journey='Navigation', description='Back path', steps='Open then back', expected='Return to origin')
        self.cycle = TestCycle.objects.create(app='portal', release='v1', environment='pilot', group_configuration=self.group, created_by=self.superuser)
        self.other_cycle = TestCycle.objects.create(app='portal', release='v1', environment='pilot', group_configuration=self.other_group, created_by=self.superuser)

    def test_it_scope_and_no_access_for_adjacent_staff(self):
        self.assertEqual(list(allowed_cycles(self.it)), [self.cycle])
        self.assertFalse(allowed_cycles(self.outsider).exists())
        self.client.force_login(self.it)
        self.assertEqual(self.client.get(reverse('admin:qa_tracker_cycle_run', args=[self.cycle.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:qa_tracker_cycle_run', args=[self.other_cycle.pk])).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse('admin:qa_tracker_cycle_run', args=[self.cycle.pk])).status_code, 404)

    def test_other_miniapp_cycles_use_their_workflow_grant(self):
        tat_cycle = TestCycle.objects.create(app='tat_tracker', release='v1', environment='pilot', group_configuration=self.group)
        self.assertGreater(len(tat_cycle.case_ids), 0)
        self.assertFalse(allowed_cycles(self.it).filter(pk=tat_cycle.pk).exists())
        AccessGrant.objects.create(user=self.it, workflow='tat_tracker', role='IT', active=True, group_configuration=self.group)
        self.assertTrue(allowed_cycles(self.it).filter(pk=tat_cycle.pk).exists())
        farmer_cycle = TestCycle.objects.create(app='farmers_review', release='v1', environment='pilot', group_configuration=self.group)
        self.assertTrue(allowed_cycles(self.it).filter(pk=farmer_cycle.pk).exists())

    def test_latest_run_comparison_and_idempotency(self):
        prior = record_result(self.cycle, self.case, self.it, result='pass', request_key=uuid.uuid4())
        self.assertEqual(record_result(self.cycle, self.case, self.it, result='pass', request_key=prior.request_key).pk, prior.pk)
        with self.assertRaises(ValidationError):
            record_result(self.cycle, self.case, self.it, result='blocked', request_key=prior.request_key)
        current_cycle = TestCycle.objects.create(app='portal', release='v2', environment='pilot', group_configuration=self.group)
        record_result(current_cycle, self.case, self.it, result='fail', severity='blocker', request_key=uuid.uuid4())
        summary = cycle_summary(current_cycle)
        self.assertEqual(summary['counts']['regressions'], 1)
        self.assertEqual(summary['counts']['blocker_regressions'], 1)
        self.assertEqual(summary['counts']['fail'], 1)
        record_result(current_cycle, self.case, self.it, result='pass', request_key=uuid.uuid4())
        self.assertEqual(cycle_summary(current_cycle)['counts']['pass'], 1)
        self.assertEqual(cycle_summary(current_cycle)['counts']['regressions'], 0)

    def test_protected_pdf_and_screenshot_download(self):
        run = record_result(self.cycle, self.case, self.it, result='pass', request_key=uuid.uuid4())
        image = Image.new('RGB', (12, 12), 'blue')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        upload = SimpleUploadedFile('customer-name.png', buffer.getvalue(), content_type='image/png')
        with patch('qa_tracker.services.GoogleDriveMediaStorage') as storage:
            storage.return_value.upload.return_value = ('private-id', 'unused')
            evidence = attach_screenshot(run, upload)
            self.assertEqual(evidence.filename.startswith('qa-'), True)
            self.assertEqual(attach_screenshot(run, SimpleUploadedFile('again.png', buffer.getvalue())), evidence)
        with patch('qa_tracker.admin.GoogleDriveMediaStorage') as storage:
            storage.return_value.download.return_value = buffer.getvalue()
            self.client.force_login(self.it)
            url = reverse('admin:qa_tracker_cycle_evidence', args=[self.cycle.pk, evidence.pk])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            pdf = self.client.get(reverse('admin:qa_tracker_cycle_report', args=[self.cycle.pk]))
            self.assertEqual(pdf.status_code, 200)
            self.assertTrue(pdf.content.startswith(b'%PDF'))
            self.client.force_login(self.outsider)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_bad_screenshot_and_retired_test(self):
        run = record_result(self.cycle, self.case, self.it, result='blocked', request_key=uuid.uuid4())
        with self.assertRaises(ValidationError):
            attach_screenshot(run, SimpleUploadedFile('bad.png', b'not-an-image'))
        self.case.active = False
        self.case.save(update_fields=['active'])
        # Retirement preserves the frozen release checklist and its run history.
        record_result(self.cycle, self.case, self.it, result='pass', request_key=uuid.uuid4())
        self.assertEqual(TestRun.objects.count(), 2)
        next_cycle = TestCycle.objects.create(app='portal', release='v2', environment='pilot', group_configuration=self.group)
        self.assertNotIn(self.case.pk, next_cycle.case_ids)
