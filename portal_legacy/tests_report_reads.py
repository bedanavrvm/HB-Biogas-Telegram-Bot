"""Report POSTs remain reads while operational cutover writes are fenced."""
import json
import uuid
from io import BytesIO

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import ComplianceAuditEvent, JawabuFarmerMaster, PortalMaintenanceState
from core.services.portal_reporting import create_definition
from core.tests_telegram_authentication import BOT_TOKEN
from .tests import LegacyHTTPMixin


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True,
                   REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LegacyReportReadTests(LegacyHTTPMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.upload = self.cleanup(self.stage())
        self.case = JawabuFarmerMaster.objects.create(
            customer_name='SYNTHETIC VISIBLE CASE', branch='EMBU', group_configuration=self.group,
            jbl_visit_date=timezone.localdate(), invoice_date=timezone.localdate(),
        )
        JawabuFarmerMaster.objects.create(
            customer_name='SYNTHETIC OTHER BRANCH', branch='NAKURU', group_configuration=self.group,
        )
        self.reader = self.staff(role='IT', branch='EMBU')
        self.configuration = {'fields': ['customer_name', 'branch'], 'filters': [],
                              'ordering': {'field': 'customer_name', 'direction': 'asc'}}
        self.definition, _ = create_definition(
            payload={'title': 'Synthetic maintenance report', 'configuration': self.configuration, 'charts': []},
            actor=self.reader, request_id=str(uuid.uuid4()),
        )

    def post(self, name, body=None, **kwargs):
        return self.client.post(reverse(name, kwargs=kwargs), json.dumps(body or {}),
                                content_type='application/json', **self.headers,
                                HTTP_X_REQUEST_ID=str(uuid.uuid4()))

    def test_report_reads_during_cutover_and_global_maintenance_keep_scope_and_audit(self):
        for mode in ('live', 'maintenance'):
            PortalMaintenanceState.objects.update_or_create(
                singleton=1, defaults={'mode': mode, 'reason': 'Synthetic maintenance'},
            )
            for preset in ('pipeline', 'outcomes', 'finance'):
                with self.subTest(mode=mode, preset=preset):
                    body = {'preset': preset, 'filters': {'date_mode': 'all'}}
                    response = self.post('portal_curated_report', body)
                    self.assertEqual(response.status_code, 200, response.content[:700])
                    self.assertEqual([row['customer_name'] for row in response.json()['result']['rows']],
                                     ['SYNTHETIC VISIBLE CASE'])
                    exported = self.post('portal_curated_report_export', body)
                    self.assertEqual(exported.status_code, 200, exported.content[:700])
                    workbook = load_workbook(BytesIO(exported.content), read_only=True)
                    names = list(workbook['Data'].values)
                    self.assertEqual(len(names), 2)
                    self.assertIn('SYNTHETIC VISIBLE CASE', names[1])
                    workbook.close()
            preview = self.post('portal_report_preview', {'configuration': self.configuration,
                'chart': {'chart_type': 'bar', 'dimension_field': 'branch', 'aggregation': 'count'}})
            self.assertEqual(preview.status_code, 200, preview.content[:700])
            for name in ('portal_report_run', 'portal_report_export'):
                response = self.post(name, report_id=str(self.definition.pk))
                self.assertEqual(response.status_code, 200, response.content[:700])
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='portal.report.curated_run').count(), 6)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='portal.report.curated_exported').count(), 6)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 2)
        self.assertEqual(self.book.replacements, [])

    def test_report_definitions_email_and_case_writes_remain_fenced(self):
        for name, kwargs in (
            ('portal_reports', {}),
            ('portal_report_detail', {'report_id': str(self.definition.pk)}),
            ('portal_curated_report_email', {}),
            ('portal_jbl_visit_draft', {'farmer_id': str(self.case.pk)}),
        ):
            with self.subTest(route=name):
                response = self.post(name, **kwargs)
                self.assertEqual(response.status_code, 503, response.content[:700])
                expected = 'legacy_case_awaiting_sync' if name == 'portal_jbl_visit_draft' else 'legacy_cutover_maintenance'
                self.assertEqual(response.json().get('code'), expected)

    def test_read_exemption_does_not_grant_reporting_access(self):
        self.staff(role='JBL_OFFICER', branch='EMBU')
        for name in ('portal_curated_report', 'portal_curated_report_export', 'portal_report_preview'):
            response = self.post(name)
            self.assertEqual(response.status_code, 403, response.content[:700])
