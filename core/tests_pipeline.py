"""
Unit tests for the JBL Pipeline Portal and its services.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import GroupSheetConfiguration, JawabuFarmerMaster, LiveSheetRecordChange
from core.services.jawabu_pipeline import (
    assign_order,
    credit_queue,
    deferred_queue,
    jbl_visit_queue,
    log_jbl_visit,
    pipeline_counts,
    requisition_queue,
    set_credit_decision,
)


class JblPipelineServiceTestCase(TestCase):
    """Test suite for the jawabu_pipeline service queue and write functions."""

    def setUp(self):
        # Create standard test config
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-1003701615384',
            sheet_id='1VFRZgbux8crsjAvH7Cn-F5NZdG-dz3E2aB2vhJV_0hg',
            sheet_name='Master Data',
            enabled=True,
            workflow={
                'type': 'jawabu',
                'master_sync_enabled': True,
                'master_sheet_id': '1VFRZgbux8crsjAvH7Cn-F5NZdG-dz3E2aB2vhJV_0hg',
                'master_sheet_name': 'Master Data',
            },
        )

        # Stage 1: HB Visited
        self.farmer_stage1 = JawabuFarmerMaster.objects.create(
            customer_name='Farmer One',
            national_id='11111111',
            primary_phone='254711111111',
            sign_date='24-June-2026',
            status='active',
        )

        # Stage 2: JBL Visited
        self.farmer_stage2 = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Two',
            national_id='22222222',
            primary_phone='254722222222',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25),
            jbl_officer='Officer Bob',
            jbl_visit_status='Awaiting Analysis',
            status='active',
        )

        # Stage 3: Credit Approved
        self.farmer_stage3 = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Three',
            national_id='33333333',
            primary_phone='254733333333',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25),
            jbl_officer='Officer Bob',
            jbl_visit_status='Approved - Paid',
            credit_decision='Approved',
            status='active',
        )

        # Stage 4: Ordered
        self.farmer_stage4 = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Four',
            national_id='44444444',
            primary_phone='254744444444',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25),
            jbl_officer='Officer Bob',
            jbl_visit_status='Approved - Paid',
            credit_decision='Approved',
            order_number='JBL-2026-004',
            requisition_date=date(2026, 6, 26),
            status='active',
        )

    def test_jbl_visit_queue(self):
        """Verify that jbl_visit_queue only returns Stage 1 (HB visited but JBL not)."""
        queue = list(jbl_visit_queue())
        self.assertIn(self.farmer_stage1, queue)
        self.assertNotIn(self.farmer_stage2, queue)
        self.assertNotIn(self.farmer_stage3, queue)
        self.assertNotIn(self.farmer_stage4, queue)

    def test_credit_queue(self):
        """Verify that credit_queue only returns Stage 2 (JBL visited but credit decision not set)."""
        queue = list(credit_queue())
        self.assertNotIn(self.farmer_stage1, queue)
        self.assertIn(self.farmer_stage2, queue)
        self.assertNotIn(self.farmer_stage3, queue)
        self.assertNotIn(self.farmer_stage4, queue)

    def test_requisition_queue(self):
        """Verify that requisition_queue only returns Stage 3 (Credit Approved but no Order No)."""
        queue = list(requisition_queue())
        self.assertNotIn(self.farmer_stage1, queue)
        self.assertNotIn(self.farmer_stage2, queue)
        self.assertIn(self.farmer_stage3, queue)
        self.assertNotIn(self.farmer_stage4, queue)

    def test_pipeline_counts(self):
        """Verify counts computed for the dashboard."""
        counts = pipeline_counts()
        self.assertEqual(counts['jbl_queue'], 1)
        self.assertEqual(counts['credit_queue'], 1)
        self.assertEqual(counts['requisition_queue'], 1)
        self.assertEqual(counts['total'], 4)

    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_log_jbl_visit(self, mock_sync):
        """Verify Advance from Stage 1 to Stage 2."""
        ok, error = log_jbl_visit(
            self.farmer_stage1,
            visit_date=date(2026, 6, 28),
            officer='Officer Joe',
            visit_status='Awaiting Analysis',
            comment='Ready for credit review',
        )
        self.assertTrue(ok)
        self.assertEqual(error, '')
        self.assertEqual(self.farmer_stage1.jbl_visit_status, 'Awaiting Analysis')
        self.assertEqual(self.farmer_stage1.jbl_officer, 'Officer Joe')
        self.assertEqual(self.farmer_stage1.jbl_visit_date, date(2026, 6, 28))
        self.assertEqual(self.farmer_stage1.jbl_visit_comment, 'Ready for credit review')
        mock_sync.assert_called_once_with(self.farmer_stage1)

    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    @patch('core.services.jawabu_pipeline._notify_credit_approved')
    def test_set_credit_decision(self, mock_notify, mock_sync):
        """Verify credit decision update and notification trigger."""
        ok, error = set_credit_decision(self.farmer_stage2, decision='Approved', sender='analyst_1')
        self.assertTrue(ok)
        self.assertEqual(self.farmer_stage2.credit_decision, 'Approved')
        self.assertEqual(self.farmer_stage2.credit_decided_by, 'analyst_1')
        mock_sync.assert_called_once_with(self.farmer_stage2)
        mock_notify.assert_called_once_with(self.farmer_stage2)

    def test_assign_order_gate_enforcement(self):
        """Verify credit approval gate block (cannot assign order to Stage 2)."""
        ok, error = assign_order(self.farmer_stage2, order_number='JBL-9999')
        self.assertFalse(ok)
        self.assertIn('not Approved', error)
        self.assertEqual(self.farmer_stage2.order_number, '')


class JblPipelineApiTestCase(TestCase):
    """Test suite for the portal Mini App API endpoints."""

    def setUp(self):
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Pipeline test farmer',
            national_id='99999999',
            primary_phone='254799999999',
            sign_date='24-June-2026',
            status='active',
        )

    def test_portal_home_render(self):
        """Verify that the home page view resolves and renders the template."""
        response = self.client.get(reverse('portal_home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'portal/portal.html')

    def test_dashboard_api(self):
        """Verify GET /api/portal/dashboard/ counts."""
        response = self.client.get(reverse('portal_dashboard'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['counts']['jbl_queue'], 1)

    def test_log_jbl_visit_api(self):
        """Verify API POST /api/portal/jbl-queue/<id>/ logs visit and advances pipeline."""
        payload = {
            'visit_date': '2026-07-01',
            'visit_status': 'Awaiting Analysis',
            'officer': 'JBL Officer Alpha',
            'comment': 'Good soil conditions',
            'latitude': -1.2921,
            'longitude': 36.8219,
        }
        url = reverse('portal_log_jbl_visit', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.jbl_visit_status, 'Awaiting Analysis')
        self.assertEqual(self.farmer.jbl_officer, 'JBL Officer Alpha')
        self.assertEqual(self.farmer.jbl_visit_date, date(2026, 7, 1))
        self.assertEqual(self.farmer.latitude, '-1.2921')
        self.assertEqual(self.farmer.longitude, '36.8219')
        self.assertEqual(self.farmer.gps_link, 'https://maps.google.com/?q=-1.2921,36.8219')


    def test_set_credit_decision_api(self):
        """Verify Stage 3 credit decision posting."""
        self.farmer.jbl_visit_date = date(2026, 7, 1)
        self.farmer.jbl_visit_status = 'Approved - Paid'
        self.farmer.save()

        payload = {'decision': 'Approved'}
        url = reverse('portal_set_credit_decision', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.credit_decision, 'Approved')

    def test_assign_order_gate_fails_on_unapproved(self):
        """Verify requisition posting fails with 403 on credit not approved."""
        # Farmer is Stage 1 (not credit-approved)
        payload = {'order_number': 'JBL-2026-X1', 'requisition_date': '2026-07-02'}
        url = reverse('portal_assign_order', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['ok'], False)

    def test_assign_order_succeeds_on_approved(self):
        """Verify requisition posting succeeds when credit is approved."""
        self.farmer.credit_decision = 'Approved'
        self.farmer.save()

        payload = {'order_number': 'JBL-2026-X1', 'requisition_date': '2026-07-02'}
        url = reverse('portal_assign_order', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, 'JBL-2026-X1')
        self.assertEqual(self.farmer.requisition_date, date(2026, 7, 2))

    def test_fca_officer_extraction_and_db_upsert(self):
        """Verify extract_officer parses headers and sync_fcaup_records_to_master_data upserts DB."""
        from core.services.fca import extract_officer, sync_fcaup_records_to_master_data
        from core.models import FcaImportRecord, JawabuFarmerMaster
        from unittest.mock import patch

        # 1. Test extract_officer
        mock_rows = [
            (1, ['', 'Field Officer / BRO:', 'Officer John', '']),
            (2, ['', 'HUB:', 'Nyeri', '']),
        ]
        officer = extract_officer(mock_rows)
        self.assertEqual(officer, 'Officer John')

        # 2. Test DB Upsert
        # Create a database record for farmer to match by phone
        db_farmer = JawabuFarmerMaster.objects.create(
            customer_name='JOHN SMITH',
            primary_phone='+254712345678',
            status='active',
        )

        # Create standard test config for GroupSheetConfiguration
        config = GroupSheetConfiguration.objects.create(
            group_id='-1003701615384',
            sheet_id='1VFRZgbux8crsjAvH7Cn-F5NZdG-dz3E2aB2vhJV_0hg',
            sheet_name='Master Data',
            enabled=True,
            workflow={
                'type': 'jawabu',
                'master_sync_enabled': True,
                'master_sheet_id': '1VFRZgbux8crsjAvH7Cn-F5NZdG-dz3E2aB2vhJV_0hg',
                'master_sheet_name': 'Master Data',
                'fca_master_header_row': 3,
                'fca_master_data_start_row': 5,
            },
        )

        # Create FcaImportRecord simulating a review batch commit
        record = FcaImportRecord.objects.create(
            group_id=config.group_id,
            customer_name='JOHN SMITH',
            primary_phone='+254712345678',
            fca_visit_date=date(2026, 7, 5),
            fca_decision='Approved - Paid',
            fca_comment='A comment',
            import_status='pending',
            parsed_fields={
                'jbl_officer': 'Officer John',
                'id_number': '',
                'primary_phone': '254712345678',
            }
        )

        with patch('core.services.sheets.GoogleSheetsService.get_instance') as mock_sheets:
            from core.tests import FakeMasterDataSheet, FakeJawabuService
            headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Jawabu Visit Date', 'Jawabu Comment After visit', 'Additional Comments', 'JBL BRO']
            fake_sheet = FakeMasterDataSheet(headers, [
                '1', 'JOHN SMITH', '', '254712345678', '', '', '', ''
            ])
            mock_sheets.return_value = FakeJawabuService(fake_sheet)

            res = sync_fcaup_records_to_master_data(config, [record])
            self.assertEqual(res['updated'], 1)

        # Check that the database record got updated (DB consistency check)
        db_farmer.refresh_from_db()
        self.assertEqual(db_farmer.jbl_officer, 'Officer John')
        self.assertEqual(db_farmer.jbl_visit_status, 'Approved - Paid')
        self.assertEqual(db_farmer.jbl_visit_comment, 'A comment')
        self.assertEqual(db_farmer.jbl_visit_date, date(2026, 7, 5))

