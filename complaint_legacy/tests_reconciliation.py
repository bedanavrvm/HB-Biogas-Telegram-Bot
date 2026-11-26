from copy import deepcopy
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from core.models import CaseUpdate, ComplaintCaseEvent, ParsedMessage
from core.services import complaint_cases
from core.services.group_config import GroupConfig
from core.tests_telegram_authentication import BOT_TOKEN
from . import reconciliation, services
from .models import ImportRow, ImportUpload
from .tests import ImportFixture, source


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False)
class HistoricalReconciliationTests(ImportFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.commit(self.stage(source(
            [[2, 'SYNTHETIC CLIENT', 'OPEN', '23/11/2026', '', '12345678', '0712345678', 'Original historical note']],
            headers=['Source Row', 'Customer Name', 'Status', 'Date Reported', 'Date Resolved',
                     'Customer National ID', 'Primary Phone Number', 'HB Comments'])))
        self.case = ParsedMessage.objects.get(source='complaint_legacy')
        self.original = self.case.complaint_legacy_rows.get()
        self.original_values = deepcopy(self.original.values)
        self.group = GroupConfig(**self.owner.as_group_config_kwargs())
        self.actor = complaint_cases.staff_actor_for_user(self.group, self.user)
        staged = self.stage(source([[2, 'SYNTHETIC CLIENT', 'CLOSED', '23/11/2026', '', '12345678',
                                    '0712345678', 'Historical repair confirmed']],
                                   headers=['Source Row', 'Customer Name', 'Status', 'Date Reported',
                                            'Date Resolved', 'Customer National ID', 'Primary Phone Number', 'HB Comments']),
                            namespace='synthetic-reconciliation')
        self.upload = ImportUpload.objects.get(pk=staged['id'])
        self.row = ImportRow.objects.get(upload=self.upload)
        self.row.approved = True
        self.row.save(update_fields=['approved'])

    def apply(self, **changes):
        args = dict(group=self.group, actor=self.actor, case_id=self.case.pk,
                    expected_revision=self.case.complaint_control.revision, fields={'status': 'Closed'},
                    notes={'historical_hb_comments': 'Historical repair confirmed'},
                    reason='Reviewed historical workbook update; closure date unknown.',
                    request_key='synthetic-historical-reconciliation')
        args.update(changes)
        return reconciliation.apply_row(self.upload, self.row.pk, **args)

    def test_unknown_closure_and_notes_preserve_sources_without_live_timing(self):
        updates = CaseUpdate.objects.count()
        with patch('complaint_legacy.services.queue_row') as queue:
            self.apply()
        self.case.refresh_from_db(); self.original.refresh_from_db(); self.row.refresh_from_db()
        self.assertEqual(self.case.complaint_status, 'Closed')
        self.assertIsNone(self.case.date_resolved)
        self.assertEqual(self.original.values, self.original_values)
        self.assertEqual(CaseUpdate.objects.count(), updates)
        self.assertEqual(ComplaintCaseEvent.objects.filter(action='legacy_reconciled').count(), 1)
        self.assertEqual(self.row.case_id, self.case.pk)
        self.assertIn('Historical repair confirmed', services.historical_notes(self.case, 'resolution_comments'))
        self.assertIn('Original historical note', services.historical_notes(self.case, 'resolution_comments'))
        from core.services.complaint_timing import hydrate_timing
        hydrate_timing([self.case])
        self.assertIsNone(self.case.complaint_timing['resolution_hours'])
        self.assertIsNone(self.case.complaint_timing['response_at'])
        queue.assert_called_once()

    def test_replay_is_idempotent_but_different_payload_is_rejected(self):
        with patch('complaint_legacy.services.queue_row') as queue:
            self.apply(); self.apply()
            self.assertEqual(queue.call_count, 1)
        self.assertEqual(ComplaintCaseEvent.objects.filter(action='legacy_reconciled').count(), 1)
        with self.assertRaisesMessage(ValueError, 'different amendment'):
            self.apply(fields={'status': 'Open'})

    def test_stale_revision_and_native_cases_are_rejected(self):
        with self.assertRaisesMessage(ValueError, 'changed after review'):
            self.apply(expected_revision=999)
        self.case.source = 'complaint_mini_app'; self.case.save(update_fields=['source'])
        with self.assertRaisesMessage(ValueError, 'owning live workflow'):
            self.apply()

    def test_native_case_can_retain_historical_feedback_without_a_transition(self):
        self.case.source = 'complaint_mini_app'; self.case.save(update_fields=['source'])
        count = CaseUpdate.objects.count()
        with patch('complaint_legacy.services.queue_row'):
            self.apply(fields={})
        self.case.refresh_from_db()
        self.assertEqual(self.case.source, 'complaint_mini_app')
        self.assertEqual(self.case.complaint_status, 'Open')
        self.assertIsNone(self.case.date_resolved)
        self.assertEqual(CaseUpdate.objects.count(), count)
        self.assertIn('Historical repair confirmed', services.historical_notes(self.case, 'resolution_comments'))

    def test_other_workspace_and_inactive_actor_are_rejected(self):
        with self.assertRaises(PermissionDenied):
            self.apply(group=GroupConfig(**self.other.as_group_config_kwargs()))
        self.user.is_active = False; self.user.save(update_fields=['is_active'])
        with self.assertRaises(PermissionDenied):
            self.apply()

    def test_dates_and_source_notes_cannot_be_fabricated(self):
        with self.assertRaisesMessage(ValueError, 'Closure must be between'):
            self.apply(fields={'status': 'Closed', 'date_resolved': '22/11/2026'})
        with self.assertRaisesMessage(ValueError, 'Only closed complaints'):
            self.apply(fields={'status': 'Open', 'date_resolved': '24/11/2026'})
        with self.assertRaisesMessage(ValueError, 'match the retained source'):
            self.apply(notes={'historical_hb_comments': 'Invented response'})
