"""Focused regression tests for the IT-only controlled Portal reports."""
from __future__ import annotations

from io import BytesIO, StringIO
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from openpyxl import load_workbook

from core.models import ComplianceAuditEvent, JawabuFarmerMaster
from core.services.portal_reporting import (
    PortalReportingError,
    create_definition,
    export_xlsx,
    run_definition,
    validate_configuration,
)
from core.services.reporting_relationships import portal_relationship_summary
from core.services.workflow_capabilities import has_capability


class PortalReportingTests(TestCase):
    """Reports remain bounded, scoped, auditable, and free of Google effects."""

    def setUp(self):
        self.it_user = get_user_model().objects.create_user(
            username='portal-reporting-it', password='not-used', is_active=True,
        )
        self.emb_u_case = JawabuFarmerMaster.objects.create(
            customer_name='Embu reporting case', national_id='10000001',
            primary_phone='254700000001', branch='EMBU', county='EMBU',
            deposit_paid_hbg=Decimal('5000.00'), status='active',
        )
        JawabuFarmerMaster.objects.create(
            customer_name='Nakuru reporting case', national_id='10000002',
            primary_phone='254700000002', branch='NAKURU', county='NAKURU',
            deposit_paid_hbg=Decimal('7500.00'), status='active',
        )
        self.configuration = {
            'fields': ['customer_name', 'branch', 'deposit_paid_hbg'],
            'filters': [],
            'ordering': {'field': 'customer_name', 'direction': 'asc'},
        }

    def test_it_capability_is_allowed_and_jbl_officer_is_explicitly_denied(self):
        """Policy has a happy path and a denied path for the sensitive module."""
        self.assertTrue(has_capability(
            self.it_user, 'jawabu_portal', 'portal.reports.view',
            access={'roles': ['IT']},
        ))
        self.assertFalse(has_capability(
            self.it_user, 'jawabu_portal', 'portal.reports.manage',
            access={'roles': ['JBL_OFFICER']},
        ))

    def test_live_run_is_branch_scoped_and_audited_definition_is_idempotent(self):
        definition, replayed = create_definition(
            payload={
                'title': 'Branch deposits',
                'configuration': self.configuration,
                'charts': [{
                    'chart_type': 'bar', 'dimension_field': 'branch',
                    'aggregation': 'count', 'metric_field': '', 'date_bucket': '',
                }],
            },
            actor=self.it_user,
            request_id='portal-report-create-1',
        )
        self.assertFalse(replayed)
        duplicate, replayed = create_definition(
            payload={'title': 'Changed retry title', 'configuration': self.configuration, 'charts': []},
            actor=self.it_user,
            request_id='portal-report-create-1',
        )
        self.assertTrue(replayed)
        self.assertEqual(duplicate.pk, definition.pk)
        self.assertEqual(definition.charts.count(), 1)
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            action='portal.report.created', subject_id=str(definition.pk),
        ).exists())

        result = run_definition(
            definition=definition,
            user=self.it_user,
            access={'roles': ['IT'], 'branches': ['EMBU']},
        )
        self.assertEqual(result['total_rows'], 1)
        self.assertEqual(result['rows'][0]['customer_name'], self.emb_u_case.customer_name)
        self.assertEqual(result['charts'][0]['labels'], ['EMBU'])
        self.assertEqual(result['charts'][0]['values'], [1.0])

    def test_catalogue_rejects_sensitive_or_arbitrary_fields_and_xlsx_is_local(self):
        with self.assertRaises(PortalReportingError):
            validate_configuration({
                'fields': ['comments'],
                'filters': [],
                'ordering': {'field': 'comments', 'direction': 'asc'},
            })

        definition, _ = create_definition(
            payload={'title': 'Local export', 'configuration': self.configuration, 'charts': []},
            actor=self.it_user,
            request_id='portal-report-create-2',
        )
        workbook = load_workbook(BytesIO(export_xlsx(
            definition=definition,
            user=self.it_user,
            access={'roles': ['IT'], 'branches': ['EMBU']},
        )))
        self.assertEqual(workbook['Data']['A1'].value, 'Customer name')
        self.assertEqual(workbook['Data']['A2'].value, self.emb_u_case.customer_name)
        self.assertEqual(workbook['Data'].max_row, 2)

    def test_relationship_inventory_keeps_other_workflows_non_joinable(self):
        summary = portal_relationship_summary()
        self.assertIn('core.TatTrackerCase', summary['unlinked_identity_only'])
        self.assertIn('core.SpinCreditRequest', summary['unlinked_identity_only'])
        self.assertIn('core.CaseUpdate', summary['unlinked_identity_only'])
        output = StringIO()
        call_command('inspect_reporting_relationships', '--json', stdout=output)
        self.assertIn('core.JawabuFarmerMaster', output.getvalue())

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    def test_catalogue_endpoint_is_wired_without_a_google_side_effect(self):
        response = self.client.get('/api/portal/reports/catalogue/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        all_keys = {
            field['key']
            for category in payload['catalogue']['categories']
            for field in category['fields']
        }
        self.assertIn('customer_name', all_keys)
        self.assertNotIn('comments', all_keys)
