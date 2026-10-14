from unittest import TestCase
from unittest.mock import Mock

from core.services.sheet_columns import (
    NamedColumns, SheetColumnError, assert_columns_unchanged, named_updates,
)


class NamedColumnTests(TestCase):
    def test_reordered_read_and_write_use_names(self):
        columns = NamedColumns(['Staff notes', 'Phone', 'Case ID'])
        self.assertEqual(columns.value(['keep', 'test-phone', 'case-1'], 'Case ID'), 'case-1')
        self.assertEqual(named_updates(columns, 5, {'Case ID': 'case-2'}),
                         [{'range': 'C5', 'values': [['case-2']]}])

    def test_duplicate_case_whitespace_and_unicode_are_rejected(self):
        for duplicate in (' case id ', 'Case  ID', 'Ｃａｓｅ ID'):
            with self.subTest(duplicate=duplicate), self.assertRaises(SheetColumnError):
                NamedColumns(['Case ID', duplicate])

    def test_aliases_cannot_choose_between_two_matching_columns(self):
        columns = NamedColumns(['Phone', 'Primary phone'])
        with self.assertRaises(SheetColumnError):
            columns.column('Phone', 'Primary phone')

    def test_missing_required_never_falls_back(self):
        columns = NamedColumns(['Notes'])
        with self.assertRaises(SheetColumnError):
            columns.column('Case ID')
        self.assertIsNone(columns.column('Optional', required=False))

    def test_legacy_normalization_cannot_hide_collision(self):
        columns = NamedColumns(['A-B', 'AB'])
        with self.assertRaises(SheetColumnError):
            columns.lookup(lambda value: value.replace('-', '').lower())

    def test_binding_one_column_to_two_fields_is_rejected(self):
        with self.assertRaises(SheetColumnError):
            NamedColumns(['ID']).bindings({'applicant': ['ID'], 'guarantor': ['ID']})

    def test_populated_unnamed_column_is_rejected(self):
        columns = NamedColumns(['Case ID', ''])
        columns.validate_row(['case-1', ''])
        with self.assertRaises(SheetColumnError):
            columns.validate_row(['case-1', 'unknown'])

    def test_schema_changed_before_mutation_is_rejected(self):
        sheet = Mock(title='Synthetic register')
        sheet.row_values.return_value = ['Notes', 'Case ID']
        with self.assertRaises(SheetColumnError):
            assert_columns_unchanged(sheet, NamedColumns(['Case ID', 'Notes']))
        sheet.update.assert_not_called()
