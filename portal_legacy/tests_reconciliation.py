from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from copy import deepcopy
from unittest.mock import patch
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook

from core.models import JawabuFarmerMaster, JawabuPipelineEvent
from core.tests_telegram_authentication import BOT_TOKEN
from .models import LegacyBatch, LegacyRow, LegacyUpload
from .reconciliation import POLICY
from .tests import LegacyHTTPMixin


class ReconciledSheetIdentityTests(TestCase):
    def setUp(self):
        from core.models import GroupSheetConfiguration
        from core.tests import FakeMasterDataSheet, FakeJawabuService
        self.group = GroupSheetConfiguration.objects.create(group_id='synthetic-reconciled-units', sheet_id='synthetic-sheet',
            workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True, 'master_header_row': 1, 'master_data_start_row': 2})
        self.first = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='FIRST UNIT',
            national_id='12345678', primary_phone='254712345678', workflow_state='credit')
        self.second = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='SECOND UNIT',
            national_id='12345678', primary_phone='254712345679')
        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Master Record ID', 'Current Pipeline State', 'Staff formula']
        self.sheet = FakeMasterDataSheet(headers)
        self.sheet.values = [headers, [1, 'FIRST UNIT', '12345678', self.first.primary_phone, str(self.first.pk), 'Awaiting JBL Visit', '=1+1'],
            [2, 'SECOND UNIT', '12345678', self.second.primary_phone, str(self.second.pk), 'Awaiting JBL Visit', '=2+2']]
        transport = patch('core.services.sheets.GoogleSheetsService.get_instance', return_value=FakeJawabuService(self.sheet))
        transport.start(); self.addCleanup(transport.stop)

    def test_unique_owned_uuid_updates_its_row_when_another_unit_shares_national_id(self):
        from core.services.jawabu_pipeline import sync_farmer_to_master_sheet
        other = deepcopy(self.sheet.values[2]); failure = {}
        self.assertTrue(sync_farmer_to_master_sheet(self.first, failure_context=failure), failure)
        self.assertEqual(self.sheet.values[1][4], str(self.first.pk))
        self.assertEqual(self.sheet.values[1][5].casefold(), 'under review')
        self.assertEqual(self.sheet.values[1][6], '=1+1')
        self.assertEqual(self.sheet.values[2][:len(other)], other)
        self.assertEqual(len(self.sheet.values), 3)

    def test_two_rows_claiming_the_same_uuid_remain_blocked(self):
        from core.services.jawabu_pipeline import sync_farmer_to_master_sheet
        self.sheet.values[2][4] = str(self.first.pk)
        self.assert_identity_hold()

    def test_repeated_national_id_without_an_owned_uuid_remains_blocked(self):
        self.sheet.values[1][4] = str(uuid.uuid4())
        self.assert_identity_hold()

    def assert_identity_hold(self):
        from core.services.jawabu_pipeline import sync_farmer_to_master_sheet
        before = deepcopy(self.sheet.values[1:]); failure = {}
        self.assertFalse(sync_farmer_to_master_sheet(self.first, failure_context=failure))
        self.assertEqual(failure['phase'], 'identity')
        for observed, original in zip(self.sheet.values[1:], before):
            self.assertEqual(observed[:len(original)], original)


