from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import JawabuFarmerMaster
from core.services.invoice_parser import _match_invoice_to_farmer
from core.services.portal_case_corrections import correct_case_fields
from core.services.workflow_timeline import jawabu_case_timeline


class PortalCaseCorrectionTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='operations-corrector')
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Incorrect Name',
            national_id='12345678',
            primary_phone='0712345678',
            workflow_revision=2,
        )

    @patch('core.services.portal_publication.reserve_farmer_publication', return_value=[])
    def test_correction_is_revision_checked_audited_and_visible_in_timeline(self, _reserve):
        updated = correct_case_fields(
            self.farmer,
            values={'customer_name': 'Correct Name', 'hbg_visit_date': '16-09-2026'},
            expected_revision=2,
            reason='Corrected against the signed customer record.',
            request_id='case-correction-1',
            actor=self.actor,
        )

        self.assertEqual(updated.customer_name, 'Correct Name')
        self.assertEqual(updated.hbg_visit_date.strftime('%d-%m-%Y'), '16-09-2026')
        self.assertEqual(updated.workflow_revision, 3)
        event = updated.pipeline_events.get(action='case_fields_corrected')
        self.assertEqual(event.source, 'admin_correction')
        self.assertEqual(event.old_values['customer_name'], 'Incorrect Name')
        self.assertEqual(event.new_values['customer_name'], 'Correct Name')
        self.assertIn('case_fields_corrected', [item['action'] for item in jawabu_case_timeline(updated)['entries']])
        self.assertEqual(updated.field_provenance.filter(source='admin_correction').count(), 2)

    @patch('core.services.portal_publication.reserve_farmer_publication', return_value=[])
    def test_correction_rejects_a_stale_revision(self, _reserve):
        with self.assertRaisesRegex(ValueError, 'changed after you opened'):
            correct_case_fields(
                self.farmer,
                values={'customer_name': 'Correct Name'},
                expected_revision=1,
                reason='Correction evidence.',
                request_id='case-correction-stale',
                actor=self.actor,
            )

    @patch('core.services.portal_publication.reserve_farmer_publication', return_value=[])
    def test_request_key_replays_only_the_same_correction(self, _reserve):
        updated = correct_case_fields(
            self.farmer,
            values={'customer_name': 'Correct Name'},
            expected_revision=2,
            reason='Correction evidence.',
            request_id='case-correction-replay',
            actor=self.actor,
        )
        replay = correct_case_fields(
            updated,
            values={'customer_name': 'Correct Name'},
            expected_revision=2,
            reason='Correction evidence.',
            request_id='case-correction-replay',
            actor=self.actor,
        )
        self.assertEqual(replay.pk, updated.pk)
        self.assertEqual(replay.workflow_revision, 3)
        with self.assertRaisesRegex(ValueError, 'different case correction'):
            correct_case_fields(
                updated,
                values={'customer_name': 'Another Name'},
                expected_revision=3,
                reason='Different correction.',
                request_id='case-correction-replay',
                actor=self.actor,
            )


class InvoiceLeadMatchingTests(TestCase):
    def test_order_upload_matches_retained_farmup_lead_identity(self):
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Current Applicant',
            national_id='99887766',
            primary_phone='0711000000',
            lead_name='Original Lead',
            lead_national_id='12345678',
            lead_primary_phone='0722000000',
        )

        matched, reason = _match_invoice_to_farmer({
            'customer_name': 'Original Lead',
            'customer_id': '12345678',
            'customer_phone': '0722000000',
        }, [farmer])

        self.assertEqual(matched, farmer)
        self.assertEqual(reason, '')
