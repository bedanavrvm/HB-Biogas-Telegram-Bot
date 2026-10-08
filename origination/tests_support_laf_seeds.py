"""Blank-template and synthetic-only supporting-seed verification."""
from dataclasses import replace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from core.tests_origination_templates import synthetic_pdf
from origination.models import OriginationDocumentTemplate
from origination.services.origination_main_laf_seeds import apply_seed, source_path, MainLafSeedError
from origination.services.origination_support_laf_seeds import DEFINITIONS
from origination.services.origination_value_contracts import validate_contract


class SupportingSourceContractTests(SimpleTestCase):
    def test_all_six_sources_have_dedicated_references_and_distinct_identity_keys(self):
        self.assertEqual(len(DEFINITIONS), 6)
        for definition in DEFINITIONS:
            self.assertEqual(definition.document_role, 'supporting')
            self.assertIsNone(definition.product_code)
            document = (Path(settings.BASE_DIR) / 'docs' / 'origination' /
                        (definition.key.replace('_', '-') + '-laf-seed.md')).read_text(encoding='utf-8')
            for token in [definition.filename, definition.sha256, definition.document_type,
                          *definition.required_signer_roles, *(field['key'] for field in definition.fields)]:
                self.assertIn('`' + token + '`', document)
            for field in definition.fields:
                validate_contract(field.get('value_contract'), source_type=field['source'])
                meaning = field.get('value_contract') or {}
                if meaning:
                    self.assertIn(meaning['subject'] + ' / ' + meaning['scope'], document)
                    if meaning.get('binding'):
                        self.assertIn('`' + meaning['binding'] + '`', document)
                for column in (field.get('structure') or {}).get('columns', []):
                    self.assertIn('`' + column['key'] + '`', document)
                    self.assertIn('`' + column['type'] + '`', document)
                for occurrence in field.get('occurrences', []):
                    self.assertGreaterEqual(occurrence['page'], 1)
                    self.assertLessEqual(occurrence['page'], definition.page_count)
            for signer in definition.signers:
                for slot in signer.get('slots', []):
                    self.assertIn('`' + slot['key'] + '`', document)
                    self.assertIn('`' + slot.get('type', 'signature') + '`', document)
                for key in (signer.get('identity_fields') or {}).values():
                    self.assertIn('`' + key + '`', document)
        transfer = next(d for d in DEFINITIONS if d.key == 'vehicle_transfer')
        self.assertTrue({'seller_national_id', 'proposed_owner_national_id'} <= {f['key'] for f in transfer.fields})

    def test_reviewed_aliases_resolve_without_relaxing_hash_checks(self):
        from origination.services.origination_main_laf_seeds import DEFINITIONS as MAIN, SOURCE_ALIASES
        with TemporaryDirectory() as folder:
            for definition in MAIN:
                if definition.key not in SOURCE_ALIASES:
                    continue
                path = Path(folder) / SOURCE_ALIASES[definition.key]
                path.touch()
                self.assertEqual(source_path(definition, folder), path)


@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
class SupportingSeedTests(TestCase):
    def test_changed_source_fails_before_any_write_or_upload(self):
        actor = get_user_model().objects.create_superuser('synthetic-source-admin', password='synthetic-only')
        with TemporaryDirectory() as folder:
            definition = replace(DEFINITIONS[0], filename='synthetic.pdf')
            (Path(folder) / definition.filename).write_bytes(synthetic_pdf())
            with patch('origination.services.origination_templates._upload_template_bytes') as upload:
                with self.assertRaises(MainLafSeedError):
                    apply_seed(definition, laf_root=folder, actor=actor, shared_values=True)
            upload.assert_not_called()
        self.assertFalse(OriginationDocumentTemplate.objects.exists())

    def test_draft_seed_is_idempotent_and_never_assigns_or_publishes(self):
        actor = get_user_model().objects.create_superuser('synthetic-support-admin', password='synthetic-only')
        with TemporaryDirectory() as folder:
            pdf = synthetic_pdf()
            definition = replace(DEFINITIONS[0], filename='synthetic.pdf', sha256=hashlib.sha256(pdf).hexdigest(), byte_size=len(pdf))
            (Path(folder) / definition.filename).write_bytes(pdf)
            with patch('origination.services.origination_templates._upload_template_bytes', return_value=('synthetic-drive', 'https://example.test/synthetic')) as upload:
                first = apply_seed(definition, laf_root=folder, actor=actor, shared_values=True)
                second = apply_seed(definition, laf_root=folder, actor=actor, shared_values=True)
            self.assertEqual(first['template'].pk, second['template'].pk)
            self.assertEqual(upload.call_count, 1)
            template = OriginationDocumentTemplate.objects.get(pk=first['template'].pk)
            self.assertEqual(template.status, 'ready')
            self.assertFalse(template.product_eligibilities.exists())
            self.assertIsNone(template.published_configuration_revision_id)
            self.assertEqual(template.form_schema['value_contract_version'], 2)
            self.assertEqual(template.document_role, 'supporting')
