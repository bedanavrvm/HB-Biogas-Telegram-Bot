"""Exercise ownership transfer against real migration states and physical tables."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OriginationOwnershipMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        loader = MigrationExecutor(connection).loader
        return loader.project_state([node for node in loader.applied_migrations if node in loader.graph.nodes]).apps

    def test_upgrade_and_rollback_preserve_records_bytes_permissions_and_tables(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        try:
            old = self.migrate([('core', '0198_physical_scan_replacement')])
            actor = old.get_model('auth', 'User').objects.create(username='synthetic-transfer-actor')
            definition = old.get_model('core', 'OriginationProductDefinition').objects.create(
                product_key='synthetic-transfer-product', name='Synthetic transfer product', version=1,
            )
            application = old.get_model('core', 'LoanOriginationApplication').objects.create(
                officer=actor, product_definition=definition, reference_number='ORG-SYNTHETIC-TRANSFER',
                client_request_id='synthetic-transfer-create', form_payload={'synthetic': True},
            )
            package = old.get_model('core', 'OriginationSigningPackage').objects.create(
                application=application, application_revision=1, document_type='synthetic',
                external_reference='synthetic-transfer-package', frozen_unsigned_document=b'synthetic-transfer-bytes',
                unsigned_document_hash='a' * 64, combined_document_hash='b' * 64,
                participants_snapshot=[{'role': 'officer'}],
            )
            types = old.get_model('contenttypes', 'ContentType').objects
            ctype, _ = types.get_or_create(app_label='core', model='loanoriginationapplication')
            permission, _ = old.get_model('auth', 'Permission').objects.get_or_create(
                content_type=ctype, codename='view_loanoriginationapplication', defaults={'name': 'View application'},
            )
            actor.user_permissions.add(permission)
            portal_grant = old.get_model('core', 'AccessGrant').objects.create(
                user=actor, workflow='jawabu_portal', role='IT',
            )
            tables = set(connection.introspection.table_names())

            adopted = self.migrate([('origination', '0003_independent_capabilities')])
            moved = adopted.get_model('origination', 'LoanOriginationApplication').objects.get(pk=application.pk)
            signed = adopted.get_model('origination', 'OriginationSigningPackage').objects.get(pk=package.pk)
            self.assertEqual(moved.form_payload, application.form_payload)
            self.assertIsNone(moved.group_configuration_id)
            self.assertEqual(bytes(signed.frozen_unsigned_document), bytes(package.frozen_unsigned_document))
            self.assertEqual(signed.unsigned_document_hash, package.unsigned_document_hash)
            self.assertEqual(signed.combined_document_hash, package.combined_document_hash)
            self.assertEqual(signed.participants_snapshot, package.participants_snapshot)
            self.assertEqual(types.filter(pk=ctype.pk).values_list('app_label', flat=True).get(), 'origination')
            self.assertEqual(actor.user_permissions.get(pk=permission.pk).content_type_id, ctype.pk)
            self.assertEqual(tables, set(connection.introspection.table_names()))
            self.assertTrue(adopted.get_model('core', 'AccessGrant').objects.filter(pk=portal_grant.pk).exists())
            self.assertFalse(adopted.get_model('core', 'AccessGrant').objects.filter(workflow='loan_origination').exists())

            restored = self.migrate([('core', '0198_physical_scan_replacement')])
            self.assertEqual(restored.get_model('core', 'LoanOriginationApplication').objects.get(pk=application.pk).form_payload,
                             application.form_payload)
            self.assertEqual(bytes(restored.get_model('core', 'OriginationSigningPackage').objects.get(pk=package.pk).frozen_unsigned_document),
                             bytes(package.frozen_unsigned_document))
            self.assertEqual(types.filter(pk=ctype.pk).values_list('app_label', flat=True).get(), 'core')
            self.assertEqual(actor.user_permissions.get(pk=permission.pk).content_type_id, ctype.pk)
        finally:
            # Leave the test database at the runtime model schema, even on failure.
            self.migrate(latest)
