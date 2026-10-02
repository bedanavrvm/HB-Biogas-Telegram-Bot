from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.services.activity_changes import invoice_activity_changes, recorded_changes
from core.services.workflow_timeline import _entry, tat_case_timeline
from payments.services import _payment_activity_changes


class ActivityChangesTests(SimpleTestCase):
    def test_only_allowlisted_actual_changes_and_distinct_missing_history(self):
        changes = recorded_changes({'county': 'Kiambu', 'amount': 0, 'comment': ''},
                                   {'county': 'Nakuru', 'amount': 0, 'comment': 'New note',
                                    'primary_phone': '', 'secret_token': 'never expose'})
        self.assertEqual([item['field'] for item in changes], ['county', 'comment', 'primary_phone'])
        self.assertTrue(changes[1]['previous_recorded'])
        self.assertEqual(changes[1]['old_value'], '')
        self.assertFalse(changes[2]['previous_recorded'])

    def test_clearing_false_and_zero_are_not_omitted(self):
        changes = recorded_changes({'comment': 'Old', 'amount': 1, 'imab_created': True},
                                   {'comment': '', 'amount': 0, 'imab_created': False})
        self.assertEqual(len(changes), 3)
        self.assertIs(changes[-1]['new_value'], False)

    def test_nested_and_technical_facts_are_never_exposed(self):
        self.assertEqual(recorded_changes({}, {'comment': {'secret': 'x'}, 'revision': 2}), [])

    def test_invoice_corrections_use_original_audit_comparisons(self):
        changes = invoice_activity_changes({'changes': {'invoice_no': {'before': 'BILL', 'after': '10116'},
                                                       'secret': {'before': 'x', 'after': 'y'}}})
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0]['old_value'], changes[0]['new_value']), ('BILL', '10116'))

    def test_redaction_removes_values_and_artifacts(self):
        row = _entry(source_id='test', action='updated', occurred_at=datetime.now(timezone.utc),
                     changes=recorded_changes({'county': 'Old'}, {'county': 'New'}),
                     artifact={'url': 'private'}, redaction=SimpleNamespace(note='Restricted'))
        self.assertEqual(row['changes'], [])
        self.assertIsNone(row['artifact'])

    @patch('core.services.workflow_timeline._annotations', return_value=({}, []))
    def test_tat_uses_recorded_old_and_new_without_duplicate_detail(self, _annotations):
        events = MagicMock()
        events.select_related.return_value.order_by.return_value = [SimpleNamespace(
            id='event', source='mini_app', stage_key='credit', stage_label='Credit analysis',
            transition_code='', created_at=datetime.now(timezone.utc), actor_user=None,
            authority_user=None, actor_name='Training officer', old_value='Pending',
            new_value='Approved', reason='')]
        rows = tat_case_timeline(SimpleNamespace(pk='case', events=events))['entries']
        self.assertEqual(rows[0]['detail'], '')
        self.assertEqual(rows[0]['changes'][0]['old_value'], 'Pending')
        self.assertEqual(rows[0]['changes'][0]['new_value'], 'Approved')

    def test_legacy_payment_values_do_not_invent_previous_mode(self):
        changes = _payment_activity_changes(SimpleNamespace(metadata={'payment_mode': 'CASH'}))
        self.assertFalse(changes[0]['previous_recorded'])

    def test_payment_metadata_cannot_expose_unknown_fields(self):
        changes = _payment_activity_changes(SimpleNamespace(metadata={'changes': [
            {'field': 'secret', 'new_value': 'private'},
            {'field': 'payment_mode', 'label': 'wrong label', 'old_value': 'CASH', 'new_value': 'LOAN-JAWABU'}]}))
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['label'], 'Payment mode')
