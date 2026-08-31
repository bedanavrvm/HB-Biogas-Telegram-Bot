from datetime import date
import unittest

from scripts.check_coverage_quality import added_lines, aggregate, quality_errors
from scripts.check_dependency_vulnerabilities import exception_errors
from scripts.check_miniapp_write_inventory import inventory_errors


class RouteGovernanceContractTests(unittest.TestCase):
    def test_every_unsafe_miniapp_route_has_auth_and_capability_governance(self):
        self.assertEqual(inventory_errors(), [])


class CoverageQualityContractTests(unittest.TestCase):
    def test_added_service_lines_are_parsed_from_zero_context_diff(self):
        diff = '\n'.join([
            '+++ b/core/services/example.py',
            '@@ -10,0 +11,3 @@',
            '+if enabled:',
            '+    run()',
            '+done()',
        ])
        self.assertEqual(added_lines(diff), {'core/services/example.py': {11, 12, 13}})

    def test_changed_missing_branch_is_rejected(self):
        payload = {
            'meta': {'branch_coverage': True},
            'totals': {'percent_covered': 80},
            'files': {
                'core/services/example.py': {
                    'summary': {
                        'covered_lines': 8, 'num_statements': 10,
                        'covered_branches': 1, 'num_branches': 2,
                    },
                    'executed_branches': [[11, 12]],
                    'missing_branches': [[11, 14]],
                },
            },
        }
        self.assertEqual(
            quality_errors(payload, {'total_percent': 80}, {'core/services/example.py': {11}}),
            ['Changed service branches need coverage: core/services/example.py:11.'],
        )

    def test_subsystems_are_reported_separately(self):
        payload = {'files': {
            'core/api/views.py': {'summary': {
                'covered_lines': 5, 'num_statements': 10, 'covered_branches': 1, 'num_branches': 2,
            }},
            'core/services/example.py': {'summary': {
                'covered_lines': 9, 'num_statements': 10, 'covered_branches': 4, 'num_branches': 4,
            }},
        }}
        report = aggregate(payload)
        self.assertEqual(report['api']['line_percent'], 50.0)
        self.assertEqual(report['services']['branch_percent'], 100.0)


class DependencyAuditExceptionTests(unittest.TestCase):
    def test_current_exception_is_bounded_and_not_expired(self):
        self.assertEqual(exception_errors(date(2026, 8, 31)), [])

    def test_exception_expiry_fails_closed(self):
        errors = exception_errors(date(2026, 10, 1))
        self.assertTrue(any('expired' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
