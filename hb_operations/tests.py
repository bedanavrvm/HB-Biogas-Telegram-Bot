import json
from importlib import import_module
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.apps import apps as django_apps
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AccessGrant,
    DocumentPhysicalSignoff,
    GroupSheetConfiguration,
    InvoiceUploadBatch,
    JawabuFarmerMaster,
    ParsedInvoice,
    RequisitionBatch,
)
from core.services.telegram_identity import user_access
from core.services.jawabu_pipeline import _pipeline_stage, current_pipeline_state_label

from .models import HomeBiogasAction, HomeBiogasActionEvent
from .services import HomeBiogasActionError, correct_action, release_requisition_signoff, scoped_actions, serialize_action, transition_action


class HomeBiogasActionServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='hb-staff')
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100-hb-action', display_name='HB action', enabled=True,
            sheet_id='test-sheet', workflow={'type': 'jawabu_homebiogas'},
        )
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Install Customer', national_id='12345678',
            primary_phone='254700000001', branch='Ruiru', payment_product='Standard',
            workflow_revision=1,
        )
        self.batch = RequisitionBatch.objects.create(
            group_configuration=self.group, order_number='1201', version=1,
            farmer_ids=[str(self.farmer.pk)], farmer_count=1,
            filename='order-1201.xlsx', file_content=b'workbook',
        )
        self.signoff = DocumentPhysicalSignoff.objects.create(
            document_type='requisition', requisition_batch=self.batch,
            source_version=1, source_filename='order-1201.xlsx',
            source_content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            source_checksum='a' * 64, source_file_content=b'workbook',
            scan_filename='signed.pdf', scan_content_type='application/pdf',
            scan_size=4, scan_checksum='b' * 64, scan_file_content=b'scan',
            status=DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
            attested_complete=True, uploaded_by=self.user, approved_by=self.user,
        )

    def release(self):
        release_requisition_signoff(self.signoff, actor=self.user)
        return HomeBiogasAction.objects.get(farmer=self.farmer)

    def test_accepted_signed_order_releases_each_case_once(self):
        first = release_requisition_signoff(self.signoff, actor=self.user)
        second = release_requisition_signoff(self.signoff, actor=self.user)

        self.assertEqual(first['created'], 1)
        self.assertEqual(second['existing'], 1)
        self.assertEqual(HomeBiogasAction.objects.count(), 1)
        action = HomeBiogasAction.objects.get()
        self.assertEqual(action.installation_status, 'open')
        self.assertEqual(action.commissioning_status, 'not_commissioned')
        self.assertEqual(action.source_order_number, '1201')
        self.assertEqual(action.events.filter(event_type='order.released_to_hb').count(), 1)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.installation_status, 'Open')
        self.assertEqual(self.farmer.workflow_revision, 2)

    def test_simplification_migration_preserves_planned_dates_and_completed_commissioning(self):
        action = self.release()
        planned = timezone.localdate() + timedelta(days=3)
        action.installation_status = 'scheduled'
        action.installation_date = planned
        action.commissioning_status = 'done'
        action.save(update_fields=['installation_status', 'installation_date', 'commissioning_status'])

        migration = import_module('hb_operations.migrations.0002_simplify_fulfilment_states')
        migration.simplify_existing_actions(django_apps, None)

        action.refresh_from_db()
        self.assertEqual(action.installation_status, 'open')
        self.assertEqual(action.planned_installation_date, planned)
        self.assertIsNone(action.installation_date)
        self.assertEqual(action.commissioning_status, 'commissioned')

    def test_release_locks_signoff_without_joining_nullable_document_sources(self):
        with CaptureQueriesContext(connection) as captured:
            release_requisition_signoff(self.signoff, actor=self.user)

        signoff_queries = [
            query['sql'] for query in captured.captured_queries
            if 'core_documentphysicalsignoff' in query['sql'].casefold()
            and 'WHERE' in query['sql'].upper()
        ]
        self.assertTrue(signoff_queries)
        self.assertNotIn(' JOIN ', signoff_queries[0].upper())

    def test_hb_queue_respects_the_complete_grant_scope(self):
        self.release()
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='HB_STAFF',
            branch='Ruiru', group_configuration=self.group,
        )
        access = user_access(self.user, 'jawabu_portal')
        self.assertEqual(scoped_actions(self.user, access).count(), 1)

        self.farmer.branch = 'Nyeri'
        self.farmer.system_branch = 'Nyeri'
        self.farmer.save(update_fields=['branch', 'system_branch', 'updated_at'])
        self.assertEqual(scoped_actions(self.user, access).count(), 0)

    def test_unaccepted_scan_never_releases_work(self):
        self.signoff.status = DocumentPhysicalSignoff.STATUS_UPLOAD_FAILED
        self.signoff.save(update_fields=['status'])
        with self.assertRaisesMessage(HomeBiogasActionError, 'has not been accepted'):
            release_requisition_signoff(self.signoff, actor=self.user)
        self.assertFalse(HomeBiogasAction.objects.exists())

    def test_scan_for_superseded_order_version_never_releases_work(self):
        self.batch.version = 2
        self.batch.save(update_fields=['version'])
        with self.assertRaisesMessage(HomeBiogasActionError, 'current requisition version'):
            release_requisition_signoff(self.signoff, actor=self.user)
        self.assertFalse(HomeBiogasAction.objects.exists())

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_drive_acceptance_hook_releases_new_order(self, storage_class):
        storage_class.return_value.upload.return_value = ('drive-file', 'https://drive.example/signed')
        self.signoff.status = DocumentPhysicalSignoff.STATUS_UPLOAD_PENDING
        self.signoff.approved_by = None
        self.signoff.approved_at = None
        self.signoff.save(update_fields=['status', 'approved_by', 'approved_at'])

        from core.services.document_signoffs import _upload_to_drive
        accepted = _upload_to_drive(self.signoff, actor=self.user)

        self.assertEqual(accepted.status, DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED)
        self.assertNotEqual(accepted.source_checksum, accepted.scan_checksum)
        self.assertTrue(HomeBiogasAction.objects.filter(farmer=self.farmer).exists())

    def test_open_installation_keeps_readiness_and_an_optional_planned_date_as_details(self):
        action = self.release()
        with self.assertRaisesMessage(HomeBiogasActionError, 'known readiness blocker'):
            transition_action(
                action.pk, actor=self.user, request_id='open-1', expected_revision=1,
                payload={'workstream': 'installation', 'installation_status': 'open', 'readiness_status': 'not_ready'},
            )
        updated, _operations, replayed = transition_action(
            action.pk, actor=self.user, request_id='open-2', expected_revision=1,
            payload={
                'workstream': 'installation',
                'installation_status': 'open', 'readiness_status': 'ready',
                'planned_installation_date': '2026-09-25',
            },
        )
        self.assertFalse(replayed)
        self.assertEqual(updated.planned_installation_date, date(2026, 9, 25))
        self.assertIsNone(updated.installation_date)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.installation_status, 'Open')

    def test_legacy_closed_installation_is_preserved_but_cannot_be_changed(self):
        action = self.release()
        action.installation_status = HomeBiogasAction.INSTALLATION_CLOSED
        action.save(update_fields=['installation_status', 'updated_at'])

        with self.assertRaisesMessage(HomeBiogasActionError, 'legacy closed installation record is read-only'):
            transition_action(
                action.pk, actor=self.user, request_id='legacy-closed-1', expected_revision=1,
                payload={'workstream': 'installation', 'installation_status': 'open'},
            )

    def test_installed_record_enters_automatic_commissioning_wait_without_extra_input(self):
        action = self.release()
        installed_on = timezone.localdate()
        updated, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='installed-1', expected_revision=1,
            payload={
                'workstream': 'installation', 'installation_status': 'installed',
                'installation_date': installed_on.isoformat(), 'installation_report_status': 'yes',
            },
        )
        self.assertEqual(updated.serial_number, '')
        self.assertEqual(updated.commissioning_status, 'not_commissioned')

    def test_delivery_pipeline_stages_follow_signed_order_installation_and_commissioning(self):
        action = self.release()
        self.assertEqual(current_pipeline_state_label(self.farmer), 'Installation in Progress')
        self.assertEqual(_pipeline_stage(self.farmer), 6)

        # Invoice and payment activity are parallel financial controls. They
        # must not replace the HomeBiogas delivery stage.
        self.farmer.invoice_number = 'HB-INV-100'
        self.farmer.save(update_fields=['invoice_number', 'updated_at'])
        self.assertEqual(current_pipeline_state_label(self.farmer), 'Installation in Progress')
        self.assertEqual(_pipeline_stage(self.farmer), 6)

        installed_on = timezone.localdate() - timedelta(days=21)
        action, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='delivery-stage-installed', expected_revision=1,
            payload={
                'workstream': 'installation', 'installation_status': 'installed',
                'installation_date': installed_on.isoformat(), 'installation_report_status': 'yes',
            },
        )
        self.assertEqual(current_pipeline_state_label(self.farmer), 'Installed — Awaiting Commissioning')
        self.assertEqual(_pipeline_stage(self.farmer), 7)

        transition_action(
            action.pk, actor=self.user, request_id='delivery-stage-commissioned', expected_revision=2,
            payload={
                'workstream': 'commissioning', 'commissioning_status': 'commissioned',
                'commissioning_date': timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(current_pipeline_state_label(self.farmer), 'Commissioned')
        self.assertEqual(_pipeline_stage(self.farmer), 8)

    def test_completed_milestone_correction_requires_reason_and_is_audited(self):
        action = self.release()
        installed_on = timezone.localdate() - timedelta(days=30)
        action, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='installed-2', expected_revision=1,
            payload={
                'workstream': 'installation', 'installation_status': 'installed',
                'installation_date': installed_on.isoformat(), 'installation_report_status': 'yes',
            },
        )
        action, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='commissioned-2', expected_revision=2,
            payload={
                'workstream': 'commissioning', 'commissioning_status': 'commissioned',
                'commissioning_date': (installed_on + timedelta(days=21)).isoformat(),
            },
        )
        with self.assertRaisesMessage(HomeBiogasActionError, 'Give a reason'):
            correct_action(
                action.pk, actor=self.user, request_id='correct-1', expected_revision=3,
                payload={'workstream': 'installation', 'installation_date': (installed_on - timedelta(days=1)).isoformat()},
            )
        corrected, _operations, _replayed = correct_action(
            action.pk, actor=self.user, request_id='correct-2', expected_revision=3,
            payload={
                'workstream': 'installation', 'installation_date': (installed_on - timedelta(days=1)).isoformat(),
                'reason': 'Corrected from installation report.',
            },
        )
        self.assertEqual(corrected.installation_date, installed_on - timedelta(days=1))
        event = HomeBiogasActionEvent.objects.get(request_id='correct-2')
        self.assertEqual(event.reason, 'Corrected from installation report.')

    def test_early_commissioning_requires_explicit_acknowledgement(self):
        action = self.release()
        installed_on = timezone.localdate() - timedelta(days=10)
        action, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='install-early', expected_revision=1,
            payload={
                'workstream': 'installation', 'installation_status': 'installed',
                'installation_date': installed_on.isoformat(), 'installation_report_status': 'yes',
            },
        )
        with self.assertRaisesMessage(HomeBiogasActionError, 'before the standard commissioning readiness date'):
            transition_action(
                action.pk, actor=self.user, request_id='commission-early-rejected', expected_revision=2,
                payload={
                    'workstream': 'commissioning', 'commissioning_status': 'commissioned',
                    'commissioning_date': timezone.localdate().isoformat(),
                },
            )
        completed, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='commission-early-accepted', expected_revision=2,
            payload={
                'workstream': 'commissioning', 'commissioning_status': 'commissioned',
                'commissioning_date': timezone.localdate().isoformat(),
                'early_commissioning_acknowledged': True,
            },
        )
        self.assertEqual(completed.commissioning_status, 'commissioned')
        event = HomeBiogasActionEvent.objects.get(request_id='commission-early-accepted')
        self.assertTrue(event.new_values['early_commissioning_acknowledged'])


