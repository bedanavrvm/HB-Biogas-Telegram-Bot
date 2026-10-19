"""Synthetic regressions for Portal lead responses and document chronology."""
from datetime import date, datetime, timezone as datetime_timezone
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase, TestCase

from core.api import portal_views
from core.models import GroupSheetConfiguration, JawabuCustomer, JawabuFarmerMaster, MediaAttachment
from core.services.jawabu_pipeline import (
    JawabuWorkflowState, create_portal_visit_lead, discard_uncompleted_portal_visit_lead,
)
from core.services.requisition import ordered_document_farmers
from core.services.telegram_identity import user_access


class DocumentChronologyTests(SimpleTestCase):
    def farmer(self, reference, **values):
        return SimpleNamespace(**{
            'id': str(reference), 'case_reference_number': reference,
            'created_at': datetime(2026, 10, 19, tzinfo=datetime_timezone.utc),
            'county': 'Kiambu', 'hb_sales_person': '', 'hbg_visit_date': None, 'sign_date': '',
            **values,
        })

    def test_original_intake_date_wins_over_creation_name_and_selection(self):
        newer = self.farmer(1, hbg_visit_date=date(2026, 10, 2), customer_name='A')
        older = self.farmer(2, hbg_visit_date=date(2026, 9, 1), customer_name='Z')
        selection = [newer, older]
        self.assertEqual(ordered_document_farmers(selection), [older, newer])
        self.assertEqual(selection, [newer, older])

    def test_typed_visit_date_precedes_legacy_sign_date(self):
        farmer = self.farmer(1, hbg_visit_date=date(2026, 10, 2), sign_date='01-Jan-2020')
        other = self.farmer(2, sign_date="'01-October-2026")
        self.assertEqual(ordered_document_farmers([farmer, other]), [other, farmer])

    def test_office_lead_fallback_uses_nairobi_creation_date(self):
        office = self.farmer(1, created_at=datetime(2026, 9, 30, 22, tzinfo=datetime_timezone.utc))
        earlier = self.farmer(2, hbg_visit_date=date(2026, 9, 30))
        self.assertEqual(ordered_document_farmers([office, earlier]), [earlier, office])

    def test_reference_and_uuid_break_exact_date_and_creation_ties(self):
        first, second = self.farmer(1), self.farmer(2)
        self.assertEqual(ordered_document_farmers([second, first]), [first, second])
        second.case_reference_number = 1
        self.assertEqual(ordered_document_farmers([second, first]), [first, second])

    def test_missing_dates_sort_last(self):
        missing = self.farmer(1, created_at=None)
        dated = self.farmer(2)
        self.assertEqual(ordered_document_farmers([missing, dated]), [dated, missing])

    def test_payment_partner_uses_canonical_county_and_salesperson_routing(self):
        hb_old = self.farmer(1, hbg_visit_date=date(2026, 1, 1))
        hb_new = self.farmer(2, hbg_visit_date=date(2026, 2, 1))
        eco_old = self.farmer(3, county='Nakuru', hbg_visit_date=date(2026, 3, 1))
        eco_new = self.farmer(4, hb_sales_person='Eco-conserve Jawabu', hbg_visit_date=date(2026, 4, 1))
        selection = [hb_new, eco_new, hb_old, eco_old]
        self.assertEqual(ordered_document_farmers(selection, eco_first=True), [eco_old, eco_new, hb_old, hb_new])
        self.assertEqual(ordered_document_farmers(selection), [hb_old, hb_new, eco_old, eco_new])


class RetainedDocumentTests(SimpleTestCase):
    def test_saved_payment_preview_keeps_original_rows_without_requerying_cases(self):
        # Historical HB-first rows deliberately differ from the new policy.
        rows = [{'name': 'Historical HB', 'hb_invoice_amount': '20'},
                {'name': 'Historical Eco', 'hb_invoice_amount': '10'}]
        batch = SimpleNamespace(
            current_document_id='synthetic-document', payment_number=7,
            current_document=SimpleNamespace(validation_summary={'preview_rows': rows}),
            case_memberships=MagicMock(),
        )
        batch.case_memberships.filter.return_value.select_related.return_value.order_by.return_value = []
        queryset = MagicMock()
        queryset.filter.return_value.select_related.return_value.first.return_value = batch
        request = RequestFactory().get('/api/portal/payments/batches/synthetic/preview/')
        with patch.object(portal_views, '_portal_capability_error', return_value=None), \
             patch.object(portal_views, '_portal_payment_batch_queryset', return_value=queryset), \
             patch.object(portal_views, '_portal_payment_batch_scope_error', return_value=None), \
             patch('core.services.payment_documents.payment_readiness') as readiness:
            response = portal_views.portal_payment_batch_preview(request, 'synthetic')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['preview']['rows'], rows)
        readiness.assert_not_called()


class PortalOfficeLeadResponseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(
            username='synthetic-portal-hardening', is_active=True, is_staff=True, is_superuser=True,
        )
        cls.group = GroupSheetConfiguration.objects.create(
            group_id='synthetic-portal-hardening', sheet_id='synthetic', enabled=True,
            workflow={'type': 'jawabu_homebiogas'},
        )

    def submit(self, outcome, *, key='synthetic-lead-retry', **values):
        request = RequestFactory().post('/api/portal/jbl-queue/create-and-complete/', {
            'customer_name': 'Synthetic Office Applicant', 'national_id': '99999991',
            'primary_phone': '0700000001', 'county': 'Kiambu', 'sub_county': 'Limuru',
            'visit_date': '2026-10-19', 'visit_status': 'Rescheduled',
            'client_request_id': key, **values,
        })
        request.portal_user = self.actor
        request.portal_access = user_access(self.actor, 'jawabu_portal')
        request.portal_request_id = key
        with patch.object(portal_views, '_portal_payment_group', return_value=self.group), \
             patch('core.services.location_catalog.validate_location_selection', return_value=(None, None, None)), \
             patch('core.services.jawabu_pipeline.complete_jbl_visit') as complete:
            if isinstance(outcome, Exception):
                complete.side_effect = outcome
            elif callable(outcome):
                complete.side_effect = outcome
            else:
                complete.return_value = outcome
            response = portal_views.portal_create_and_complete_jbl_lead(request)
        return response, complete

    def test_success_returns_json_and_replay_reuses_one_identity_and_case(self):
        success = (True, '', {'visit_logged': True})
        first, complete = self.submit(success)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertTrue(json.loads(first.content)['created_lead'])
        complete.assert_called_once()
        second, _ = self.submit((True, '', {'already_completed': True, 'evidence_saved': True}))
        self.assertEqual(second.status_code, 200, second.content)
        self.assertFalse(json.loads(second.content)['created_lead'])
        self.assertTrue(json.loads(second.content)['already_completed'])
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)
        self.assertEqual(JawabuCustomer.objects.count(), 1)

    def test_local_validation_failure_returns_fields_and_removes_untouched_pair(self):
        response, _ = self.submit((False, 'Visit date is invalid.', {'evidence_saved': False}))
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(json.loads(response.content)['code'], 'jbl_visit_validation_failed')
        self.assertIn('visit_date', json.loads(response.content)['field_errors'])
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        self.assertFalse(JawabuCustomer.objects.exists())

    def test_expected_exception_is_a_response_not_an_orphaned_intake(self):
        response, _ = self.submit(ValueError('Visit date is invalid.'))
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        self.assertFalse(JawabuCustomer.objects.exists())

    def test_saved_evidence_survives_partial_failure_and_retry(self):
        def partial(farmer, **kwargs):
            MediaAttachment.objects.create(jawabu_farmer=farmer, group_id=self.group.group_id,
                                           original_filename='synthetic.jpg', file_type='JBL_VISIT_PHOTO')
            return False, 'Evidence retained; retry the visit.', {'evidence_saved': True}

        failed, _ = self.submit(partial)
        self.assertEqual(failed.status_code, 409, failed.content)
        farmer = JawabuFarmerMaster.objects.get()
        retried, _ = self.submit((True, '', {'visit_logged': True, 'evidence_saved': True}))
        self.assertEqual(retried.status_code, 200, retried.content)
        self.assertEqual(json.loads(retried.content)['farmer']['id'], str(farmer.pk))
        self.assertEqual(MediaAttachment.objects.filter(jawabu_farmer=farmer).count(), 1)

    def test_existing_retry_case_is_not_deleted_on_later_validation_failure(self):
        self.submit((True, '', {'visit_logged': True}))
        response, _ = self.submit((False, 'Visit date is invalid.', {'evidence_saved': False}))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)

    def test_cleanup_never_deletes_progressed_case_or_evidence(self):
        farmer = create_portal_visit_lead(
            national_id='99999992', primary_phone='254700000002', external_id='synthetic-cleanup',
            workflow_state=JawabuWorkflowState.JBL_VISIT, workflow_revision=2,
        )
        self.assertFalse(discard_uncompleted_portal_visit_lead(farmer.pk, external_id='synthetic-cleanup'))
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())

    def test_capability_denial_never_creates_a_lead(self):
        with patch.object(portal_views, '_portal_capability_error', return_value=JsonResponse({'ok': False}, status=403)):
            response, complete = self.submit((True, '', {}))
        self.assertEqual(response.status_code, 403)
        complete.assert_not_called()
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_missing_request_key_fails_before_processing(self):
        response, complete = self.submit((True, '', {}), key='')
        self.assertEqual(response.status_code, 428, response.content)
        complete.assert_not_called()
        self.assertFalse(JawabuFarmerMaster.objects.exists())