def source(*, outcome='Deferred', guide='', comment='', hb='', visit='', name='SYNTHETIC CLIENT', national_id='12345678', final='Ignored', phone='0712345678'):
    book = Workbook(); sheet = book.active; sheet.title = 'Master Data'
    sheet.append(['Name', 'ID NUMBER', 'First Phone Number', 'Decision/Action', 'Additional Comments',
        'Decision/Action', 'JAWABU FINAL POSITION ', 'HB  ACTION', 'UPDATED COMMENT FOR NOVEMBER 26 AS AT 10TH', 'Jawabu Visit Date'])
    sheet.append([name, national_id, phone, outcome, '', guide, final, hb, comment, visit])
    out = BytesIO(); book.save(out); return out.getvalue()


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False, REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class OperationalReconciliationTests(LegacyHTTPMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.group.workflow.update(master_sync_enabled=True); self.group.save(update_fields=['workflow'])
        self.case = JawabuFarmerMaster.objects.create(group_configuration=self.group, source='portal_legacy',
            customer_name='SYNTHETIC CLIENT', national_id='12345678', primary_phone='254712345678',
            deposit_paid_hbg=Decimal('5000'), workflow_state='legacy_review', hbg_visit_date=timezone.localdate()-timedelta(days=30))
        batch = LegacyBatch.objects.create(group=self.group, namespace='old', source_hash='a'*64, created_by=self.actor)
        self.original = LegacyRow.objects.create(batch=batch, source_sheet='Master Data', source_row=12, source_hash='a'*64,
            values={'customer_name': self.case.customer_name, 'national_id': self.case.national_id,
                    'primary_phone': self.case.primary_phone, 'legacy_outcome': 'DEFERRED / ON HOLD',
                    'case_comment_history': 'Original source note'}, farmer=self.case, proposal={},
            committed_at=timezone.now(), continuation_confirmed=False, publication_ready=True)

    def create(self, content=None, **kwargs):
        upload, data = super().create(content, **kwargs)
        LegacyUpload.objects.filter(pk=upload['id']).update(mode='updates', state={'update_policy': POLICY})
        return self.request(upload=upload, method='get', query='?summary=1')['upload'], data

    def staged(self, **kwargs):
        return self.finish(self.stage(source(**kwargs)), 'comparing')

    def row(self, upload):
        return self.request(upload=upload, method='get', query='?filter=all')['rows'][0]

    def apply(self, upload, *, fields=None, **review):
        row = self.row(upload)
        item = {'id': row['id'], 'approved': True, **review}
        if fields is not None: item['selected_fields'] = fields
        upload = self.request('select', {'rows': [item]}, upload=upload)['upload']
        return self.finish(self.request('commit', upload=upload)['upload'], 'committing')

    def test_duplicate_decisions_are_separate_and_final_position_ignored(self):
        from .updates import bind_update_headers
        binding = bind_update_headers(['Name', 'Decision/Action', 'Decision/Action', 'JAWABU FINAL POSITION ', 'HB  ACTION'])
        self.assertEqual(binding[1], 'legacy_outcome'); self.assertEqual(binding[2], 'guidance_decision')
        self.assertNotIn(3, binding); self.assertEqual(binding[4], 'guidance_hb_action')
        with self.assertRaisesMessage(ValueError, 'Duplicate source header'):
            bind_update_headers(['Name', 'Decision/Action', 'Decision/Action', 'Decision/Action'])

    def test_approved_enters_credit_without_fabricating_approval_or_changing_origin(self):
        upload = self.staged(outcome='Approved')
        row = self.row(upload)
        self.assertEqual(row['proposal']['changes']['reconciled_position']['after'], 'Credit Analysis')
        upload = self.apply(upload)
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state, 'credit'); self.assertEqual(self.case.source, 'portal_legacy')
        self.assertEqual(self.case.credit_decision, ''); self.assertIsNone(self.case.credit_decided_at)
        self.assertEqual(self.case.final_decision, ''); self.assertIsNone(self.case.final_decided_at)
        self.assertIsNone(self.case.jbl_visit_date); self.assertEqual(self.case.jbl_officer, '')
        self.assertFalse(self.case.pipeline_events.filter(action='jbl_visit_completed').exists())
        self.original.refresh_from_db(); self.assertEqual(self.original.values['legacy_outcome'], 'DEFERRED / ON HOLD')
        from .updates import effective_values
        self.assertEqual(effective_values(self.original)['legacy_outcome'], 'APPROVED')
        self.assertTrue(self.original.continuation_confirmed)
        self.assertTrue(self.row(upload)['reconciliation']['operations'])
        count = self.case.pipeline_events.count()
        self.apply(upload)
        self.assertEqual(self.case.pipeline_events.count(), count)

    def test_farmup_origin_and_append_only_comments_survive_replay_and_new_version(self):
        from core.services.jawabu_comments import record_case_comment, master_comment_history
        self.original.delete()
        self.case.source = 'jawabu_farmup_review'; self.case.workflow_state = 'jbl_visit'; self.case.save()
        record_case_comment(farmer=self.case, stage_key='correction', comment='Existing app note', request_id='old')
        visit = timezone.localdate()-timedelta(days=2)
        upload = self.apply(self.staged(outcome='Approved', comment='New source note', visit=visit.isoformat()))
        self.case.refresh_from_db()
        self.assertEqual(self.case.source, 'jawabu_farmup_review'); self.assertFalse(self.case.legacy_records.exists())
        self.assertEqual(self.case.jbl_visit_date, visit); self.assertEqual(self.case.workflow_state, 'credit')
        self.assertEqual(self.case.jbl_officer, '')
        history = master_comment_history(self.case)
        self.assertIn('Existing app note', history); self.assertEqual(history.count('New source note'), 1)
        self.assertIn(timezone.localdate().strftime('%d/%m/%Y'), history)
        # A distinct source hash cannot re-add a previously accepted fact/note.
        second = self.staged(outcome='Approved', comment='New source note', visit=visit.isoformat(), final='Different ignored cell')
        self.assertEqual(second['counts'], {'unchanged': 1})
        self.assertEqual(self.row(upload)['proposal']['kind'], 'changed')

    def test_conflicting_approved_guidance_can_be_reviewed_as_deferred_without_expiry(self):
        upload = self.staged(guide='Approved', comment='Requested more time till December to discuss with family')
        self.assertEqual(self.row(upload)['proposal']['changes']['reconciled_position']['target'], 'deferred')
        upload = self.apply(upload, position_override='deferred')
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state, 'deferred'); self.assertIsNone(self.case.deferred_at)
        self.assertIsNone(self.case.deferred_until)
        event = self.case.pipeline_events.get(action='source_reconciled')
        self.assertEqual(event.metadata['position_override'], 'deferred')

    def test_latest_current_credit_note_overrides_short_deferred_guide(self):
        upload = self.staged(outcome='Approved', guide='Deffered', comment='Client visited and in process for credit analysis to be concluded tomorrow')
        self.assertEqual(self.row(upload)['proposal']['changes']['reconciled_position']['target'], 'credit')

    def test_guided_cash_and_hb_instructions_do_not_fabricate_installation(self):
        upload = self.apply(self.staged(guide='opted', comment='Opted for cash', hb='Installation and commissioning'))
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_state, 'withdrawn'); self.assertEqual(self.case.jbl_visit_status, 'Opted for Cash')
        self.assertFalse(hasattr(self.case, 'homebiogas_action'))
        from core.services.jawabu_comments import master_comment_history
        self.assertIn('Installation and commissioning', master_comment_history(self.case))
        self.assertEqual(upload['committed'], 1)

    def test_source_order_and_existing_order_prevent_automatic_backwards_transition(self):
        self.case.order_number = 'HB-7'; self.case.workflow_state = 'ordered'; self.case.save()
        upload = self.staged(guide='Rejected', comment='New source note')
        row = self.row(upload)
        self.assertIn('later order', row['proposal']['changes']['reconciled_position']['error'])
        self.assertEqual(row['reconciliation']['selected_fields'], [])
        upload = self.request('select', {'all': True, 'approved': True}, upload=upload)['upload']
        self.assertEqual(upload['selected'], 0)
        self.apply(upload, fields=['reconciled_position'])
        self.case.refresh_from_db(); self.assertEqual(self.case.workflow_state, 'ordered')
        self.assertFalse(self.case.pipeline_events.filter(action='source_reconciled').exists())

    def test_rescheduled_requires_exact_date_and_rejects_unsupported_override(self):
        upload = self.staged(outcome='Rescheduled', comment='Next week')
        self.assertIn('exact next visit', self.row(upload)['proposal']['changes']['reconciled_position']['error'])
        row = self.row(upload)
        self.request('select', {'rows': [{'id': row['id'], 'position_override': 'order'}]}, upload=upload, status=409)
        upload = self.apply(upload, next_visit_date=(timezone.localdate()+timedelta(days=2)).strftime('%d/%m/%Y'))
        self.case.refresh_from_db(); self.assertEqual(self.case.jbl_next_visit_date, timezone.localdate()+timedelta(days=2))
        self.assertIsNone(self.case.jbl_visit_date)

    def test_unique_wrong_id_cannot_override_name_phone_evidence(self):
        other = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='OTHER PERSON',
            national_id='87654321', primary_phone='254700000000')
        upload = self.staged(national_id=other.national_id)
        row = self.row(upload)
        self.assertEqual(row['proposal']['kind'], 'ambiguous'); self.assertFalse(row['proposal']['case_id'])
        self.assertEqual(set(row['proposal']['candidates']), {str(self.case.pk), str(other.pk)})

    def test_current_new_intake_is_not_created_as_a_historical_record(self):
        upload = self.staged(name='NEW PERSON', national_id='87654321', phone='0700000001')
        row = self.row(upload); self.assertEqual(row['proposal']['kind'], 'new')
        self.assertTrue(row['proposal']['new_intake_required'])
        upload = self.apply(upload, create_new=True)
        self.assertEqual(upload['committed'], 0); self.assertEqual(JawabuFarmerMaster.objects.count(), 1)

    def test_order_membership_blocks_transition_even_when_case_reference_fields_are_blank(self):
        from core.models import RequisitionBatch
        RequisitionBatch.objects.create(group_configuration=self.group, order_number='HB-12', farmer_ids=[str(self.case.pk)])
        upload = self.staged(outcome='Approved')
        self.assertIn('Live order', self.row(upload)['proposal']['changes']['reconciled_position']['error'])
        self.apply(upload, fields=['reconciled_position'])
        self.case.refresh_from_db(); self.assertEqual(self.case.workflow_state, 'legacy_review')

    def test_blank_source_is_never_an_erase_proposal_and_native_withdrawal_requires_resume(self):
        self.case.secondary_phone = '254700000001'; self.case.workflow_state = 'withdrawn'; self.case.save()
        JawabuPipelineEvent.objects.create(farmer=self.case, action='case_withdrawn', source='portal')
        upload = self.staged(outcome='Approved')
        row = self.row(upload)
        self.assertNotIn('secondary_phone', row['proposal']['changes'])
        self.assertIn('owning workflow', row['proposal']['changes']['reconciled_position']['error'])
        self.apply(upload, fields=['reconciled_position'])
        self.case.refresh_from_db(); self.assertEqual(self.case.workflow_state, 'withdrawn')
        self.assertEqual(self.case.secondary_phone, '254700000001')

    def test_conflict_with_later_native_work_and_other_workflow_authority_is_held(self):
        self.case.workflow_state = 'credit'; self.case.save()
        JawabuPipelineEvent.objects.create(farmer=self.case, action='jbl_visit_completed', source='portal')
        upload = self.staged(guide='Rejected')
        self.assertTrue(self.row(upload)['proposal']['changes']['reconciled_position']['app_conflict'])
        self.assertEqual(self.row(upload)['reconciliation']['selected_fields'], [])
        self.staff(role='IT', workflow='complaint_cases')
        self.request('select', {'all': True, 'approved': True}, upload=upload, status=403)

    def test_scoped_portal_it_can_apply_but_stale_comparison_cannot_overwrite(self):
        self.actor = self.staff(role='IT', group=self.group)
        upload = self.staged(outcome='Approved')
        self.apply(upload)
        self.case.refresh_from_db(); self.assertEqual(self.case.workflow_state, 'credit')
        self.assertEqual(self.case.pipeline_events.get(action='source_reconciled').actor_user_id, self.actor.pk)
        second = self.staged(guide='Rejected')
        self.case.workflow_revision += 1; self.case.save(update_fields=['workflow_revision'])
        self.apply(second)
        self.case.refresh_from_db(); self.assertEqual(self.case.workflow_state, 'credit')
        self.assertIn('changed since comparison', self.row(second)['proposal']['commit_error'])

    def test_reported_dates_do_not_turn_into_native_sla_or_performance_evidence(self):
        from core.services.portal_report_timing import report_timing
        from core.services.jawabu_case360 import calculate_case_tat
        from core.services.report_provenance import report_scope
        self.original.delete(); self.case.source = 'jawabu_farmup_review'; self.case.workflow_state = 'jbl_visit'; self.case.save()
        JawabuPipelineEvent.objects.create(farmer=self.case, action='application_imported', source='farmup', occurred_at=timezone.now()-timedelta(days=1))
        visit = timezone.localdate()-timedelta(days=2)
        self.apply(self.staged(outcome='Approved', visit=visit.isoformat()))
        record = report_scope(JawabuFarmerMaster.objects.all(), 'portal', 'exclude').get(pk=self.case.pk)
        self.assertFalse(record.report_historical)
        events = list(record.pipeline_events.order_by('occurred_at','created_at'))
        timing = report_timing(record, now=timezone.now(), events=events, hb_events=[], targets={'stages': {}}, holidays=set())
        first = timing['stages'][0]
        self.assertTrue(first['externally_reported']); self.assertEqual(first['precision'], 'date')
        self.assertIsNotNone(first['minutes']); self.assertIsNone(first['target_minutes'])
        self.assertEqual(first['target_basis'], 'unavailable')
        native = calculate_case_tat(record, events=events, hb_events=[], targets={'stages': {}}, holidays=set())
        self.assertIsNone(native['stages'][0]['minutes'])
        self.assertFalse(native['stages'][0]['running'])
        self.assertFalse(record.pipeline_events.filter(action='jbl_visit_completed').exists())

    def test_external_position_without_a_visit_date_does_not_leave_native_intake_clock_running(self):
        from core.services.portal_report_timing import report_timing
        self.original.delete(); self.case.source = 'jawabu_farmup_review'; self.case.workflow_state = 'jbl_visit'; self.case.save()
        JawabuPipelineEvent.objects.create(farmer=self.case, action='application_imported', source='farmup', occurred_at=timezone.now()-timedelta(days=1))
        self.apply(self.staged(outcome='Approved'))
        self.case.refresh_from_db(); self.case.report_historical = False
        timing = report_timing(self.case, now=timezone.now(), events=list(self.case.pipeline_events.order_by('occurred_at','created_at')),
            hb_events=[], targets={'stages': {}}, holidays=set())
        first = timing['stages'][0]
        self.assertTrue(first['externally_reported']); self.assertIsNone(first['minutes']); self.assertFalse(first['running'])

    def test_external_closure_stops_an_earlier_native_stage_without_inventing_its_duration(self):
        from core.services.jawabu_case360 import calculate_case_tat
        self.original.delete(); self.case.source = 'jawabu_farmup_review'; self.case.workflow_state = 'credit'; self.case.save()
        now = timezone.now()
        JawabuPipelineEvent.objects.create(farmer=self.case, action='application_imported', occurred_at=now-timedelta(days=2))
        JawabuPipelineEvent.objects.create(farmer=self.case, action='jbl_visit_completed', occurred_at=now-timedelta(days=1))
        self.apply(self.staged(outcome='Rejected'), fields=['reconciled_position'])
        self.case.refresh_from_db()
        timing = calculate_case_tat(self.case, now=timezone.now(), events=list(self.case.pipeline_events.order_by('occurred_at','created_at')),
            hb_events=[], targets={'stages': {}}, holidays=set())
        self.assertIsNotNone(timing['stages'][0]['minutes'])
        self.assertIsNone(timing['stages'][1]['minutes']); self.assertFalse(timing['stages'][1]['running'])

    def test_subsequent_native_visit_restores_native_timing_and_no_source_replay(self):
        from core.services.report_provenance import external_timing
        from core.services.jawabu_case360 import calculate_case_tat
        self.original.delete(); self.case.source = 'jawabu_farmup_review'; self.case.workflow_state = 'jbl_visit'; self.case.save()
        now = timezone.now()
        JawabuPipelineEvent.objects.create(farmer=self.case, action='application_imported', source='farmup', occurred_at=now-timedelta(days=1))
        upload = self.staged(outcome='Approved')
        self.apply(upload)
        self.case.refresh_from_db()
        JawabuPipelineEvent.objects.create(farmer=self.case, action='jbl_visit_completed', source='portal', occurred_at=now+timedelta(minutes=1))
        events = list(self.case.pipeline_events.order_by('occurred_at','created_at'))
        fields, position = external_timing(events)
        self.assertIsNone(position); self.assertNotIn('jbl_visit_date', fields)
        timing = calculate_case_tat(self.case, now=now+timedelta(minutes=2), events=events,
            hb_events=[], targets={'stages': {}}, holidays=set())
        self.assertIsNotNone(timing['stages'][0]['minutes'])
        self.assertFalse(timing['stages'][0]['running'])
        self.case.workflow_state = 'deferred'; self.case.save(update_fields=['workflow_state'])
        repeated = self.staged(outcome='Approved', final='Different ignored guide')
        self.assertNotIn('reconciled_position', self.row(repeated)['proposal']['changes'])

    def test_installation_guidance_is_held_and_impossible_visit_chronology_is_not_selected(self):
        upload = self.staged(guide='Installed', comment='Already installed, HB to confirm date')
        row = self.row(upload)
        self.assertIn('owning workflow', row['proposal']['changes']['reconciled_position']['error'])
        self.assertEqual(row['reconciliation']['selected_fields'], [])
        invalid = self.staged(outcome='Approved', visit=(timezone.localdate()+timedelta(days=1)).isoformat())
        self.assertIn('real date', self.row(invalid)['proposal']['changes']['jbl_visit_date']['error'])
        self.assertEqual(self.row(invalid)['reconciliation']['selected_fields'], [])
