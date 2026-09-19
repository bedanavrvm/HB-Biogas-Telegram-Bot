import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    AccessGrant,
    DocumentPhysicalSignoff,
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    RequisitionBatch,
)
from core.services.telegram_identity import user_access

from .models import HomeBiogasAction, HomeBiogasActionEvent
from .services import HomeBiogasActionError, correct_action, release_requisition_signoff, scoped_actions, transition_action


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
        self.assertEqual(action.installation_status, 'needs_planning')
        self.assertEqual(action.source_order_number, '1201')
        self.assertEqual(action.events.filter(event_type='order.released_to_hb').count(), 1)

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
        self.assertTrue(HomeBiogasAction.objects.filter(farmer=self.farmer).exists())

    def test_scheduled_requires_date_and_pending_context(self):
        action = self.release()
        with self.assertRaisesMessage(HomeBiogasActionError, 'scheduled installation date'):
            transition_action(
                action.pk, actor=self.user, request_id='schedule-1', expected_revision=1,
                payload={'installation_status': 'scheduled', 'readiness_status': 'ready'},
            )
        updated, _operations, replayed = transition_action(
            action.pk, actor=self.user, request_id='schedule-2', expected_revision=1,
            payload={
                'installation_status': 'scheduled', 'readiness_status': 'ready',
                'installation_date': '2026-09-25',
            },
        )
        self.assertFalse(replayed)
        self.assertEqual(updated.installation_date, date(2026, 9, 25))
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.installation_status, 'Scheduled')

    def test_installed_record_keeps_serial_optional_and_commissioning_contextual(self):
        action = self.release()
        updated, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='installed-1', expected_revision=1,
            payload={
                'installation_status': 'installed', 'installation_date': '2026-09-19',
                'installation_report_status': 'yes', 'commissioning_status': 'pending',
                'pending_commissioning_comment': 'Customer training booked.',
            },
        )
        self.assertEqual(updated.serial_number, '')
        self.assertEqual(updated.commissioning_status, 'pending')

    def test_completed_milestone_correction_requires_reason_and_is_audited(self):
        action = self.release()
        action, _operations, _replayed = transition_action(
            action.pk, actor=self.user, request_id='installed-2', expected_revision=1,
            payload={
                'installation_status': 'installed', 'installation_date': '2026-09-18',
                'installation_report_status': 'yes', 'commissioning_status': 'done',
                'commissioning_date': '2026-09-18',
            },
        )
        with self.assertRaisesMessage(HomeBiogasActionError, 'Give a reason'):
            correct_action(
                action.pk, actor=self.user, request_id='correct-1', expected_revision=2,
                payload={'installation_date': '2026-09-19'},
            )
        corrected, _operations, _replayed = correct_action(
            action.pk, actor=self.user, request_id='correct-2', expected_revision=2,
            payload={'installation_date': '2026-09-19', 'reason': 'Corrected from installation report.'},
        )
        self.assertEqual(corrected.installation_date, date(2026, 9, 19))
        event = HomeBiogasActionEvent.objects.get(request_id='correct-2')
        self.assertEqual(event.reason, 'Corrected from installation report.')


@override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
class HomeBiogasActionApiTests(HomeBiogasActionServiceTests):
    def test_list_detail_and_mobile_screen_routes(self):
        action = self.release()
        listing = self.client.get(reverse('portal_hb_action_list'))
        detail = self.client.get(reverse('portal_hb_action_api_detail', kwargs={'farmer_id': self.farmer.pk}))
        screen = self.client.get(reverse('portal_hb_action_detail', kwargs={'farmer_id': self.farmer.pk}))

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()['items'][0]['case_reference'].startswith('JBL-'), True)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['action']['id'], str(action.pk))
        self.assertContains(screen, 'id="hb-action-form"')

    def test_api_transition_rejects_incomplete_installed_state(self):
        self.release()
        response = self.client.post(
            reverse('portal_hb_action_transition', kwargs={'farmer_id': self.farmer.pk}),
            data=json.dumps({'revision': 1, 'installation_status': 'installed'}),
            content_type='application/json', HTTP_X_REQUEST_ID='hb-api-transition-1',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('actual installation date', response.json()['error'])
