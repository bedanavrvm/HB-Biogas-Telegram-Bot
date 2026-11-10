"""Synthetic register status contracts, separate from workflow authority."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import GroupSheetConfiguration, JawabuFarmerMaster
from core.services.jawabu_pipeline import current_pipeline_state_label, master_projection_fields
from core.services.portal_sheet_status import PortalSheetStatus, sheet_pipeline_status
from hb_operations.models import HomeBiogasAction
from portal_legacy.models import LegacyBatch, LegacyEvent, LegacyRow
from portal_legacy.projection import record_values
from portal_legacy.workbook import propose


class PortalSheetStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(username='synthetic-status-reviewer')
        cls.group = GroupSheetConfiguration.objects.create(
            group_id='synthetic-status-owner', sheet_id='synthetic-status-book',
            workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True,
                      'master_sheet_id': 'synthetic-status-book', 'master_header_row': 1,
                      'master_data_start_row': 2},
        )
        cls.batch = LegacyBatch.objects.create(
            group=cls.group, namespace='synthetic-statuses', source_hash='a' * 64,
            created_by=cls.actor,
        )

    def case(self, **values):
        return JawabuFarmerMaster.objects.create(**{
            'group_configuration': self.group, 'customer_name': 'SYNTHETIC STATUS CASE',
            'workflow_state': 'jbl_visit', 'deposit_paid_hbg': Decimal('5000'),
            'hbg_visit_date': date(2026, 1, 2), **values,
        })

    def legacy(self, *, source='Master Data', state='legacy_review', farmer=None, **values):
        values = {'customer_name': 'SYNTHETIC HISTORY', **values}
        farmer = farmer or self.case(source='portal_legacy', workflow_state=state,
                                    legacy_fulfillment_partner='ECOCONSERVE' if source == 'Eco-conserve' else 'HB')
        row = LegacyRow.objects.create(
            batch=self.batch, source_sheet=source, source_row=2 + LegacyRow.objects.count(),
            source_hash='a' * 64, values=values, proposal=propose(values), farmer=farmer,
            committed_at=timezone.now(), publication_ready=True,
        )
        return farmer, row

    def test_exactly_twelve_unique_approved_labels(self):
        self.assertEqual(set(PortalSheetStatus.values), {
            'Awaiting JBL Visit', 'Deferred', 'Rejected', 'Cancelled/Withdrawn',
            'Approved — Order Processing', 'Installation in Progress',
            'Installed — Awaiting Commissioning', 'Commissioned', 'Legacy',
            'Pending Minimum Deposit', 'Opted for Other', 'Under Review',
        })
        self.assertEqual(len(PortalSheetStatus.values), 12)

    def test_minimum_deposit_boundaries_and_fallback(self):
        for amount, receipts, expected in [
            (None, '', 'Pending Minimum Deposit'), (Decimal('0'), '', 'Pending Minimum Deposit'),
            (Decimal('4999.99'), '', 'Pending Minimum Deposit'),
            (Decimal('5000'), '', 'Awaiting JBL Visit'),
            (None, '5,000.00', 'Awaiting JBL Visit'), (None, 'unknown', 'Pending Minimum Deposit'),
        ]:
            with self.subTest(amount=amount, receipts=receipts):
                farmer = self.case(deposit_paid_hbg=amount, actual_receipts=receipts)
                self.assertEqual(sheet_pipeline_status(farmer), expected)
        farmer = self.case(deposit_paid_hbg=None, jbl_visit_date=date(2026, 1, 3))
        self.assertEqual(sheet_pipeline_status(farmer), 'Awaiting JBL Visit')

    def test_credit_approval_alone_stays_under_review(self):
        for state in ('credit', 'final_review'):
            farmer = self.case(workflow_state=state, credit_decision='Approved', deposit_paid_hbg=None)
            self.assertEqual(sheet_pipeline_status(farmer), 'Under Review')
        for state, extra in [('order', {'final_decision': 'Approved'}),
                             ('ordered', {'order_number': 'HB-1'})]:
            farmer = self.case(workflow_state=state, **extra)
            self.assertEqual(sheet_pipeline_status(farmer), 'Approved — Order Processing')

    def test_halts_collapse_without_changing_detailed_miniapp_labels(self):
        farmer = self.case(workflow_state='deferred', deferred_stage='credit',
                           deferred_until=timezone.localdate() - timedelta(days=1))
        self.assertEqual(sheet_pipeline_status(farmer), 'Deferred')
        self.assertEqual(current_pipeline_state_label(farmer), 'Reappraisal Required')
        farmer = self.case(workflow_state='rejected', credit_decision='Rejected')
        self.assertEqual(sheet_pipeline_status(farmer), 'Rejected')
        self.assertEqual(current_pipeline_state_label(farmer), 'Rejected — Credit')
        farmer = self.case(jbl_visit_status='Rescheduled')
        self.assertEqual(sheet_pipeline_status(farmer), 'Deferred')
        self.assertEqual(current_pipeline_state_label(farmer), 'JBL Visit Rescheduled')

    def test_opted_out_route_is_distinct_from_a_later_withdrawal(self):
        for route in ('Opted for Cash', 'Opted for Other Partner'):
            farmer = self.case(workflow_state='withdrawn', jbl_visit_status=route)
            self.assertEqual(sheet_pipeline_status(farmer), 'Opted for Other')
            farmer.withdrawn_stage = 'credit'
            self.assertEqual(sheet_pipeline_status(farmer), 'Cancelled/Withdrawn')
        farmer, _ = self.legacy(state='withdrawn', legacy_outcome='OPTED FOR OTHER PARTNER')
        self.assertEqual(sheet_pipeline_status(farmer), 'Opted for Other')
        farmer, _ = self.legacy(state='withdrawn', legacy_outcome='WITHDRAWN')
        self.assertEqual(sheet_pipeline_status(farmer), 'Cancelled/Withdrawn')

    def test_known_historical_outcome_survives_unknown_stage_and_is_read_only(self):
        for outcome, expected in [
            ('Rejected', 'Rejected'), ('Deferred', 'Deferred'), ('On Hold', 'Deferred'),
            ('Withdrawn', 'Cancelled/Withdrawn'), ('Cancelled', 'Cancelled/Withdrawn'),
            ('Opted for Cash', 'Opted for Other'), ('Opted for Other Partner', 'Opted for Other'),
            ('Rescheduled', 'Deferred'), ('Visited, Awaiting Credit Analysis', 'Under Review'),
            ('Approved', 'Legacy'), ('', 'Legacy'),
        ]:
            with self.subTest(outcome=outcome):
                farmer, row = self.legacy(legacy_outcome=outcome)
                before = JawabuFarmerMaster.objects.filter(pk=farmer.pk).values().get()
                self.assertEqual(sheet_pipeline_status(farmer), expected)
                self.assertEqual(JawabuFarmerMaster.objects.filter(pk=farmer.pk).values().get(), before)
                row.refresh_from_db()
                self.assertFalse(row.continuation_confirmed)
                self.assertFalse(farmer.pipeline_events.exists())
                self.assertEqual(farmer.credit_decision, '')
                self.assertEqual(farmer.final_decision, '')

    def test_explicit_historical_decision_does_not_gain_a_new_approval_event(self):
        for decision_stage, expected in [('credit', 'Under Review'),
                                         ('final_review', 'Approved — Order Processing')]:
            farmer, row = self.legacy(legacy_outcome='Approved', decision_stage=decision_stage)
            self.assertEqual(sheet_pipeline_status(farmer), expected)
            self.assertFalse(farmer.pipeline_events.exists())
            self.assertIsNone(farmer.credit_decided_at)
            self.assertEqual(farmer.final_decision, '')

    def test_reported_fulfilment_remains_visible_with_date_warnings(self):
        for commissioning, expected in [('Commissioned', 'Commissioned'),
                                        ('Not Commissioned', 'Installed — Awaiting Commissioning')]:
            farmer, row = self.legacy(
                installation_status='Installed', commissioning_status=commissioning,
                installation_date='2026-01-20', commissioning_date='2026-01-10')
            self.assertTrue(row.proposal['issues'])
            self.assertEqual(sheet_pipeline_status(farmer), expected)
            self.assertEqual(current_pipeline_state_label(farmer), 'Legacy review - stage not confirmed')
            self.assertFalse(HomeBiogasAction.objects.filter(farmer=farmer).exists())
            self.assertEqual(farmer.workflow_state, 'legacy_review')

    def test_conflicting_historical_facts_stay_legacy(self):
        for values in [
            {'legacy_outcome': 'Rejected', 'installation_status': 'Installed'},
            {'legacy_outcome': 'Opted for Cash', 'installation_status': 'Installed'},
            {'installation_status': 'Open', 'commissioning_status': 'Commissioned'},
            {'legacy_outcome': 'Rejected', 'order_number': 'HB-1'},
        ]:
            farmer, _ = self.legacy(**values)
            self.assertEqual(sheet_pipeline_status(farmer), 'Legacy')
        farmer, _ = self.legacy(legacy_outcome='Rejected')
        self.legacy(farmer=farmer, legacy_outcome='Deferred')
        self.assertEqual(sheet_pipeline_status(farmer), 'Legacy')

    def test_unrelated_source_warning_does_not_hide_a_known_outcome(self):
        farmer, row = self.legacy(legacy_outcome='Rejected', legacy_deposit_paid_jbl='unrecorded')
        self.assertTrue(row.proposal['issues'])
        self.assertEqual(sheet_pipeline_status(farmer), 'Rejected')

    def test_later_canonical_work_wins_over_old_reported_outcome(self):
        farmer, _ = self.legacy(state='credit', legacy_outcome='Rejected')
        self.assertEqual(sheet_pipeline_status(farmer), 'Under Review')
        farmer, _ = self.legacy(state='ordered', order_number='HB-1')
        self.assertEqual(sheet_pipeline_status(farmer), 'Approved — Order Processing')

    def test_legacy_order_number_establishes_historical_approval_without_fabricating_evidence(self):
        for source in ('Master Data', 'Eco-conserve'):
            for state in ('legacy_review', 'ordered'):
                with self.subTest(source=source, state=state):
                    farmer, row = self.legacy(source=source, state=state, order_number='HB-12')
                    self.assertEqual(sheet_pipeline_status(farmer), 'Approved — Order Processing')
                    self.assertEqual(farmer.final_decision, '')
                    self.assertIsNone(farmer.final_decided_at)
                    self.assertEqual(farmer.final_decided_by, '')
                    self.assertFalse(farmer.pipeline_events.exists())
                    self.assertFalse(HomeBiogasAction.objects.filter(farmer=farmer).exists())
                    self.assertEqual(farmer.workflow_state, state)

    def test_accepted_source_amendment_is_used_without_rewriting_original(self):
        farmer, row = self.legacy(legacy_outcome='Rejected')
        LegacyEvent.objects.create(row=row, actor=self.actor, request_key='synthetic-source-amendment',
                                   action='fields_updated', payload={'source_changes': {'legacy_outcome': 'Deferred'}})
        self.assertEqual(sheet_pipeline_status(farmer), 'Deferred')
        row.refresh_from_db()
        self.assertEqual(row.values['legacy_outcome'], 'Rejected')

    def test_post_order_progress_never_falls_back_to_deposit_hold(self):
        for installation, commissioning, expected in [
            ('open', 'not_commissioned', 'Installation in Progress'),
            ('installed', 'not_commissioned', 'Installed — Awaiting Commissioning'),
            ('installed', 'commissioned', 'Commissioned'),
            ('closed', 'not_commissioned', 'Cancelled/Withdrawn'),
        ]:
            farmer, row = self.legacy(state='ordered')
            farmer.deposit_paid_hbg = None
            action = HomeBiogasAction.objects.create(
                farmer=farmer, legacy_origin=row, source_order_number='HB-1', source_requisition_version=1,
                installation_status=installation, commissioning_status=commissioning,
            )
            self.assertEqual(sheet_pipeline_status(farmer), expected)
            self.assertEqual(action.revision, 1)

    def test_initial_and_normal_master_eco_projections_share_exact_status_spelling(self):
        for source in ('Master Data', 'Eco-conserve'):
            farmer, row = self.legacy(source=source, legacy_outcome='Rejected')
            fields = master_projection_fields(farmer)
            self.assertEqual(fields['current_pipeline_state'][1], 'REJECTED')
            headers = ['Staff formula', 'Current Pipeline State', 'Customer Name']
            projected = record_values(row, headers, 1, existing=['=SUM(1,2)', 'old label', 'SYNTHETIC'])
            self.assertEqual(projected[0], '=SUM(1,2)')
            self.assertEqual(projected[1], 'REJECTED')

    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_normal_publication_updates_existing_row_and_preserves_formula(self, get_service):
        from core.tests import FakeJawabuService, FakeMasterDataSheet
        from core.services.jawabu_pipeline import sync_farmer_to_master_sheet
        for source in ('Master Data', 'Eco-conserve'):
            farmer, _ = self.legacy(source=source, legacy_outcome='Rejected')
            farmer.national_id = '12345678' if source == 'Master Data' else '87654321'
            farmer.save(update_fields=['national_id'])
            headers = ['No.', 'Customer Name', 'National ID', 'Current Pipeline State',
                       'Master Record ID', 'Staff formula']
            sheet = FakeMasterDataSheet(headers)
            sheet.values = [headers, [1, 'SYNTHETIC', farmer.national_id,
                                      'LEGACY REVIEW - STAGE NOT CONFIRMED',
                                      str(farmer.pk), '=SUM(1,2)']]
            get_service.return_value = FakeJawabuService(sheet)
            failure = {}
            self.assertTrue(sync_farmer_to_master_sheet(farmer, failure_context=failure), failure)
            self.assertEqual(sheet.values[1][3], 'REJECTED')
            self.assertEqual(sheet.values[1][5], '=SUM(1,2)')
            self.assertEqual(len(sheet.values), 2)
            self.assertEqual(farmer.workflow_state, 'legacy_review')
