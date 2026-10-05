"""Portal reason lists do not reinterpret legacy or payment decisions."""
from django.test import SimpleTestCase
from django.test import RequestFactory
from unittest.mock import patch
from types import SimpleNamespace
from inspect import unwrap
import json
from core.services.jawabu_approvals import (
    REJECTED_REASONS, DEFERRED_REASONS, validate_pipeline_reason,
    validate_reason, JawabuApprovalError,
    record_approval,
)


class PipelineReasonTests(SimpleTestCase):
    def test_all_outcomes_and_other_explanations(self):
        for decision, reasons in [('Rejected', REJECTED_REASONS), ('Rejected by JBL', REJECTED_REASONS),
                                  ('Deferred / On Hold', DEFERRED_REASONS)]:
            for code, label in reasons:
                with self.subTest(decision=decision, code=code):
                    note = 'Synthetic explanation' if code in {'r07', 'd12'} else ''
                    self.assertEqual(validate_pipeline_reason(decision=decision, reason_code=code.upper(), comment=note), code)
                    if code in {'r07', 'd12'}:
                        with self.assertRaises(JawabuApprovalError):
                            validate_pipeline_reason(decision=decision, reason_code=code)

    def test_mismatched_lists_and_legacy_new_submissions_are_rejected(self):
        for decision, reason in [('Rejected','d01'),('Deferred / On Hold','r01'),('Approved','r01'),
                                 ('Rejected','affordability'),('Rejected','')]:
            with self.subTest(decision=decision, reason=reason), self.assertRaises(JawabuApprovalError):
                validate_pipeline_reason(decision=decision, reason_code=reason)

    def test_legacy_validation_remains_available(self):
        self.assertEqual(validate_reason(decision='Rejected', reason_code='affordability')[1], 'affordability')
        self.assertEqual(validate_reason(decision='Rejected', reason_code='r01')[1], 'r01')
        with self.assertRaises(JawabuApprovalError):
            validate_reason(decision='Approved', reason_code='d01')

    def test_non_negative_outcomes_need_no_reason(self):
        for outcome in ['Approved','Rescheduled','Opted for Cash','Opted for Other Partner']:
            self.assertEqual(validate_pipeline_reason(decision=outcome), '')

    def test_payment_review_does_not_accept_pipeline_codes(self):
        with self.assertRaises(JawabuApprovalError):
            unwrap(record_approval)(farmer=None, gate='payment_review', decision='Rejected', reason_code='R01')

    def test_api_returns_a_field_error_for_invalid_reason(self):
        from core.api.portal_views import _portal_pipeline_reason_error
        response = _portal_pipeline_reason_error({'reason_code':'d01'}, 'Rejected', '')
        self.assertEqual(response.status_code, 400)
        self.assertIn('reason_code', json.loads(response.content)['field_errors'])
        self.assertIsNone(_portal_pipeline_reason_error({'reason_code':'r01'}, 'Rejected', ''))


class FarmupSourceRowsTests(SimpleTestCase):
    def test_source_rows_are_scoped_read_only_and_paged(self):
        from core.api.portal_views import portal_farmup_detail
        batch = SimpleNamespace(total_rows=60, source_content=b'Name,Comment\nSynthetic lead,Original text\n', import_kind='farmers')
        with patch('core.api.portal_views._portal_read_access_error', return_value=None), \
             patch('core.api.portal_views._portal_farmup_in_scope', return_value=batch) as scope, \
             patch('core.services.portal_imports.serialize_import_batch') as serialize, \
             patch('core.services.portal_imports.validate_portal_farmup') as validate:
            request = RequestFactory().get('/synthetic/', {'source_page':1})
            result = unwrap(portal_farmup_detail)(request, 'synthetic-batch')
            self.assertEqual(result.status_code, 200)
            data = json.loads(result.content)
            self.assertEqual(data['source_table']['headers'], ['Name','Comment'])
            self.assertEqual(data['source_table']['rows'], [['Synthetic lead','Original text']])
            scope.assert_called_once_with(request, 'synthetic-batch')
            serialize.assert_not_called()
            validate.assert_not_called()

    def test_unavailable_batch_does_not_expose_source(self):
        from core.api.portal_views import portal_farmup_detail
        with patch('core.api.portal_views._portal_read_access_error', return_value=None), \
             patch('core.api.portal_views._portal_farmup_in_scope', return_value=None), \
             patch('core.services.portal_imports.source_table_page') as source:
            result = unwrap(portal_farmup_detail)(RequestFactory().get('/synthetic/', {'source_page':1}), 'outside-scope')
            self.assertEqual(result.status_code, 404)
            source.assert_not_called()
