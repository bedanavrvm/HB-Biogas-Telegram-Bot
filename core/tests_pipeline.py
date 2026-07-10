"""
Unit tests for the JBL Pipeline Portal and its services.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import GroupSheetConfiguration, JawabuFarmerMaster, LiveSheetRecordChange, RequisitionBatch
from core.services.jawabu_pipeline import (
    assign_order,
    credit_queue,
    deferred_queue,
    final_review_queue,
    jbl_visit_queue,
    log_jbl_visit,
    pipeline_counts,
    requisition_queue,
    set_credit_decision,
    set_final_decision,
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

        # Stage 3: Credit Approved, awaiting Head of Rural final review
        self.farmer_stage_review = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Review',
            national_id='33333332',
            primary_phone='254733333332',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25),
            jbl_officer='Officer Bob',
            jbl_visit_status='Approved',
            credit_decision='Approved',
            imab_created='Yes',
            customer_no='15118',
            status='active',
        )

        # Stage 4: Final approved, awaiting order
        self.farmer_stage3 = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Three',
            national_id='33333333',
            primary_phone='254733333333',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25),
            jbl_officer='Officer Bob',
            jbl_visit_status='Approved',
            credit_decision='Approved',
            imab_created='Yes',
            customer_no='15119',
            final_decision='Approved',
            status='active',
        )

        # Stage 5: Ordered
        self.farmer_stage4 = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Four',
            national_id='44444444',
            primary_phone='254744444444',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25),
            jbl_officer='Officer Bob',
            jbl_visit_status='Approved',
            credit_decision='Approved',
            imab_created='Yes',
            customer_no='15120',
            final_decision='Approved',
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
        self.assertNotIn(self.farmer_stage_review, queue)
        self.assertNotIn(self.farmer_stage3, queue)
        self.assertNotIn(self.farmer_stage4, queue)

    def test_final_review_queue(self):
        """Verify final review queue only returns BRO analysis-complete records."""
        queue = list(final_review_queue())
        self.assertNotIn(self.farmer_stage1, queue)
        self.assertNotIn(self.farmer_stage2, queue)
        self.assertIn(self.farmer_stage_review, queue)
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
        self.assertEqual(counts['final_review_queue'], 1)
        self.assertEqual(counts['requisition_queue'], 1)
        self.assertEqual(counts['total'], 5)

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

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_set_credit_decision(self, mock_sync, mock_order_sync):
        """Verify credit decision update and notification trigger."""
        ok, error = set_credit_decision(
            self.farmer_stage2,
            decision='Approved',
            imab_created='Yes',
            customer_no='15121',
            sender='analyst_1',
        )
        self.assertTrue(ok)
        self.assertEqual(self.farmer_stage2.credit_decision, 'Approved')
        self.assertEqual(self.farmer_stage2.imab_created, 'Yes')
        self.assertEqual(self.farmer_stage2.customer_no, '15121')
        self.assertEqual(self.farmer_stage2.credit_decided_by, 'analyst_1')
        mock_sync.assert_called_once_with(self.farmer_stage2)
        mock_order_sync.assert_called_once_with(self.farmer_stage2)

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    @patch('core.services.jawabu_pipeline._notify_final_approved')
    def test_set_final_decision(self, mock_notify, mock_sync, mock_order_sync):
        """Verify Head of Rural final decision update and notification trigger."""
        ok, error = set_final_decision(
            self.farmer_stage_review,
            final_decision='Approved',
            decision_comment='Called and approved',
            sender='head_rural',
        )
        self.assertTrue(ok)
        self.assertEqual(error, '')
        self.assertEqual(self.farmer_stage_review.final_decision, 'Approved')
        self.assertEqual(self.farmer_stage_review.final_decision_comment, 'Called and approved')
        self.assertEqual(self.farmer_stage_review.final_decided_by, 'head_rural')
        mock_sync.assert_called_once_with(self.farmer_stage_review)
        mock_order_sync.assert_called_once_with(self.farmer_stage_review)
        mock_notify.assert_called_once_with(self.farmer_stage_review)

    def test_assign_order_gate_enforcement(self):
        """Verify credit approval gate block (cannot assign order to Stage 2)."""
        ok, error = assign_order(self.farmer_stage2, order_number='JBL-9999')
        self.assertFalse(ok)
        self.assertIn('not Approved', error)
        self.assertEqual(self.farmer_stage2.order_number, '')


class PortalMiniAppAuthTestCase(TestCase):
    def _signed_init_data(self, token='test-token'):
        import hashlib
        import hmac
        import time
        from urllib.parse import urlencode

        payload = {
            'auth_date': str(int(time.time())),
            'query_id': 'portal-test-query',
            'user': json.dumps({'id': 12345, 'first_name': 'Portal', 'last_name': 'User'}, separators=(',', ':')),
        }
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(payload.items())
        )
        secret_key = hmac.new(b'WebAppData', token.encode('utf-8'), hashlib.sha256).digest()
        payload['hash'] = hmac.new(
            secret_key,
            data_check_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        return urlencode(payload)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token')
    def test_portal_api_rejects_missing_telegram_init_data(self):
        response = self.client.get(reverse('portal_dashboard'))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        self.assertIn('authentication data is missing', response.json()['error'])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token')
    def test_portal_api_accepts_valid_telegram_init_data(self):
        response = self.client.get(
            reverse('portal_dashboard'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

@override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
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


    @patch('core.services.jawabu_pipeline.append_jbl_media_links')
    def test_upload_jbl_media_api(self, mock_upload):
        """Verify JBL visit media upload endpoint accepts files and returns stored counts."""
        mock_upload.return_value = (
            True,
            '',
            {'stored_count': 1, 'skipped_count': 0, 'warnings': [], 'links': ['https://drive.example/file']},
        )
        upload = SimpleUploadedFile('visit.jpg', b'image-bytes', content_type='image/jpeg')
        url = reverse('portal_upload_jbl_media', args=[self.farmer.id])
        response = self.client.post(url, {'files': upload})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['stored_count'], 1)
        mock_upload.assert_called_once()

    def test_set_credit_decision_api(self):
        """Verify Stage 3 credit decision posting."""
        self.farmer.jbl_visit_date = date(2026, 7, 1)
        self.farmer.jbl_visit_status = 'Approved'
        self.farmer.save()

        payload = {'decision': 'Approved', 'imab_created': 'Yes', 'customer_no': '15122'}
        url = reverse('portal_set_credit_decision', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.credit_decision, 'Approved')
        self.assertEqual(self.farmer.imab_created, 'Yes')
        self.assertEqual(self.farmer.customer_no, '15122')

    def test_set_final_decision_api(self):
        """Verify Head of Rural final review stores decision and after-call comments."""
        self.farmer.jbl_visit_date = date(2026, 7, 1)
        self.farmer.jbl_visit_status = 'Approved'
        self.farmer.credit_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15123'
        self.farmer.save()

        payload = {
            'final_decision': 'Approved',
            'decision_comment': 'Called client; ready for order.',
        }
        url = reverse('portal_set_final_decision', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.final_decision, 'Approved')
        self.assertEqual(self.farmer.final_decision_comment, 'Called client; ready for order.')

    def test_assign_order_gate_fails_on_unapproved(self):
        """Verify requisition posting fails with 403 on credit not approved."""
        # Farmer is Stage 1 (not finally approved)
        payload = {'order_number': 'JBL-2026-X1', 'requisition_date': '2026-07-02'}
        url = reverse('portal_assign_order', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['ok'], False)

    def test_assign_order_succeeds_on_approved(self):
        """Verify requisition posting succeeds when credit is approved."""
        self.farmer.final_decision = 'Approved'
        self.farmer.save()

        payload = {'order_number': 'JBL-2026-X1', 'requisition_date': '2026-07-02'}
        url = reverse('portal_assign_order', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, 'JBL-2026-X1')
        self.assertEqual(self.farmer.requisition_date, date(2026, 7, 2))

    def test_portal_requisition_preview_reports_ready_clients(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()
        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-PREVIEW-1',
            'requisition_date': '2026-07-06',
        }
        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['ready_count'], 1)
        self.assertEqual(data['blocked_count'], 0)

    def test_portal_requisition_preview_blocks_missing_customer_no(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = ''
        self.farmer.save()
        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-PREVIEW-2',
            'requisition_date': '2026-07-06',
        }
        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['ready_count'], 0)
        self.assertEqual(data['blocked_count'], 1)
        self.assertIn('Customer No', data['blocked'][0]['missing'])

    @patch('core.services.requisition.generate_requisition_excel', return_value=b'xlsx-bytes')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_portal_requisition_generate_success(self, mock_sync, mock_generate):
        """Verify requisition generation view succeeds and downloads Excel file."""
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()

        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-BATCH-99',
            'requisition_date': '2026-07-06',
            'return_url': True,
        }
        url = reverse('portal_requisition_generate')
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['filename'], 'JBL_Requisition_Form_REQ-BATCH-99.xlsx')
        self.assertIn('/api/portal/requisition-batches/REQ-BATCH-99/download/', data['download_url'])
        self.assertTrue(RequisitionBatch.objects.filter(order_number='REQ-BATCH-99').exists())

        download_response = self.client.get(data['download_url'])
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            download_response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('attachment; filename="JBL_Requisition_Form_REQ-BATCH-99.xlsx"', download_response['Content-Disposition'])

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, 'REQ-BATCH-99')
        self.assertEqual(self.farmer.requisition_date, date(2026, 7, 6))
        mock_sync.assert_called_once_with(self.farmer)
        mock_generate.assert_called_once()

    def test_portal_requisition_batch_detail_and_download(self):
        self.farmer.order_number = 'REQ-DETAIL-1'
        self.farmer.requisition_date = date(2026, 7, 6)
        self.farmer.final_decision = 'Approved'
        self.farmer.save()
        RequisitionBatch.objects.create(
            order_number='REQ-DETAIL-1',
            requisition_date=date(2026, 7, 6),
            filename='JBL_Requisition_Form_REQ-DETAIL-1.xlsx',
            file_content=b'xlsx-bytes',
            farmer_ids=[str(self.farmer.id)],
            farmer_count=1,
        )

        detail = self.client.get(reverse('portal_requisition_batch_detail', args=['REQ-DETAIL-1']))
        self.assertEqual(detail.status_code, 200)
        detail_data = detail.json()
        self.assertTrue(detail_data['ok'])
        self.assertEqual(detail_data['batch']['order_number'], 'REQ-DETAIL-1')
        self.assertEqual(len(detail_data['batch']['farmers']), 1)

        download = self.client.get(reverse('portal_requisition_batch_download', args=['REQ-DETAIL-1']))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b'xlsx-bytes')

    @override_settings(BASE_DIR='C:/tmp/no-requisition-template')
    def test_portal_requisition_generate_reports_missing_template(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()
        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-BATCH-99',
            'requisition_date': '2026-07-06'
        }

        response = self.client.post(
            reverse('portal_requisition_generate'),
            json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertIn('requisition Excel template', data['error'])
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, '')
        self.assertIsNone(self.farmer.requisition_date)

    def test_portal_requisition_generate_fails_on_unapproved(self):
        """Verify requisition generation fails with 403 on unapproved credit decision."""
        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-BATCH-99',
            'requisition_date': '2026-07-06'
        }
        url = reverse('portal_requisition_generate')
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertIn('not ready for requisition', response.json()['error'])

    def test_portal_requisition_batches(self):
        """Verify that the requisition batches view correctly lists unique batches."""
        self.farmer.credit_decision = 'Approved'
        self.farmer.order_number = 'BATCH-ORDER-123'
        self.farmer.requisition_date = date(2026, 7, 7)
        self.farmer.save()

        url = reverse('portal_requisition_batches')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['batches']), 1)
        self.assertEqual(data['batches'][0]['order_number'], 'BATCH-ORDER-123')
        self.assertEqual(data['batches'][0]['farmer_count'], 1)
        self.assertEqual(data['batches'][0]['farmers'][0]['id'], str(self.farmer.id))

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
            fca_decision='Approved',
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
        self.assertEqual(db_farmer.jbl_visit_status, 'Approved')
        self.assertEqual(db_farmer.jbl_visit_comment, 'A comment')
        self.assertEqual(db_farmer.jbl_visit_date, date(2026, 7, 5))

    @override_settings(INVOICE_UPLOAD_MAX_FILE_SIZE_MB=1)
    def test_invoice_upload_rejects_file_over_configured_limit(self):
        from core.api.portal_views import portal_upload_batch_invoices

        request = RequestFactory().post(
            '/api/portal/requisition-batches/upload-invoices/',
            {
                'order_number': 'B-1234',
                'file': SimpleUploadedFile('invoices.pdf', b'x' * (1024 * 1024 + 1), content_type='application/pdf'),
            },
        )

        response = portal_upload_batch_invoices(request)
        payload = json.loads(response.content.decode('utf-8'))

        self.assertEqual(response.status_code, 413)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['max_file_size_mb'], 1)
        self.assertIn('too large', payload['error'])

    @patch('core.services.invoice_parser.match_and_update_invoices')
    def test_invoice_upload_updates_requisition_batch_status(self, mock_match):
        from core.api.portal_views import portal_upload_batch_invoices

        self.farmer.order_number = 'B-1234'
        self.farmer.save(update_fields=['order_number'])
        RequisitionBatch.objects.create(
            order_number='B-1234',
            farmer_ids=[str(self.farmer.id)],
            farmer_count=1,
            filename='JBL_Requisition_Form_B-1234.xlsx',
            file_content=b'xlsx-bytes',
        )

        def mark_invoice(order_number, pdf_bytes):
            self.farmer.invoice_number = 'INV-1'
            self.farmer.save(update_fields=['invoice_number'])
            return {'ok': True, 'total_parsed': 1, 'matched_count': 1, 'candidate_count': 1}

        mock_match.side_effect = mark_invoice
        request = RequestFactory().post(
            '/api/portal/requisition-batches/upload-invoices/',
            {
                'order_number': 'B-1234',
                'file': SimpleUploadedFile('invoices.pdf', b'%PDF-1.4', content_type='application/pdf'),
            },
        )

        response = portal_upload_batch_invoices(request)
        payload = json.loads(response.content.decode('utf-8'))
        batch = RequisitionBatch.objects.get(order_number='B-1234')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual(batch.status, 'completed')
        self.assertEqual(batch.invoice_summary['matched_count'], 1)
        self.assertEqual(batch.invoice_summary['pending_invoice_count'], 0)
        self.assertEqual(batch.last_invoice_result['total_parsed'], 1)

    @patch('core.services.invoice_parser.PdfReader')
    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_invoice_matching_updates_farmer_and_syncs(self, mock_get_sheets, mock_pdf_reader):
        from decimal import Decimal
        from core.services.invoice_parser import match_and_update_invoices
        from core.tests import FakeMasterDataSheet, FakeJawabuService

        # Setup mock sheet service
        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Invoice Number', 'Invoice Date', 'Invoice Amount', 'Discount', 'Payment', 'Balance Due']
        fake_sheet = FakeMasterDataSheet(headers, [
            '1', 'DAVID MUGAMBI', '23215888', '254712345678', '', '', '', '', '', ''
        ])
        mock_get_sheets.return_value = FakeJawabuService(fake_sheet)

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
                'master_header_row': 3,
                'master_data_start_row': 5,
            },
        )

        # Setup a farmer record with order_number = 'B-1234'
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='DAVID MUGAMBI',
            national_id='23215888',
            primary_phone='+254712345678',
            order_number='B-1234',
            status='active'
        )

        # Setup mock PDF pages â€” stacked format (label then value on next line)
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "HOMEBIOGAS VENTURES LIMITED\n"
            "BILL TO\n"
            "DAVID MUGAMBI\n"
            "23215888\n"
            "0712345678\n"
            "DUE DATE\n"
            "INV-2026-999\n"
            "15-Jun-2026\n"
            "Terms\n"
            "15-Jun-2026\n"
            "DESCRIPTION\n"
            "HomeBiogas 2.0 System\n"
            "SERIAL NUMBER\n"
            "HB20-100223\n"
            "QTY\n"
            "1\n"
            "RATE\n"
            "KES 89,900.00\n"
            "AMOUNT\n"
            "KES 89,900.00\n"
            "SUBTOTAL\n"
            "KES 89,900.00\n"
            "DISCOUNT\n"
            "KES 5,000.00\n"
            "TOTAL\n"
            "KES 84,900.00\n"
            "PAYMENT\n"
            "KES 10,000.00\n"
            "BALANCE DUE\n"
            "KES 74,900.00\n"
        )
        mock_pdf_reader.return_value.pages = [mock_page]

        # Process the invoices
        res = match_and_update_invoices('B-1234', b'dummy_pdf_bytes')
        
        self.assertTrue(res['ok'])
        self.assertEqual(res['matched_count'], 1)
        self.assertEqual(res['total_parsed'], 1)
        self.assertEqual(res['results'][0]['status'], 'Matched')

        # Check DB updates
        farmer.refresh_from_db()
        self.assertEqual(farmer.invoice_number, 'INV-2026-999')
        self.assertEqual(farmer.invoice_date, date(2026, 6, 15))
        self.assertEqual(farmer.invoice_amount, Decimal('89900.00'))
        self.assertEqual(farmer.discount, Decimal('5000.00'))
        self.assertEqual(farmer.payment, Decimal('10000.00'))
        self.assertEqual(farmer.balance_due, Decimal('74900.00'))

        # Check Google Sheets updates
        row = fake_sheet.values[4]
        self.assertEqual(row[4], 'INV-2026-999')
        self.assertEqual(row[5], '15-June-2026')
        self.assertEqual(row[6], 89900)
        self.assertEqual(row[7], 5000)
        self.assertEqual(row[8], 10000)
        self.assertEqual(row[9], 74900)

    @patch('core.services.invoice_parser.PdfReader')
    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_invoice_inline_format_real_pdf_layout(self, mock_get_sheets, mock_pdf_reader):
        """Regression test: parse the real #076.pdf inline-label format."""
        from decimal import Decimal
        from core.services.invoice_parser import match_and_update_invoices
        from core.tests import FakeMasterDataSheet, FakeJawabuService

        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Invoice Number', 'Invoice Date', 'Invoice Amount', 'Discount', 'Payment', 'Balance Due']
        fake_sheet = FakeMasterDataSheet(headers, [
            '1', 'ALICEBETTY KIMOTHO', '2476584', '254721929868', '', '', '', '', '', ''
        ])
        mock_get_sheets.return_value = FakeJawabuService(fake_sheet)

        GroupSheetConfiguration.objects.create(
            group_id='-1003701615384',
            sheet_id='1VFRZgbux8crsjAvH7Cn-F5NZdG-dz3E2aB2vhJV_0hg',
            sheet_name='Master Data',
            enabled=True,
            workflow={
                'type': 'jawabu',
                'master_sync_enabled': True,
                'master_sheet_id': '1VFRZgbux8crsjAvH7Cn-F5NZdG-dz3E2aB2vhJV_0hg',
                'master_sheet_name': 'Master Data',
                'master_header_row': 3,
                'master_data_start_row': 5,
            },
        )

        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Alicebetty Kimotho',
            national_id='2476584',
            primary_phone='+254721929868',
            order_number='076',
            status='active'
        )

        # Inline format â€” matches actual #076.pdf output
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Page 1 of 1\n"
            "HOMEBIOGAS VENTURES LIMITED\n"
            "P.O Box 11500\n"
            "Kiambu, Kenya  900 KE\n"
            "+254797878853\n"
            "hbg.kenya@homebiogas.com\n"
            "Govt. UID P052063409Q\n"
            "INVOICE\n"
            "BILL TO\n"
            "Alicebetty Kimotho\n"
            "+254721929868\n"
            "2476584\n"
            "Kenya\n"
            "INVOICE 9505\n"
            "DATE 16/03/2026\n"
            "TERMS Net 30\n"
            "DUE DATE 15/04/2026\n"
            "DESCRIPTION SERIAL NUMBER QTY RATE AMOUNT\n"
            "HBG Complete Farmer's System 1106112511402 1 54,000.00 54,000.00\n"
            "We appreciate your business. SUBTOTAL 54,000.00\n"
            "DISCOUNT -3,000.00\n"
            "TOTAL 51,000.00\n"
            "PAYMENT 5,000.00\n"
            "BALANCE DUE KES 46,000.00\n"
        )
        mock_pdf_reader.return_value.pages = [mock_page]
        from core.services.invoice_parser import parse_invoice_text
        parsed = parse_invoice_text(mock_page.extract_text.return_value, 1)
        self.assertEqual(parsed['balance_due'], '46,000.00')
        self.assertEqual(parsed['calculated_balance_due'], '46000.00')
        self.assertEqual(parsed['discount'], '3000.00')
        self.assertEqual(parsed['balance_due_check'], 'OK')

        res = match_and_update_invoices('076', b'dummy')
        self.assertTrue(res['ok'], msg=str(res))
        self.assertEqual(res['matched_count'], 1)
        self.assertEqual(res['results'][0]['status'], 'Matched')

        farmer.refresh_from_db()
        self.assertEqual(farmer.invoice_number, '9505')
        self.assertEqual(farmer.invoice_amount, Decimal('54000.00'))
        self.assertEqual(farmer.discount, Decimal('3000.00'))
        self.assertEqual(farmer.payment, Decimal('5000.00'))
        self.assertEqual(farmer.balance_due, Decimal('46000.00'))

    @patch('core.services.invoice_parser.PdfReader')
    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_invoice_duplicate_identifier_is_not_auto_matched(self, mock_get_sheets, mock_pdf_reader):
        from core.services.invoice_parser import match_and_update_invoices
        from core.tests import FakeMasterDataSheet, FakeJawabuService

        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Invoice Number']
        fake_sheet = FakeMasterDataSheet(headers, [])
        mock_get_sheets.return_value = FakeJawabuService(fake_sheet)

        GroupSheetConfiguration.objects.create(
            group_id='-1003701615384',
            sheet_id='sheet',
            sheet_name='Master Data',
            enabled=True,
            workflow={
                'type': 'jawabu',
                'master_sync_enabled': True,
                'master_sheet_id': 'sheet',
                'master_sheet_name': 'Master Data',
            },
        )
        first = JawabuFarmerMaster.objects.create(
            customer_name='ALICEBETTY KIMOTHO',
            national_id='2476584',
            primary_phone='254700000001',
            order_number='076',
            status='active',
        )
        second = JawabuFarmerMaster.objects.create(
            customer_name='ALICEBETTY KIMOTHO',
            national_id='2476584',
            primary_phone='254700000002',
            order_number='076',
            status='active',
        )

        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Page 1 of 1\n"
            "HOMEBIOGAS VENTURES LIMITED\n"
            "BILL TO\n"
            "Alicebetty Kimotho\n"
            "2476584\n"
            "Kenya\n"
            "INVOICE 9505\n"
            "DATE 16/03/2026\n"
            "TOTAL 51,000.00\n"
            "PAYMENT 5,000.00\n"
            "BALANCE DUE KES 46,000.00\n"
        )
        mock_pdf_reader.return_value.pages = [mock_page]
        from core.services.invoice_parser import parse_invoice_text
        parsed = parse_invoice_text(mock_page.extract_text.return_value, 1)
        self.assertEqual(parsed['balance_due'], '46,000.00')
        self.assertEqual(parsed['calculated_balance_due'], '46000.00')
        self.assertEqual(parsed['balance_due_check'], 'OK')

        res = match_and_update_invoices('076', b'dummy')

        self.assertFalse(res['ok'], msg=str(res))
        self.assertEqual(res['matched_count'], 0)
        self.assertEqual(res['results'][0]['status'], 'Ambiguous')
        self.assertIn('Multiple farmers matched by National ID', res['results'][0]['reason'])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.invoice_number, '')
        self.assertEqual(second.invoice_number, '')


    @patch('core.services.invoice_parser.PdfReader')
    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_invoice_sheet_sync_failure_fails_upload_and_rolls_back_db(self, mock_get_sheets, mock_pdf_reader):
        from core.services.invoice_parser import match_and_update_invoices
        from core.tests import FakeMasterDataSheet, FakeJawabuService

        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Invoice Number']
        fake_sheet = FakeMasterDataSheet(headers, [])
        mock_get_sheets.return_value = FakeJawabuService(fake_sheet)

        GroupSheetConfiguration.objects.create(
            group_id='-1003701615384',
            sheet_id='sheet',
            sheet_name='Master Data',
            enabled=True,
            workflow={
                'type': 'jawabu',
                'master_sync_enabled': True,
                'master_sheet_id': 'sheet',
                'master_sheet_name': 'Master Data',
                'master_header_row': 3,
                'master_data_start_row': 5,
            },
        )
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='ALICEBETTY KIMOTHO',
            national_id='2476584',
            primary_phone='254721929868',
            order_number='076',
            status='active',
        )

        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Page 1 of 1\n"
            "HOMEBIOGAS VENTURES LIMITED\n"
            "BILL TO\n"
            "Alicebetty Kimotho\n"
            "+254721929868\n"
            "2476584\n"
            "Kenya\n"
            "INVOICE 9505\n"
            "DATE 16/03/2026\n"
            "TOTAL 51,000.00\n"
            "PAYMENT 5,000.00\n"
            "BALANCE DUE KES 46,000.00\n"
        )
        mock_pdf_reader.return_value.pages = [mock_page]
        from core.services.invoice_parser import parse_invoice_text
        parsed = parse_invoice_text(mock_page.extract_text.return_value, 1)
        self.assertEqual(parsed['balance_due'], '46,000.00')
        self.assertEqual(parsed['calculated_balance_due'], '46000.00')
        self.assertEqual(parsed['balance_due_check'], 'OK')

        res = match_and_update_invoices('076', b'dummy')

        self.assertFalse(res['ok'], msg=str(res))
        self.assertEqual(res['matched_count'], 0)
        self.assertEqual(res['results'][0]['status'], 'Sync failed')
        self.assertIn('Google Sheet sync failed', res['error'])
        farmer.refresh_from_db()
        self.assertEqual(farmer.invoice_number, '')
        self.assertIsNone(farmer.invoice_date)
        self.assertIsNone(farmer.invoice_amount)

    @patch('core.services.invoice_parser.PdfReader')
    def test_invoice_unmatched_reports_possible_match_outside_selected_order(self, mock_pdf_reader):
        from core.services.invoice_parser import match_and_update_invoices

        farmer = JawabuFarmerMaster.objects.create(
            customer_name='ALICEBETTY KIMOTHO',
            national_id='2476584',
            primary_phone='254721929868',
            order_number='OTHER-ORDER',
            status='active',
        )

        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Page 1 of 1\n"
            "HOMEBIOGAS VENTURES LIMITED\n"
            "BILL TO\n"
            "Alicebetty Kimotho\n"
            "+254721929868\n"
            "2476584\n"
            "Kenya\n"
            "INVOICE 9505\n"
            "DATE 16/03/2026\n"
            "TOTAL 51,000.00\n"
            "PAYMENT 5,000.00\n"
            "BALANCE DUE KES 46,000.00\n"
        )
        mock_pdf_reader.return_value.pages = [mock_page]

        res = match_and_update_invoices('SELECTED-ORDER', b'dummy')

        self.assertFalse(res['ok'], msg=str(res))
        self.assertEqual(res['matched_count'], 0)
        self.assertEqual(res['candidate_count'], 0)
        self.assertEqual(res['results'][0]['status'], 'Unmatched')
        self.assertIn('outside the selected batch/order', res['results'][0]['reason'])
        self.assertEqual(res['results'][0]['parsed_national_id'], '2476584')
        self.assertEqual(res['results'][0]['outside_batch_matches'][0]['farmer_id'], str(farmer.id))
        self.assertEqual(res['results'][0]['outside_batch_matches'][0]['order_number'], 'OTHER-ORDER')

    def test_invoice_parser_handles_glued_pdf_labels_from_render_log(self):
        from core.services.invoice_parser import parse_invoice_text

        text = (
            "Page 1 of 1HOMEBIOGAS VENTURES LIMITED "
            "P.O Box 11500 Kiambu, Kenya 900 KE +254797878853 "
            "hbg.kenya@homebiogas.com Govt. UID P052063409Q INVOICE "
            "BILL TO Peter Gitahi Karuba +254726682896 22181007 KenyaINVOICE 10029 "
            "DATE 20/05/2026 TERMS Net 30 DUE DATE 19/06/2026 "
            "DESCRIPTION SERIAL NUMBER QTY RATE AMOUNT "
            "HBG Complete Farmer's System 1106112511402 1 54,000.00 54,000.00 "
            "We appreciate your business and look forward to serving you again. SUBTOTAL 54,000.00 "
            "DISCOUNT -3,000.00 TOTAL 51,000.00 PAYMENT 5,000.00 BALANCE DUE KES 46,000.00"
        )

        parsed = parse_invoice_text(text, 1)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['invoice_no'], '10029')
        self.assertEqual(parsed['customer_name'], 'Peter Gitahi Karuba')
        self.assertEqual(parsed['customer_phone'], '+254726682896')
        self.assertEqual(parsed['customer_id'], '22181007')
        self.assertEqual(parsed['invoice_amount'], '54,000.00')
        self.assertEqual(parsed['total_after_discount'], '51,000.00')
        self.assertEqual(parsed['discount'], '3000.00')
        self.assertEqual(parsed['balance_due'], '46,000.00')
        self.assertEqual(parsed['balance_due_check'], 'OK')
