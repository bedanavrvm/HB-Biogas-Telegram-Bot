from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.core.exceptions import ValidationError
from contextlib import ExitStack
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch, Mock

from openpyxl import load_workbook

from core.models import WorkflowRoleCapability
from core.services.tat_presentation import REPORT_PANEL_ORDER, REPORT_PANEL_VIEWS, validate_report_panel_order
from core.services.tat_reporting import _heatmap_dimension_labels, _stage_columns_for_rows
from core.services.access_control import create_capability_request
from core.services.workflow_capabilities import (
    default_enabled_capability_keys, dependency_closure, effective_capability_keys,
)


class TatReportPresentationPolicyTests(SimpleTestCase):
    def test_bro_correction_submits_canonical_identity_to_audit_and_rejects_unknown(self):
        from core.services.tat_tracker import apply_update, record_tat_event
        case = SimpleNamespace(bro_name='Historical BRO', group_id='training', sheet_name='Training', row_number=7)
        user = {'capabilities': ['tat.case.correct'], 'name': 'Synthetic IT'}
        with patch('core.services.tat_tracker.configured_bro_users', return_value=[{'id': 7, 'name': 'Current BRO'}]), \
             patch('core.services.tat_tracker.record_tat_event') as audit:
            apply_update(case, user, {'field': 'bro_user_id', 'value': '7', 'correction': True})
            self.assertEqual(case.bro_name, 'Current BRO')
            self.assertEqual(audit.call_args.kwargs['selected_bro_user_id'], 7)
            self.assertEqual(audit.call_args.kwargs['stage_label'], 'Corrected BRO')
            with self.assertRaisesMessage(ValueError, 'Select an active TAT BRO'):
                apply_update(case, user, {'field': 'bro_user_id', 'value': '99', 'correction': True})
        with patch('core.services.tat_tracker.TatTrackerEvent.objects.create') as create, \
             patch('core.services.compliance_audit.record_event') as compliance:
            event = create.return_value
            event.source = 'admin_correction'; event.request_id = 'synthetic'
            record_tat_event(selected_bro_user_id=7, source='admin_correction')
            self.assertNotIn('selected_bro_user_id', create.call_args.kwargs)
            self.assertEqual(compliance.call_args.kwargs['metadata']['selected_bro_user_id'], '7')

    def test_sheet_minutes_use_two_decimal_numeric_format_at_mapped_headers(self):
        from decimal import Decimal
        from core.services.tat_tracker import ProductConfig, StageConfig, StageTatColumn, format_tat_sheet_case_row
        product = ProductConfig('synthetic', 'Training', 'Training', 'TRAIN', Decimal(1), None,
            8, 9, 10, {}, (StageConfig('visit', 'Visit', 2, 'BRO'),),
            stage_tat_columns=(StageTatColumn('visit', 3, ('Visit minutes',)),))
        case = SimpleNamespace(status='Active', case_id='SYNTHETIC', current_stage='', stage_values={})
        sheet = Mock()
        headers = ['Reference', 'Visit', 'Other', 'Total TAT Minutes', 'Visit minutes', 'Status']
        sheet.row_values.return_value = headers
        format_tat_sheet_case_row(SimpleNamespace(workflow={}), sheet, 7, case, product, headers=headers)
        formats = sheet.batch_format.call_args.args[0]
        numeric = {item['range']: item['format']['numberFormat'] for item in formats
                   if 'numberFormat' in item['format']}
        self.assertEqual(numeric, {'D7': {'type': 'NUMBER', 'pattern': '0.00'},
                                   'E7': {'type': 'NUMBER', 'pattern': '0.00'}})
        sheet.batch_format.side_effect = RuntimeError('Synthetic cosmetic failure')
        with self.assertLogs('core.services.tat_tracker', level='WARNING'):
            format_tat_sheet_case_row(SimpleNamespace(workflow={}), sheet, 7, case, product, headers=headers)

    @override_settings(SECRET_KEY='synthetic-download-key')
    def test_download_token_hides_filters_and_rejects_expiry_and_tampering(self):
        from core.services.tat_reporting import encode_report_download, decode_report_download
        from django.core.signing import BadSignature, SignatureExpired
        payload = {'user_id': 42, 'group_id': 'training',
                   'filters': {'search': 'Synthetic search', 'export_scope': 'filtered'}}
        with patch('django.core.signing.time.time', return_value=1000):
            token = encode_report_download(payload)
        self.assertNotIn('Synthetic', token)
        with patch('django.core.signing.time.time', return_value=1800):
            self.assertEqual(decode_report_download(token), payload)
            with self.assertRaises(BadSignature):
                decode_report_download(token + 'tampered')
        with patch('django.core.signing.time.time', return_value=1901):
            with self.assertRaises(SignatureExpired):
                decode_report_download(token)

    def exported_heatmap(self, metric, value):
        from core.services.tat_reporting import export_report_xlsx
        heatmap = {'title': 'Stage x Branch', 'basis': 'completed_stage_actions',
                   'metric': metric, 'row_dimension': 'stage', 'columns': ['Training'],
                   'rows': ['Visit'], 'cells': [{'row': 'Visit', 'column': 'Training',
                   'value': value, 'sample_count': 4, 'excluded_count': 1}]}
        with ExitStack() as stack:
            for name, result in [('_filtered_cases', []), ('_ReportContext', None),
                                 ('_eligible_rows', []), ('_stage_samples', []),
                                 ('_comparison_explorer', {'title': 'Comparison', 'basis': 'current',
                                  'subtitle': 'Synthetic', 'series': [], 'labels': []}),
                                 ('_heatmap_payload', heatmap)]:
                stack.enter_context(patch('core.services.tat_reporting.' + name, return_value=result))
            stack.enter_context(patch('core.services.compliance_audit.record_event'))
            content, _ = export_report_xlsx(SimpleNamespace(pk=1), {'view': 'performance'},
                                            include_people=True, request_id='synthetic-export')
        return load_workbook(BytesIO(content))

    def test_heatmap_retains_numeric_percent_colours_and_sample_context(self):
        for value, colour in [(80, 'C6EFCE'), (75, 'FFEB9C'), (59, 'FFC7CE')]:
            workbook = self.exported_heatmap('sla_met', value)
            cell = workbook['Selected Heatmap']['B6']
            self.assertEqual(cell.value, value / 100)
            self.assertIn('%', cell.number_format)
            self.assertEqual(cell.fill.fgColor.rgb[-6:], colour)
            self.assertIn('4', cell.comment.text)
            self.assertIn('1', cell.comment.text)
            headers = [c.value for c in workbook['TAT Report'][1]]
            self.assertNotIn('Responsible Person', headers)
            for label in ('Current stage', 'Case created', 'Case finished', 'Target result', 'Status'):
                self.assertIn(label, headers)

    def test_other_heatmap_units_and_missing_values_are_not_percentages(self):
        for metric, value, expected in [('target_usage', 125, 1.25),
                                        ('median_tat', 1.25, 1.25), ('workload', 4, 4),
                                        ('sla_met', None, None)]:
            cell = self.exported_heatmap(metric, value)['Selected Heatmap']['B6']
            self.assertEqual(cell.value, expected)
            if metric == 'target_usage':
                self.assertIn('%', cell.number_format)
            elif value is not None:
                self.assertNotIn('%', cell.number_format)

    def test_report_panels_have_one_owner_without_changing_order(self):
        self.assertEqual(set(REPORT_PANEL_VIEWS), set(REPORT_PANEL_ORDER))
        current = {key for key, view in REPORT_PANEL_VIEWS.items() if view == 'current'}
        performance = {key for key, view in REPORT_PANEL_VIEWS.items() if view == 'performance'}
        self.assertFalse(current & performance)
        self.assertEqual(len(current), 5)
        self.assertEqual(len(performance), 5)

    def test_stage_labels_follow_loan_cycle_not_alphabetical_or_frequency(self):
        rows = [
            {'current_stage': 'Credit', 'current_stage_key': 'credit', '_stage_columns': [
                {'key': 'intake', 'label': 'Intake', 'order': 0},
                {'key': 'visit', 'label': 'Visit', 'order': 1},
                {'key': 'credit', 'label': 'Credit', 'order': 2},
            ]},
            {'current_stage': 'Intake', 'current_stage_key': 'intake', '_stage_columns': [
                {'key': 'intake', 'label': 'Intake', 'order': 0},
                {'key': 'visit', 'label': 'Visit', 'order': 1},
                {'key': 'credit', 'label': 'Credit', 'order': 2},
            ]},
        ]
        self.assertEqual(
            _heatmap_dimension_labels(rows, 'stage', sample=False), ['Intake', 'Credit'],
        )
        self.assertEqual(
            [item['key'] for item in _stage_columns_for_rows(rows)],
            ['intake', 'visit', 'credit'],
        )

    def test_global_panel_order_requires_every_panel_once(self):
        self.assertEqual(validate_report_panel_order(list(reversed(REPORT_PANEL_ORDER))), list(reversed(REPORT_PANEL_ORDER)))
        for invalid in ([], list(REPORT_PANEL_ORDER[:-1]), [*REPORT_PANEL_ORDER[:-1], REPORT_PANEL_ORDER[0]]):
            with self.assertRaisesMessage(ValueError, 'exactly once'):
                validate_report_panel_order(invalid)

    def test_panel_grant_includes_whole_report_and_target_signals_defaults_to_it(self):
        self.assertIn('tat.reports.view', dependency_closure('tat_tracker', {'tat.reports.insight.heatmap'}))
        self.assertIn('tat.reports.insight.heatmap', default_enabled_capability_keys('tat_tracker', 'MANAGEMENT'))
        self.assertNotIn('tat.reports.insight.target_review_signals', default_enabled_capability_keys('tat_tracker', 'MANAGEMENT'))
        self.assertIn('tat.reports.insight.target_review_signals', default_enabled_capability_keys('tat_tracker', 'IT'))


