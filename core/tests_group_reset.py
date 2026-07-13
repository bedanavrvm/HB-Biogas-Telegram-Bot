from django.test import TestCase

from core.models import SpinCreditRequest
from core.services.group_reset import group_data_counts, reset_group_data


class GroupResetSpinTests(TestCase):
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