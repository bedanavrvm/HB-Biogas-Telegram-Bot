from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    GroupSheetConfiguration, JawabuFarmerMaster, JawabuFarmerUploadBatch,
    JawabuMediaAccessEvent, MediaAttachment, PortalMaintenanceState,
    RequisitionBatch, DocumentPhysicalSignoff, PaymentDocument,
)
from core.services.portal_full_reset import (
    PortalResetError, _delete_verified_sheet_rows, portal_reset_manifest,
    reset_portal_configuration,
)
from hb_operations.models import HomeBiogasAction, HomeBiogasActionEvent
from payments.models import (
    PaymentBatch, PaymentBatchCase, PaymentBatchEvent, PaymentCaseReview,
    PaymentSequenceEvent, PaymentSequenceState,
)
from requisitions.models import OrderSequenceState


class PortalFullResetTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(
            username='portal-reset-it', email='reset-it@example.test', password='unused',
        )
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100portal-reset', workflow={'type': 'jawabu_homebiogas'},
        )
        PortalMaintenanceState.objects.create(singleton=1, mode='maintenance', reason='Reset test')

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows', return_value=0)
    def test_global_empty_reset_restarts_staff_reference_numbers(self, _sheet_delete):
        first = JawabuFarmerMaster.objects.create(group_configuration=self.group, national_id='12345678')
        result = reset_portal_configuration(self.group, actor=self.actor, backup_reference='reference-reset-test')
        self.assertTrue(result['case_references_restarted'])
        replacement = JawabuFarmerMaster.objects.create(group_configuration=self.group, national_id='87654321')
        self.assertEqual(replacement.case_reference_number, 1)
        self.assertNotEqual(replacement.pk, first.pk)

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows', return_value=0)
    def test_clears_owned_case_and_operational_links_but_keeps_access_audit(self, _sheet_delete):
        upload = JawabuFarmerUploadBatch.objects.create(
            group_id=self.group.group_id, source_filename='source.csv', parsed_rows=[],
        )
        farmer = JawabuFarmerMaster.objects.create(
            group_configuration=self.group, national_id='12345678',
            raw_data={'upload_batch_id': str(upload.pk)},
        )
        attachment = MediaAttachment.objects.create(group_id=self.group.group_id, jawabu_farmer=farmer)
        event = JawabuMediaAccessEvent.objects.create(farmer=farmer, attachment=attachment)
        other_group = GroupSheetConfiguration.objects.create(
            group_id='-100other-portal', workflow={'type': 'jawabu_homebiogas'},
        )
        other_farmer = JawabuFarmerMaster.objects.create(group_configuration=other_group, national_id='87654321')
        order = RequisitionBatch.objects.create(group_configuration=self.group, order_number='HB-104')
        order_sequence = OrderSequenceState.objects.create(group_configuration=self.group, partner='HB', next_number=105)
        payment_sequence = PaymentSequenceState.objects.create(group_configuration=self.group, next_number=23)

        result = reset_portal_configuration(self.group, actor=self.actor, backup_reference='test-backup-1')

        self.assertEqual(result['cases_deleted'], 1)
        self.assertFalse(result['case_references_restarted'])
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        self.assertFalse(MediaAttachment.objects.filter(pk=attachment.pk).exists())
        self.assertFalse(JawabuFarmerUploadBatch.objects.filter(pk=upload.pk).exists())
        self.assertFalse(RequisitionBatch.objects.filter(pk=order.pk).exists())
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=other_farmer.pk).exists())
        event.refresh_from_db()
        self.assertIsNone(event.farmer_id)
        self.assertIsNone(event.attachment_id)
        self.assertEqual(event.farmer_id_snapshot, str(farmer.pk))
        self.assertEqual(event.attachment_id_snapshot, str(attachment.pk))
        order_sequence.refresh_from_db()
        payment_sequence.refresh_from_db()
        self.assertEqual(order_sequence.next_number, 105)
        self.assertEqual(payment_sequence.next_number, 23)
        self.assertEqual(portal_reset_manifest(self.group)['counts']['cases'], 0)

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows')
    def test_sheet_error_leaves_database_intact(self, delete_rows):
        delete_rows.side_effect = RuntimeError('Sheet unavailable')
        farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group, national_id='12345677')
        with self.assertRaisesRegex(RuntimeError, 'Sheet unavailable'):
            reset_portal_configuration(self.group, actor=self.actor, backup_reference='test-backup-1')
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())

    def test_sheet_delete_targets_only_immutable_case_ids(self):
        farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group, national_id='12345676')
        self.group.workflow = {
            'type': 'jawabu_homebiogas', 'master_sheet_id': 'test-sheet',
            'master_header_row': 1, 'master_data_start_row': 2,
            'master_sheet_name': 'Master Data', 'eco_conserve_sheet_name': 'Eco-conserve',
        }
        self.group.save(update_fields=['workflow'])

        class Sheet:
            def __init__(self, rows):
                self.rows = rows
            def get_all_values(self):
                return [list(row) for row in self.rows]
            def row_values(self, number):
                return list(self.rows[number - 1])
            def delete_rows(self, number):
                del self.rows[number - 1]

        owned = ['Master Record ID', 'Customer Name']
        master = Sheet([owned, [str(farmer.pk), 'Owned'], ['other-case', 'Other']])
        eco = Sheet([owned, ['manual-entry', 'Manual']])

        class Service:
            def __init__(self, sheet):
                self._sheet = sheet
            def is_available(self):
                return True

        def service_for(*, sheet_id, sheet_name):
            self.assertEqual(sheet_id, 'test-sheet')
            return Service(master if sheet_name == 'Master Data' else eco)

        with patch('core.services.sheets.GoogleSheetsService.get_instance', side_effect=service_for):
            deleted = _delete_verified_sheet_rows(self.group, [farmer.pk])
        self.assertEqual(deleted, 1)
        self.assertEqual(master.rows[1], ['other-case', 'Other'])
        self.assertEqual(eco.rows[1], ['manual-entry', 'Manual'])

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows', return_value=0)
    def test_numbering_uses_initial_it_adjustment_baseline(self, _sheet_delete):
        sequence = PaymentSequenceState.objects.create(group_configuration=self.group, next_number=54)
        PaymentSequenceEvent.objects.create(
            sequence=sequence, action='adjusted', number_before=1,
            number_after=50, revision_after=2, reason='Initial IT setting',
        )
        reset_portal_configuration(self.group, actor=self.actor, backup_reference='test-backup-3')
        sequence.refresh_from_db()
        self.assertEqual(sequence.next_number, 50)

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows')
    def test_cross_group_payment_membership_blocks_before_sheet_deletion(self, delete_rows):
        other_group = GroupSheetConfiguration.objects.create(
            group_id='-100other-payment', workflow={'type': 'jawabu_homebiogas'},
        )
        other_case = JawabuFarmerMaster.objects.create(group_configuration=other_group, national_id='87654320')
        batch = PaymentBatch.objects.create(group_configuration=self.group)
        PaymentBatchCase.objects.create(
            batch=batch, farmer=other_case, payment_mode='CASH', case_digest='d' * 64,
        )
        with self.assertRaisesRegex(PortalResetError, 'another group'):
            reset_portal_configuration(self.group, actor=self.actor, backup_reference='test-backup-4')
        delete_rows.assert_not_called()
        self.assertTrue(PaymentBatch.objects.filter(pk=batch.pk).exists())

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows')
    def test_ambiguous_legacy_owner_blocks_selected_group_reset(self, delete_rows):
        GroupSheetConfiguration.objects.create(
            group_id='-100another-portal', workflow={'type': 'jawabu_homebiogas'},
        )
        legacy = JawabuFarmerMaster.objects.create(national_id='12345674')
        with self.assertRaisesRegex(PortalResetError, 'no group owner'):
            reset_portal_configuration(self.group, actor=self.actor, backup_reference='test-backup-5')
        delete_rows.assert_not_called()
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=legacy.pk).exists())

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows', return_value=0)
    def test_blank_order_number_does_not_capture_unrelated_payment_document(self, _sheet_delete):
        RequisitionBatch.objects.create(group_configuration=self.group, order_number='')
        unrelated = PaymentDocument.objects.create(order_number='', farmer_ids=[])
        reset_portal_configuration(self.group, actor=self.actor, backup_reference='test-backup-6')
        self.assertTrue(PaymentDocument.objects.filter(pk=unrelated.pk).exists())

    @patch('core.services.portal_full_reset._delete_verified_sheet_rows', return_value=0)
    def test_clears_signed_order_hb_action_and_reviewed_payment(self, _sheet_delete):
        farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group, national_id='12345675')
        order = RequisitionBatch.objects.create(group_configuration=self.group, order_number='HB-31')
        signoff = DocumentPhysicalSignoff.objects.create(
            document_type='requisition', requisition_batch=order,
            source_filename='order.xlsx', source_content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            source_checksum='a' * 64, scan_filename='signed.pdf', scan_content_type='application/pdf',
            scan_checksum='b' * 64, uploaded_by=self.actor, status='signed_approved',
        )
        action = HomeBiogasAction.objects.create(
            farmer=farmer, source_requisition_batch=order, source_signoff=signoff,
            source_order_number='HB-31', source_requisition_version=1,
        )
        HomeBiogasActionEvent.objects.create(action=action, event_type='released', revision=1)
        sequence = PaymentSequenceState.objects.create(group_configuration=self.group, next_number=13)
        batch = PaymentBatch.objects.create(group_configuration=self.group, payment_number=12)
        member = PaymentBatchCase.objects.create(
            batch=batch, farmer=farmer, payment_mode='LOAN-JAWABU', case_digest='c' * 64,
        )
        PaymentCaseReview.objects.create(membership=member)
        PaymentBatchEvent.objects.create(batch=batch, action='created', revision=1)
        PaymentSequenceEvent.objects.create(
            sequence=sequence, batch=batch, action='allocated', number_before=12,
            number_after=13, revision_after=2, reason='Test allocation',
        )

        reset_portal_configuration(self.group, actor=self.actor, backup_reference='test-backup-2')

        self.assertFalse(HomeBiogasAction.objects.filter(pk=action.pk).exists())
        self.assertFalse(DocumentPhysicalSignoff.objects.filter(pk=signoff.pk).exists())
        self.assertFalse(PaymentBatch.objects.filter(pk=batch.pk).exists())
        sequence.refresh_from_db()
        self.assertEqual(sequence.next_number, 12)
