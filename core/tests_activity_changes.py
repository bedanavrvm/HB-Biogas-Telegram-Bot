from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.services.activity_changes import invoice_activity_changes, recorded_changes
from core.services.workflow_timeline import _entry, tat_case_timeline
from payments.services import _payment_activity_changes


class ActivityChangesTests(SimpleTestCase):
    def test_complaint_labels_hide_codes_priority_and_duplicate_locations(self):
        from core.services.complaint_cases import complaint_display_changes

        changes = recorded_changes(
            {'county_code': 'KE-21', 'category_key': 'burner', 'priority': 'normal'},
            {'county_code': 'KE-22', 'category_key': 'installation', 'priority': 'high'})
        readable = complaint_display_changes(changes,
            {('county', 'KE-21'): 'Murang’a', ('county', 'KE-22'): 'Kiambu'},
            {'burner': 'Burner issue', 'installation': 'Installation issue'})
        self.assertEqual([row['field'] for row in readable], ['county_code', 'category_key'])
        self.assertEqual(readable[0]['old_display'], 'Murang’a')
        self.assertEqual(readable[0]['new_display'], 'Kiambu')
        self.assertEqual(readable[1]['new_display'], 'Installation issue')
        self.assertEqual(changes[0]['old_value'], 'KE-21')
        self.assertNotIn('old_display', changes[0])
        duplicate = recorded_changes({'county': 'Murang’a', 'county_code': 'KE-21'},
                                     {'county': 'Kiambu', 'county_code': 'KE-22'})
        self.assertEqual([row['field'] for row in complaint_display_changes(duplicate, {}, {})], ['county'])
        self.assertEqual(complaint_display_changes(changes, {}, {})[0]['old_display'], 'Unknown county')

    @patch('core.services.complaint_cases.ComplaintCategory.objects.filter')
    @patch('core.services.complaint_cases.OperationalLocation.objects.filter')
    @patch('core.services.complaint_cases.ComplaintCaseEvent.objects.filter')
    @patch('core.models.ComplianceAuditEvent.objects.filter')
    def test_complaint_history_uses_action_and_resolves_catalogue_names(self, audit, events, locations, categories):
        from core.services.complaint_cases import complaint_history

        audit.return_value.values_list.return_value = [('update', {'actor_affiliation': 'JBL'})]
        events.return_value = [SimpleNamespace(pk='operation', request_id='request', action='details_completed',
            before_values={'county_code': 'KE-21', 'priority': 'normal'},
            after_values={'county_code': 'KE-22', 'priority': 'high'})]
        locations.return_value.values_list.return_value = [('county', 'KE-21', 'Murang’a'), ('county', 'KE-22', 'Kiambu')]
        update = SimpleNamespace(pk='update', old_status='Open', new_status='Open', resolution_text='',
            updated_by='Training officer', created_at=datetime.now(timezone.utc), gps_link='',
            source='mini_app_review_completion', client_request_id='request')
        rows = complaint_history(SimpleNamespace(resolution_details=''), [update])
        self.assertEqual(rows[0]['action'], 'details_completed')
        self.assertEqual(rows[0]['action_group'], 'operation')
        self.assertEqual(rows[0]['changes'][0]['old_value'], 'KE-21')
        self.assertEqual(rows[0]['display_changes'][0]['old_display'], 'Murang’a')
        self.assertEqual(len(rows[0]['display_changes']), 1)
        categories.assert_not_called()

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
