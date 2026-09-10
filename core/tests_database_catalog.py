from pathlib import Path

from django.apps import apps
from django.core.management import call_command
from django.test import SimpleTestCase

from core.services.database_catalog import database_catalog, table_comment


class DatabaseCatalogueTests(SimpleTestCase):
    def test_every_core_model_has_complete_catalogue_metadata(self):
        entries = database_catalog(include_usage=False)
        models = list(apps.get_app_config('core').get_models())

        self.assertEqual(len(entries), len(models))
        self.assertEqual(len({item['table'] for item in entries}), len(models))
        for item in entries:
            with self.subTest(table=item['table']):
                for key in (
                    'domain', 'table', 'django_model', 'application_area', 'purpose',
                    'classification', 'lifecycle', 'retention',
                ):
                    self.assertTrue(item[key])
                self.assertIsInstance(item['source_of_truth'], bool)
                self.assertIsInstance(item['direct_orm_writers'], list)
                self.assertIn('Domain:', table_comment(item))
                self.assertIn('Retention:', table_comment(item))

    def test_tat_case_relationships_and_usage_are_discoverable(self):
        entry = next(
            item for item in database_catalog(include_usage=True)
            if item['django_model'] == 'core.TatTrackerCase'
        )

        self.assertIn('core.Product', entry['parents'])
        self.assertIn('core.TatTrackerEvent', entry['children'])
        self.assertIn('core/services/tat_tracker.py', entry['used_by'])

    def test_candidates_reported_as_obsolete_are_documented_as_active(self):
        entries = {item['django_model']: item for item in database_catalog(include_usage=True)}

        self.assertEqual(entries['core.OriginationDocumentProductEligibility']['lifecycle'], 'active')
        self.assertIn(
            'core/services/origination_document_catalogue.py',
            entries['core.OriginationDocumentProductEligibility']['used_by'],
        )
        self.assertEqual(entries['core.FcaImportRecord']['lifecycle'], 'active')
        self.assertIn('core/services/fca.py', entries['core.FcaImportRecord']['used_by'])
        self.assertEqual(entries['core.MiniAppLegacyWriteDailyAggregate']['lifecycle'], 'compatibility')

    def test_generated_catalogue_is_current(self):
        output_dir = Path(__file__).resolve().parents[1] / 'docs' / 'database'
        call_command('generate_database_catalog', '--output-dir', str(output_dir), '--check')

    def test_duplicate_explicit_single_column_indexes_are_absent(self):
        duplicates = []
        for model in apps.get_app_config('core').get_models():
            fields = {field.name: field for field in model._meta.concrete_fields}
            for index in model._meta.indexes:
                if len(index.fields) != 1 or index.condition or index.expressions:
                    continue
                field = fields.get(index.fields[0].lstrip('-'))
                if field and field.db_index and not field.unique:
                    duplicates.append((model._meta.label, field.name, index.name))

        self.assertEqual(duplicates, [])
