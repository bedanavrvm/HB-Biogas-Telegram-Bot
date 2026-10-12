"""Upgrade and reverse only synthetic legacy evidence; never convert its policy."""
from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class SigningPlanMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_legacy_bytes_sessions_and_policy_survive_upgrade_and_reverse(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old_target = [('origination', '0006_originationdatafield_value_contract')]
        try:
            old = self.migrate(old_target)
            actor = old.get_model('auth', 'User').objects.create(username='synthetic-migration-signer')
            product = old.get_model('origination', 'OriginationProductDefinition').objects.create(
                product_key='synthetic-legacy-upgrade', name='Synthetic retained product')
            application = old.get_model('origination', 'LoanOriginationApplication').objects.create(
                reference_number='ORG-SYNTHETIC-UPGRADE', product_definition=product, officer=actor,
                approval_roles_snapshot=['branch_manager'], signer_rules_snapshot=[{'role': 'borrower'}])
            package = old.get_model('origination', 'OriginationSigningPackage').objects.create(
                application=application, application_revision=1, document_type='synthetic',
                external_reference='synthetic-upgrade', frozen_unsigned_document=b'synthetic legacy bytes',
                unsigned_document_hash='a' * 64, consent_policy_snapshot={'approval_roles': ['branch_manager']},
                participants_snapshot=[{'role': 'borrower'}])
            session = old.get_model('origination', 'OriginationSignerSession').objects.create(
                package=package, signer_role='borrower', token_hash='b' * 64,
                token_expires_at=timezone.now() + timedelta(hours=1), created_by=actor)
            new = self.migrate(latest)
            upgraded = new.get_model('origination', 'LoanOriginationApplication').objects.get(pk=application.pk)
            self.assertEqual(upgraded.signing_policy_snapshot, 'legacy')
            self.assertEqual(upgraded.signing_plan, {})
            self.assertEqual(upgraded.approval_roles_snapshot, ['branch_manager'])
            self.assertFalse(new.get_model('origination', 'OriginationSigningParticipant').objects.exists())
            self.assertIsNone(new.get_model('origination', 'OriginationSignerSession').objects.get(pk=session.pk).participant_id)
            restored = self.migrate(old_target)
            retained = restored.get_model('origination', 'OriginationSigningPackage').objects.get(pk=package.pk)
            self.assertEqual(bytes(retained.frozen_unsigned_document), b'synthetic legacy bytes')
            self.assertEqual(retained.consent_policy_snapshot, package.consent_policy_snapshot)
            self.assertEqual(restored.get_model('origination', 'OriginationSignerSession').objects.get(pk=session.pk).token_hash, 'b' * 64)
        finally:
            self.migrate(latest)
