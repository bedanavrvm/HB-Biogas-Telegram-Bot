from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    ComplaintCaseControl,
    ComplaintCaseEvent,
    ComplaintCaseImportBatch,
    ComplaintCaseImportItem,
    GroupSheetConfiguration,
    JawabuCustomer,
    JawabuFarmerMaster,
    JawabuFarmerUploadBatch,
    JawabuMediaAccessEvent,
    JawabuPipelineEvent,
    JawabuVisitRecord,
    OrderApprovalUpdate,
    MediaAttachment,
    SpinCreditRequest,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
)
from core.services.group_reset import group_data_counts, reset_group_data


User = get_user_model()


class GroupResetAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='group-reset-admin',
            email='group-reset@example.test',
            password='unused-test-password',
        )
        self.client.force_login(self.admin_user)

    def test_complaint_reset_page_exposes_only_complaint_configuration_scope(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100complaint-page',
            display_name='Complaint Page',
            workflow={'type': 'case'},
        )

        response = self.client.get(reverse(
            'admin:core_groupsheetconfiguration_reset_data',
            args=[config.pk],
        ), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'workflow-specific reset allowlist')
        self.assertContains(response, 'complaint_case_controls')
        self.assertNotContains(response, 'include_all_farmer_master')
        self.assertNotContains(response, 'include_order_records')
        self.assertNotContains(response, 'include_drive_upload_records')
        self.assertNotContains(response, 'all_farmer_master_records')
        self.assertNotContains(response, 'requisition_batches')
        self.assertNotContains(response, 'invoice_upload_batches')

    def test_forged_legacy_global_options_cannot_expand_complaint_reset(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100complaint-forged', workflow={'type': 'case'},
        )
        order = OrderApprovalUpdate.objects.create(
            group_id=config.group_id,
            sheet_id='sheet-order',
            id_number='12345678',
        )

        response = self.client.post(
            reverse('admin:core_groupsheetconfiguration_reset_data', args=[config.pk]),
            data={
                'confirm_reset': 'yes',
                'include_all_farmer_master': 'yes',
                'include_order_records': 'yes',
                'include_drive_upload_records': 'yes',
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(OrderApprovalUpdate.objects.filter(pk=order.pk).exists())

    def test_portal_admin_reset_requires_explicit_group_and_backup_confirmation(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100audited-admin', workflow={'type': 'jawabu_homebiogas'},
        )
        upload = JawabuFarmerUploadBatch.objects.create(
            group_id=config.group_id, source_filename='test.csv', parsed_rows=[],
        )
        farmer = JawabuFarmerMaster.objects.create(
            national_id='12345677', primary_phone='254700000003', status='active',
            raw_data={'upload_batch_id': str(upload.pk)},
        )
        attachment = MediaAttachment.objects.create(group_id=config.group_id, jawabu_farmer=farmer)
        JawabuMediaAccessEvent.objects.create(farmer=farmer, attachment=attachment)
        visit = JawabuVisitRecord.objects.create(group_id=config.group_id)

        response = self.client.post(
            reverse('admin:core_groupsheetconfiguration_reset_data', args=[config.pk]),
            data={'confirm_reset': 'yes', 'include_farmer_uploads': 'yes'}, secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter the exact group ID')
        self.assertTrue(JawabuVisitRecord.objects.filter(pk=visit.pk).exists())

    def test_portal_admin_confirmed_reset_clears_case_and_restores_live_mode(self):
        from core.models import PortalMaintenanceState

        config = GroupSheetConfiguration.objects.create(
            group_id='-100portal-confirmed', workflow={'type': 'jawabu_homebiogas'},
        )
        farmer = JawabuFarmerMaster.objects.create(group_configuration=config, national_id='12345671')
        url = reverse('admin:core_groupsheetconfiguration_reset_data', args=[config.pk])
        response = self.client.get(url, secure=True)
        self.assertContains(response, 'FarmUp intake through orders')
        response = self.client.post(url, data={
            'confirm_reset': 'yes', 'confirm_group': config.group_id,
            'confirm_number_reuse': 'yes', 'backup_reference': 'test-backup-snapshot',
        }, secure=True, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        self.assertEqual(PortalMaintenanceState.objects.get(singleton=1).mode, 'live')


class GroupResetSpinTests(TestCase):
    def test_farmer_reset_retains_access_audited_media_and_clears_other_rows(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100audited-media', workflow={'type': 'jawabu_homebiogas'},
        )
        farmer = JawabuFarmerMaster.objects.create(
            national_id='12345678', primary_phone='254700000001', status='active',
        )
        audited = MediaAttachment.objects.create(group_id=config.group_id, jawabu_farmer=farmer)
        ordinary = MediaAttachment.objects.create(group_id=config.group_id, jawabu_farmer=farmer)
        event = JawabuMediaAccessEvent.objects.create(farmer=farmer, attachment=audited)
        JawabuVisitRecord.objects.create(group_id=config.group_id)

        result = reset_group_data(config)

        self.assertEqual(result['retained_audited_media'], 1)
        self.assertEqual(result['deleted']['media_attachments'], 1)
        self.assertTrue(MediaAttachment.objects.filter(pk=audited.pk).exists())
        self.assertFalse(MediaAttachment.objects.filter(pk=ordinary.pk).exists())
        self.assertTrue(JawabuMediaAccessEvent.objects.filter(pk=event.pk).exists())
        self.assertEqual(result['after']['jawabu_records'], 0)

    def test_optional_farmer_purge_refuses_audited_farmer_without_partial_delete(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100audited-farmer', workflow={'type': 'jawabu_homebiogas'},
        )
        upload = JawabuFarmerUploadBatch.objects.create(
            group_id=config.group_id, source_filename='test.csv', parsed_rows=[],
        )
        farmer = JawabuFarmerMaster.objects.create(
            national_id='12345679', primary_phone='254700000002', status='active',
            raw_data={'upload_batch_id': str(upload.pk)},
        )
        attachment = MediaAttachment.objects.create(group_id=config.group_id, jawabu_farmer=farmer)
        JawabuMediaAccessEvent.objects.create(farmer=farmer, attachment=attachment)
        visit = JawabuVisitRecord.objects.create(group_id=config.group_id)

        with self.assertRaisesRegex(ValueError, 'audited media access'):
            reset_group_data(config, include_farmer_uploads=True)

        self.assertTrue(JawabuVisitRecord.objects.filter(pk=visit.pk).exists())
        self.assertTrue(JawabuFarmerUploadBatch.objects.filter(pk=upload.pk).exists())

    def test_reset_removes_protected_complaint_records_in_dependency_order(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100complaintreset', workflow={'type': 'case'},
        )
        raw = RawMessage.objects.create(telegram_message_id='reset-complaint-raw', content='complaint')
        processed = ProcessedMessage.objects.create(message_hash='reset-complaint-hash', raw_message=raw)
        case = ParsedMessage.objects.create(
            processed_message=processed, message_id='CMP-RESET-1', group_id='-100complaintreset',
            customer_name='Reset Customer', complaint_description='Reset test', complaint_status='Open',
        )
        control = ComplaintCaseControl.objects.create(parsed_message=case)
        ComplaintCaseEvent.objects.create(case=control, revision=1, action='created')
        batch = ComplaintCaseImportBatch.objects.create(
            group_id='-100complaintreset', source_telegram_message_id='reset-source',
            source_hash='reset-source-hash',
        )
        ComplaintCaseImportItem.objects.create(batch=batch, parsed_message=case, source_index=1)

        result = reset_group_data(config)

        self.assertEqual(result['after']['parsed_messages'], 0)
        self.assertEqual(result['after']['complaint_case_controls'], 0)
        self.assertEqual(result['after']['complaint_case_events'], 0)
        self.assertEqual(result['after']['complaint_import_batches'], 0)
        self.assertEqual(result['after']['complaint_import_items'], 0)
        self.assertFalse(ProcessedMessage.objects.filter(pk=processed.pk).exists())
        self.assertFalse(RawMessage.objects.filter(pk=raw.pk).exists())

    def test_farmer_reset_removes_only_rows_linked_to_this_configuration(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100jawabureset', workflow={'type': 'jawabu_homebiogas'},
        )
        upload = JawabuFarmerUploadBatch.objects.create(
            group_id='-100jawabureset',
            source_filename='application-review.csv',
            parsed_rows=[{
                'National ID': 'RESET-TEST-ID',
                'Application Action': 'create_additional_unit',
                '_review_required': True,
            }],
            review_needed=1,
        )
        customer = JawabuCustomer.objects.create(
            national_id='RESET-TEST-ID',
            primary_phone='254700000099',
        )
        farmer = JawabuFarmerMaster.objects.create(
            customer=customer,
            national_id='RESET-TEST-ID',
            primary_phone='254700000099',
            credit_decision='Deferred',
            status='active',
            raw_data={'upload_batch_id': str(upload.id)},
        )
        JawabuPipelineEvent.objects.create(
            farmer=farmer,
            action='deferred',
            actor='reset-test',
        )
        other_customer = JawabuCustomer.objects.create(
            national_id='KEEP-TEST-ID',
            primary_phone='254700000088',
        )
        other_farmer = JawabuFarmerMaster.objects.create(
            customer=other_customer,
            national_id='KEEP-TEST-ID',
            primary_phone='254700000088',
            credit_decision='Deferred',
            status='active',
        )

        result = reset_group_data(
            config,
            include_farmer_uploads=True,
        )

        self.assertEqual(result['after']['farmer_upload_batches'], 0)
        self.assertFalse(JawabuFarmerUploadBatch.objects.exists())
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=other_farmer.pk).exists())
        self.assertTrue(JawabuCustomer.objects.filter(pk=customer.pk).exists())
        self.assertTrue(JawabuCustomer.objects.filter(pk=other_customer.pk).exists())

    def test_reset_group_data_keeps_spin_legacy_batch_unless_requested(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100spinreset', workflow={'type': 'spin_credit_analysis'},
        )
        SpinCreditRequest.objects.create(
            group_id='-100spinreset',
            sheet_name='Spin',
            request_type='spin_crb',
            customer_name='LIVE REQUEST',
            source_message_hash='live-hash-1',
        )
        SpinCreditRequest.objects.create(
            group_id='-100spinreset',
            sheet_name='SPIN Legacy Batch',
            request_type='spin_crb',
            customer_name='LEGACY REQUEST',
            source_message_hash='legacy-hash-1',
        )

        counts = group_data_counts(config)
        self.assertEqual(counts['spin_requests'], 1)
        self.assertEqual(counts['spin_legacy_batch_requests'], 1)

        result = reset_group_data(config)

        self.assertEqual(result['deleted']['spin_requests'], 1)
        self.assertEqual(result['deleted']['spin_legacy_batch_requests'], 0)
        self.assertFalse(SpinCreditRequest.objects.filter(customer_name='LIVE REQUEST').exists())
        self.assertTrue(SpinCreditRequest.objects.filter(customer_name='LEGACY REQUEST').exists())

        result = reset_group_data(config, include_spin_legacy_batch=True)

        self.assertEqual(result['deleted']['spin_legacy_batch_requests'], 1)
        self.assertFalse(SpinCreditRequest.objects.filter(group_id='-100spinreset').exists())

    def test_reset_group_data_uses_configured_spin_legacy_batch_sheet_name(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100spinreset', workflow={'type': 'spin_credit_analysis'},
        )
        SpinCreditRequest.objects.create(
            group_id='-100spinreset',
            sheet_name='Spin',
            request_type='spin_crb',
            customer_name='LIVE REQUEST',
            source_message_hash='live-hash-2',
        )
        SpinCreditRequest.objects.create(
            group_id='-100spinreset',
            sheet_name='Custom Legacy Imports',
            request_type='spin_crb',
            customer_name='CUSTOM LEGACY REQUEST',
            source_message_hash='legacy-hash-2',
        )

        result = reset_group_data(
            config,
            include_spin_legacy_batch=True,
            spin_legacy_batch_sheet_name='Custom Legacy Imports',
        )

        self.assertEqual(result['deleted']['spin_requests'], 1)
        self.assertEqual(result['deleted']['spin_legacy_batch_requests'], 1)
        self.assertFalse(SpinCreditRequest.objects.filter(group_id='-100spinreset').exists())
