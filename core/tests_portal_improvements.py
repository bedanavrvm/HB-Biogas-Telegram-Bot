"""Synthetic regressions for the agreed Portal corrections; no provider I/O."""
from datetime import date, datetime, timezone as utc_timezone
from decimal import Decimal
from unittest.mock import patch
from io import BytesIO
import hashlib

from django.test import TestCase, SimpleTestCase, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import JawabuFarmerMaster, OperationalLocation, OperationalLocationAlias
from core.services.invoice_parser import extract_serial_number
from core.services.jawabu_validation import canonicalize_farmer
from core.services.locations import county_label_map
from hb_operations.deposits import stamp_deposit_date


class PortalSerialAndDateTests(SimpleTestCase):
    def test_serial_layout_variants_preserve_text_and_reject_ambiguity(self):
        for source in ['Serial Number: 000HB-7/003', 'SERIAL NO.\n000HB-7/003', 'S/N 000HB-7/003']:
            self.assertEqual(extract_serial_number(source), '000HB-7/003')
        for source in ['', 'SERIAL NUMBER\nDESCRIPTION', 'Serial No: HB01\nSerial No: HB02']:
            self.assertEqual(extract_serial_number(source), '')

    def test_serial_in_invoice_table_and_glued_pdf_text(self):
        table = "DESCRIPTION SERIAL NUMBER QTY RATE AMOUNT\nHBG Complete Farmer's System 001106112511402 1 54,000.00 54,000.00"
        for source in [table, table.replace('\n', ' ') + ' We appreciate your business. SUBTOTAL 54,000.00']:
            self.assertEqual(extract_serial_number(source), '001106112511402')
        self.assertEqual(extract_serial_number(table + '\nHBG System 001106112511403 1 54,000.00 54,000.00'), '')
        self.assertEqual(extract_serial_number('SERIAL NUMBER QTY RATE AMOUNT\nHBG System 1 54,000.00 54,000.00'), '')

    def test_hybrid_date_uses_change_day_in_nairobi_only_for_amount_changes(self):
        farmer = JawabuFarmerMaster(source='jawabu_farmup_review', deposit_paid_hbg=Decimal('2000'), hbg_visit_date=date(2025, 2, 18))
        stamp_deposit_date(farmer, None, initial=True)
        self.assertEqual(farmer.hb_deposit_date, date(2025, 2, 18))
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 25, 22, 30, tzinfo=utc_timezone.utc)):
            stamp_deposit_date(farmer, Decimal('2000'))
            self.assertEqual(farmer.hb_deposit_date, date(2025, 2, 18))
            farmer.deposit_paid_hbg = Decimal('5000')
            stamp_deposit_date(farmer, Decimal('2000'))
            self.assertEqual(farmer.hb_deposit_date, date(2026, 10, 26))

    def test_office_date_is_not_a_visit_date(self):
        farmer = JawabuFarmerMaster(source='jawabu_office_lead', deposit_paid_hbg=Decimal('0'), hbg_visit_date=date(2025, 1, 1))
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 26, 4, tzinfo=utc_timezone.utc)):
            stamp_deposit_date(farmer, None, initial=True)
        self.assertEqual(farmer.hb_deposit_date, date(2026, 10, 26))

    def test_local_pdf_preview_is_bounded_private_and_keeps_original_bytes(self):
        from core.api.portal_views import portal_local_document_preview
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=500)
        stream = BytesIO()
        writer.write(stream)
        source = stream.getvalue()
        original = hashlib.sha256(source).hexdigest()
        request = RequestFactory().post('/api/portal/documents/local-preview/',
            {'file': SimpleUploadedFile('synthetic.pdf', source, content_type='application/pdf')})
        with patch('core.api.portal_views._portal_capability_error', return_value=None):
            response = portal_local_document_preview(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertIn(b'data:image/jpeg;base64,', response.content)
        self.assertEqual(hashlib.sha256(source).hexdigest(), original)
        with patch('core.api.portal_views._portal_capability_error', return_value=object()):
            self.assertEqual(portal_local_document_preview(request).status_code, 403)
        invalid = RequestFactory().post('/api/portal/documents/local-preview/',
            {'file': SimpleUploadedFile('bad.pdf', b'not a PDF')})
        with patch('core.api.portal_views._portal_capability_error', return_value=None):
            self.assertEqual(portal_local_document_preview(invalid).status_code, 400)


class PortalCountyAndStatusTests(TestCase):
    def setUp(self):
        self.county = OperationalLocation.objects.filter(location_type='county', name__iexact="Murang'a").first()
        if not self.county:
            self.county = OperationalLocation.objects.create(code='county-training-muranga', name="Murang'a", location_type='county')

    def test_catalogue_normalizes_case_and_apostrophes_without_guessing(self):
        labels = county_label_map(["Murang'a", "MURANG'A", ' Murang’a ', 'Not a county'])
        self.assertEqual(set(value for value in labels.values() if value), {"Murang'a"})
        self.assertIsNone(labels['Not a county'])
        farmer = JawabuFarmerMaster(county="MURANG'A")
        warnings = canonicalize_farmer(farmer, branch_catalog=[], product_catalog=[])
        self.assertNotIn('county', warnings)
        self.assertEqual(farmer.county, "Murang'a")

    def test_queue_filter_includes_all_alias_variants_without_widening_scope(self):
        from core.api.portal_views import _apply_county_branch_filters
        for index, value in enumerate(["MURANG'A", 'Murang’a', 'Nakuru']):
            JawabuFarmerMaster.objects.create(customer_name=f'Synthetic {index}', county=value)
        request = RequestFactory().get('/portal/', {'county': "Murang'a"})
        self.assertEqual(_apply_county_branch_filters(JawabuFarmerMaster.objects.all(), request).count(), 2)

    def test_sheet_import_without_a_canonical_date_preserves_existing_projection(self):
        from types import SimpleNamespace
        from core.services.jawabu_master import merge_master_row_values, header_lookup_from_headers
        farmer = JawabuFarmerMaster.objects.create()
        headers = ['HB Deposit Date']
        row = ['18-Feb-2025']
        cleaned = {'id':str(farmer.pk)}
        batch = SimpleNamespace(id='synthetic-batch', source_filename='synthetic.csv', sender='Synthetic staff')
        args = dict(row_values=row, headers=headers, header_lookup=header_lookup_from_headers(headers),
                    cleaned=cleaned, batch=batch, now_text='26-Oct-2026 10:00', created=False)
        merge_master_row_values(**args)
        self.assertEqual(row, ['18-Feb-2025'])
        cleaned['hb_deposit_date'] = '2026-10-26'
        merge_master_row_values(**args)
        self.assertEqual(row, ['2026-10-26'])

    def test_approved_alias_is_accepted_by_the_read_only_quality_report(self):
        from core.services.jawabu_data_quality import active_jawabu_quality_report
        OperationalLocationAlias.objects.create(location=self.county, alias='Training county legacy name')
        farmer = JawabuFarmerMaster.objects.create(county='Training county legacy name', status='active')
        result = active_jawabu_quality_report()
        self.assertNotIn('unknown_county', result['by_code'])
        farmer.refresh_from_db()
        self.assertEqual(farmer.county, 'Training county legacy name')

    def test_status_summary_covers_every_page(self):
        from core.services.portal_recovery import status_payload
        rows = [{'key': str(index), 'title': 'Training file', 'status': 'Waiting' if index < 12 else 'Needs review'} for index in range(15)]
        with patch('core.services.portal_recovery._scoped_cases', return_value=JawabuFarmerMaster.objects.none()), patch('core.services.portal_recovery.storage_rows', return_value=rows), patch('report_delivery.recovery.recovery_rows', return_value=[]):
            result = status_payload(None, None, page=2)
        self.assertEqual(result['summary'], {'waiting': 12, 'processing': 0, 'needs_attention': 3})
        self.assertEqual(len(result['items']), 5)
        self.assertEqual(result['items'][-1]['status_code'], 'needs_attention')

    def test_report_preference_key_changes_when_current_scope_changes(self):
        import json
        from django.contrib.auth import get_user_model
        from core.api.portal_views import portal_meta
        actor = get_user_model().objects.create_user(username='synthetic-report-key', is_superuser=True)
        request = RequestFactory().get('/api/portal/meta/')
        request.portal_user = actor
        request.portal_access = {'authorized':True,'roles':['IT'],'grants':[],'technical_override':True}
        with patch('core.api.portal_views._portal_any_capability_error', return_value=None), patch('core.api.portal_views._portal_capabilities', return_value=['portal.reports.view']), patch('core.services.portal_permissions.portal_capability_scope') as scope:
            scope.return_value = {'branches':['Synthetic branch A']}
            first = json.loads(portal_meta(request).content)['report_session_key']
            scope.return_value = {'branches':['Synthetic branch B']}
            second = json.loads(portal_meta(request).content)['report_session_key']
            repeated = json.loads(portal_meta(request).content)['report_session_key']
        self.assertNotEqual(first, second)
        self.assertEqual(second, repeated)

    def test_date_backfill_requires_evidence_and_ignores_unchanged_totals(self):
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        from importlib import import_module
        for initial, latest, expected in [
            ({'deposit_paid_hbg':'5000'}, None, None),
            ({'deposit_paid_hbg':'5000','hbg_visit_date':'2024-02-29'}, None, date(2024,2,29)),
            ({'deposit_paid_hbg':'5000','hbg_visit_date':'2024-02-29'}, {'old_values':{'deposit_paid_hbg':'5000.00'},'new_values':{'deposit_paid_hbg':'5000'}}, date(2024,2,29)),
            ({'deposit_paid_hbg':'2000'}, {'old_values':{'deposit_paid_hbg':'2000'},'new_values':{'deposit_paid_hbg':'5000'}}, date(2026,10,26)),
            ({'deposit_paid_hbg':'5000'}, {'old_values':{'deposit_paid_hbg':'2000'},'new_values':{'deposit_paid_hbg':'5000','hb_deposit_date':'bad-date'}}, None),
        ]:
            farmer = JawabuFarmerMaster.objects.create(deposit_paid_hbg=Decimal('5000'), hbg_visit_date=date(2026,10,1))
            farmer.pipeline_events.create(action='application_imported', new_values=initial, occurred_at=datetime(2024,2,29,10,tzinfo=utc_timezone.utc))
            if latest:
                farmer.pipeline_events.create(action='application_updated', **latest, occurred_at=datetime(2026,10,25,22,30,tzinfo=utc_timezone.utc))
            import_module('core.migrations.0209_portal_deposit_date').backfill_dates(apps, SimpleNamespace(connection=connection))
            farmer.refresh_from_db()
            self.assertEqual(farmer.hb_deposit_date, expected)
