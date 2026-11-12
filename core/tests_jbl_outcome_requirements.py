"""Visit outcomes must not invent visits or require unrelated documents."""
from datetime import timedelta
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import JawabuFarmerMaster
from core.tests_jbl_visit_documents import pdf_fixture


def unwrap(view):
    while hasattr(view, '__wrapped__'):
        view = view.__wrapped__
    return view


class JblOutcomeRequirementsTests(TestCase):
    def setUp(self):
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_user(username='synthetic-visit-officer')
        self.case = JawabuFarmerMaster.objects.create(
            customer_name='SYNTHETIC CLIENT', national_id='12345678',
            workflow_state='jbl_visit', hbg_visit_date=timezone.localdate() - timedelta(days=20),
            deposit_paid_hbg=0,
        )

    def submit(self, *, media_allowed=True, **values):
        from core.api.portal_views import portal_complete_jbl_visit
        body = {
            'visit_status': 'Rejected by JBL', 'reason_code': 'r01', 'visit_occurred': 'false',
            'visit_date': '', 'workflow_revision': self.case.workflow_revision, **values,
        }
        request = RequestFactory().post('/synthetic-visit/', body)
        request.portal_user = self.actor
        from django.http import JsonResponse
        def capability_error(request, capability, farmer=None):
            if not media_allowed and capability == 'portal.jbl_media.write':
                return JsonResponse({'ok': False, 'error': 'Media denied'}, status=403)
            return None
        with patch('core.api.portal_views._portal_capability_error', side_effect=capability_error), \
             patch('core.api.portal_views._portal_request_id',return_value='synthetic-outcome'), \
             patch('core.api.portal_views._portal_sender_from_request',return_value='Synthetic officer'), \
             patch('core.services.portal_publication.reserve_farmer_publication',return_value=[]):
            return unwrap(portal_complete_jbl_visit)(request, str(self.case.pk))

    def test_phone_rejection_requires_no_deposit_location_date_or_documents(self):
        response=self.submit()
        self.assertEqual(response.status_code,200,response.content)
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state,'rejected')
        self.assertIsNone(self.case.jbl_visit_date)
        self.assertFalse(self.case.jbl_officer)
        self.assertFalse(self.case.pipeline_events.filter(action='jbl_visit_completed').exists())

    def test_pending_deposit_is_last_before_pagination(self):
        from core.services.jawabu_pipeline import jbl_visit_queue
        ready=JawabuFarmerMaster.objects.create(customer_name='READY',workflow_state='jbl_visit',
            hbg_visit_date=timezone.localdate()-timedelta(days=2),deposit_paid_hbg=5000)
        self.assertEqual(list(jbl_visit_queue().values_list('pk',flat=True)),[ready.pk,self.case.pk])

    def test_combined_one_page_laf_and_two_page_id_are_accepted(self):
        from core.services.jawabu_pipeline import _validate_jbl_media_files
        for category,pages in [('LAF',1),('CLIENT_ID',2)]:
            with self.subTest(category=category):
                error=_validate_jbl_media_files([SimpleUploadedFile('complete.pdf',pdf_fixture(pages),content_type='application/pdf')],category)
                self.assertEqual(error,'')

    def test_actual_rejection_records_a_visit_but_needs_no_deposit_or_documents(self):
        response = self.submit(visit_occurred='true', visit_date=timezone.localdate().isoformat())
        self.assertEqual(response.status_code, 200, response.content)
        self.case.refresh_from_db()
        self.assertEqual(self.case.jbl_visit_date, timezone.localdate())
        self.assertTrue(self.case.pipeline_events.filter(action='jbl_visit_completed').exists())

    def test_phone_outcome_preserves_prior_physical_visit_facts(self):
        from core.services.jawabu_pipeline import last_physical_jbl_visit
        previous_date = timezone.localdate() - timedelta(days=4)
        self.case.jbl_visit_date = previous_date
        self.case.jbl_officer = 'Original officer'
        self.case.jbl_visit_status = 'Rescheduled'
        self.case.save()
        response = self.submit()
        self.assertEqual(response.status_code, 200, response.content)
        self.case.refresh_from_db()
        self.assertEqual(self.case.jbl_visit_date, previous_date)
        self.assertEqual(self.case.jbl_officer, 'Original officer')
        self.assertEqual(last_physical_jbl_visit(self.case)['status'], 'Rescheduled')
        self.assertEqual(self.case.jbl_visit_status, 'Rejected by JBL')

    def test_no_visit_cannot_forward_even_with_deposit(self):
        self.case.deposit_paid_hbg = 5000
        self.case.save()
        response = self.submit(visit_status='Visited, Awaiting Credit Analysis', reason_code='', county='Nakuru', sub_county='Nakuru Town East')
        self.assertEqual(response.status_code, 400)
        self.assertIn('physical visit', json.loads(response.content)['error'].lower())
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state, 'jbl_visit')
        self.assertFalse(self.case.pipeline_events.exists())

    def test_forward_still_requires_deposit(self):
        from core.services.jawabu_pipeline import complete_jbl_visit
        ok, error, _ = complete_jbl_visit(self.case, categorized_files={}, visit_date=timezone.localdate(),
            officer='Synthetic', visit_status='Visited, Awaiting Credit Analysis')
        self.assertFalse(ok)
        self.assertIn('deposit', error.lower())
        self.assertFalse(self.case.pipeline_events.exists())

    def test_incomplete_optional_capture_does_not_block_outcome(self):
        from core.tests_jbl_visit_documents import photo
        response = self.submit(laf_page_1=photo())
        self.assertEqual(response.status_code, 200, response.content)
        result = json.loads(response.content)
        self.assertTrue(result['outcome_saved'])
        self.assertTrue(result['evidence_pending'])
        self.assertEqual(result['errors'][0]['category'], 'LAF')
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state, 'rejected')

    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads')
    def test_optional_transport_failure_keeps_outcome_and_retry_does_not_repeat_it(self, upload):
        upload.return_value = (False, 'Synthetic Drive outage', {'stored_count': 0})
        response = self.submit(laf_files=SimpleUploadedFile('complete.pdf', pdf_fixture(1)))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(json.loads(response.content)['evidence_pending'])
        self.case.refresh_from_db()
        revision = self.case.workflow_revision
        upload.return_value = (True, '', {'stored_count': 1, 'errors': []})
        response = self.submit(laf_files=SimpleUploadedFile('complete.pdf', pdf_fixture(1)))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(json.loads(response.content)['evidence_pending'])
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_revision, revision)
        self.assertEqual(self.case.pipeline_events.filter(action='jbl_outcome_recorded').count(), 1)

    def test_replay_and_completion_status_do_not_claim_a_physical_visit(self):
        from core.api.portal_views import portal_jbl_visit_completion_status
        self.assertEqual(self.submit().status_code, 200)
        self.assertFalse(json.loads(self.submit().content)['visit_logged'])
        request = RequestFactory().get('/synthetic-status/', {'request_id': 'synthetic-outcome'})
        with patch('core.api.portal_views._portal_capability_error', return_value=None):
            result = json.loads(unwrap(portal_jbl_visit_completion_status)(request, str(self.case.pk)).content)
        self.assertTrue(result['completed'])
        self.assertFalse(result['visit_logged'])
        self.assertEqual(self.case.pipeline_events.count(), 1)

    def test_stale_outcome_cannot_upload_or_change_state(self):
        from core.services.jawabu_pipeline import complete_jbl_visit
        from core.services.workflow_transitions import WorkflowRevisionConflict
        with patch('core.services.jawabu_pipeline.append_jbl_media_uploads') as upload:
            with self.assertRaises(WorkflowRevisionConflict):
                complete_jbl_visit(self.case, categorized_files={}, visit_date=None, visit_occurred=False,
                    officer='Synthetic', visit_status='Rescheduled', expected_revision=999)
            upload.assert_not_called()
        self.case.refresh_from_db()
        self.assertFalse(self.case.pipeline_events.exists())

    def test_newest_order_still_keeps_deposit_holds_last(self):
        from core.api.portal_views import _apply_portal_ordering
        from core.services.jawabu_pipeline import jbl_visit_queue
        ready = JawabuFarmerMaster.objects.create(customer_name='READY', workflow_state='jbl_visit',
            hbg_visit_date=timezone.localdate(), deposit_paid_hbg=5000)
        rows = _apply_portal_ordering(jbl_visit_queue(), params={'ordering': 'newest'})
        self.assertEqual(list(rows[:1]), [ready])

    def test_rescheduled_physical_visit_does_not_bypass_or_lock_deposit(self):
        from hb_operations.deposits import deposit_editable, visit_deposit_error
        response = self.submit(visit_status='Rescheduled', reason_code='', visit_occurred='true',
                               visit_date=timezone.localdate().isoformat(), next_visit_date=timezone.localdate().isoformat())
        self.assertEqual(response.status_code, 200, response.content)
        self.case.refresh_from_db()
        self.assertTrue(deposit_editable(self.case))
        self.assertIn('deposit', visit_deposit_error(self.case).lower())

    @patch('core.services.jbl_visit_documents.render_document', return_value=pdf_fixture(1))
    def test_combined_image_uses_one_legible_document_page(self, renderer):
        from core.tests_jbl_visit_documents import photo
        from core.services.jbl_visit_documents import prepare_visit_documents
        files = prepare_visit_documents({'LAF': [photo('combined.jpg')]})
        self.assertEqual(len(renderer.call_args.args[1]), 1)
        self.assertEqual(files['LAF'][0].content_type, 'application/pdf')

    def test_three_page_and_encrypted_pdfs_still_fail(self):
        import io
        from pypdf import PdfWriter
        from core.services.jawabu_pipeline import _validate_jbl_media_files
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_metadata({'/Subject': 'synthetic ' * 500})
        writer.encrypt('synthetic-password')
        output = io.BytesIO()
        writer.write(output)
        for data in (pdf_fixture(3), output.getvalue()):
            self.assertTrue(_validate_jbl_media_files([SimpleUploadedFile('bad.pdf', data)], 'LAF'))

    def test_outcome_without_visit_gets_no_performance_points(self):
        from core.services.portal_recognition import _facts_for_cases
        self.assertEqual(self.submit().status_code, 200)
        self.assertEqual(_facts_for_cases(JawabuFarmerMaster.objects.filter(pk=self.case.pk),
            start=timezone.localdate() - timedelta(days=1), end=timezone.localdate()), [])

    def test_outcome_still_requires_its_own_portal_authority(self):
        from core.api.portal_views import portal_complete_jbl_visit
        from core.services.telegram_identity import user_access
        request = RequestFactory().post('/synthetic-visit/', {'visit_status': 'Rescheduled', 'visit_occurred': 'false'})
        request.portal_user = self.actor
        request.portal_access = user_access(self.actor, 'jawabu_portal')
        response = unwrap(portal_complete_jbl_visit)(request, str(self.case.pk))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.case.pipeline_events.exists())

    def test_other_group_visit_grant_cannot_record_outcome(self):
        from core.api.portal_views import portal_complete_jbl_visit
        from core.models import AccessGrant, GroupSheetConfiguration
        from core.services.telegram_identity import user_access
        current = GroupSheetConfiguration.objects.create(group_id='synthetic-outcome-current', sheet_id='synthetic')
        other = GroupSheetConfiguration.objects.create(group_id='synthetic-outcome-other', sheet_id='synthetic')
        self.case.group_configuration = current
        self.case.save()
        AccessGrant.objects.create(user=self.actor, workflow='jawabu_portal', role='JBL_OFFICER', group_configuration=other)
        request = RequestFactory().post('/synthetic-visit/', {'visit_status': 'Rescheduled', 'visit_occurred': 'false'})
        request.portal_user = self.actor
        request.portal_access = user_access(self.actor, 'jawabu_portal')
        response = unwrap(portal_complete_jbl_visit)(request, str(self.case.pk))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.case.pipeline_events.exists())

    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads', side_effect=RuntimeError('synthetic transport failure'))
    def test_unexpected_optional_upload_error_cannot_rollback_outcome(self, upload):
        response = self.submit(laf_files=SimpleUploadedFile('complete.pdf', pdf_fixture(1)))
        self.assertEqual(response.status_code, 200, response.content)
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state, 'rejected')
        self.assertTrue(json.loads(response.content)['evidence_pending'])
        upload.assert_called_once()

    def test_visit_storage_name_is_searchable_and_path_safe(self):
        from core.services.order_approval import build_storage_filename, TelegramMediaItem
        from core.services.jawabu_case_reference import display_case_reference
        self.case.customer_name = 'Synthetic / Client: Example'
        filename = build_storage_filename(
            TelegramMediaItem('', 'LAF', 'combined.PDF', 'application/pdf', 5000),
            self.case.national_id, 2, timezone.now(), jawabu_farmer=self.case,
        )
        self.assertIn('Synthetic Client Example', filename)
        self.assertIn('ID-' + self.case.national_id, filename)
        self.assertIn(display_case_reference(self.case), filename)
        self.assertIn('LAF', filename)
        self.assertTrue(filename.endswith('02.pdf'))
        self.assertNotIn('/', filename)
        self.assertNotIn(':', filename)

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-only')
    @patch('core.services.order_approval.GoogleDriveMediaStorage.upload', return_value=('synthetic-drive-file', 'https://example.test/synthetic-file'))
    @patch('core.services.portal_publication.reserve_farmer_publication', return_value=[])
    def test_real_upload_boundary_receives_searchable_name_and_retry_reuses_hash(self, publication, upload):
        from core.models import GroupSheetConfiguration
        from core.services.jawabu_pipeline import append_jbl_media_links
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-naming', sheet_id='synthetic')
        with patch('core.services.jawabu_pipeline._jawabu_group_config', return_value=group):
            for _ in range(2):
                ok, error, _ = append_jbl_media_links(self.case,
                    uploaded_files=[SimpleUploadedFile('original.pdf', pdf_fixture(1), content_type='application/pdf')],
                    media_category='LAF', expected_revision=self.case.workflow_revision, request_id='synthetic-named-media')
                self.assertTrue(ok, error)
        upload.assert_called_once()
        self.assertIn(self.case.customer_name, upload.call_args.kwargs['filename'])
        self.assertIn('ID-' + self.case.national_id, upload.call_args.kwargs['filename'])
        self.assertEqual(self.case.media_attachments.get().original_filename, 'original.pdf')

    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads')
    def test_missing_media_permission_does_not_block_negative_outcome_or_upload_files(self, upload):
        response = self.submit(media_allowed=False, laf_files=SimpleUploadedFile('complete.pdf', pdf_fixture(1)))
        self.assertEqual(response.status_code, 200, response.content)
        result = json.loads(response.content)
        self.assertTrue(result['evidence_pending'])
        self.assertFalse(result['evidence_saved'])
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state, 'rejected')
        upload.assert_not_called()

    def test_forwarding_still_requires_media_permission(self):
        response = self.submit(media_allowed=False, visit_status='Visited, Awaiting Credit Analysis', reason_code='',
            visit_occurred='true', visit_date=timezone.localdate().isoformat())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.case.pipeline_events.exists())

    def test_rescheduling_requires_today_or_future_date_before_upload(self):
        with patch('core.services.jawabu_pipeline.append_jbl_media_uploads') as upload:
            for planned in ('', 'not-a-date', (timezone.localdate() - timedelta(days=1)).isoformat()):
                with self.subTest(planned=planned):
                    response = self.submit(visit_status='Rescheduled', reason_code='', next_visit_date=planned)
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertIn('next_visit_date', json.loads(response.content)['field_errors'])
            upload.assert_not_called()
        self.assertFalse(self.case.pipeline_events.exists())

    def test_reschedule_date_is_saved_audited_and_in_queue_without_inventing_a_visit(self):
        from core.services.jawabu_pipeline import farmer_to_card, jbl_visit_queue
        planned = timezone.localdate() + timedelta(days=3)
        response = self.submit(visit_status='Rescheduled', reason_code='', next_visit_date=planned.isoformat())
        self.assertEqual(response.status_code, 200, response.content)
        self.case.refresh_from_db()
        self.assertEqual(self.case.jbl_next_visit_date, planned)
        self.assertIsNone(self.case.jbl_visit_date)
        self.assertFalse(self.case.jbl_officer)
        self.assertEqual(self.case.workflow_state, 'jbl_visit')
        self.assertIsNone(self.case.deferred_until)
        self.assertIn(self.case, jbl_visit_queue())
        self.assertEqual(farmer_to_card(self.case, include_detail_metadata=False)['next_visit_date'], planned.isoformat())
        event = self.case.pipeline_events.get(action='jbl_outcome_recorded')
        self.assertIsNone(event.old_values['next_visit_date'])
        self.assertEqual(event.new_values['next_visit_date'], planned.isoformat())
        self.assertFalse(self.case.pipeline_events.filter(action='jbl_visit_completed').exists())

    def test_reschedule_can_be_today_in_nairobi_even_before_utc_midnight(self):
        from datetime import datetime, timezone as dt_timezone
        from zoneinfo import ZoneInfo
        instant = datetime(2026, 11, 12, 22, 0, tzinfo=dt_timezone.utc)
        with timezone.override(ZoneInfo('Africa/Nairobi')), patch('django.utils.timezone.now', return_value=instant):
            response = self.submit(visit_status='Rescheduled', reason_code='', next_visit_date='2026-11-13')
            self.assertEqual(response.status_code, 200, response.content)
            self.case.refresh_from_db()
            self.assertEqual(self.case.jbl_next_visit_date.isoformat(), '2026-11-13')

    def test_replaying_due_reschedule_after_date_passes_is_idempotent(self):
        planned = timezone.localdate()
        response = self.submit(visit_status='Rescheduled', reason_code='', next_visit_date=planned.isoformat())
        self.assertEqual(response.status_code, 200, response.content)
        self.case.refresh_from_db()
        revision = self.case.workflow_revision
        with patch('django.utils.timezone.localdate', return_value=planned + timedelta(days=2)):
            response = self.submit(visit_status='Rescheduled', reason_code='', next_visit_date=planned.isoformat())
        self.assertEqual(response.status_code, 200, response.content)
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_revision, revision)
        self.assertEqual(self.case.pipeline_events.filter(action='jbl_outcome_recorded').count(), 1)

    def test_replacing_reschedule_clears_active_date_but_keeps_audit(self):
        from core.services.jawabu_pipeline import complete_jbl_visit
        planned = timezone.localdate()
        self.assertEqual(self.submit(visit_status='Rescheduled', reason_code='', next_visit_date=planned.isoformat()).status_code, 200)
        self.case.refresh_from_db()
        with patch('core.services.portal_publication.reserve_farmer_publication', return_value=[]):
            ok, error, _ = complete_jbl_visit(self.case, categorized_files={}, visit_date=None, visit_occurred=False,
                officer='Synthetic', visit_status='Rejected by JBL', reason_code='r01',
                request_id='replace-schedule', expected_revision=self.case.workflow_revision)
        self.assertTrue(ok, error)
        self.case.refresh_from_db()
        self.assertIsNone(self.case.jbl_next_visit_date)
        self.assertEqual(self.case.pipeline_events.get(request_id='replace-schedule').old_values['next_visit_date'], planned.isoformat())

    def test_withdrawal_clears_active_next_visit(self):
        from core.services.portal_withdrawals import change_withdrawal
        planned = timezone.localdate()
        self.case.jbl_visit_status, self.case.jbl_next_visit_date = 'Rescheduled', planned
        self.case.save()
        with patch('core.services.portal_publication.reserve_farmer_publication', return_value=[]):
            updated = change_withdrawal(self.case, action='withdraw', reason='Client withdrew',
                expected_revision=self.case.workflow_revision, request_id='withdraw-schedule', actor=self.actor, stage='jbl_visit')
        self.assertIsNone(updated.jbl_next_visit_date)
        event = updated.pipeline_events.get(request_id='withdraw-schedule')
        self.assertEqual(event.old_values['next_visit_date'], planned.isoformat())

    def test_rescheduled_draft_retains_date_in_field_allowlist(self):
        from core.api.portal_views import _portal_jbl_visit_draft_payload, PORTAL_JBL_VISIT_DRAFT_FIELDS
        planned = timezone.localdate().isoformat()
        self.assertIn('jbl-next-visit-date', PORTAL_JBL_VISIT_DRAFT_FIELDS)
        draft = _portal_jbl_visit_draft_payload({'payload': {'values': {'jbl-next-visit-date': planned}}})
        self.assertEqual(draft['values']['jbl-next-visit-date'], planned)

    def test_stale_reschedule_cannot_overwrite_existing_schedule(self):
        from core.services.jawabu_pipeline import complete_jbl_visit
        from core.services.workflow_transitions import WorkflowRevisionConflict
        self.assertEqual(self.submit(visit_status='Rescheduled', reason_code='', next_visit_date=timezone.localdate().isoformat()).status_code, 200)
        with self.assertRaises(WorkflowRevisionConflict):
            complete_jbl_visit(self.case, categorized_files={}, visit_date=None, visit_occurred=False,
                officer='Synthetic', visit_status='Rescheduled', next_visit_date=timezone.localdate() + timedelta(days=1),
                request_id='stale-schedule', expected_revision=1)