@override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
class HomeBiogasActionApiTests(HomeBiogasActionServiceTests):
    def test_list_detail_and_mobile_screen_routes(self):
        action = self.release()
        listing = self.client.get(reverse('portal_hb_action_list'))
        detail = self.client.get(reverse('portal_hb_action_api_detail', kwargs={'farmer_id': self.farmer.pk}))
        screen = self.client.get(reverse('portal_hb_action_detail', kwargs={'farmer_id': self.farmer.pk}))
        commissioning_screen = self.client.get(
            reverse('portal_hb_action_detail', kwargs={'farmer_id': self.farmer.pk}),
            {'workstream': 'commissioning'},
        )
        list_screen = self.client.get(reverse('portal_hb_actions_screen'))

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()['items'][0]['case_reference'].startswith('JBL-'), True)
        self.assertEqual(set(listing.json()['filters']), {'readiness'})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['action']['id'], str(action.pk))
        self.assertContains(screen, 'id="hb-action-form"')
        self.assertContains(screen, 'id="hb-installation-status"')
        self.assertNotContains(screen, 'id="hb-commissioning-date"')
        self.assertContains(commissioning_screen, 'id="hb-commissioning-date"')
        self.assertNotContains(commissioning_screen, 'id="hb-installation-status"')
        self.assertContains(list_screen, 'id="hb-filter-readiness"')
        self.assertNotContains(list_screen, 'All authorized branches')
        self.assertNotContains(list_screen, 'Installation report<select')

    def test_installed_case_deep_link_renders_commissioning_form_by_default(self):
        action = self.release()
        action.installation_status = HomeBiogasAction.INSTALLATION_INSTALLED
        action.installation_date = timezone.localdate()
        action.installation_report_status = HomeBiogasAction.REPORT_YES
        action.save(update_fields=['installation_status', 'installation_date', 'installation_report_status', 'updated_at'])

        screen = self.client.get(reverse('portal_hb_action_detail', kwargs={'farmer_id': self.farmer.pk}))

        self.assertContains(screen, 'id="hb-commissioning-date"')
        self.assertNotContains(screen, 'id="hb-installation-status"')

    def test_api_transition_rejects_incomplete_installed_state(self):
        self.release()
        response = self.client.post(
            reverse('portal_hb_action_transition', kwargs={'farmer_id': self.farmer.pk}),
            data=json.dumps({'revision': 1, 'workstream': 'installation', 'installation_status': 'installed'}),
            content_type='application/json', HTTP_X_REQUEST_ID='hb-api-transition-1',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('actual installation date', response.json()['error'])

    def test_api_transition_uses_verified_miniapp_auth_not_a_cookie_csrf_token(self):
        self.release()
        csrf_enforcing_client = Client(enforce_csrf_checks=True)

        response = csrf_enforcing_client.post(
            reverse('portal_hb_action_transition', kwargs={'farmer_id': self.farmer.pk}),
            data=json.dumps({'revision': 1, 'workstream': 'installation', 'installation_status': 'installed'}),
            content_type='application/json', HTTP_X_REQUEST_ID='hb-api-transition-csrf-contract',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('actual installation date', response.json()['error'])

    def test_installation_list_hides_legacy_closed_records_and_only_counts_active_states(self):
        action = self.release()
        action.installation_status = HomeBiogasAction.INSTALLATION_CLOSED
        action.save(update_fields=['installation_status', 'updated_at'])

        listing = self.client.get(reverse('portal_hb_action_list'))
        detail = self.client.get(reverse('portal_hb_action_api_detail', kwargs={'farmer_id': self.farmer.pk}))

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()['items'], [])
        self.assertEqual(set(listing.json()['counts']), {'open', 'installed'})
        self.assertEqual(detail.json()['action']['installation_status_label'], 'Legacy closed')

    def test_commissioning_queue_derives_waiting_due_and_delayed_from_installation_date(self):
        action = self.release()
        action.installation_status = HomeBiogasAction.INSTALLATION_INSTALLED
        action.installation_date = timezone.localdate()
        action.installation_report_status = HomeBiogasAction.REPORT_YES
        action.save(update_fields=['installation_status', 'installation_date', 'installation_report_status', 'updated_at'])

        waiting = self.client.get(reverse('portal_hb_action_list'), {'queue': 'commissioning'})
        self.assertEqual(waiting.status_code, 200)
        self.assertEqual(waiting.json()['counts']['not_commissioned'], 1)
        self.assertEqual(waiting.json()['items'][0]['commissioning_state'], 'waiting')
        self.assertEqual(waiting.json()['items'][0]['days_until_ready'], 21)

        action.installation_date = timezone.localdate() - timedelta(days=22)
        action.save(update_fields=['installation_date', 'updated_at'])
        delayed = self.client.get(reverse('portal_hb_action_list'), {
            'queue': 'commissioning', 'state': 'delayed',
        })
        self.assertEqual(delayed.json()['counts']['not_commissioned'], 1)
        self.assertEqual(delayed.json()['counts']['delayed'], 1)
        self.assertEqual(delayed.json()['items'][0]['commissioning_overdue_days'], 1)

    def test_invoice_card_is_preview_for_hb_and_record_for_operations(self):
        action = self.release()
        batch = InvoiceUploadBatch.objects.create(
            original_filename='invoice.pdf', drive_file_id='drive-invoice',
            drive_url='https://drive.example/invoice', status='matched',
        )
        ParsedInvoice.objects.create(
            batch=batch, invoice_no='INV-20', status='matched', matched_farmer=self.farmer,
        )
        from hb_operations.views import _invoice_presentation

        request = RequestFactory().get('/')
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='HB_STAFF',
            branch='Ruiru', group_configuration=self.group,
        )
        request.portal_user = self.user
        request.portal_access = user_access(self.user, 'jawabu_portal')
        hb_invoice = _invoice_presentation(request, action, serialize_action(action))['invoice']
        self.assertEqual(hb_invoice['mode'], 'preview')
        self.assertEqual(hb_invoice['label'], 'Invoice sent')

        operations = get_user_model().objects.create_user(username='operations')
        AccessGrant.objects.create(
            user=operations, workflow='jawabu_portal', role='OPERATIONS_ADMIN',
            branch='Ruiru', group_configuration=self.group,
        )
        request.portal_user = operations
        request.portal_access = user_access(operations, 'jawabu_portal')
        operations_invoice = _invoice_presentation(request, action, serialize_action(action))['invoice']
        self.assertEqual(operations_invoice['mode'], 'record')
        self.assertEqual(operations_invoice['label'], 'Invoice received')