class TatReportInsightAccessTests(TestCase):
    def test_non_it_cannot_gain_target_signals_from_a_stale_policy_row(self):
        user = get_user_model().objects.create_user(username='tat-report-insight-test')
        for key in ('tat.home.view', 'tat.reports.view', 'tat.reports.insight.heatmap',
                    'tat.reports.insight.target_review_signals'):
            WorkflowRoleCapability.objects.update_or_create(
                workflow='tat_tracker', role='MANAGEMENT', capability_key=key,
                defaults={'effect': 'allow', 'enabled': True},
            )
        enabled = effective_capability_keys(user, 'tat_tracker', access={'roles': ['MANAGEMENT']})
        self.assertIn('tat.reports.insight.heatmap', enabled)
        self.assertNotIn('tat.reports.insight.target_review_signals', enabled)

    def test_matrix_rejects_non_it_target_signal_grant(self):
        requester = get_user_model().objects.create_superuser(
            username='tat-report-policy-admin', email='admin@example.invalid', password='test-pass-1234',
        )
        with self.assertRaisesMessage(ValidationError, 'restricted to IT'):
            create_capability_request(
                requester=requester, workflow='tat_tracker', role='MANAGEMENT',
                capability_keys={'tat.reports.insight.target_review_signals'},
                reason='Restrict this insight to the technical team.',
            )
