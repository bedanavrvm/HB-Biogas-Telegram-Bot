"""Retire obsolete authoring without deleting configuration that still exists."""
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from origination.models import OriginationProductDefinition


class AuthoringNavigationTests(TestCase):
    def test_old_product_editor_opens_current_workspace(self):
        actor = get_user_model().objects.create_superuser('synthetic-navigation', password='test-only')
        self.client.force_login(actor)
        definition = OriginationProductDefinition.objects.create(product_key='synthetic-navigation', name='Synthetic')
        response = self.client.get(reverse('admin:origination_originationproductdefinition_change', args=[definition.pk]))
        self.assertRedirects(response, reverse('admin:origination_origination_setup_workspace', args=[definition.pk]),
                             fetch_redirect_response=False)
        for model in ('OriginationProductDocumentAssignment', 'OriginationFieldReviewIssue'):
            with self.assertRaises(LookupError):
                apps.get_model('origination', model)


class LegacyAuthoringMigrationTests(TransactionTestCase):
    def test_guard_upgrade_and_rollback_preserve_application_bytes(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [('origination', '0011_phone_identity_pilot_capability')]
        executor.migrate(previous)
        old = executor.loader.project_state(previous).apps
        assignment_model = old.get_model('origination', 'OriginationProductDocumentAssignment')
        issue_model = old.get_model('origination', 'OriginationFieldReviewIssue')
        try:
            actor = old.get_model('auth', 'User').objects.create(username='synthetic-retirement')
            definition = old.get_model('origination', 'OriginationProductDefinition').objects.create(
                product_key='synthetic-retirement', name='Synthetic retirement')
            template = old.get_model('origination', 'OriginationDocumentTemplate').objects.create(
                document_type='synthetic-retirement', version=1, name='Synthetic retirement',
                source_byte_size=100, page_count=1, created_by=actor)
            application = old.get_model('origination', 'LoanOriginationApplication').objects.create(
                product_definition=definition, officer=actor, reference_number='ORG-SYNTHETIC-RETIRE',
                client_request_id='synthetic-retirement', form_payload={'retained': 'synthetic'},
            )
            package = old.get_model('origination', 'OriginationSigningPackage').objects.create(
                application=application, application_revision=1, external_reference='synthetic-retirement',
                frozen_unsigned_document=b'unchanged synthetic bytes', unsigned_document_hash='a' * 64)
            fixtures = [
                (assignment_model, {'product_definition': definition, 'template': template,
                                    'document_key': 'synthetic', 'name': 'Synthetic', 'created_by': actor}),
                (issue_model, {'product_definition': definition, 'legacy_key': 'synthetic',
                               'legacy_type': 'text', 'legacy_label': 'Synthetic'}),
            ]
            for model, values in fixtures:
                row = model.objects.create(**values)
                with self.assertRaisesRegex(RuntimeError, 'still contain records'):
                    MigrationExecutor(connection).migrate(latest)
                self.assertTrue(model.objects.filter(pk=row.pk).exists())
                row.delete()
            MigrationExecutor(connection).migrate(latest)
            self.assertNotIn(assignment_model._meta.db_table, connection.introspection.table_names())
            self.assertNotIn(issue_model._meta.db_table, connection.introspection.table_names())
            current = MigrationExecutor(connection).loader.project_state(latest).apps
            retained = current.get_model('origination', 'OriginationSigningPackage').objects.get(pk=package.pk)
            self.assertEqual(bytes(retained.frozen_unsigned_document), b'unchanged synthetic bytes')
            self.assertEqual(retained.unsigned_document_hash, 'a' * 64)
            self.assertEqual(current.get_model('origination', 'LoanOriginationApplication').objects.get(pk=application.pk).form_payload,
                             {'retained': 'synthetic'})
            merged_application = current.get_model('origination', 'LoanOriginationApplication').objects.get(pk=application.pk)
            self.assertEqual(merged_application.reference_number, 'ORG-SYNTHETIC-RETIRE')
            self.assertRegex(merged_application.display_reference, r'^ORG-[1-9][0-9]*$')
            self.assertTrue(current.get_model('origination', 'OriginationApplicationReferenceSequence').objects.filter(pk=1).exists())
            MigrationExecutor(connection).migrate(previous)
            self.assertEqual(assignment_model.objects.count(), 0)
            self.assertEqual(issue_model.objects.count(), 0)
        finally:
            tables = connection.introspection.table_names()
            for model in (assignment_model, issue_model):
                if model._meta.db_table in tables:
                    model.objects.all().delete()
            MigrationExecutor(connection).migrate(latest)
