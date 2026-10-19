"""Synthetic deposit, scope, import and first-visit policy regressions."""
from datetime import date
from decimal import Decimal
import json
from unittest.mock import patch
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase, override_settings

from core.models import AccessGrant, GroupSheetConfiguration, JawabuFarmerMaster
from core.services.telegram_identity import user_access
from core.services.jawabu_pipeline import (
    complete_jbl_visit, farmer_to_card, jbl_visit_queue, log_jbl_visit, preflight_jbl_visit_completion,
)
from .deposits import (
    DepositError, deposit_queryset, deposit_state, hb_owns_deposit, parse_deposit,
    scoped_deposits, serialize_deposit, update_deposit,
)


class DepositAmountTests(SimpleTestCase):
    def test_boundary_amounts(self):
        for value, held in [(None, True), ('0', True), ('4999.99', True), ('5000', False), ('5000.01', False)]:
            with self.subTest(value=value):
                farmer = JawabuFarmerMaster(deposit_paid_hbg=Decimal(value) if value is not None else None)
                self.assertEqual(deposit_state(farmer)['deposit_hold'], held)

    def test_invalid_numbers(self):
        for value in ['', None, '-1', 'NaN', 'Infinity', '1.001', '5.000', '5e3', '10000000000', 'not money', '\u0665\u0660\u0660\u0660']:
            with self.subTest(value=value), self.assertRaises(DepositError):
                parse_deposit(value)

    def test_legacy_sql_cast_guard_is_ascii_only(self):
        # PostgreSQL numeric input must never receive arbitrary Unicode text
        # just because a locale-sensitive digit character class matched it.
        query = deposit_queryset(JawabuFarmerMaster.objects.all()).values('_deposit_total').query
        _, params = query.sql_with_params()
        self.assertIn(r'^0*[0-9]{1,10}(\.[0-9]{1,2})?$', params)


class DepositWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(username='deposit-superuser', is_superuser=True)
        cls.group = GroupSheetConfiguration.objects.create(group_id='synthetic-deposits', sheet_id='synthetic', enabled=True, workflow={'type': 'jawabu_homebiogas'})

    def setUp(self):
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Synthetic Deposit Applicant', national_id='99999981', primary_phone='254700000081',
            secondary_phone='254700000082', county='KIAMBU', sub_county='Limuru',
            group_configuration=self.group, workflow_state='jbl_visit',
            sign_date='01-10-2026', hbg_visit_date=date(2026, 10, 1), hb_sales_person='Synthetic HB',
            source='jawabu_farmup_review', actual_receipts='2000.00', deposit_paid_hbg=Decimal('2000'),
        )

    def save(self, amount='5000', **kwargs):
        return update_deposit(self.farmer, amount=amount, reason=kwargs.pop('reason', ''),
                              expected_revision=kwargs.pop('revision', 1), request_id=kwargs.pop('key', 'deposit-save'),
                              actor=kwargs.pop('actor', self.actor), **kwargs)

    def grant(self, role='HB_STAFF', **scope):
        user = get_user_model().objects.create_user(username=f'deposit-{role}-{get_user_model().objects.count()}')
        AccessGrant.objects.create(user=user, workflow='jawabu_portal', role=role, active=True, **scope)
        return user

    def test_save_updates_canonical_alias_audit_and_reserves_publication(self):
        with patch('core.services.portal_publication.reserve_farmer_publication') as reserve:
            farmer = self.save()
        self.assertEqual(farmer.deposit_paid_hbg, Decimal('5000'))
        self.assertEqual(farmer.actual_receipts, '5000.00')
        self.assertEqual(farmer.actual_receipts_currency, 'KES')
        self.assertEqual(farmer.workflow_revision, 2)
        self.assertTrue(hb_owns_deposit(farmer))
        self.assertFalse(deposit_state(farmer)['deposit_hold'])
        event = farmer.pipeline_events.get(action='hb_deposit_updated')
        self.assertEqual(event.old_values['deposit_paid_hbg'], '2000.00')
        self.assertEqual(event.new_values['deposit_paid_hbg'], '5000.00')
        self.assertEqual(event.actor_user, self.actor)
        reserve.assert_called_once()
        self.assertFalse(hasattr(farmer, 'homebiogas_action'))

    def test_canonicalization_cannot_restore_old_total(self):
        from core.services.jawabu_validation import canonicalize_farmer
        farmer = self.save()
        canonicalize_farmer(farmer)
        self.assertEqual(farmer.deposit_paid_hbg, Decimal('5000'))

    def test_retry_returns_original_success_after_new_changes_and_visit(self):
        self.save()
        self.save('6000', revision=2, key='later')
        self.farmer.jbl_visit_date = date(2026, 10, 2)
        self.farmer.save(update_fields=['jbl_visit_date'])
        result = self.save()
        self.assertEqual(result.deposit_paid_hbg, Decimal('6000'))
        self.assertEqual(result.pipeline_events.filter(action='hb_deposit_updated').count(), 2)

    def test_reused_key_changed_payload_fails(self):
        self.save()
        with self.assertRaises(DepositError) as raised:
            self.save('6000')
        self.assertEqual(raised.exception.code, 'idempotency_conflict')

    def test_stale_revision_and_missing_key_fail(self):
        self.save()
        for values, code in [({'revision': 1, 'key': 'stale'}, 'workflow_revision_conflict'), ({'key': ''}, 'request_key_required')]:
            with self.subTest(code=code), self.assertRaises(DepositError) as raised:
                self.save('6000', **values)
            self.assertEqual(raised.exception.code, code)

    def test_decrease_requires_reason_and_reapplies_hold(self):
        self.save()
        with self.assertRaises(DepositError):
            self.save('4000', revision=2, key='reduce')
        result = self.save('4000', revision=2, key='reduce', reason='Corrected duplicate recorded amount')
        self.assertTrue(deposit_state(result)['deposit_hold'])
        self.assertEqual(result.pipeline_events.get(request_id='reduce').reason, 'Corrected duplicate recorded amount')

    def test_visited_case_is_read_only(self):
        self.farmer.jbl_visit_date = date(2026, 10, 2)
        self.farmer.save(update_fields=['jbl_visit_date'])
        with self.assertRaises(DepositError) as raised:
            self.save()
        self.assertEqual(raised.exception.code, 'deposit_locked')
        self.assertFalse(serialize_deposit(self.farmer, actor=self.actor, access=None)['can_edit'])

    def test_operations_can_view_but_not_edit(self):
        actor = self.grant('OPERATIONS_ADMIN', group_configuration=self.group)
        access = user_access(actor, 'jawabu_portal')
        self.assertTrue(scoped_deposits(actor, access).filter(pk=self.farmer.pk).exists())
        self.assertFalse(serialize_deposit(self.farmer, actor=actor, access=access)['can_edit'])
        with self.assertRaises(PermissionDenied):
            self.save(actor=actor, access=access)

    def test_hb_edit_and_wrong_scope_denial(self):
        actor = self.grant(group_configuration=self.group)
        self.save(actor=actor, access=user_access(actor, 'jawabu_portal'))
        wrong = self.grant(branch='OTHER')
        self.assertFalse(scoped_deposits(wrong, user_access(wrong, 'jawabu_portal')).exists())
        with self.assertRaises(PermissionDenied):
            self.save('6000', actor=wrong, revision=2, key='wrong')

    def test_other_workflow_hb_grant_does_not_authorize(self):
        user = get_user_model().objects.create_user(username='complaint-hb-only')
        AccessGrant.objects.create(user=user, workflow='complaint_cases', role='HB_STAFF', active=True)
        with self.assertRaises(PermissionDenied):
            self.save(actor=user)

    def test_scoped_it_override_does_not_borrow_another_grants_scope(self):
        actor = self.grant('IT', branch='OTHER')
        AccessGrant.objects.create(user=actor, workflow='jawabu_portal', role='OPERATIONS_ADMIN', group_configuration=self.group, active=True)
        with self.assertRaises(PermissionDenied):
            self.save(actor=actor)

    def test_other_group_and_product_are_denied(self):
        other = GroupSheetConfiguration.objects.create(group_id='synthetic-other-deposit-group', sheet_id='synthetic')
        for values in [{'group_configuration': other}, {'product': 'OTHER'}]:
            actor = self.grant(**values)
            self.assertFalse(scoped_deposits(actor, user_access(actor, 'jawabu_portal')).exists())
            with self.assertRaises(PermissionDenied):
                self.save(actor=actor)

    def test_cleared_unowned_import_may_update_total(self):
        from core.services.jawabu_master import upsert_farmer
        cleaned = dict(source='jawabu_farmup_review', source_fingerprint='synthetic-unowned-import', national_id=self.farmer.national_id,
                       primary_phone=self.farmer.primary_phone, customer_name=self.farmer.customer_name,
                       actual_receipts='5000', sign_date='01-10-2026')
        with patch('core.services.jawabu_identity.resolve_application_identity', return_value=(None, 1, self.farmer)):
            upsert_farmer(cleaned)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.deposit_paid_hbg, Decimal('5000'))
        self.assertFalse(hb_owns_deposit(self.farmer))

    def test_deposit_request_key_is_not_a_successful_visit_replay(self):
        self.save()
        ok, _ = log_jbl_visit(self.farmer, officer='Synthetic', visit_date=date(2026, 10, 2), visit_status='Rescheduled', request_id='deposit-save', expected_revision=2)
        self.assertFalse(ok)
        self.farmer.refresh_from_db()
        self.assertIsNone(self.farmer.jbl_visit_date)

    def test_visit_commit_rechecks_concurrent_reduction(self):
        farmer = self.save()
        with patch('core.services.location_catalog.validate_location_selection', return_value=(None, None, None)):
            self.assertTrue(preflight_jbl_visit_completion(farmer, visit_date=date(2026, 10, 2), visit_status='Rescheduled', village='Synthetic', expected_revision=2)[0])
        self.save('4000', revision=2, key='reduction', reason='Corrected recorded total')
        ok, _ = log_jbl_visit(farmer, officer='Synthetic', visit_date=date(2026, 10, 2), visit_status='Rescheduled', expected_revision=3)
        self.assertFalse(ok)

    def test_downstream_records_without_a_legacy_visit_date_are_not_editable(self):
        self.farmer.workflow_state = 'credit'
        self.farmer.save(update_fields=['workflow_state'])
        with self.assertRaises(DepositError) as raised:
            self.save()
        self.assertEqual(raised.exception.code, 'deposit_locked')

    def test_held_case_is_in_queue_and_card(self):
        self.assertIn(self.farmer.pk, jbl_visit_queue().values_list('pk', flat=True))
        self.assertTrue(farmer_to_card(self.farmer, include_detail_metadata=False)['deposit']['deposit_hold'])

    def test_held_office_lead_without_hbg_visit_is_in_queue(self):
        self.farmer.source, self.farmer.sign_date, self.farmer.hbg_visit_date = 'jawabu_office_lead', '', None
        self.farmer.save()
        self.assertIn(self.farmer.pk, jbl_visit_queue().values_list('pk', flat=True))

    def test_both_transition_boundaries_reject_held_case(self):
        kwargs = {'visit_date': date(2026, 10, 2), 'visit_status': 'Rescheduled', 'expected_revision': 1, 'request_id': 'held-visit'}
        self.assertFalse(preflight_jbl_visit_completion(self.farmer, **kwargs)[0])
        self.assertFalse(log_jbl_visit(self.farmer, officer='Synthetic', **kwargs)[0])
        self.farmer.refresh_from_db()
        self.assertIsNone(self.farmer.jbl_visit_date)

    def test_no_document_processing_or_upload_for_held_case(self):
        with patch('core.services.jbl_visit_documents.prepare_visit_documents') as prepare:
            ok, _, result = complete_jbl_visit(self.farmer, categorized_files={}, visit_date=date(2026, 10, 2), officer='Synthetic', visit_status='Rescheduled', request_id='held')
        self.assertFalse(ok)
        self.assertEqual(result['code'], 'deposit_required')
        prepare.assert_not_called()

    def test_cleared_case_passes_preflight(self):
        farmer = self.save()
        with patch('core.services.location_catalog.validate_location_selection', return_value=(None, None, None)):
            self.assertTrue(preflight_jbl_visit_completion(farmer, visit_date=date(2026, 10, 2), visit_status='Rescheduled', village='Synthetic', expected_revision=2)[0])

    def test_import_cannot_overwrite_hb_total_and_discrepancy_is_idempotent(self):
        from core.services.jawabu_master import upsert_farmer
        self.save()
        cleaned = dict(source='jawabu_farmup_review', national_id=self.farmer.national_id,
                       source_fingerprint='synthetic-deposit-import',
                       primary_phone=self.farmer.primary_phone, customer_name=self.farmer.customer_name,
                       actual_receipts='1000', deposit_paid_hbg=Decimal('1000'), sign_date='01-10-2026')
        with patch('core.services.jawabu_identity.resolve_application_identity', return_value=(None, 1, self.farmer)):
            upsert_farmer(dict(cleaned))
            upsert_farmer(dict(cleaned))
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.deposit_paid_hbg, Decimal('5000'))
        self.assertEqual(self.farmer.actual_receipts, '5000.00')
        self.assertEqual(self.farmer.pipeline_events.filter(action='hb_deposit_import_observed').count(), 1)

    def test_blank_deposit_is_not_a_farmup_intake_error(self):
        from core.services.jawabu_master import farmup_review_validation_notes
        cleaned = dict(national_id='99999981', primary_phone='254700000081', secondary_phone='254700000082', county='KIAMBU', sign_date='01-10-2026', hb_sales_person='Synthetic', actual_receipts='')
        self.assertEqual(farmup_review_validation_notes({}, cleaned), [])
        cleaned['county'] = ''
        self.assertIn('Missing County', farmup_review_validation_notes({}, cleaned))
        cleaned['county'] = 'KIAMBU'
        self.assertTrue(farmup_review_validation_notes({'Deposit Paid to HB': 'not money'}, cleaned))

    def test_blank_deposit_clean_intake_commits_as_active_financial_hold(self):
        from core.services.jawabu_master import clean_farmer_row, upsert_farmer
        raw = {'name': 'Synthetic Blank Deposit', 'id': '99999983', 'phone': '254700000083',
               'secondary': '254700000084', 'county': 'KIAMBU', 'HBG Visit Date': '01-10-2026', 'sales': 'Synthetic HB', 'deposit': ''}
        mapping = {'customer_name': 'name', 'national_id': 'id', 'primary_phone': 'phone', 'secondary_phone': 'secondary',
                   'county': 'county', 'sign_date': 'HBG Visit Date', 'hb_sales_person': 'sales', 'actual_receipts': 'deposit'}
        cleaned = clean_farmer_row(raw, mapping)
        self.assertEqual(cleaned['status'], 'active', cleaned['cleaning_notes'])
        _, _, farmer = upsert_farmer(cleaned, return_instance=True)
        self.assertEqual(farmer.status, 'active')
        self.assertTrue(deposit_state(farmer)['deposit_hold'])

    def test_permission_seed_is_idempotent_and_preserves_explicit_denial(self):
        from importlib import import_module
        from django.apps import apps
        from core.models import WorkflowRoleCapability, WorkflowRoleCapabilityAuditEvent
        migration = import_module('core.migrations.0208_hb_deposit_capabilities')
        WorkflowRoleCapability.objects.filter(workflow='jawabu_portal', role='HB_STAFF', capability_key='portal.hb_deposit.write').update(effect='deny', enabled=False)
        migration.seed(apps, None)
        count = WorkflowRoleCapabilityAuditEvent.objects.count()
        migration.seed(apps, None)
        self.assertEqual(WorkflowRoleCapabilityAuditEvent.objects.count(), count)
        self.assertEqual(WorkflowRoleCapability.objects.get(workflow='jawabu_portal', role='HB_STAFF', capability_key='portal.hb_deposit.write').effect, 'deny')

    def test_server_fragment_disables_held_case_without_phone_link(self):
        from django.template.loader import render_to_string
        fragment = render_to_string('portal/partials/farmer_card.html', {'farmer': farmer_to_card(self.farmer, include_detail_metadata=False), 'queue_key': 'jbl'})
        self.assertIn('aria-disabled="true"', fragment)
        self.assertIn('deposit-held-card', fragment)
        self.assertIn('3000.00', fragment)
        self.assertNotIn('href="tel:', fragment)

    def test_legacy_reconciliation_is_dry_run_by_default_and_auditable_reversible(self):
        from django.core.management import call_command
        from io import StringIO
        self.farmer.status, self.farmer.cleaning_notes = 'review_needed', 'Missing Deposit Paid to HB'
        self.farmer.save()
        out = StringIO()
        call_command('reconcile_hb_deposit_holds', configuration=self.group.pk, stdout=out)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.status, 'review_needed')
        self.assertIn('changed=0', out.getvalue())
        call_command('reconcile_hb_deposit_holds', configuration=self.group.pk, actor=self.actor.pk, apply=True, stdout=StringIO())
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.status, 'active')
        event = self.farmer.pipeline_events.get(action='hb_deposit_review_reconciled')
        call_command('reconcile_hb_deposit_holds', configuration=self.group.pk, actor=self.actor.pk, apply=True, undo_event=str(event.pk), stdout=StringIO())
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.status, 'review_needed')

    def test_legacy_reconciliation_preserves_other_review_blockers(self):
        from hb_operations.management.commands.reconcile_hb_deposit_holds import eligible
        self.farmer.status = 'review_needed'
        self.farmer.cleaning_notes = 'Missing Deposit Paid to HB; Missing County'
        self.assertFalse(eligible(self.farmer))
        self.farmer.cleaning_notes = 'Missing Deposit Paid to HB'
        self.farmer.primary_phone = ''
        self.assertFalse(eligible(self.farmer))

    def test_general_case_correction_cannot_bypass_hb_editor(self):
        from core.services.portal_case_corrections import correct_case_fields, correction_payload
        self.assertNotIn('deposit_paid_hbg', [item['key'] for item in correction_payload(self.farmer)['fields']])
        with self.assertRaisesMessage(ValueError, 'HB Actions > Deposits'):
            correct_case_fields(self.farmer, values={'deposit_paid_hbg': '5000'}, expected_revision=1, request_id='bypass', reason='Attempt', actor=self.actor)

    def test_sql_projection_matches_amount_boundaries(self):
        for value in [None, Decimal('0'), Decimal('4999.99'), Decimal('5000')]:
            self.farmer.deposit_paid_hbg, self.farmer.actual_receipts = value, ''
            self.farmer.save()
            row = deposit_queryset(JawabuFarmerMaster.objects.filter(pk=self.farmer.pk)).get()
            self.assertEqual(row._deposit_total, value)

    def request(self, method='get', user=None, **payload):
        actor = user or self.actor
        request = getattr(RequestFactory(), method)('/api/portal/hb-deposits/', data=json.dumps(payload) if method == 'post' else {}, content_type='application/json')
        request.META['HTTP_IDEMPOTENCY_KEY'] = payload.get('client_request_id', 'api-deposit')
        request.portal_user, request.portal_access = actor, user_access(actor, 'jawabu_portal')
        request.portal_request_id = payload.get('client_request_id', 'api-deposit')
        return request

    def test_list_and_detail_scoped_api(self):
        from .deposit_views import hb_deposit_list, hb_deposit_detail
        response = hb_deposit_list.__wrapped__(self.request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['counts']['awaiting'], 1)
        wrong = self.grant(branch='OTHER')
        response = hb_deposit_detail.__wrapped__(self.request(user=wrong), self.farmer.pk)
        self.assertEqual(response.status_code, 404)

    def test_update_api_and_operations_denial(self):
        from .deposit_views import hb_deposit_update
        view = hb_deposit_update.__wrapped__.__wrapped__
        response = view(self.request('post', amount='5000', expected_revision=1), self.farmer.pk)
        self.assertEqual(response.status_code, 200, response.content)
        actor = self.grant('OPERATIONS_ADMIN')
        response = view(self.request('post', user=actor, amount='6000', expected_revision=2), self.farmer.pk)
        self.assertEqual(response.status_code, 403)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True)
    def test_unauthenticated_api_denied(self):
        response = self.client.get('/api/portal/hb-deposits/')
        self.assertEqual(response.status_code, 403)


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks; SQLite is not concurrency evidence.')
class DepositConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='synthetic-pg-deposit', is_superuser=True)
        self.farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic concurrency applicant', workflow_state='jbl_visit', deposit_paid_hbg=Decimal('5000'), actual_receipts='5000')

    def race(self, left, right):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)
        def run(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                action()
                return 'saved'
            except ValueError:
                return 'conflict'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, [left, right]))

    def change(self, amount, key):
        return update_deposit(self.farmer, amount=amount, reason='Synthetic correction', expected_revision=1, request_id=key, actor=self.actor)

    def test_two_deposit_edits_only_one_revision_wins(self):
        self.assertCountEqual(self.race(lambda: self.change('6000', 'a'), lambda: self.change('7000', 'b')), ['saved', 'conflict'])
        self.assertEqual(self.farmer.pipeline_events.filter(action='hb_deposit_updated').count(), 1)

    def test_visit_and_deposit_reduction_cannot_both_commit(self):
        def visit():
            ok, message = log_jbl_visit(self.farmer, visit_date=date(2026, 10, 1), officer='Synthetic', visit_status='Rescheduled', village='Synthetic', expected_revision=1, request_id='visit')
            if not ok:
                raise ValueError(message)
        with patch('core.services.location_catalog.validate_location_selection', return_value=(None, None, None)):
            self.assertCountEqual(self.race(lambda: self.change('4000', 'reduce'), visit), ['saved', 'conflict'])
        self.farmer.refresh_from_db()
        self.assertFalse(self.farmer.jbl_visit_date and self.farmer.deposit_paid_hbg < Decimal('5000'))
