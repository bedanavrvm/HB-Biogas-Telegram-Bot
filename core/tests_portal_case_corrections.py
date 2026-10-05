from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from core.models import JawabuApprovalRecord, JawabuFarmerMaster, OperationalLocation
from core.services.invoice_parser import _match_invoice_to_farmer
from core.services.portal_case_corrections import correction_payload, correct_case_fields
from core.services.workflow_timeline import _group_same_moment_activity, jawabu_case_timeline


class CaseTimelineProjectionTests(SimpleTestCase):
    def test_same_moment_visit_media_and_farmup_fields_are_nested(self):
        occurred_at = '2026-09-22T07:17:00+03:00'
        entries = [
            {'source_event_id': 'visit', 'action': 'jbl_visit_completed', 'title': 'JBL Visit Completed', 'kind': 'event', 'stage': 'jbl_visit', 'source': 'portal', 'occurred_at': occurred_at, 'children': []},
            {'source_event_id': 'media-receipt', 'action': 'jbl_media_uploaded', 'title': 'JBL Media Uploaded', 'kind': 'event', 'stage': 'jbl_visit', 'source': 'portal', 'occurred_at': occurred_at, 'children': []},
            {'source_event_id': 'laf', 'action': 'visit_media_uploaded', 'title': 'LAF', 'kind': 'document', 'stage': 'jbl_visit', 'source': 'telegram', 'occurred_at': occurred_at},
            {'source_event_id': 'import', 'action': 'application_imported', 'title': 'Application Imported', 'kind': 'event', 'stage': 'intake', 'source': 'farmup', 'occurred_at': occurred_at, 'children': []},
            {'source_event_id': 'field-name', 'action': 'customer_field_synchronized', 'title': 'Customer Field Synchronized', 'kind': 'provenance', 'stage': 'identity', 'source': 'farmup', 'occurred_at': occurred_at},
            {'source_event_id': 'field-id', 'action': 'customer_field_synchronized', 'title': 'Customer Field Synchronized', 'kind': 'provenance', 'stage': 'identity', 'source': 'farmup', 'occurred_at': occurred_at},
        ]

        grouped = _group_same_moment_activity(entries)
        self.assertEqual([entry['action'] for entry in grouped], ['jbl_visit_completed', 'application_imported'])
        self.assertEqual([child['source_event_id'] for child in grouped[0]['children']], ['laf'])
        self.assertEqual({child['source_event_id'] for child in grouped[1]['children']}, {'field-name', 'field-id'})
        self.assertEqual(grouped[1]['detail'], '2 fields updated from Farmup.')


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
        entry = next(item for item in jawabu_case_timeline(updated)['entries'] if item['action'] == 'case_fields_corrected')
        change = next(item for item in entry['changes'] if item['field'] == 'customer_name')
        self.assertEqual((change['old_value'], change['new_value']), ('Incorrect Name', 'Correct Name'))
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

    @patch('core.services.portal_publication.reserve_farmer_publication', return_value=[])
    def test_location_correction_preserves_stage_and_existing_approval(self, _reserve):
        county = OperationalLocation.objects.create(location_type='county', code='KE-TEST', name='Test County')
        constituency = OperationalLocation.objects.create(
            location_type='sub_county', code='KE-TEST-EAST', name='East Constituency', parent=county,
        )
        self.farmer.workflow_state = 'requisition'
        self.farmer.final_decision = 'Approved'
        self.farmer.save(update_fields=['workflow_state', 'final_decision'])
        approval = JawabuApprovalRecord.objects.create(
            farmer=self.farmer, gate=JawabuApprovalRecord.GATE_FINAL_REVIEW,
            decision=JawabuApprovalRecord.DECISION_APPROVED,
        )

        fields = {field['key'] for field in correction_payload(self.farmer)['fields']}
        self.assertTrue({'county', 'sub_county', 'village'} <= fields)
        self.assertNotIn('landmark', fields)
        values = {
            'customer_name': 'Correct Name', 'national_id': '87654321',
            'primary_phone': '0712000001', 'secondary_phone': '0712000002',
            'customer_no': '12345', 'lead_name': 'Original Lead',
            'lead_national_id': '1234567', 'lead_primary_phone': '0712000003',
            'hbg_visit_date': '16-09-2026', 'county': county.code,
            'sub_county': constituency.code, 'village': 'Market centre',
            'lead_source': 'JAWABU', 'hb_sales_person': 'Sales Officer',
            'deposit_paid_hbg': '1000',
        }
        self.assertEqual(set(values), fields)
        updated = correct_case_fields(
            self.farmer,
            values=values,
            expected_revision=2, reason='Corrected visit location against field notes.',
            request_id='case-correction-location', actor=self.actor,
        )
        approval.refresh_from_db()
        self.assertEqual(updated.county, county.name)
        self.assertEqual(updated.sub_county, constituency.name)
        self.assertEqual(updated.village, 'Market centre')
        self.assertEqual(updated.workflow_state, 'requisition')
        self.assertEqual(updated.final_decision, 'Approved')
        self.assertEqual(approval.status, JawabuApprovalRecord.STATUS_ACTIVE)


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
