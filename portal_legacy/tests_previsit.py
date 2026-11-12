"""Historical pre-visit evidence must reach the queue without waiving deposits."""
import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import IntegrationOperation
from core.services.jawabu_pipeline import credit_decision_label, jbl_visit_queue, log_jbl_visit
from core.tests_telegram_authentication import BOT_TOKEN
from .models import LegacyRow
from .test_support import workbook_bytes
from .tests import LegacyHTTPMixin
from .workbook import propose


class PrevisitProposalTests(SimpleTestCase):
    def values(self, **changes):
        return {'customer_name': 'SYNTHETIC PREVISIT', 'hbg_visit_date': '2026-01-02',
                'legacy_outcome': 'JBL To Schedule Visit', **changes}

    def test_explicit_statuses_accept_case_and_spacing_without_inventing_a_decision(self):
        for outcome in ('JBL To Schedule Visit', '  jawabu TO schedule visit ',
                        'Awaiting JBL Visit', 'Pending Minimum Deposit'):
            for stage in ('', 'Unspecified legacy stage', 'JBL Visit'):
                with self.subTest(outcome=outcome, stage=stage):
                    proposal = propose(self.values(legacy_outcome=outcome, decision_stage=stage))
                    self.assertEqual(proposal['state'], 'jbl_visit')
                    self.assertEqual(proposal['stage'], 'jbl_visit')
                    self.assertEqual(proposal['issues'], [])
                    self.assertNotIn('credit_decision', proposal['fields'])
                    self.assertNotIn('final_decision', proposal['fields'])
                    self.assertNotIn('jbl_visit_date', proposal['fields'])

    def test_historical_sign_date_can_supply_the_hbg_date(self):
        proposal = propose(self.values(hbg_visit_date='', legacy_sign_date='2026-01-02'))
        self.assertEqual(proposal['state'], 'jbl_visit')
        self.assertEqual(proposal['fields']['hbg_visit_date'], '2026-01-02')

    def test_missing_invalid_or_future_hbg_date_stays_under_review(self):
        for value in ('', 'unconfirmed', (timezone.localdate() + timedelta(days=1)).isoformat()):
            with self.subTest(value=value):
                proposal = propose(self.values(hbg_visit_date=value))
                self.assertEqual(proposal['state'], 'legacy_review')
                self.assertTrue(any('Pending JBL visit needs reconciliation' in issue for issue in proposal['issues']))

    def test_completed_visit_or_downstream_evidence_never_creates_a_revisit(self):
        for changes in (
            {'jbl_visit_date': '2026-01-03'}, {'jbl_visit_date': 'unconfirmed'},
            {'order_number': 'unconfirmed'}, {'payment_number': 'HB-1'},
            {'requisition_date': '2026-01-03'}, {'installation_date': '2026-01-04'},
            {'commissioning_date': '2026-01-05'}, {'installation_status': 'Open'},
            {'commissioning_status': 'Not Commissioned'}, {'jbl_visit_status': 'Visited, Awaiting Credit Analysis'},
            {'decision_stage': 'Credit'}, {'decision_stage': 'Final Review'},
            {'credit_decision': 'Rescheduled'},
        ):
            with self.subTest(changes=changes):
                proposal = propose(self.values(**changes))
                self.assertEqual(proposal['state'], 'legacy_review')
                self.assertTrue(any('Pending JBL visit needs reconciliation' in issue for issue in proposal['issues']))

    def test_later_recorded_decisions_orders_and_physical_completion_take_precedence(self):
        for changes, state in (
            ({'credit_decision': 'Approved'}, 'final_review'),
            ({'final_decision': 'Rejected'}, 'rejected'),
            ({'credit_decision': 'Deferred / On Hold'}, 'deferred'),
            ({'order_number': 'HB-12'}, 'ordered'),
            ({'installation_status': 'Installed'}, 'ordered'),
            ({'commissioning_status': 'Commissioned'}, 'ordered'),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(propose(self.values(**changes))['state'], state)

    def test_ambiguous_or_conflicting_outcomes_stay_under_review(self):
        for changes in (
            {'legacy_outcome': ''}, {'legacy_outcome': 'Approved'},
            {'legacy_outcome': 'Approved - Pending Minimum Deposit'},
            {'legacy_outcome': 'Legacy'},
            {'case_comment_history': 'Credit decision rejected.'},
            {'case_comment_history': 'JBL visit approved.'},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(propose(self.values(**changes))['state'], 'legacy_review')


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True,
                   REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class PrevisitImportTests(LegacyHTTPMixin, TestCase):
    def imported(self, source, rows):
        sheet = self.book.service(sheet_name=source)._sheet
        sheet.cells[1].extend(['No.', 'Current Pipeline State', 'Credit Decision'])
        sheet.cells[2] = []
        data = workbook_bytes(rows, headers=['Source Row', 'Customer Name', 'Primary Phone', 'National ID',
            'HBG Visit Date', 'Legacy Outcome', 'Deposit Paid to HBG', 'Deposit Paid to JBL'])
        upload = self.commit(self.stage(data, source=source))
        upload = self.finish(self.request('sync_rows', upload=upload)['upload'], 'syncing_rows')
        return upload, sheet

    def test_both_registers_import_publish_and_queue_with_the_real_deposit_boundary(self):
        for register, source in enumerate(('Master Data', 'Eco-conserve')):
            with self.subTest(source=source):
                rows = [[2+i, f'SYNTHETIC PREVISIT {register}-{i}', f'7123456{register}{i}',
                         f'123456{register}{i}', '2026-01-02', outcome, deposit, 9000]
                        for i, (outcome, deposit) in enumerate((
                            ('JBL To Schedule Visit', ''), ('Pending Minimum Deposit', '0'),
                            ('Awaiting JBL Visit', '4999.99'), ('JBL To Schedule Visit', '5000')))]
                upload, sheet = self.imported(source, rows)
                self.assertEqual(upload['sheet_sync']['synced'], 4)
                records = list(LegacyRow.objects.filter(source_sheet=source).select_related('farmer').order_by('source_row'))
                for index, row in enumerate(records):
                    farmer = row.farmer
                    self.assertEqual(farmer.workflow_state, 'jbl_visit')
                    self.assertTrue(row.continuation_confirmed)
                    self.assertEqual(credit_decision_label(farmer), 'Legacy')
                    self.assertEqual(farmer.credit_decision, '')
                    self.assertEqual(farmer.final_decision, '')
                    self.assertIsNone(farmer.jbl_visit_date)
                    self.assertIsNone(farmer.credit_decided_at)
                    self.assertIsNone(farmer.final_decided_at)
                    self.assertFalse(farmer.pipeline_events.exists())
                    self.assertTrue(jbl_visit_queue().filter(pk=farmer.pk).exists())
                    self.assertEqual(jbl_visit_queue(status='deposit_pending').filter(pk=farmer.pk).exists(), index < 3)
                    self.assertEqual(jbl_visit_queue(status='awaiting_visit').filter(pk=farmer.pk).exists(), index == 3)
                    cells = sheet.row_values(farmer.source_row_number)
                    self.assertEqual(cells[sheet.cells[1].index('Current Pipeline State')],
                                     'PENDING MINIMUM DEPOSIT' if index < 3 else 'AWAITING JBL VISIT')
                    self.assertEqual(cells[sheet.cells[1].index('Credit Decision')], 'LEGACY')
                    if index < 3:
                        ok, _ = log_jbl_visit(farmer, officer='Synthetic', visit_date=timezone.localdate(),
                            visit_status='Visited, Awaiting Credit Analysis', expected_revision=farmer.workflow_revision,
                            request_id=f'synthetic-held-{register}-{index}')
                        self.assertFalse(ok)
        for status, count in (('', 8), ('deposit_pending', 6), ('awaiting_visit', 2)):
            response = self.client.get(reverse('portal_jbl_queue'), {'status': status}, **self.headers)
            self.assertEqual(response.status_code, 200, response.content)
            cards = response.json()['farmers']
            self.assertEqual(len(cards), count)
            if status:
                self.assertTrue(all(card['deposit']['deposit_hold'] == (status == 'deposit_pending') for card in cards))

    def test_existing_reviewed_case_continuation_preserves_facts_and_replays_once(self):
        from core.services.portal_publication import attempt_publication, queued_publication_operations

        _, sheet = self.imported('Master Data', [[72, 'SYNTHETIC PRIOR IMPORT', '712345678', '12345678',
            '2026-01-02', 'JBL To Schedule Visit', '4999.99', '9000']])
        row = LegacyRow.objects.select_related('farmer').get()
        # Reproduce the previous parser's committed, verified classification.
        row.farmer.workflow_state = 'legacy_review'
        row.farmer.save(update_fields=['workflow_state'])
        row.continuation_confirmed = False
        row.save(update_fields=['continuation_confirmed'])
        before = dict(row.farmer.__dict__)
        source_values = dict(row.values)
        self.group.workflow = {**self.group.workflow, 'master_sync_enabled': True}
        self.group.save(update_fields=['workflow'])
        key = str(uuid.uuid4())
        body = {'state': 'jbl_visit', 'revision': row.revision, 'request_id': key,
                'note': 'Reviewed explicit pre-visit evidence; preserve the recorded deposit hold.'}
        path = reverse('portal_legacy_confirm', kwargs={'row_id': row.pk})
        for _ in range(2):
            response = self.client.post(path, json.dumps(body), content_type='application/json',
                                        HTTP_X_REQUEST_ID=key, **self.headers)
            self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        farmer = row.farmer
        for field in farmer._meta.concrete_fields:
            if field.attname not in {'workflow_state', 'workflow_revision', 'updated_at'}:
                self.assertEqual(getattr(farmer, field.attname), before[field.attname], field.attname)
        self.assertEqual(farmer.workflow_state, 'jbl_visit')
        self.assertEqual(farmer.workflow_revision, before['workflow_revision']+1)
        self.assertEqual(farmer.deposit_paid_hbg, Decimal('4999.99'))
        self.assertEqual(row.values, source_values)
        self.assertEqual(row.events.filter(action='stage_confirmed').count(), 1)
        self.assertEqual(farmer.pipeline_events.filter(action='legacy_continuation_confirmed').count(), 1)
        operation = queued_publication_operations().get(source_id=str(farmer.pk))
        attempt_publication(operation)
        operation.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_SUCCEEDED, operation.last_error)
        physical_rows = [number for number, cells in sheet.cells.items() if str(farmer.pk) in cells]
        self.assertEqual(len(physical_rows), 1)
        self.assertNotEqual(physical_rows[0], farmer.source_row_number)
        cells = sheet.row_values(physical_rows[0])
        self.assertEqual(cells[sheet.cells[1].index('Current Pipeline State')], 'PENDING MINIMUM DEPOSIT')
        self.assertEqual(cells[sheet.cells[1].index('Credit Decision')], 'LEGACY')
        self.assertEqual(sum(str(farmer.pk) in cells for cells in sheet.cells.values()), 1)
