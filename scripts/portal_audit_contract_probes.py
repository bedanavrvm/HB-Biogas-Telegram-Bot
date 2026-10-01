"""Read-only acceptance probes for the 2026-10-01 Portal repairs."""
from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from core.models import JawabuFarmerMaster
from hb_operations.models import HomeBiogasAction
from hb_operations.services import HomeBiogasActionError, _validate_commissioning, _validate_installation
from payments.services import case_payment_digest


class PortalAuditContractProbes(SimpleTestCase):
    def test_revision_only_change_preserves_payment_digest(self):
        farmer = JawabuFarmerMaster(customer_name='Synthetic audit customer', workflow_revision=1)
        original = case_payment_digest(farmer, 'CASH')
        farmer.workflow_revision = 2
        self.assertEqual(original, case_payment_digest(farmer, 'CASH'))

    def test_early_ack_rejects_commissioning_before_installation(self):
        today = timezone.localdate()
        action = HomeBiogasAction(
            installation_status=HomeBiogasAction.INSTALLATION_INSTALLED,
            installation_date=today - timedelta(days=10),
            commissioning_status=HomeBiogasAction.COMMISSIONING_NOT_COMMISSIONED,
        )
        with self.assertRaisesMessage(HomeBiogasActionError, 'cannot be before'):
            _validate_commissioning(action, {
                'commissioning_date': (today - timedelta(days=11)).isoformat(),
                'early_commissioning_acknowledged': True,
            })

    def test_installation_correction_is_locked_after_commissioning(self):
        today = timezone.localdate()
        action = HomeBiogasAction(
            installation_status=HomeBiogasAction.INSTALLATION_INSTALLED,
            installation_date=today - timedelta(days=30),
            commissioning_status=HomeBiogasAction.COMMISSIONING_COMMISSIONED,
            commissioning_date=today - timedelta(days=2),
        )
        with self.assertRaisesMessage(HomeBiogasActionError, 'read-only after commissioning'):
            _validate_installation(action, {
                'installation_status': HomeBiogasAction.INSTALLATION_INSTALLED,
                'installation_date': (today - timedelta(days=1)).isoformat(),
            }, correction=True)
