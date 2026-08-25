"""Contract checks keeping reviewed LAF documentation aligned with seed code."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from core.services.generic_jawabu_laf_seed import (
    EVIDENCE_REQUIREMENTS,
    EXTERNAL_LOANS_STRUCTURE,
    FIELD_SPECS as GENERIC_FIELD_SPECS,
    PLEDGED_ASSETS_STRUCTURE,
    SECTIONS as GENERIC_SECTIONS,
    SIGNER_RULES as GENERIC_SIGNER_RULES,
)
from core.services.invoice_finance_origination_seed import (
    FIELD_SPECS as INVOICE_FIELD_SPECS,
    SECTIONS as INVOICE_SECTIONS,
    SIGNER_RULES as INVOICE_SIGNER_RULES,
)
from core.services.origination_commercial_terms import (
    FIELD_SPECS as COMMERCIAL_FIELD_SPECS,
    LOAN_FEES_STRUCTURE,
)


class LafSeedDocumentationContractTests(SimpleTestCase):
    maxDiff = None

    def _document(self, name):
        path = Path(settings.BASE_DIR) / 'docs' / 'origination' / name
        self.assertTrue(path.is_file(), f'Missing dedicated LAF reference: {path}')
        return path.read_text(encoding='utf-8')

    def _assert_token(self, document, token, *, contract):
        self.assertIn(f'`{token}`', document, f'{contract} `{token}` is undocumented')

    def _assert_seed_contract(self, document, *, sections, fields, signers, contract):
        for key, _label, _help_text in sections:
            self._assert_token(document, key, contract=f'{contract} section')
        for field in fields:
            self._assert_token(document, field['key'], contract=f'{contract} field')
            self._assert_token(document, field['type'], contract=f'{contract} field type')
            for option in field.get('options') or []:
                self._assert_token(
                    document,
                    option['code'],
                    contract=f"{contract} choice for {field['key']}",
                )
        for signer in signers:
            self._assert_token(document, signer['role'], contract=f'{contract} signer role')
            for identity_key in (signer.get('identity_fields') or {}).values():
                self._assert_token(
                    document,
                    identity_key,
                    contract=f"{contract} identity mapping for {signer['role']}",
                )
            for slot in signer.get('slots') or []:
                self._assert_token(document, slot['key'], contract=f'{contract} signer slot')
                self._assert_token(document, slot['type'], contract=f'{contract} slot type')

    def _assert_commercial_contract(self, document):
        self._assert_token(document, 'commercial_terms', contract='Commercial Terms section')
        for key, _label, data_type, _required, options, _validation, _reporting in COMMERCIAL_FIELD_SPECS:
            self._assert_token(document, key, contract='Commercial Terms field')
            self._assert_token(document, data_type, contract=f'Commercial Terms type for {key}')
            for option in options:
                self._assert_token(document, option['code'], contract=f'Commercial Terms option for {key}')
        for column in LOAN_FEES_STRUCTURE['columns']:
            self._assert_token(document, column['key'], contract='Commercial fee column')

    def test_invoice_finance_reference_covers_the_seed_contract(self):
        document = self._document('invoice-finance-laf-seed.md')

        self._assert_seed_contract(
            document,
            sections=INVOICE_SECTIONS,
            fields=INVOICE_FIELD_SPECS,
            signers=INVOICE_SIGNER_RULES,
            contract='Invoice Finance',
        )
        self.assertIn('the seed does not create or publish coordinates', document)
        self.assertIn('`checked_when=male`', document)
        self.assertIn('**Not placed**', document)
        self._assert_commercial_contract(document)

    def test_generic_reference_covers_fields_tables_signers_and_evidence(self):
        document = self._document('generic-jawabu-laf-seed.md')

        self._assert_seed_contract(
            document,
            sections=GENERIC_SECTIONS,
            fields=GENERIC_FIELD_SPECS,
            signers=GENERIC_SIGNER_RULES,
            contract='Generic Jawabu LAF',
        )
        for structure_name, structure in (
            ('external loans', EXTERNAL_LOANS_STRUCTURE),
            ('pledged assets', PLEDGED_ASSETS_STRUCTURE),
        ):
            for column in structure['columns']:
                self._assert_token(
                    document,
                    column['key'],
                    contract=f'Generic Jawabu LAF {structure_name} column',
                )
                self._assert_token(
                    document,
                    column['type'],
                    contract=f'Generic Jawabu LAF {structure_name} column type',
                )
        for requirement in EVIDENCE_REQUIREMENTS:
            self._assert_token(
                document,
                requirement['key'],
                contract='Generic Jawabu LAF evidence requirement',
            )
        self.assertIn('manually entered canonical fields', ' '.join(document.split()))
        self.assertIn('`repeating_table`', document)
        self.assertIn('the seed does not create or publish coordinates', document)
        self._assert_commercial_contract(document)
