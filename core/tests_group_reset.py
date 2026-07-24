from django.test import TestCase

from core.models import (
    JawabuCustomer,
    JawabuFarmerMaster,
    JawabuFarmerUploadBatch,
    JawabuPipelineEvent,
    SpinCreditRequest,
)
from core.services.group_reset import group_data_counts, reset_group_data


class GroupResetSpinTests(TestCase):
    def test_clear_all_farmer_master_works_without_upload_batch_option(self):
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

        result = reset_group_data(
            '-100jawabureset',
            include_all_farmer_master=True,
            include_farmer_uploads=False,
        )

        self.assertEqual(result['after']['all_farmer_master_records'], 0)
        self.assertEqual(result['after']['all_jawabu_customers'], 0)
        self.assertEqual(result['after']['all_jawabu_pipeline_events'], 0)
        self.assertEqual(result['after']['farmer_upload_batches'], 0)
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        self.assertFalse(JawabuFarmerUploadBatch.objects.exists())

    def test_reset_group_data_keeps_spin_legacy_batch_unless_requested(self):
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

        counts = group_data_counts('-100spinreset')
        self.assertEqual(counts['spin_requests'], 1)
        self.assertEqual(counts['spin_legacy_batch_requests'], 1)

        result = reset_group_data('-100spinreset')

        self.assertEqual(result['deleted']['spin_requests'], 1)
        self.assertEqual(result['deleted']['spin_legacy_batch_requests'], 0)
        self.assertFalse(SpinCreditRequest.objects.filter(customer_name='LIVE REQUEST').exists())
        self.assertTrue(SpinCreditRequest.objects.filter(customer_name='LEGACY REQUEST').exists())

        result = reset_group_data('-100spinreset', include_spin_legacy_batch=True)

        self.assertEqual(result['deleted']['spin_legacy_batch_requests'], 1)
        self.assertFalse(SpinCreditRequest.objects.filter(group_id='-100spinreset').exists())

    def test_reset_group_data_uses_configured_spin_legacy_batch_sheet_name(self):
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
            '-100spinreset',
            include_spin_legacy_batch=True,
            spin_legacy_batch_sheet_name='Custom Legacy Imports',
        )

        self.assertEqual(result['deleted']['spin_requests'], 1)
        self.assertEqual(result['deleted']['spin_legacy_batch_requests'], 1)
        self.assertFalse(SpinCreditRequest.objects.filter(group_id='-100spinreset').exists())
