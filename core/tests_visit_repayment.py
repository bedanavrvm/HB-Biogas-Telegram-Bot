"""Synthetic repayment capture at the visit and review-stage compatibility."""
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import ComplianceAuditChainState, JawabuFarmerMaster
from core.tests_jbl_outcome_requirements import unwrap
from core.tests_jbl_visit_documents import pdf_fixture


class VisitRepaymentTests(TestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_user(username='synthetic-repayment-review', is_superuser=True)
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='SYNTHETIC REPAYMENT CLIENT', national_id='12345678',
            workflow_state='jbl_visit', deposit_paid_hbg=5000,
            hbg_visit_date=timezone.localdate() - timedelta(days=2),
            county='NAKURU', sub_county='Kieni', village='Synthetic landmark',
        )
        for target, value in [
            ('core.api.portal_views._portal_capability_error', None),
            ('core.api.portal_views._portal_approval_authority_error', None),
            ('core.api.portal_views._portal_sender_from_request', 'Synthetic officer'),
            ('core.services.portal_publication.reserve_farmer_publication', []),
            ('core.services.location_catalog.validate_location_selection', (None, None, None)),
            ('core.services.jawabu_approvals.visit_evidence_status', {'CLIENT_ID': 1, 'LAF': 1, 'JBL_VISIT_PHOTO': 1}),
        ]:
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def visit(self, **values):
        from core.api.portal_views import portal_complete_jbl_visit
        request = RequestFactory().post('/synthetic-visit/', {
            'client_request_id': 'synthetic-repayment-visit',
            'workflow_revision': self.farmer.workflow_revision,
            'visit_status': 'Visited, Awaiting Credit Analysis', 'visit_occurred': 'true',
            'visit_date': timezone.localdate().isoformat(), 'county': 'NAKURU', 'sub_county': 'Kieni',
            'village': 'Synthetic landmark', 'location_unavailable_reason': 'Synthetic offline location',
            **values,
        })
        request.portal_user = self.actor
        return unwrap(portal_complete_jbl_visit)(request, str(self.farmer.pk))

    def final(self, **values):
        from core.api.portal_views import portal_set_final_decision
        request = RequestFactory().post('/synthetic-final/', json.dumps({
            'client_request_id': 'synthetic-final-review', 'workflow_revision': self.farmer.workflow_revision,
            'final_decision': 'Approved', **values,
        }), content_type='application/json')
        request.portal_user = self.actor
        return unwrap(portal_set_final_decision)(request, str(self.farmer.pk))

    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads')
    def test_forwarding_requires_terms_before_any_evidence_upload(self, upload):
        response = self.visit(laf_files=SimpleUploadedFile('complete.pdf', pdf_fixture(1)))
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('repayment', json.loads(response.content)['error'].lower())
        upload.assert_not_called()
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.workflow_state, 'jbl_visit')
        self.assertFalse(self.farmer.pipeline_events.exists())

    def test_visit_saves_terms_in_same_revision_and_audits_them(self):
        response = self.visit(repayment_date='15', repayment_tenor='12')
        self.assertEqual(response.status_code, 200, response.content)
        self.farmer.refresh_from_db()
        self.assertEqual((self.farmer.repayment_day, self.farmer.repayment_tenor_months), (15, 12))
        self.assertEqual((self.farmer.repayment_date, self.farmer.repayment_tenor), ('15', '12'))
        self.assertEqual(self.farmer.workflow_state, 'credit')
        event = self.farmer.pipeline_events.get(action='jbl_visit_completed')
        self.assertEqual(event.new_values['repayment_day'], 15)
        self.assertEqual(event.new_values['repayment_tenor_months'], 12)
        self.assertEqual(event.revision_after, self.farmer.workflow_revision)

    def test_bounds_and_fractional_terms_are_rejected(self):
        for day, months in [('', '12'), ('15', ''), ('0', '12'), ('32', '12'), ('15', '0'), ('15', '121'), ('15.5', '12'), ('15', '6.5')]:
            with self.subTest(day=day, months=months):
                response = self.visit(repayment_date=day, repayment_tenor=months)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(self.farmer.pipeline_events.exists())

    def test_negative_outcome_does_not_clear_existing_terms(self):
        self.farmer.repayment_date, self.farmer.repayment_day = '10TH', 10
        self.farmer.repayment_tenor, self.farmer.repayment_tenor_months = '6', 6
        self.farmer.save()
        response = self.visit(visit_status='Rejected by JBL', reason_code='r01', visit_occurred='false',
                              repayment_date='', repayment_tenor='')
        self.assertEqual(response.status_code, 200, response.content)
        self.farmer.refresh_from_db()
        self.assertEqual((self.farmer.repayment_day, self.farmer.repayment_tenor_months), (10, 6))

    def test_valid_legacy_terms_are_reused_without_reentry(self):
        self.farmer.repayment_date, self.farmer.repayment_tenor = '10TH', '12 MONTHS'
        self.farmer.save()
        response = self.visit()
        self.assertEqual(response.status_code, 200, response.content)
        self.farmer.refresh_from_db()
        self.assertEqual((self.farmer.repayment_day, self.farmer.repayment_tenor_months), (10, 12))

    def test_replay_cannot_change_terms_or_create_another_visit(self):
        self.assertEqual(self.visit(repayment_date='15', repayment_tenor='12').status_code, 200)
        response = self.visit(repayment_date='20', repayment_tenor='24')
        self.assertEqual(response.status_code, 200, response.content)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.repayment_day, 15)
        self.assertEqual(self.farmer.pipeline_events.filter(action='jbl_visit_completed').count(), 1)

    def ready_for_final(self):
        self.farmer.workflow_state = 'final_review'
        self.farmer.jbl_visit_date = timezone.localdate()
        self.farmer.credit_decision, self.farmer.imab_created, self.farmer.customer_no = 'Approved', 'Yes', '42'
        self.farmer.repayment_date, self.farmer.repayment_day = '15', 15
        self.farmer.repayment_tenor, self.farmer.repayment_tenor_months = '12', 12
        self.farmer.save()

    def test_final_decision_without_correction_keeps_visit_terms(self):
        self.ready_for_final()
        response = self.final()
        self.assertEqual(response.status_code, 200, response.content)
        self.farmer.refresh_from_db()
        self.assertEqual((self.farmer.repayment_day, self.farmer.repayment_tenor_months), (15, 12))

    def test_explicit_final_correction_records_before_and_after(self):
        self.ready_for_final()
        response = self.final(repayment_date='20', repayment_tenor='18')
        self.assertEqual(response.status_code, 200, response.content)
        event = self.farmer.pipeline_events.get(action='final_decision_recorded')
        self.assertEqual(event.old_values['repayment_day'], 15)
        self.assertEqual(event.new_values['repayment_day'], 20)
        self.assertEqual(event.new_values['repayment_tenor_months'], 18)

    def test_draft_contract_includes_visit_terms_and_final_correction_mode(self):
        from core.api.portal_views import _PORTAL_JBL_VISIT_DRAFT_FIELD_LIMITS, _PORTAL_CASE_DRAFT_CONFIG
        self.assertIn('jbl-repayment-day', _PORTAL_JBL_VISIT_DRAFT_FIELD_LIMITS)
        self.assertIn('jbl-repayment-tenor', _PORTAL_JBL_VISIT_DRAFT_FIELD_LIMITS)
        self.assertIn('final-edit-repayment', _PORTAL_CASE_DRAFT_CONFIG['final_review']['fields'])

    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads')
    def test_stale_visit_cannot_store_terms_or_evidence(self, upload):
        response = self.visit(workflow_revision=999, repayment_date='15', repayment_tenor='12')
        self.assertEqual(response.status_code, 409, response.content)
        self.farmer.refresh_from_db()
        self.assertIsNone(self.farmer.repayment_day)
        upload.assert_not_called()

    def test_term_projection_still_populates_the_existing_sheet_columns(self):
        from core.services.jawabu_pipeline import master_projection_fields
        self.assertEqual(self.visit(repayment_date='15', repayment_tenor='12').status_code, 200)
        self.farmer.refresh_from_db()
        projected = master_projection_fields(self.farmer)
        self.assertEqual(projected['repayment_date'][1], '15')
        self.assertEqual(projected['repayment_tenor'][1], '12')

    def test_visit_draft_round_trip_keeps_repayment_values(self):
        from core.api.portal_views import portal_jbl_visit_draft
        values = {'jbl-repayment-day': '17', 'jbl-repayment-tenor': '18'}
        request = RequestFactory().post('/synthetic-draft/', json.dumps({'payload': {'values': values}}), content_type='application/json')
        request.portal_user = self.actor
        response = unwrap(portal_jbl_visit_draft)(request, str(self.farmer.pk))
        self.assertEqual(response.status_code, 200, response.content)
        request = RequestFactory().get('/synthetic-draft/')
        request.portal_user = self.actor
        response = unwrap(portal_jbl_visit_draft)(request, str(self.farmer.pk))
        saved = json.loads(response.content)['draft']['payload']['values']
        self.assertEqual({key: saved[key] for key in values}, values)

    def test_failed_visit_audit_rolls_back_the_terms_and_state(self):
        from core.services.jawabu_pipeline import log_jbl_visit
        with patch('core.services.jawabu_case360.record_pipeline_event', side_effect=RuntimeError('Synthetic audit failure')):
            with self.assertRaisesRegex(RuntimeError, 'Synthetic audit failure'):
                log_jbl_visit(self.farmer, visit_date=timezone.localdate(), officer='Synthetic',
                    visit_status='Visited, Awaiting Credit Analysis', repayment_date='15', repayment_tenor='12',
                    location_unavailable_reason='Synthetic unavailable', expected_revision=self.farmer.workflow_revision)
        self.farmer.refresh_from_db()
        self.assertIsNone(self.farmer.repayment_day)
        self.assertIsNone(self.farmer.repayment_tenor_months)
        self.assertEqual(self.farmer.workflow_state, 'jbl_visit')

    @patch('core.services.jawabu_pipeline.complete_jbl_visit', return_value=(True, '', {'visit_logged': True}))
    @patch('core.api.portal_views._portal_payment_group')
    def test_new_office_visit_forwards_the_same_repayment_contract(self, payment_group, completion):
        from core.api.portal_views import portal_create_and_complete_jbl_lead
        from core.models import GroupSheetConfiguration
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-repayment-office', sheet_id='synthetic')
        payment_group.return_value = group
        request = RequestFactory().post('/synthetic-office/', {
            'client_request_id': 'synthetic-office-terms', 'customer_name': 'SYNTHETIC OFFICE CLIENT',
            'national_id': '87654321', 'primary_phone': '0712345678', 'deposit_paid_hbg': '5000',
            'county': 'NAKURU', 'sub_county': 'Kieni', 'village': 'Synthetic landmark',
            'visit_date': timezone.localdate().isoformat(), 'visit_status': 'Visited, Awaiting Credit Analysis',
            'visit_occurred': 'true', 'repayment_date': '17', 'repayment_tenor': '18',
        })
        request.portal_user = self.actor
        response = unwrap(portal_create_and_complete_jbl_lead)(request)
        self.assertIn(response.status_code, (200, 201), response.content)
        self.assertEqual(completion.call_args.kwargs['repayment_date'], '17')
        self.assertEqual(completion.call_args.kwargs['repayment_tenor'], '18')

    def test_unauthorized_final_correction_cannot_change_terms(self):
        from django.http import JsonResponse
        self.ready_for_final()
        with patch('core.api.portal_views._portal_approval_authority_error', return_value=JsonResponse({'ok': False}, status=403)):
            response = self.final(repayment_date='20', repayment_tenor='18')
        self.assertEqual(response.status_code, 403)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.repayment_day, 15)
