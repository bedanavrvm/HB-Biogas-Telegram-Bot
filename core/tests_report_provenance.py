"""Worked examples spanning source selection, metrics, readback and exports."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from openpyxl import load_workbook

from core.models import JawabuFarmerMaster, JawabuPipelineEvent
from core.services.complaint_register import complaint_report_page, complaint_report_summary, export_register_xlsx
from core.services.portal_reporting import run_curated_report
from core import tests_complaint_timing as fixtures


class HistoricalReportTests(TestCase):
    now = fixtures.ComplaintTimingTests.now
    setUp = fixtures.ComplaintTimingTests.setUp
    make_case = fixtures.ComplaintTimingTests.make_case

    def test_legacy_counts_are_optional_and_timings_never_pool(self):
        native = self.make_case(closed=True, duration=6, target=24)
        historical = self.make_case(closed=True, duration=96, target=1)
        historical.source = 'complaint_legacy'; historical.save(update_fields=['source'])
        missing = self.make_case(closed=True)
        missing.source = 'whatsapp_export'; missing.date_resolved = None
        missing.save(update_fields=['source', 'date_resolved'])
        # A real historical interval cannot end after the fixed reporting clock.
        historical.timestamp = self.now - timedelta(days=10)
        historical.date_resolved = historical.timestamp + timedelta(days=4)
        historical.save(update_fields=['timestamp', 'date_resolved'])
        self.assertEqual(complaint_report_summary()['total'], 1)
        included = complaint_report_summary(filters={'historical_scope': 'include'})
        self.assertEqual(included['total'], 3)
        self.assertEqual(included['card_timing']['median_resolution_hours'], 6)
        self.assertEqual(included['timing']['median_resolution_hours'], 6)
        self.assertEqual(included['historical']['timing']['median_resolution_hours'], 96)
        self.assertEqual(included['historical']['timing']['resolution_excluded'], 1)
        rows = complaint_report_page(filters={'historical_scope': 'include'})['results']
        legacy = next(row for row in rows if row['record_id'] == str(historical.pk))
        self.assertEqual(legacy['target_basis'], 'current_target_estimate')
        self.assertIn('Historical', legacy['timing_note'])
        actor = get_user_model().objects.create_user(username='report-export', is_superuser=True)
        content, count = export_register_xlsx(actor=actor, request_id='history-export', filters={'historical_scope': 'include'})
        workbook = load_workbook(BytesIO(content), read_only=True)
        self.assertEqual(count, 3)
        self.assertIn('Data origin', next(workbook.active.values))
        workbook.close()
        historical.refresh_from_db()
        self.assertEqual(historical.complaint_control.sla_target_hours, 1)

    def test_portal_historical_response_uses_activity_dates_not_import_execution(self):
        user = get_user_model().objects.create_user(username='report-provenance', is_superuser=True)
        historical = JawabuFarmerMaster.objects.create(customer_name='Historical', source='portal_legacy',
            hbg_visit_date=self.now.date()-timedelta(days=5), jbl_visit_date=self.now.date()-timedelta(days=2))
        # Import happens today; this is deliberately not the original stage start.
        JawabuPipelineEvent.objects.create(farmer=historical, action='application_imported', occurred_at=self.now)
        JawabuFarmerMaster.objects.create(customer_name='FarmUp', source='jawabu_farmers_csv')
        default = run_curated_report(preset='pipeline', filters={}, user=user, access=None)
        self.assertEqual([row['customer_name'] for row in default['rows']], ['FarmUp'])
        report = run_curated_report(preset='outcomes', filters={'historical_scope':'include','date_mode':'all'}, user=user, access=None)
        duration = next(chart for chart in report['charts'] if chart['id']=='duration')
        self.assertEqual(Decimal(duration['datasets'][0]['values'][0]), Decimal('72'))
        self.assertIn('Historical estimate', duration['labels'][0])
        self.assertEqual(duration['sample_counts'][duration['bucket_keys'][0]], 1)
        historical.refresh_from_db()
        self.assertEqual(historical.source, 'portal_legacy')

    def test_reset_includes_own_legacy_rows_but_preserves_other_groups(self):
        from core.models import GroupSheetConfiguration, IntegrationOperation
        from complaint_legacy.models import ImportUpload, ImportRow
        from core.services.group_reset import reset_group_data
        actor = get_user_model().objects.create_user(username='reset-provenance', is_superuser=True)
        owner = GroupSheetConfiguration.objects.create(group_id='-100-timing', workflow={'type':'case'})
        other = GroupSheetConfiguration.objects.create(group_id='other-reset-group', workflow={'type':'case'})
        case = self.make_case()
        preserved = self.make_case(); preserved.group_id = other.group_id; preserved.save(update_fields=['group_id'])
        upload = ImportUpload.objects.create(group=owner, actor=actor, namespace='reset', filename='synthetic.xlsx', digest='a'*64, size=1)
        ImportRow.objects.create(upload=upload, source_row=2, case=case, committed_at=self.now)
        job=IntegrationOperation.objects.create(integration='google_sheets',operation_type='complaint_browser.sheet',
            deduplication_key='reset-history-job',source_model='ComplaintCaseControl',source_id=str(case.complaint_control.pk))
        result = reset_group_data(owner)
        self.assertEqual(result['deleted']['complaint_legacy_rows'], 1)
        self.assertFalse(type(case).objects.filter(pk=case.pk).exists())
        self.assertTrue(type(case).objects.filter(pk=preserved.pk).exists())
        job.refresh_from_db()
        self.assertEqual(job.status,'dead_letter')
        self.assertEqual(job.last_error_code,'source_deleted')
        crossed = ImportUpload.objects.create(group=owner, actor=actor, namespace='reset', filename='synthetic.xlsx', digest='b'*64, size=1)
        ImportRow.objects.create(upload=crossed, source_row=2, case=preserved, committed_at=self.now)
        with self.assertRaisesMessage(ValueError, 'crosses group ownership'):
            reset_group_data(owner)
        self.assertTrue(ImportRow.objects.filter(upload=crossed).exists())

    def test_it_correction_is_audited_idempotent_and_preserves_workflow(self):
        from core.models import GroupSheetConfiguration, AccessGrant, ComplaintCaseEvent
        from core.services.access_grant_governance import governed_access_grant_mutation
        from core.services.complaint_cases import staff_actor_for_user, ComplaintCaseError, ComplaintCaseConflict
        from core.services.complaint_corrections import correct
        from django.core.exceptions import PermissionDenied
        group = GroupSheetConfiguration.objects.create(group_id='-100-timing',workflow={'type':'case'},complaint_sheet_projection_enabled=False)
        user = get_user_model().objects.create_user(username='correction-it')
        with governed_access_grant_mutation('Synthetic correction authority'):
            AccessGrant.objects.create(user=user,workflow='complaint_cases',role='IT',group_configuration=group)
        actor = staff_actor_for_user(group,user)
        case = self.make_case(closed=True)
        original_start = case.complaint_control.sla_started_at
        original_closed = case.date_resolved
        case.resolution_details = 'Original resolution retained.'
        case.save(update_fields=['resolution_details'])
        body = {'expected_revision':1,'client_request_id':'it-correct-1','customer_name':'Corrected name','reason':'Verified spelling with source.'}
        correct(group,actor,case.message_id,body)
        correct(group,actor,case.message_id,body)
        case.refresh_from_db()
        self.assertEqual(case.customer_name,'Corrected name')
        self.assertEqual(case.complaint_status,'Closed')
        self.assertEqual(case.date_resolved,original_closed)
        from core.services.complaint_cases import latest_resolution_text
        self.assertEqual(latest_resolution_text(case),'Original resolution retained.')
        self.assertEqual(case.complaint_control.sla_started_at,original_start)
        self.assertEqual(ComplaintCaseEvent.objects.filter(action='fields_corrected').count(),1)
        with self.assertRaises(ComplaintCaseError):
            correct(group,actor,case.message_id,{**body,'customer_name':'Other'})
        with self.assertRaises(ComplaintCaseConflict):
            correct(group,actor,case.message_id,{**body,'client_request_id':'it-correct-stale'})
        with self.assertRaises(ComplaintCaseError):
            correct(group,actor,case.message_id,{**body,'client_request_id':'it-future','expected_revision':2,'timestamp':(self.now+timedelta(days=1)).isoformat()})
        with self.assertRaises(ComplaintCaseError):
            correct(group,actor,case.message_id,{**body,'client_request_id':'it-invalid','expected_revision':2,'date_resolved':'bad date'})
        other = get_user_model().objects.create_user(username='correction-manager')
        with governed_access_grant_mutation('Synthetic manager authority'):
            AccessGrant.objects.create(user=other,workflow='complaint_cases',role='MANAGER',group_configuration=group)
        with self.assertRaises(PermissionDenied):
            correct(group,staff_actor_for_user(group,other),case.message_id,body)

    def test_current_targets_do_not_rewrite_captured_complaint_sla(self):
        from core.models import ComplaintCaseControl, ComplaintCaseEvent
        case = self.make_case(closed=True, duration=6, target=24)
        ComplaintCaseControl.objects.filter(parsed_message=case).update(sla_target_hours=1)
        summary = complaint_report_summary()
        self.assertEqual(summary['timing']['on_time'], 1)
        self.assertEqual(complaint_report_page(filters={})['results'][0]['target_hours'], 24)
        # Controlled missing audit evidence represents an old case with no retained target.
        ComplaintCaseEvent.objects.filter(case__parsed_message=case).delete()
        summary = complaint_report_summary()
        self.assertIsNone(summary['timing']['on_time_percent'])
        row = complaint_report_page(filters={})['results'][0]
        self.assertEqual(row['target_basis'], 'current_target_estimate')
        self.assertEqual(row['target_outcome'], 'estimate_on_time')
