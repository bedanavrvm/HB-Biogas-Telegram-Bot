"""Source-preserving Portal SysUp review regression boundary."""
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from core.models import JawabuFarmerMaster
from core.tests_system_export import export_csv
from core.services.system_export import create_system_export_review_batch
from core.services.sysup_review import commit_review


class PortalSysupReviewTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='training-reviewer')
        self.farmer = JawabuFarmerMaster.objects.create(customer_name='Training Applicant',
            national_id='99999991', primary_phone='254700000091', branch='Limuru')
        self.source = export_csv([{'Customer ID': '991', 'Name': 'Applicant, Training',
            'ID NO': '99999991', 'Mobile No': '0700000091', 'Branch': 'Limuru', 'LGF Balance': '6000'}])
        self.batch, _ = create_system_export_review_batch(group_id='training-group', telegram_message_id='review-1',
            sender='Training reviewer', source_filename='synthetic.csv', content=self.source)
        row = self.batch.parsed_rows[0]
        self.submitted = [{'row_fingerprint': row['row_fingerprint'], 'approved': True,
            'Matched Farmer ID': str(self.farmer.pk), 'case_revision': self.farmer.workflow_revision,
            'field_choices': {'Name': 'portal', 'LGF Balance': 'sysup'}, 'source_corrections': {'LGF Balance': '0'}}]

    def commit(self, *, authorize=lambda farmer: None, revision=None, request_id='synthetic-review'):
        with patch('core.services.portal_publication.reserve_farmer_publication'):
            return commit_review(self.batch.pk, self.submitted, revision=revision or self.batch.portal_revision,
                request_id=request_id, actor=self.actor, authorize=authorize)

    def test_choices_preserve_portal_and_accept_corrected_zero_without_changing_source(self):
        original = self.batch.parsed_rows[0]['LGF Balance']
        batch, result = self.commit()
        self.assertTrue(result['success'])
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.customer_name, 'Training Applicant')
        self.assertEqual(self.farmer.system_deposit_paid_jbl, Decimal('0'))
        self.assertEqual(original, '6000')
        self.assertEqual(batch.portal_commit_replays[0]['actor'], self.actor.pk)

    def test_replay_survives_consumed_rows_and_stale_revision(self):
        first, result = self.commit()
        replay, replay_result = self.commit(revision=1)
        self.assertEqual(replay_result, result)
        self.assertEqual(replay.portal_revision, first.portal_revision)
        self.assertEqual(len(replay.portal_commit_replays), 1)

    def test_stale_case_and_scope_failure_leave_upload_and_case_unchanged(self):
        self.farmer.workflow_revision += 1
        self.farmer.save(update_fields=['workflow_revision'])
        with self.assertRaisesMessage(ValueError, 'selected case changed'):
            self.commit()
        self.submitted[0]['case_revision'] = self.farmer.workflow_revision
        def denied(farmer):
            raise ValueError('Outside scope')
        with self.assertRaisesMessage(ValueError, 'Outside scope'):
            self.commit(authorize=denied)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.portal_revision, 1)
        self.assertEqual(self.batch.parsed_rows[0]['LGF Balance'], '6000')

    def test_altered_source_fingerprint_and_unsupported_field_rejected(self):
        self.submitted[0]['field_choices']['final_decision'] = 'sysup'
        with self.assertRaisesMessage(ValueError, 'Unsupported SysUp field'):
            self.commit()
        self.submitted[0]['row_fingerprint'] = 'different-file'
        with self.assertRaisesMessage(ValueError, 'source rows changed'):
            self.commit()

    def test_invalid_case_id_is_a_clean_conflict(self):
        self.submitted[0]['Matched Farmer ID'] = 'not-a-case'
        with self.assertRaisesMessage(ValueError, 'Choose an available Portal case'):
            self.commit()

    def test_numeric_zero_correction_is_preserved(self):
        self.submitted[0]['source_corrections']['LGF Balance'] = 0
        self.commit()
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.system_deposit_paid_jbl, Decimal('0'))

    def test_unchanged_batch_can_close_without_selection_or_case_write(self):
        self.batch.parsed_rows[0]['Import Status'] = 'already_current'
        self.batch.save(update_fields=['parsed_rows'])
        self.submitted[0]['approved'] = False
        before = self.farmer.workflow_revision
        batch, result = self.commit()
        self.assertTrue(result['success'])
        self.assertEqual(batch.status, 'committed')
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.workflow_revision, before)

    def test_string_false_does_not_select_a_row(self):
        self.submitted[0]['approved'] = 'false'
        with self.assertRaises(ValueError):
            self.commit()
