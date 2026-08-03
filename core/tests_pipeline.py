"""
Unit tests for the JBL Pipeline Portal and its services.
"""
from __future__ import annotations

import json
from decimal import Decimal
from io import BytesIO, StringIO
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AccessGrant, ComplianceAuditEvent, GroupSheetConfiguration, InvoiceUploadBatch, JawabuCaseComment, JawabuFarmerMaster, JawabuMediaAccessEvent, JawabuPipelineEvent, LiveSheetRecordChange, MediaAttachment, ParsedInvoice, PaymentDocument, PortalCaseWorkspace, RequisitionBatch, UserProfile, WorkflowRoleCapability
from core.services.jawabu_comments import master_comment_history
from core.services.jawabu_pipeline import (
    append_jbl_media_links,
    assign_order,
    all_cases,
    complete_jbl_visit,
    credit_queue,
    deferred_queue,
    farmer_to_card,
    final_review_queue,
    jbl_visit_queue,
    log_jbl_visit,
    pipeline_counts,
    requisition_queue,
    return_for_rework,
    set_credit_decision,
    set_final_decision,
    sync_farmer_to_internal_order_sheet,
    sync_farmer_to_master_sheet,
    current_pipeline_state_label,
)
from core.services.workflow_transitions import WorkflowRevisionConflict


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
            county='Kiambu',
            branch='Ruiru',
            status='active',
        )

        # Stage 2: JBL Visited
        self.farmer_stage2 = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Two',
            national_id='22222222',
            primary_phone='254722222222',
            sign_date='24-June-2026',
            county='Kiambu',
            branch='Thika',
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
            county='Nakuru',
            branch='Naivasha',
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
            county='Nakuru',
            branch='Naivasha',
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
            county='Meru',
            branch='Maua',
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

    def test_jbl_visit_queue_orders_by_hbg_visit_and_supports_search(self):
        later = JawabuFarmerMaster.objects.create(
            customer_name='Later HBG Visit', national_id='99999999',
            primary_phone='254799999999', sign_date='30-June-2026',
            county='Kiambu', branch='Ruiru', status='active',
        )
        queue = list(jbl_visit_queue())
        self.assertLess(queue.index(self.farmer_stage1), queue.index(later))
        self.assertEqual(list(jbl_visit_queue('Later HBG')), [later])

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

    def test_all_cases_filters_by_county_and_branch(self):
        """Verify all-cases browsing supports combined county and branch filters."""
        results = list(all_cases(county='Nakuru', branch='Naivasha'))
        self.assertEqual(results, [self.farmer_stage_review, self.farmer_stage3])

        branch_only = list(all_cases(branch='Thika'))
        self.assertEqual(branch_only, [self.farmer_stage2])

    def test_farmer_card_exposes_hb_visit_date_source(self):
        card = farmer_to_card(self.farmer_stage1)
        self.assertEqual(card['sign_date'], '24-June-2026')

    def test_farmer_card_strips_legacy_hb_date_marker(self):
        self.farmer_stage1.sign_date = "'15-May-2026"
        self.farmer_stage1.save(update_fields=['sign_date', 'updated_at'])

        card = farmer_to_card(self.farmer_stage1)

        self.assertEqual(card['sign_date'], '15-May-2026')
        self.assertEqual(card['hbg_visit_date'], '2026-05-15')

    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_log_jbl_visit(self, mock_reserve_publication):
        """Verify Advance from Stage 1 to Stage 2."""
        ok, error = log_jbl_visit(
            self.farmer_stage1,
            visit_date=date(2026, 6, 28),
            officer='Officer Joe',
            visit_status='Awaiting Analysis',
            comment='Ready for credit review',
            county='Muranga',
            sub_county='Kandara',
            village='Gakira',
        )
        self.assertTrue(ok)
        self.assertEqual(error, '')
        self.assertEqual(self.farmer_stage1.jbl_visit_status, 'Awaiting Analysis')
        self.assertEqual(self.farmer_stage1.jbl_officer, 'Officer Joe')
        self.assertEqual(self.farmer_stage1.jbl_visit_date, date(2026, 6, 28))
        self.assertEqual(self.farmer_stage1.jbl_visit_comment, 'Ready for credit review')
        self.assertEqual(self.farmer_stage1.county, 'Muranga')
        self.assertEqual(self.farmer_stage1.sub_county, 'Kandara')
        self.assertEqual(self.farmer_stage1.village, 'Gakira')
        mock_reserve_publication.assert_called_once()

    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_jbl_visit_comment_is_append_only_and_retry_safe(self, mock_reserve_publication):
        request_id = 'jbl-comment-1'
        ok, error = log_jbl_visit(
            self.farmer_stage1,
            visit_date=date(2026, 6, 28),
            officer='Officer Joe',
            visit_status='Awaiting Analysis',
            comment='Client requested a morning follow-up.',
            sender='Officer Joe',
            request_id=request_id,
        )

        self.assertTrue(ok, error)
        comment = self.farmer_stage1.case_comments.get(request_id=request_id)
        self.assertEqual(comment.stage_key, 'jbl_visit')
        self.assertEqual(comment.role_code, 'JBL_OFFICER')
        self.assertEqual(comment.role_label, 'JBL Officer')
        self.assertEqual(comment.comment, 'Client requested a morning follow-up.')

        ok, error = log_jbl_visit(
            self.farmer_stage1,
            visit_date=date(2026, 6, 28),
            officer='Officer Joe',
            visit_status='Awaiting Analysis',
            comment='Client requested a morning follow-up.',
            sender='Officer Joe',
            request_id=request_id,
        )
        self.assertTrue(ok, error)
        self.assertEqual(self.farmer_stage1.case_comments.count(), 1)

    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    def test_log_jbl_visit_rejects_date_before_hbg_visit(self, mock_order_sync, mock_sync):
        ok, error = log_jbl_visit(
            self.farmer_stage1,
            visit_date=date(2026, 6, 23),
            officer='Officer Joe',
            visit_status='Awaiting Analysis',
        )
        self.assertFalse(ok)
        self.assertIn('cannot be earlier than the HBG visit date', error)
        mock_sync.assert_not_called()
        mock_order_sync.assert_not_called()

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_scheduling_handoff_is_not_a_loggable_jbl_visit_outcome(self, mock_sync, mock_order_sync):
        """FarmUp may queue a visit, but only an officer may record its outcome."""
        ok, error = log_jbl_visit(
            self.farmer_stage1,
            visit_date=date(2026, 6, 28),
            officer='Officer Joe',
            visit_status='JBL to Schedule Visit',
        )

        self.assertFalse(ok)
        self.assertIn('outcome of the JBL visit', error)
        self.farmer_stage1.refresh_from_db()
        self.assertIsNone(self.farmer_stage1.jbl_visit_date)
        mock_sync.assert_not_called()
        mock_order_sync.assert_not_called()

    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_master_sheet_sync_writes_jbl_location_fields(self, mock_get_sheets):
        """Verify editable JBL visit location fields are pushed to Master Data."""
        from core.tests import FakeMasterDataSheet, FakeJawabuService

        self.farmer_stage1.county = 'Muranga'
        self.farmer_stage1.sub_county = 'Kandara'
        self.farmer_stage1.village = 'Gakira'
        self.farmer_stage1.save(update_fields=['county', 'sub_county', 'village', 'updated_at'])

        headers = [
            'No.',
            'Customer Name',
            'National ID',
            'Primary Phone',
            'County',
            'Constituency',
            'Village',
            'Last Updated At',
        ]
        fake_sheet = FakeMasterDataSheet(headers, [
            '1',
            self.farmer_stage1.customer_name,
            self.farmer_stage1.national_id,
            self.farmer_stage1.primary_phone,
            'Kiambu',
            '',
            '',
            '',
        ])
        mock_get_sheets.return_value = FakeJawabuService(fake_sheet)

        self.assertTrue(sync_farmer_to_master_sheet(self.farmer_stage1))
        row = fake_sheet.values[4]
        self.assertEqual(row[4], 'Muranga')
        self.assertEqual(row[5], 'Kandara')
        self.assertEqual(row[6], 'Gakira')

    @patch('core.services.jawabu_pipeline._jawabu_group_config')
    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_internal_order_sheet_sync_serializes_decimal_fields(self, mock_get_sheets, mock_group_config):
        """Financial fields must cross the Google JSON boundary as primitives."""
        from core.tests import FakeJawabuService, FakeMasterDataSheet

        workflow = {
            'type': 'jawabu',
            'internal_order_sync_enabled': True,
            'internal_order_sheet_id': 'internal-orders-sheet',
            'internal_order_sheet_name': 'Orders',
            'internal_order_header_row': 3,
            'internal_order_data_start_row': 5,
        }
        mock_group_config.return_value = SimpleNamespace(
            group_id=self.config.group_id,
            workflow=workflow,
        )
        self.farmer_stage1.deposit_paid_hbg = Decimal('60000.00')
        self.farmer_stage1.system_deposit_paid_jbl = Decimal('13500.50')
        self.farmer_stage1.save(update_fields=['deposit_paid_hbg', 'system_deposit_paid_jbl', 'updated_at'])

        headers = [
            'ORDER RECORD ID',
            'CUSTOMER NAME',
            'DEPOSIT / HB',
            'DEPOSIT / JBL',
            'LAST UPDATED AT',
        ]
        fake_sheet = FakeMasterDataSheet(headers)
        mock_get_sheets.return_value = FakeJawabuService(fake_sheet)

        self.assertTrue(sync_farmer_to_internal_order_sheet(self.farmer_stage1))

        synced_row = fake_sheet.values[-1]
        self.assertEqual(synced_row[2], 60000)
        self.assertEqual(synced_row[3], 13500.5)
        self.assertFalse(any(isinstance(value, Decimal) for value in synced_row))
        change = LiveSheetRecordChange.objects.get(sheet_id='internal-orders-sheet')
        self.assertEqual(change.changes['DEPOSIT / HB']['after'], 60000)
        self.assertEqual(change.changes['DEPOSIT / JBL']['after'], 13500.5)

    def test_forward_visit_requires_missing_evidence_before_drive_upload(self):
        """A missing multipart category must never leave an orphaned upload."""
        laf = SimpleUploadedFile('laf.pdf', b'x' * 5000, content_type='application/pdf')

        with patch('core.services.jawabu_pipeline.append_jbl_media_uploads') as mock_upload:
            ok, error, result = complete_jbl_visit(
                self.farmer_stage1,
                categorized_files={'LAF': [laf]},
                visit_date=date(2026, 6, 28),
                officer='Officer Joe',
                visit_status='Awaiting Analysis',
                latitude=-1.2921,
                longitude=36.8219,
                request_id='visit-missing-photo-001',
                expected_revision=self.farmer_stage1.workflow_revision,
            )

        self.assertFalse(ok)
        self.assertIn('JBL visit photo', error)
        self.assertFalse(result['evidence_saved'])
        self.assertEqual(result['missing_evidence'], ['JBL_VISIT_PHOTO'])
        mock_upload.assert_not_called()

    @patch('core.services.jawabu_pipeline.log_jbl_visit')
    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads')
    @patch('core.services.jawabu_pipeline.preflight_jbl_visit_completion')
    def test_atomic_visit_uses_the_revision_created_by_its_evidence_uploads(
        self, mock_preflight, mock_uploads, mock_log_visit,
    ):
        """A compound visit must not reject its own media-link revisions."""
        mock_preflight.return_value = (True, '', False)
        initial_revision = self.farmer_stage1.workflow_revision
        mock_uploads.return_value = (
            True,
            '',
            {
                'stored_count': 2,
                'skipped_count': 0,
                'warnings': [],
                'errors': [],
                'workflow_revision': initial_revision + 2,
            },
        )
        mock_log_visit.return_value = (True, '')
        laf = SimpleUploadedFile('laf.pdf', b'x' * 5000, content_type='application/pdf')
        photo = SimpleUploadedFile('visit.jpg', b'x' * 5000, content_type='image/jpeg')

        ok, error, result = complete_jbl_visit(
            self.farmer_stage1,
            categorized_files={'LAF': [laf], 'JBL_VISIT_PHOTO': [photo]},
            visit_date=date(2026, 6, 28),
            officer='Officer Joe',
            visit_status='Awaiting Analysis',
            latitude=-1.2921,
            longitude=36.8219,
            request_id='visit-revision-chain-001',
            expected_revision=initial_revision,
        )

        self.assertTrue(ok, error)
        self.assertTrue(result['visit_logged'])
        self.assertEqual(
            mock_log_visit.call_args.kwargs['expected_revision'],
            initial_revision + 2,
        )

    def test_jbl_media_link_keeps_a_genuine_concurrent_revision_conflict(self):
        """Stored Drive evidence must not overwrite another user's newer case edit."""
        from core.services.order_approval import hash_uploaded_file

        initial_revision = self.farmer_stage1.workflow_revision
        self.farmer_stage1.workflow_revision = initial_revision + 1
        self.farmer_stage1.save(update_fields=['workflow_revision', 'updated_at'])
        laf = SimpleUploadedFile('laf.pdf', b'x' * 5000, content_type='application/pdf')
        content_hash, _size = hash_uploaded_file(laf)
        attachment = MediaAttachment.objects.create(
            group_id=self.config.group_id,
            business_key_type='case_reference',
            business_key_value=f'case-{self.farmer_stage1.pk}',
            file_type='LAF',
            original_filename='laf.pdf',
            content_hash=content_hash,
            drive_url='https://drive.example/laf',
            upload_status='success',
        )
        uploaded = SimpleNamespace(
            links=['https://drive.example/laf'], stored_count=1, skipped_count=0, warnings=[],
        )

        with (
            patch('core.services.jawabu_pipeline._jawabu_group_config', return_value=SimpleNamespace(group_id=self.config.group_id)),
            patch('core.services.order_approval.store_uploaded_files_for_order', return_value=uploaded),
        ):
            ok, error, result = append_jbl_media_links(
                self.farmer_stage1,
                uploaded_files=[laf],
                sender='Officer Joe',
                media_category='LAF',
                expected_revision=initial_revision,
            )

        self.assertFalse(ok)
        self.assertIn('This case changed while you were working', error)
        self.assertTrue(result['evidence_saved'])
        attachment.refresh_from_db()
        self.assertIsNone(attachment.jawabu_farmer_id)

    def test_new_jbl_evidence_is_linked_to_the_case_before_visit_guard(self):
        """A stored case-reference upload must satisfy the case evidence guard."""
        from core.models import MediaAttachment
        from core.services.order_approval import hash_uploaded_file

        laf = SimpleUploadedFile('laf.pdf', b'x' * 5000, content_type='application/pdf')
        content_hash, _size = hash_uploaded_file(laf)
        attachment = MediaAttachment.objects.create(
            group_id=self.config.group_id,
            business_key_type='case_reference',
            business_key_value=f'case-{self.farmer_stage1.pk}',
            file_type='LAF',
            original_filename='laf.pdf',
            content_hash=content_hash,
            drive_url='https://drive.example/laf',
            upload_status='success',
        )
        uploaded = SimpleNamespace(
            links=['https://drive.example/laf'],
            stored_count=1,
            skipped_count=0,
            warnings=[],
        )
        group_config = SimpleNamespace(group_id=self.config.group_id)

        with (
            patch('core.services.jawabu_pipeline._jawabu_group_config', return_value=group_config),
            patch(
                'core.services.order_approval.store_uploaded_files_for_order',
                return_value=uploaded,
            ) as mock_store,
            patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet', return_value=True),
            patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet', return_value=True),
        ):
            ok, error, result = append_jbl_media_links(
                self.farmer_stage1,
                uploaded_files=[laf],
                sender='Officer Joe',
                media_category='LAF',
            )

        self.assertTrue(ok, error)
        self.assertEqual(result['stored_count'], 1)
        self.assertEqual(mock_store.call_args.kwargs['record_type'], 'ID')
        self.assertEqual(mock_store.call_args.kwargs['record_key'], self.farmer_stage1.national_id)
        self.assertEqual(mock_store.call_args.kwargs['storage_reference_value'], self.farmer_stage1.national_id)
        self.assertEqual(mock_store.call_args.kwargs['business_key_type'], 'case_reference')
        attachment.refresh_from_db()
        self.assertEqual(attachment.jawabu_farmer_id, self.farmer_stage1.id)

    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_set_credit_decision(self, mock_reserve_publication):
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
        mock_reserve_publication.assert_called_once()

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_set_credit_decision_requires_imab_yes_for_terminal_decision(self, mock_sync, mock_order_sync):
        """Verify terminal credit decisions cannot proceed when IMAB creation is not complete."""
        ok, error = set_credit_decision(
            self.farmer_stage2,
            decision='Approved',
            imab_created='No',
            customer_no='15121',
            sender='analyst_1',
        )
        self.assertFalse(ok)
        self.assertIn('created in IMAB', error)
        self.farmer_stage2.refresh_from_db()
        self.assertEqual(self.farmer_stage2.credit_decision, 'Pending')
        mock_sync.assert_not_called()
        mock_order_sync.assert_not_called()

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_pending_credit_decision_is_display_only(self, mock_sync, mock_order_sync):
        """Pending is the initial state, not an analyst-submittable decision."""
        ok, error = set_credit_decision(
            self.farmer_stage2,
            decision='Pending',
            imab_created='Yes',
            customer_no='15121',
            sender='analyst_1',
        )
        self.assertFalse(ok)
        self.assertIn('initial credit state', error)
        self.farmer_stage2.refresh_from_db()
        self.assertEqual(self.farmer_stage2.credit_decision, 'Pending')
        mock_sync.assert_not_called()
        mock_order_sync.assert_not_called()

    @patch('core.services.jawabu_pipeline._notify_final_approved')
    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_set_final_decision(self, mock_reserve_publication, mock_notify):
        """Verify Head of Rural final decision update and notification trigger."""
        ok, error = set_final_decision(
            self.farmer_stage_review,
            final_decision='Approved',
            decision_comment='Called and approved',
            repayment_date='10TH',
            repayment_tenor='6 months',
            sender='head_rural',
        )
        self.assertTrue(ok)
        self.assertEqual(error, '')
        self.assertEqual(self.farmer_stage_review.final_decision, 'Approved')
        self.assertEqual(self.farmer_stage_review.final_decision_comment, 'Called and approved')
        self.assertEqual(self.farmer_stage_review.repayment_date, '10TH')
        self.assertEqual(self.farmer_stage_review.repayment_tenor, '6 months')
        self.assertEqual(self.farmer_stage_review.final_decided_by, 'head_rural')
        comment = self.farmer_stage_review.case_comments.get()
        self.assertEqual(comment.role_label, 'Head of Rural')
        self.assertEqual(comment.comment, 'Called and approved')
        mock_reserve_publication.assert_called_once()
        mock_notify.assert_called_once_with(self.farmer_stage_review)

    def test_assign_order_gate_enforcement(self):
        """Verify credit approval gate block (cannot assign order to Stage 2)."""
        ok, error = assign_order(self.farmer_stage2, order_number='JBL-9999')
        self.assertFalse(ok)
        self.assertIn('not Approved', error)
        self.assertEqual(self.farmer_stage2.order_number, '')

    def test_assign_order_rejects_mixed_requisition_dates_at_service_boundary(self):
        self.farmer_stage3.requisition_date = date(2026, 7, 13)
        self.farmer_stage3.order_number = 'ORDER-SAME-DATE'
        self.farmer_stage3.save(update_fields=['requisition_date', 'order_number', 'updated_at'])
        candidate = JawabuFarmerMaster.objects.create(
            customer_name='Farmer Same Batch', national_id='55555555',
            primary_phone='254755555555', sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25), jbl_visit_status='Approved',
            credit_decision='Approved', imab_created='Yes', customer_no='15120',
            final_decision='Approved', status='active',
        )

        ok, error = assign_order(
            candidate, order_number='ORDER-SAME-DATE',
            requisition_date=date(2026, 7, 14),
        )

        self.assertFalse(ok)
        self.assertIn('already has requisition date', error)
        candidate.refresh_from_db()
        self.assertEqual(candidate.order_number, '')

    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_credit_transition_rejects_stale_revision_after_a_successful_write(self, mock_reserve_publication):
        expected_revision = self.farmer_stage2.workflow_revision

        ok, error = set_credit_decision(
            self.farmer_stage2,
            decision='Approved',
            imab_created='Yes',
            customer_no='15121',
            sender='analyst_1',
            request_id='credit-revision-1',
            expected_revision=expected_revision,
        )

        self.assertTrue(ok, error)
        self.assertEqual(self.farmer_stage2.workflow_revision, expected_revision + 1)
        event = self.farmer_stage2.pipeline_events.get(request_id='credit-revision-1')
        self.assertEqual(event.from_state, 'credit')
        self.assertEqual(event.to_state, 'final_review')
        self.assertEqual(event.revision_before, expected_revision)
        self.assertEqual(event.revision_after, expected_revision + 1)

        with self.assertRaises(WorkflowRevisionConflict):
            set_credit_decision(
                self.farmer_stage2,
                decision='Approved',
                imab_created='Yes',
                customer_no='15121',
                sender='analyst_1',
                request_id='credit-revision-stale',
                expected_revision=expected_revision,
            )
        self.assertEqual(mock_reserve_publication.call_count, 1)

    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_final_review_can_return_a_case_to_credit_with_a_reason(self, mock_reserve_publication):
        ok, error = return_for_rework(
            self.farmer_stage_review,
            target_state='credit',
            reason='Recheck affordability against the corrected income evidence.',
            sender='head_rural',
            request_id='return-credit-1',
            expected_revision=self.farmer_stage_review.workflow_revision,
        )

        self.assertTrue(ok, error)
        self.assertEqual(self.farmer_stage_review.workflow_state, 'credit')
        self.assertEqual(self.farmer_stage_review.final_decision, '')
        event = self.farmer_stage_review.pipeline_events.get(request_id='return-credit-1')
        self.assertEqual(event.transition_code, 'jawabu.final_review.return_to_credit')
        self.assertEqual(event.reason, 'Recheck affordability against the corrected income evidence.')
        comment = self.farmer_stage_review.case_comments.get(request_id='return-credit-1')
        self.assertEqual(comment.stage_key, 'final_review')
        self.assertEqual(comment.comment, 'Recheck affordability against the corrected income evidence.')
        self.assertEqual(mock_reserve_publication.call_count, 1)

    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_master_sheet_projects_post_jbl_comments_in_chronological_order(self, mock_get_sheets):
        from core.tests import FakeJawabuService, FakeMasterDataSheet

        earlier = timezone.now() - timedelta(minutes=5)
        later = timezone.now()
        JawabuCaseComment.objects.create(
            farmer=self.farmer_stage1,
            stage_key='jbl_visit',
            comment='First comment.',
            actor='Officer Joe',
            role_code='JBL_OFFICER',
            role_label='JBL Officer',
            occurred_at=earlier,
        )
        JawabuCaseComment.objects.create(
            farmer=self.farmer_stage1,
            stage_key='final_review',
            comment='Second comment.',
            actor='Head Rural',
            role_code='BUSINESS_ADMIN',
            role_label='Head of Rural',
            occurred_at=later,
        )
        expected = master_comment_history(self.farmer_stage1)
        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Additional Comments']
        fake_sheet = FakeMasterDataSheet(headers, [
            '1', self.farmer_stage1.customer_name, self.farmer_stage1.national_id,
            self.farmer_stage1.primary_phone, 'Legacy Sheet-only comment',
        ])
        mock_get_sheets.return_value = FakeJawabuService(fake_sheet)

        self.assertTrue(sync_farmer_to_master_sheet(self.farmer_stage1))
        self.assertEqual(fake_sheet.values[4][4], expected)
        self.assertLess(expected.index('First comment.'), expected.index('Second comment.'))

    def test_rework_route_cannot_skip_credit_back_to_jbl_visit(self):
        ok, error = return_for_rework(
            self.farmer_stage_review,
            target_state='jbl_visit',
            reason='This route must not be allowed.',
            expected_revision=self.farmer_stage_review.workflow_revision,
        )

        self.assertFalse(ok)
        self.assertIn('return route is not permitted', error)


class PortalMiniAppAuthTestCase(TestCase):
    def test_portal_workspace_controls_are_not_rendered_while_feature_is_on_hold(self):
        template = Path(__file__).resolve().parent / 'templates' / 'portal' / 'portal.html'
        source = template.read_text(encoding='utf-8')
        script = (Path(__file__).resolve().parent / 'static' / 'miniapp' / 'portal.js').read_text(encoding='utf-8')

        self.assertNotIn('portal-workspace-dashboard', source)
        self.assertNotIn('portal-workspace-save-view-form', source)
        self.assertNotIn('Saved views', source)
        self.assertIn('const PORTAL_WORKSPACE_UI_ENABLED = false;', script)

    def grant_portal_access(self, role='JBL_OFFICER', branches=None):
        user = get_user_model().objects.create_user(
            username=f'portal-{role.lower()}', first_name='Portal', last_name='User', is_active=True,
        )
        user.set_unusable_password()
        user.save(update_fields=['password'])
        UserProfile.objects.create(user=user, telegram_id='12345')
        AccessGrant.objects.create(
            user=user, workflow='jawabu_portal', role=role,
            branch=(branches or [''])[0],
        )
        return user

    def grant_portal_it_access(self, user, branches=None):
        """Add the paused-workspace support role without replacing live work roles."""
        return AccessGrant.objects.create(
            user=user,
            workflow='jawabu_portal',
            role='IT',
            branch=(branches or [''])[0],
        )

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

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_api_rejects_missing_telegram_init_data(self):
        response = self.client.get(reverse('portal_dashboard'))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        self.assertIn('authentication data is missing', response.json()['error'])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_api_accepts_valid_telegram_init_data(self):
        self.grant_portal_access(role='BUSINESS_ADMIN')
        response = self.client.get(
            reverse('portal_dashboard'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
            HTTP_X_REQUEST_ID='portal-test-request-001',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response['X-Request-ID'], 'portal-test-request-001')
        self.assertEqual(response.json()['request_id'], 'portal-test-request-001')

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_jbl_visit_recovery_draft_is_staff_scoped_and_field_only(self):
        user = self.grant_portal_access(role='JBL_OFFICER', branches=['Ruiru'])
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Draft recovery farmer', national_id='49999111',
            primary_phone='254799991111', branch='Ruiru', status='active',
        )
        url = reverse('portal_jbl_visit_draft', kwargs={'farmer_id': farmer.id})
        headers = {
            'HTTP_X_TELEGRAM_INIT_DATA': self._signed_init_data(),
            'HTTP_X_REQUEST_ID': 'jbl-visit-draft-save-001',
        }
        payload = {
            'payload': {
                'saved_at': 1_754_000_000_000,
                'values': {
                    'jbl-date': '2026-08-03',
                    'jbl-status': 'JBL Visit Completed',
                    'jbl-officer': 'Portal User',
                    'jbl-county': 'Kiambu',
                    'jbl-sub-county': 'Ruiru',
                    'jbl-village': 'Kahawa',
                    'jbl-comment': 'Draft note',
                    'jbl-lat': '-1.2',
                    'jbl-lng': '36.8',
                    'jbl-location-unavailable': '',
                },
            },
        }

        saved = self.client.post(url, data=json.dumps(payload), content_type='application/json', **headers)

        self.assertEqual(saved.status_code, 200)
        restored = self.client.get(url, HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data())
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()['draft']['payload']['values']['jbl-comment'], 'Draft note')
        self.assertEqual(restored.json()['draft']['payload']['saved_at'], 1_754_000_000_000)
        self.assertEqual(restored.json()['draft']['revision'], 1)
        self.assertEqual(user.miniapp_drafts.filter(workflow='portal_jbl_visit').count(), 1)

        rejected_attachment = self.client.post(
            url,
            data=json.dumps({'payload': {'values': {'files': 'data:application/pdf;base64,not-a-file'}}}),
            content_type='application/json',
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
            HTTP_X_REQUEST_ID='jbl-visit-draft-attachment-001',
        )
        self.assertEqual(rejected_attachment.status_code, 400)
        self.assertEqual(
            self.client.get(url, HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data()).json()['draft']['payload']['values']['jbl-comment'],
            'Draft note',
        )

        cleared = self.client.delete(
            url,
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
            HTTP_X_REQUEST_ID='jbl-visit-draft-delete-001',
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(self.client.get(url, HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data()).json()['draft'])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_jbl_visit_recovery_draft_requires_the_visit_write_capability(self):
        self.grant_portal_access(role='CREDIT_ANALYST', branches=['Ruiru'])
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Draft access farmer', national_id='49999112',
            primary_phone='254799991112', branch='Ruiru', status='active',
        )

        response = self.client.get(
            reverse('portal_jbl_visit_draft', kwargs={'farmer_id': farmer.id}),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['ok'], False)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_api_generates_request_id_when_client_does_not_supply_one(self):
        self.grant_portal_access(role='BUSINESS_ADMIN')
        response = self.client.get(
            reverse('portal_dashboard'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['X-Request-ID'])
        self.assertEqual(response['X-Request-ID'], response.json()['request_id'])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
    def test_portal_health_reports_template_and_storage_state(self):
        response = self.client.get(reverse('portal_health'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn(data['status'], {'live', 'maintenance', 'degraded', 'down'})
        self.assertIn('requisition_template', data['checks'])
        self.assertIn('payment_template', data['checks'])
        self.assertIn('due_order_retries', data)
        self.assertIn('due_payment_retries', data)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
    def test_portal_health_counts_due_failed_artifacts(self):
        from django.utils import timezone
        RequisitionBatch.objects.create(
            order_number='HEALTH-RETRY-1',
            drive_upload_error='Drive upload failed; retry required.',
            drive_next_retry_at=timezone.now(),
        )
        PaymentDocument.objects.create(
            order_number='HEALTH-ORDER-1', payment_number='1', status='failed',
            error='Drive upload failed; retry required.',
            drive_next_retry_at=timezone.now(),
        )

        response = self.client.get(reverse('portal_health'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data['failed_order_syncs'], 1)
        self.assertGreaterEqual(data['failed_payment_syncs'], 1)
        self.assertGreaterEqual(data['due_order_retries'], 1)
        self.assertGreaterEqual(data['due_payment_retries'], 1)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
    def test_maintenance_mode_blocks_new_portal_writes_but_keeps_reads_available(self):
        from core.services.portal_maintenance import maintenance_write_blocked, set_maintenance_state

        state = set_maintenance_state(
            actor=None,
            mode='maintenance',
            reason='Template maintenance',
            request_id='maintenance-test-001',
        )
        self.assertEqual(state.mode, 'maintenance')
        self.assertTrue(maintenance_write_blocked()[0])
        self.assertEqual(self.client.get(reverse('portal_dashboard')).status_code, 200)
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Maintenance Test Farmer', national_id='77773333',
            primary_phone='254777733333', sign_date='01-July-2026', status='active',
        )
        response = self.client.post(
            reverse('portal_log_jbl_visit', args=[farmer.id]),
            json.dumps({}),
            content_type='application/json',
            HTTP_X_REQUEST_ID='maintenance-write-001',
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'portal_read_only_maintenance')
        set_maintenance_state(actor=None, mode='live', reason='', request_id='maintenance-test-002')
        self.assertFalse(maintenance_write_blocked()[0])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_api_rejects_valid_but_unregistered_telegram_user(self):
        response = self.client.get(
            reverse('portal_dashboard'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('not authorized for the Jawabu Portal', response.json()['error'])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_navigation_omits_links_disallowed_for_role(self):
        self.grant_portal_access()
        response = self.client.get(
            reverse('portal_navigation'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'JBL Queue')
        self.assertNotContains(response, 'Credit')
        self.assertNotContains(response, 'Invoices')

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_settings_persist_only_permitted_workspace_defaults(self):
        self.grant_portal_access(role='BUSINESS_ADMIN', branches=['EMBU'])
        headers = {'HTTP_X_TELEGRAM_INIT_DATA': self._signed_init_data()}

        settings_response = self.client.get(reverse('portal_settings'), **headers)

        self.assertEqual(settings_response.status_code, 200)
        settings_data = settings_response.json()['data']
        self.assertTrue(settings_data['operations']['health'])
        self.assertTrue(settings_data['operations']['delegation'])
        self.assertEqual(settings_data['branches'], ['Embu'])
        self.assertIn('jbl', {item['key'] for item in settings_data['queues']})
        self.assertEqual(settings_data['account']['workflow'], 'jawabu_portal')
        self.assertEqual(settings_data['account']['roles'][0]['key'], 'BUSINESS_ADMIN')
        self.assertEqual(settings_data['account']['branches'], ['EMBU'])

        response = self.client.post(
            reverse('portal_settings'),
            data=json.dumps({'preferences': {
                'default_screen': 'dashboard',
                'default_filters': {'queue': 'jbl', 'branch': 'EMBU', 'status': 'decision'},
                'compact_cards': True,
                'alert_mode': 'quiet',
            }}),
            content_type='application/json',
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
            HTTP_X_REQUEST_ID='portal-settings-test-001',
        )

        self.assertEqual(response.status_code, 200)
        personal = response.json()['data']
        self.assertEqual(personal['default_filters']['queue'], 'jbl')
        self.assertEqual(personal['default_filters']['branch'], 'Embu')
        self.assertTrue(personal['compact_cards'])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_workspace_saved_views_are_private_validated_and_safe_after_access_drift(self):
        user = self.grant_portal_access(role='BUSINESS_ADMIN', branches=['EMBU'])
        self.grant_portal_it_access(user, branches=['EMBU'])
        headers = {'HTTP_X_TELEGRAM_INIT_DATA': self._signed_init_data()}
        payload = {
            'name': 'Embu visit queue',
            'screen': 'jbl',
            'queue': 'jbl',
            'filters': {'branch': 'EMBU'},
            'ordering': 'newest',
        }
        create = self.client.post(
            reverse('portal_workspace_views'), data=json.dumps(payload),
            content_type='application/json', **headers,
        )
        self.assertEqual(create.status_code, 201)
        saved_view = create.json()['data']
        self.assertTrue(saved_view['available'])
        self.assertEqual(saved_view['filters']['branch'], 'Embu')

        invalid = self.client.post(
            reverse('portal_workspace_views'),
            data=json.dumps({**payload, 'name': 'Outside scope', 'filters': {'branch': 'Nakuru'}}),
            content_type='application/json', **headers,
        )
        self.assertEqual(invalid.status_code, 400)

        startup = self.client.post(
            reverse('portal_workspace_view_startup', args=[saved_view['id']]),
            data='{}', content_type='application/json', **headers,
        )
        self.assertEqual(startup.status_code, 200)
        workspace = self.client.get(reverse('portal_workspace'), {'summary': '1'}, **headers)
        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(workspace.json()['data']['startup_view']['id'], saved_view['id'])
        self.assertEqual(workspace.json()['data']['summary']['default_view_label'], 'Embu visit queue')
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            workflow='portal', action='portal.workspace.view.created', actor_id=user.pk,
        ).exists())

        AccessGrant.objects.filter(
            user=user, workflow='jawabu_portal', role='BUSINESS_ADMIN',
        ).update(role='CREDIT_ANALYST')
        drifted = self.client.get(reverse('portal_workspace'), **headers)
        self.assertEqual(drifted.status_code, 200)
        data = drifted.json()['data']
        self.assertIsNone(data['startup_view'])
        self.assertFalse(data['views'][0]['available'])
        self.assertIn('available to your current access', data['views'][0]['unavailable_reason'])

        repair = self.client.patch(
            reverse('portal_workspace_view_detail', args=[saved_view['id']]),
            data=json.dumps({
                'name': 'Embu credit queue',
                'screen': 'credit',
                'queue': 'credit',
                'filters': {'branch': 'Embu'},
                'ordering': 'queue_default',
            }),
            content_type='application/json', **headers,
        )
        self.assertEqual(repair.status_code, 200)
        self.assertTrue(repair.json()['data']['available'])
        repaired_workspace = self.client.get(reverse('portal_workspace'), **headers).json()['data']
        self.assertEqual(repaired_workspace['startup_view']['name'], 'Embu credit queue')
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            workflow='portal', action='portal.workspace.view.updated', actor_id=user.pk,
        ).exists())

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_workspace_case_open_is_idempotent_and_pins_hide_when_scope_changes(self):
        user = self.grant_portal_access(branches=['EMBU'])
        self.grant_portal_it_access(user, branches=['EMBU'])
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Workspace farmer', national_id='10000234',
            primary_phone='254700000234', branch='Embu', status='active',
        )
        headers = {
            'HTTP_X_TELEGRAM_INIT_DATA': self._signed_init_data(),
            'HTTP_X_PORTAL_WORKSPACE_OPEN_KEY': 'open-workspace-farmer-001',
        }
        detail_url = reverse('portal_farmer_detail', args=[farmer.pk])
        first = self.client.get(detail_url, **headers)
        second = self.client.get(detail_url, **headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PortalCaseWorkspace.objects.filter(user=user, farmer=farmer).count(), 1)

        pin = self.client.post(
            reverse('portal_workspace_case_pin', args=[farmer.pk]), data='{}',
            content_type='application/json', HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )
        self.assertEqual(pin.status_code, 200)
        pin_repeat = self.client.post(
            reverse('portal_workspace_case_pin', args=[farmer.pk]), data='{}',
            content_type='application/json', HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )
        self.assertEqual(pin_repeat.status_code, 200)
        self.assertEqual(PortalCaseWorkspace.objects.filter(user=user, farmer=farmer, pinned=True).count(), 1)

        farmer.branch = 'Nakuru'
        farmer.save(update_fields=['branch', 'updated_at'])
        workspace = self.client.get(reverse('portal_workspace'), HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data())
        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(workspace.json()['data']['pinned'], [])
        item = PortalCaseWorkspace.objects.get(user=user, farmer=farmer)
        self.assertIsNotNone(item.unavailable_since)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_workspace_is_denied_and_does_not_track_case_opens_without_it_role(self):
        user = self.grant_portal_access(branches=['EMBU'])
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Non IT workspace farmer', national_id='10000236',
            primary_phone='254700000236', branch='Embu', status='active',
        )
        headers = {
            'HTTP_X_TELEGRAM_INIT_DATA': self._signed_init_data(),
            'HTTP_X_PORTAL_WORKSPACE_OPEN_KEY': 'non-it-open-key-001',
        }

        workspace = self.client.get(reverse('portal_workspace'), **headers)
        self.assertEqual(workspace.status_code, 403)
        self.assertIn('not authorized', workspace.json()['error'])

        detail = self.client.get(reverse('portal_farmer_detail', args=[farmer.pk]), **headers)
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(PortalCaseWorkspace.objects.filter(user=user, farmer=farmer).exists())

        pin = self.client.post(
            reverse('portal_workspace_case_pin', args=[farmer.pk]), data='{}',
            content_type='application/json', HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )
        self.assertEqual(pin.status_code, 403)

    def test_portal_workspace_retention_releases_only_private_metadata(self):
        from core.services.portal_workspace import purge_expired_workspace_metadata

        user = self.grant_portal_access(branches=['EMBU'])
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Retention farmer', national_id='10000235',
            primary_phone='254700000235', branch='Embu', status='active',
        )
        now = timezone.now()
        item = PortalCaseWorkspace.objects.create(
            user=user, farmer=farmer, pinned=True, pinned_at=now - timedelta(days=40),
            unavailable_since=now - timedelta(days=31), last_opened_at=now - timedelta(days=1),
        )
        preview = purge_expired_workspace_metadata(now=now, apply=False)
        self.assertEqual(preview['stale_pins_released'], 1)
        self.assertEqual(preview['expired_workspace_rows_deleted'], 0)

        applied = purge_expired_workspace_metadata(now=now, apply=True)
        self.assertEqual(applied['stale_pins_released'], 1)
        item.refresh_from_db()
        self.assertFalse(item.pinned)
        self.assertIsNone(item.unavailable_since)
        farmer.refresh_from_db()
        self.assertEqual(farmer.customer_name, 'Retention farmer')

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_delegation_api_is_business_admin_only_and_audited(self):
        self.grant_portal_access(role='BUSINESS_ADMIN', branches=['EMBU'])
        delegate = get_user_model().objects.create_user(username='portal-cover', is_active=True)
        AccessGrant.objects.create(
            user=delegate, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )
        payload = {
            'delegate_id': str(delegate.pk),
            'gate': 'credit',
            'branch': 'EMBU',
            'expires_at': (timezone.now() + timedelta(days=1)).isoformat(),
            'reason': 'Annual leave cover.',
        }
        response = self.client.post(
            reverse('portal_approval_delegations'), data=json.dumps(payload), content_type='application/json',
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(), HTTP_X_REQUEST_ID='portal-delegation-test-001',
        )

        self.assertEqual(response.status_code, 201)
        delegation = response.json()['data']
        self.assertTrue(delegation['active'])
        self.assertEqual(delegation['branch'], 'Embu')
        self.assertEqual(delegation['delegate'], 'portal-cover')

        revoke = self.client.post(
            reverse('portal_approval_delegation_revoke', args=[delegation['id']]),
            data=json.dumps({'reason': 'Primary approver returned.'}), content_type='application/json',
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(), HTTP_X_REQUEST_ID='portal-delegation-test-002',
        )
        self.assertEqual(revoke.status_code, 200)
        self.assertFalse(revoke.json()['data']['active'])

        AccessGrant.objects.filter(user__staff_profile__telegram_id='12345').update(role='JBL_OFFICER')
        denied = self.client.get(
            reverse('portal_approval_delegations'), HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )
        self.assertEqual(denied.status_code, 403)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_matrix_change_hides_a_portal_module_and_blocks_its_endpoint(self):
        self.grant_portal_access()
        WorkflowRoleCapability.objects.filter(
            workflow='jawabu_portal', role='JBL_OFFICER', capability_key='portal.jbl_queue.view',
        ).update(enabled=False, effect='deny')

        navigation = self.client.get(
            reverse('portal_navigation'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )
        queue = self.client.get(
            reverse('portal_jbl_queue'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )

        self.assertEqual(navigation.status_code, 200)
        self.assertNotContains(navigation, 'JBL Queue')
        self.assertEqual(queue.status_code, 403)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_portal_reads_are_limited_to_staff_branch_scope(self):
        self.grant_portal_access(branches=['Ruiru'])
        allowed = JawabuFarmerMaster.objects.create(
            customer_name='Ruiru client', national_id='12345678',
            primary_phone='254700000001', branch='Ruiru', status='active',
        )
        JawabuFarmerMaster.objects.create(
            customer_name='Kiambu client', national_id='12345679',
            primary_phone='254700000002', branch='Kiambu', status='active',
        )

        response = self.client.get(
            reverse('portal_all_cases'),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )

        self.assertEqual(response.status_code, 200)
        returned_ids = {item['id'] for item in response.json()['farmers']}
        self.assertEqual(returned_ids, {str(allowed.id)})

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, TELEGRAM_BOT_TOKEN='test-token', SECURE_SSL_REDIRECT=False)
    def test_requisition_download_requires_branch_scope(self):
        self.grant_portal_access(branches=['Ruiru'])
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Kiambu client', national_id='12345680',
            primary_phone='254700000003', branch='Kiambu', order_number='OUTSIDE-1',
            status='active',
        )

    def test_current_pipeline_state_labels_cover_halts_and_finance_lifecycle(self):
        self.assertEqual(current_pipeline_state_label(self.farmer_stage1), 'Awaiting JBL Visit')
        self.assertEqual(current_pipeline_state_label(self.farmer_stage2), 'Awaiting Credit Analysis')
        self.assertEqual(current_pipeline_state_label(self.farmer_stage_review), 'Awaiting Head of Rural Review')
        self.assertEqual(current_pipeline_state_label(self.farmer_stage3), 'Ready for Order')
        self.assertEqual(current_pipeline_state_label(self.farmer_stage4), 'Ordered — Awaiting Invoice')

        self.farmer_stage1.jbl_visit_status = 'Rescheduled'
        self.farmer_stage1.save(update_fields=['jbl_visit_status'])
        self.assertEqual(current_pipeline_state_label(self.farmer_stage1), 'JBL Visit Rescheduled')

        paused = JawabuFarmerMaster.objects.create(
            customer_name='Paused case', national_id='55555555', primary_phone='254755555555',
            workflow_state='deferred', deferred_stage='credit',
            deferred_until=timezone.localdate() + timedelta(days=1), status='active',
        )
        self.assertEqual(current_pipeline_state_label(paused), 'Deferred — Credit')
        paused.deferred_until = timezone.localdate()
        paused.save(update_fields=['deferred_until'])
        self.assertEqual(current_pipeline_state_label(paused), 'Reappraisal Required')

        batch = InvoiceUploadBatch.objects.create(order_number=self.farmer_stage4.order_number, status='matched')
        ParsedInvoice.objects.create(
            batch=batch, status='matched', matched_farmer=self.farmer_stage4,
            invoice_no='STATE-INV-1', balance_due=Decimal('5000.00'),
        )
        self.assertEqual(current_pipeline_state_label(self.farmer_stage4), 'Payment Processing')
        JawabuPipelineEvent.objects.create(farmer=self.farmer_stage4, action='payment_finalized', stage_key='payment')
        self.assertEqual(current_pipeline_state_label(self.farmer_stage4), 'Payment Finalized')
        RequisitionBatch.objects.create(
            order_number='OUTSIDE-1', file_content=b'xlsx-bytes',
            farmer_ids=[str(farmer.id)], farmer_count=1,
        )

        response = self.client.get(
            reverse('portal_requisition_batch_download', args=['OUTSIDE-1']),
            HTTP_X_TELEGRAM_INIT_DATA=self._signed_init_data(),
        )

        self.assertEqual(response.status_code, 403)

@override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
class JblPipelineApiTestCase(TestCase):
    """Test suite for the portal Mini App API endpoints."""

    def setUp(self):
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Pipeline test farmer',
            national_id='99999999',
            primary_phone='254799999999',
            sign_date='24-June-2026',
            county='Kiambu',
            branch='Ruiru',
            status='active',
        )

    def mark_requisition_location_ready(self, farmer=None):
        farmer = farmer or self.farmer
        farmer.sub_county = 'Kieni'
        farmer.village = 'Mweiga'
        farmer.save(update_fields=['sub_county', 'village', 'updated_at'])

    def test_portal_home_render(self):
        """Verify that the home page view resolves and renders the template."""
        response = self.client.get(reverse('portal_home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'base_shell.html')
        self.assertTemplateUsed(response, 'portal/portal_screen_full.html')
        self.assertTemplateUsed(response, 'portal/portal.html')
        self.assertContains(response, 'htmx.org')
        self.assertContains(response, 'miniapp/utils.js')

    def test_portal_screen_fragment_omits_shell(self):
        response = self.client.get(
            reverse('portal_screen', kwargs={'screen': 'credit'}),
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'portal/portal.html')
        self.assertNotContains(response, '<html')
        self.assertNotContains(response, 'id="bottom-tabs"')
        self.assertContains(response, 'data-screen="credit"')

    def test_each_portal_screen_cold_load_includes_shell(self):
        for screen in ('dashboard', 'jbl', 'credit', 'final', 'requisition', 'deferred', 'all', 'case_history', 'batches', 'invoices', 'payments', 'history'):
            with self.subTest(screen=screen):
                response = self.client.get(reverse('portal_screen', kwargs={'screen': screen}))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<html')
                self.assertContains(response, 'id="content"')
                self.assertContains(response, f'data-screen="{screen}"')

    def test_case_history_is_a_dedicated_screen(self):
        response = self.client.get(reverse('portal_screen', kwargs={'screen': 'case_history'}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="page-case_history"')
        self.assertContains(response, 'id="case-history-search-form"')
        self.assertContains(response, 'id="case-history-content"')
        self.assertNotContains(response, 'id="case360"')

    def test_case_history_customer_has_its_own_page(self):
        response = self.client.get(reverse('portal_case_history_detail', kwargs={'farmer_id': self.farmer.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html')
        self.assertContains(response, f'data-case-farmer-id="{self.farmer.id}"')
        self.assertContains(response, 'data-top-level="false"')
        self.assertContains(response, 'Complete Case History')
        self.assertNotContains(response, 'id="case-history-search-form"')

    def test_case_history_customer_fragment_omits_shell(self):
        response = self.client.get(
            reverse('portal_case_history_detail', kwargs={'farmer_id': self.farmer.id}),
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<html')
        self.assertContains(response, f'data-case-farmer-id="{self.farmer.id}"')

    def test_payment_candidates_include_only_cases_with_matched_invoices(self):
        delayed = JawabuFarmerMaster.objects.create(
            customer_name='Invoice Delayed Customer', national_id='10000001',
            primary_phone='254700000001', order_number='ORDER-DELAYED', status='active',
        )
        invoiced = JawabuFarmerMaster.objects.create(
            customer_name='Invoice Received Customer', national_id='10000002',
            primary_phone='254700000002', order_number='ORDER-RECEIVED', status='active',
        )
        batch = InvoiceUploadBatch.objects.create(order_number='ORDER-RECEIVED', status='matched')
        ParsedInvoice.objects.create(
            batch=batch, status='matched', matched_farmer=invoiced,
            invoice_no='INV-RECEIVED', balance_due='49000.00',
        )

        response = self.client.get(reverse('portal_payment_candidates'))
        payload = response.json()
        returned_ids = {
            item['farmer_id']
            for item in [*(payload.get('ready') or []), *(payload.get('blocked') or [])]
        }

        self.assertEqual(response.status_code, 200)
        self.assertIn(str(invoiced.id), returned_ids)
        self.assertNotIn(str(delayed.id), returned_ids)

    def test_head_of_rural_review_lenses_include_requisition_and_payment_batches(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.order_number = ''
        self.farmer.jbl_visit_date = date(2026, 7, 24)
        self.farmer.credit_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = 'C-1'
        self.farmer.save()

        requisition = self.client.get(reverse('portal_final_review_queue'), {'stage': 'requisition'})
        self.assertEqual(requisition.status_code, 200)
        self.assertIn(str(self.farmer.id), {item['id'] for item in requisition.json()['farmers']})

        payment = PaymentDocument.objects.create(
            order_number='ORDER-PAYMENT', payment_number='12', status='pending_review',
            farmer_ids=[str(self.farmer.id)], row_count=1,
        )
        payment_queue = self.client.get(reverse('portal_final_review_queue'), {'stage': 'payment'})
        self.assertEqual(payment_queue.status_code, 200)
        item = next(item for item in payment_queue.json()['farmers'] if item['id'] == str(self.farmer.id))
        self.assertEqual(item['payment_review_document_id'], str(payment.id))
        self.assertEqual(item['payment_review_payment_number'], '12')

        payment_fragment = self.client.get(
            reverse('portal_queue_fragment', kwargs={'queue_key': 'final'}),
            {'stage': 'payment'},
        )
        self.assertEqual(payment_fragment.status_code, 200)
        self.assertContains(payment_fragment, 'Payment #12 awaiting HOR review')
        self.assertContains(payment_fragment, f'data-payment-document-id="{payment.id}"')

    def test_portal_jbl_queue_fragment_renders_cards(self):
        """Verify the htmx JBL queue fragment renders useful farmer cards."""
        self.farmer.sub_county = 'Kieni'
        self.farmer.village = 'Mweiga'
        self.farmer.save(update_fields=['sub_county', 'village', 'updated_at'])
        response = self.client.get(reverse('portal_jbl_queue_fragment'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'portal/partials/farmer_list.html')
        self.assertContains(response, 'Pipeline test farmer')
        self.assertContains(response, 'Kiambu | Kieni | Mweiga | Ruiru')
        self.assertContains(response, 'htmx-farmer-card')
        self.assertContains(response, 'HB visit: 24-June-2026')
        self.assertContains(response, 'aria-label="Queue position 1"')

    def test_portal_jbl_queue_exposes_ephemeral_page_relative_card_numbers(self):
        for index in range(31):
            JawabuFarmerMaster.objects.create(
                customer_name=f'Queue position {index}', national_id=f'7111{index:04d}',
                primary_phone=f'254700{index:06d}', sign_date='24-June-2026', status='active',
            )

        first_page = self.client.get(reverse('portal_jbl_queue'), {'page': 1}).json()
        second_page = self.client.get(reverse('portal_jbl_queue'), {'page': 2}).json()

        self.assertEqual(first_page['farmers'][0]['display_number'], 1)
        self.assertEqual(second_page['farmers'][0]['display_number'], 31)

    def test_portal_farmer_detail_reads_latest_location_values(self):
        """A detail request must reflect location edits made after a queue load."""
        first = self.client.get(reverse('portal_farmer_detail', args=[self.farmer.id]))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['farmer']['county'], 'Kiambu')

        self.farmer.county = 'Embu'
        self.farmer.sub_county = 'Manyatta'
        self.farmer.village = 'Kithimu'
        self.farmer.save(update_fields=['county', 'sub_county', 'village', 'updated_at'])

        latest = self.client.get(reverse('portal_farmer_detail', args=[self.farmer.id]))
        self.assertEqual(latest.status_code, 200)
        latest_location = latest.json()['farmer']
        self.assertEqual(
            (latest_location['county'], latest_location['sub_county'], latest_location['village']),
            ('Embu', 'Manyatta', 'Kithimu'),
        )

    def test_portal_jbl_queue_fragment_filters_by_county_and_branch(self):
        """Verify server-rendered JBL queue fragments honor selected filters."""
        JawabuFarmerMaster.objects.create(
            customer_name='Other branch farmer',
            national_id='88888888',
            primary_phone='254788888888',
            sign_date='24-June-2026',
            county='Nakuru',
            branch='Naivasha',
            status='active',
        )

        response = self.client.get(reverse('portal_jbl_queue_fragment'), {
            'county': 'Kiambu',
            'branch': 'Ruiru',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pipeline test farmer')
        self.assertNotContains(response, 'Other branch farmer')

    def test_portal_queue_fragment_renders_credit_final_requisition_and_all(self):
        """Verify the shared htmx fragment supports the main farmer queues."""
        credit_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Credit queue farmer',
            national_id='77777777',
            primary_phone='254777777777',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 7, 1),
            jbl_visit_status='Awaiting Analysis',
            county='Kiambu',
            branch='Ruiru',
            status='active',
        )
        final_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Final queue farmer',
            national_id='66666666',
            primary_phone='254766666666',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 7, 1),
            credit_decision='Approved',
            imab_created='Yes',
            customer_no='15130',
            county='Nakuru',
            branch='Naivasha',
            status='active',
        )
        req_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Requisition queue farmer',
            national_id='55555555',
            primary_phone='254755555555',
            sign_date='24-June-2026',
            jbl_visit_date=date(2026, 7, 1),
            credit_decision='Approved',
            imab_created='Yes',
            customer_no='15131',
            final_decision='Approved',
            county='Meru',
            branch='Maua',
            status='active',
        )

        credit_response = self.client.get(reverse('portal_queue_fragment', args=['credit']))
        self.assertContains(credit_response, credit_farmer.customer_name)
        self.assertContains(credit_response, 'data-mode="credit"')

        final_response = self.client.get(reverse('portal_queue_fragment', args=['final']))
        self.assertContains(final_response, final_farmer.customer_name)
        self.assertContains(final_response, 'data-mode="final_review"')

        requisition_response = self.client.get(reverse('portal_queue_fragment', args=['requisition']))
        self.assertContains(requisition_response, req_farmer.customer_name)
        self.assertContains(requisition_response, 'farmer-card-checkbox')

        all_response = self.client.get(reverse('portal_queue_fragment', args=['all']), {'search': 'Pipeline test'})
        self.assertContains(all_response, 'Pipeline test farmer')
        self.assertNotContains(all_response, credit_farmer.customer_name)

    def test_portal_requisition_batches_fragment_renders_actions(self):
        """Verify the htmx batch fragment preserves batch action controls."""
        self.farmer.order_number = 'JBL-ORD-001'
        self.farmer.requisition_date = date(2026, 7, 2)
        self.farmer.save()
        RequisitionBatch.objects.create(
            order_number='JBL-ORD-001',
            requisition_date=date(2026, 7, 2),
            generated_by='tester',
            farmer_ids=[str(self.farmer.id)],
            farmer_count=1,
            status='generated',
            invoice_summary={'invoiced_count': 0, 'pending_invoice_count': 1},
        )

        response = self.client.get(reverse('portal_requisition_batches_fragment'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'portal/partials/batch_list.html')
        self.assertContains(response, 'Order JBL-ORD-001')
        self.assertContains(response, 'btn-view-batch')
        self.assertContains(response, 'btn-download-batch')
        self.assertContains(response, 'btn-upload-invoices')

    def test_dashboard_api(self):
        """Verify GET /api/portal/dashboard/ counts."""
        response = self.client.get(reverse('portal_dashboard'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['counts']['jbl_queue'], 1)

    def test_legacy_jbl_visit_write_route_requires_the_atomic_client(self):
        """Cached two-step clients cannot create an evidence/visit split."""
        url = reverse('portal_log_jbl_visit', args=[self.farmer.id])
        response = self.client.post(url, json.dumps({}), content_type='application/json')
        self.assertEqual(response.status_code, 426)
        self.assertEqual(response.json()['code'], 'jbl_visit_completion_upgrade_required')

    @patch('core.services.jawabu_pipeline.complete_jbl_visit')
    def test_atomic_jbl_visit_completion_accepts_both_evidence_categories(self, mock_complete):
        mock_complete.return_value = (True, '', {'stored_count': 2, 'evidence_saved': True})
        laf = SimpleUploadedFile('laf.pdf', b'x' * 5000, content_type='application/pdf')
        photo = SimpleUploadedFile('visit.jpg', b'x' * 5000, content_type='image/jpeg')
        response = self.client.post(
            reverse('portal_complete_jbl_visit', args=[self.farmer.id]),
            {
                'client_request_id': 'atomic-visit-001',
                'workflow_revision': self.farmer.workflow_revision,
                'visit_date': '2026-07-01',
                'visit_status': 'Awaiting Analysis',
                'officer': 'JBL Officer Alpha',
                'capture_latitude': '-1.2921',
                'capture_longitude': '36.8219',
                'laf_files': laf,
                'jbl_visit_photo_files': photo,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        categorized = mock_complete.call_args.kwargs['categorized_files']
        self.assertEqual(set(categorized), {'LAF', 'JBL_VISIT_PHOTO'})
        self.assertEqual(len(categorized['LAF']), 1)
        self.assertEqual(len(categorized['JBL_VISIT_PHOTO']), 1)

    def test_portal_workflow_write_requires_the_case_revision(self):
        response = self.client.post(
            reverse('portal_complete_jbl_visit', args=[self.farmer.id]),
            {
                'visit_date': '2026-07-01',
                'visit_status': 'Awaiting Analysis',
                'officer': 'JBL Officer Alpha',
            },
        )

        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.json()['code'], 'workflow_revision_required')

    def test_legacy_jbl_media_route_requires_the_atomic_client(self):
        url = reverse('portal_upload_jbl_media', args=[self.farmer.id])
        response = self.client.post(url, {'files': SimpleUploadedFile('visit.pdf', b'x' * 5000, content_type='application/pdf')})
        self.assertEqual(response.status_code, 426)

    def test_laf_media_list_api_returns_only_successful_client_laf_documents(self):
        MediaAttachment.objects.create(
            group_id='portal-test',
            business_key_type='id_number',
            business_key_value=self.farmer.national_id,
            file_type='LAF',
            original_filename='laf.pdf',
            mime_type='application/pdf',
            drive_file_id='drive-laf-1',
            drive_url='https://drive.example/laf',
            upload_status='success',
        )
        MediaAttachment.objects.create(
            group_id='portal-test',
            business_key_type='id_number',
            business_key_value=self.farmer.national_id,
            file_type='JBL_VISIT_PHOTO',
            original_filename='visit.jpg',
            drive_file_id='drive-photo-1',
            drive_url='https://drive.example/visit',
            upload_status='success',
        )
        MediaAttachment.objects.create(
            group_id='portal-test',
            business_key_type='id_number',
            business_key_value=self.farmer.national_id,
            file_type='LAF',
            original_filename='failed.pdf',
            drive_url='https://drive.example/failed',
            upload_status='failed',
        )

        response = self.client.get(reverse('portal_jbl_media', args=[self.farmer.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        media = payload['laf_media']
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(len(media), 1)
        self.assertIn(str(self.farmer.id), media[0]['view_url'])
        self.assertIn(str(media[0]['id']), media[0]['view_url'])
        self.assertIn('/media/', media[0]['preview_url'])
        self.assertTrue(media[0]['preview_url'].endswith('/preview/'))
        self.assertIn('/api/portal/jbl-media-open/', media[0]['open_url'])
        self.assertNotIn('drive.example', media[0]['open_url'])
        self.assertEqual(media[0]['name'], 'laf.pdf')
        self.assertEqual([item['name'] for item in payload['jbl_visit_photo_media']], ['visit.jpg'])
        self.assertEqual({item['category'] for item in payload['media']}, {'LAF', 'JBL_VISIT_PHOTO'})

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='test-media-folder')
    @patch('core.services.order_approval.GoogleDriveMediaStorage.download', return_value=b'\xff\xd8\xff\xe0test-photo')
    def test_preview_jbl_media_streams_authorized_drive_content_inside_portal(self, download):
        attachment = MediaAttachment.objects.create(
            group_id='portal-test', jawabu_farmer=self.farmer,
            business_key_type='case_reference', business_key_value=f'case-{self.farmer.pk}',
            file_type='JBL_VISIT_PHOTO', original_filename='visit.jpg', mime_type='image/jpeg',
            drive_file_id='drive-photo-preview', drive_url='https://drive.example/photo', upload_status='success',
        )

        response = self.client.get(reverse(
            'portal_preview_jbl_media', args=[self.farmer.id, attachment.id],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'\xff\xd8\xff\xe0test-photo')
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertIn('inline', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        download.assert_called_once_with('drive-photo-preview')
        self.assertTrue(JawabuMediaAccessEvent.objects.filter(
            farmer=self.farmer, attachment=attachment, action='view',
        ).exists())

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='test-media-folder')
    @patch('core.services.order_approval.GoogleDriveMediaStorage.download')
    def test_preview_jbl_pdf_is_rendered_as_internal_page_images(self, download):
        from pypdf import PdfWriter

        source_pdf = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        writer.write(source_pdf)
        download.return_value = source_pdf.getvalue()
        attachment = MediaAttachment.objects.create(
            group_id='portal-test', jawabu_farmer=self.farmer,
            business_key_type='case_reference', business_key_value=f'case-{self.farmer.pk}',
            file_type='LAF', original_filename='laf.pdf', mime_type='application/pdf',
            drive_file_id='drive-laf-preview', drive_url='https://drive.example/laf', upload_status='success',
        )

        response = self.client.get(reverse(
            'portal_preview_jbl_media', args=[self.farmer.id, attachment.id],
        ))

        self.assertEqual(response.status_code, 200)
        preview = response.content.decode('utf-8')
        self.assertTrue(response['Content-Type'].startswith('text/html'))
        self.assertIn('inline', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(preview.count('<figure>'), 2)
        self.assertIn('data:image/jpeg;base64,', preview)
        self.assertNotIn('drive.example', preview)
        download.assert_called_once_with('drive-laf-preview')
        self.assertTrue(JawabuMediaAccessEvent.objects.filter(
            farmer=self.farmer, attachment=attachment, action='view',
        ).exists())

    def test_open_jbl_media_redirects_and_records_an_access_event(self):
        attachment = MediaAttachment.objects.create(
            group_id='portal-test', jawabu_farmer=self.farmer,
            business_key_type='case_reference', business_key_value=f'case-{self.farmer.pk}',
            file_type='LAF', original_filename='laf.pdf',
            drive_url='https://drive.example/laf', upload_status='success',
        )

        response = self.client.get(reverse(
            'portal_open_jbl_media', args=[self.farmer.id, attachment.id],
        ))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], attachment.drive_url)
        self.assertTrue(JawabuMediaAccessEvent.objects.filter(
            farmer=self.farmer, attachment=attachment, action='view',
        ).exists())

    def test_signed_jbl_media_link_opens_in_external_browser_and_is_audited(self):
        attachment = MediaAttachment.objects.create(
            group_id='portal-test', jawabu_farmer=self.farmer,
            business_key_type='case_reference', business_key_value=f'case-{self.farmer.pk}',
            file_type='JBL_VISIT_PHOTO', original_filename='visit.jpg',
            drive_url='https://drive.example/visit', upload_status='success',
        )

        listing = self.client.get(reverse('portal_jbl_media', args=[self.farmer.id])).json()
        open_url = listing['media'][0]['open_url']
        response = self.client.get(urlsplit(open_url).path)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], attachment.drive_url)
        self.assertTrue(JawabuMediaAccessEvent.objects.filter(
            farmer=self.farmer, attachment=attachment, action='view',
        ).exists())

    def test_signed_jbl_media_link_rejects_tampering(self):
        response = self.client.get(reverse('portal_open_jbl_media_signed', args=['not-a-valid-token']))

        self.assertEqual(response.status_code, 404)
        self.assertIn('invalid or has expired', response.json()['error'])

    def test_legacy_jbl_media_list_includes_a_short_lived_external_open_link(self):
        self.farmer.jbl_media_urls = 'https://drive.example/legacy-laf'
        self.farmer.save(update_fields=['jbl_media_urls'])

        listing = self.client.get(reverse('portal_jbl_media', args=[self.farmer.id])).json()
        response = self.client.get(urlsplit(listing['laf_media'][0]['open_url']).path)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://drive.example/legacy-laf')

    def test_legacy_jbl_media_is_opened_through_an_audited_internal_redirect(self):
        self.farmer.jbl_media_urls = 'https://drive.example/legacy-laf'
        self.farmer.save(update_fields=['jbl_media_urls'])

        listing = self.client.get(reverse('portal_jbl_media', args=[self.farmer.id])).json()
        self.assertTrue(listing['laf_media'][0]['view_url'].endswith('/media/legacy/0/open/'))
        self.assertNotIn('drive.example', listing['laf_media'][0]['view_url'])
        response = self.client.get(reverse('portal_open_legacy_jbl_media', args=[self.farmer.id, 0]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://drive.example/legacy-laf')
        self.assertTrue(JawabuPipelineEvent.objects.filter(
            farmer=self.farmer, action='legacy_jbl_media_viewed',
        ).exists())

    def test_set_credit_decision_api(self):
        """Verify Stage 3 credit decision posting."""
        self.farmer.jbl_visit_date = date(2026, 7, 1)
        self.farmer.jbl_visit_status = 'Approved'
        self.farmer.save()

        payload = {'workflow_revision': self.farmer.workflow_revision, 'decision': 'Approved', 'imab_created': 'Yes', 'customer_no': '15122'}
        url = reverse('portal_set_credit_decision', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.credit_decision, 'Approved')
        self.assertEqual(self.farmer.imab_created, 'Yes')
        self.assertEqual(self.farmer.customer_no, '15122')

    def test_set_credit_decision_api_blocks_imab_no(self):
        """Verify the API blocks Head of Rural progression until IMAB is complete."""
        self.farmer.jbl_visit_date = date(2026, 7, 1)
        self.farmer.jbl_visit_status = 'Approved'
        self.farmer.save()

        payload = {'workflow_revision': self.farmer.workflow_revision, 'decision': 'Approved', 'imab_created': 'No', 'customer_no': '15122'}
        url = reverse('portal_set_credit_decision', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.assertIn('created in IMAB', response.json()['error'])

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.credit_decision, 'Pending')

    def test_portal_all_cases_filters_by_branch(self):
        """Verify all cases endpoint honors the branch filter from the Mini App."""
        self.farmer.customer_name = 'Branch Filter Farmer'
        self.farmer.county = 'Kiambu'
        self.farmer.branch = 'Ruiru'
        self.farmer.save()
        other = JawabuFarmerMaster.objects.create(
            customer_name='Other Branch Farmer',
            national_id='88888888',
            primary_phone='254788888888',
            county='Kiambu',
            branch='Thika',
            status='active',
        )

        response = self.client.get(reverse('portal_all_cases'), {'county': 'Kiambu', 'branch': 'Ruiru'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        ids = {item['id'] for item in data['farmers']}
        self.assertIn(str(self.farmer.id), ids)
        self.assertNotIn(str(other.id), ids)

    def test_set_final_decision_api(self):
        """Verify Head of Rural final review stores decision and after-call comments."""
        self.farmer.jbl_visit_date = date(2026, 7, 1)
        self.farmer.jbl_visit_status = 'Approved'
        self.farmer.credit_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15123'
        self.farmer.save()

        payload = {
            'workflow_revision': self.farmer.workflow_revision,
            'final_decision': 'Approved',
            'decision_comment': 'Called client; ready for order.',
            'repayment_date': '15TH',
            'repayment_tenor': '9 months',
        }
        url = reverse('portal_set_final_decision', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.final_decision, 'Approved')
        self.assertEqual(self.farmer.final_decision_comment, 'Called client; ready for order.')
        self.assertEqual(self.farmer.repayment_date, '15TH')
        self.assertEqual(self.farmer.repayment_tenor, '9 months')

    def test_individual_order_assignment_is_retired(self):
        """Orders can only be assigned by the selected-cases batch flow."""
        payload = {'workflow_revision': self.farmer.workflow_revision, 'order_number': 'JBL-2026-X1', 'requisition_date': '2026-07-02'}
        url = reverse('portal_assign_order', args=[self.farmer.id])
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()['ok'], False)
        self.assertEqual(response.json()['code'], 'batch_assignment_required')
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, '')

    def test_portal_requisition_preview_reports_ready_clients(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.final_decision_comment = 'Customer confirmed during callup.'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()
        self.mark_requisition_location_ready()
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
        self.assertEqual(
            data['workflow_revisions'],
            {str(self.farmer.id): self.farmer.workflow_revision},
        )
        self.assertEqual(data['ready'][0]['final_decision_comment'], 'Customer confirmed during callup.')

    def test_portal_document_preview_returns_printable_rows_without_workbook_canvas(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.deposit_paid_hbg = 5000
        self.farmer.save()
        self.mark_requisition_location_ready()
        payload = {
            'farmer_ids': [str(self.farmer.id)], 'order_number': 'REQ-DOCUMENT-1',
            'requisition_date': '2026-07-06', 'preview_format': 'document',
        }

        response = self.client.post(
            reverse('portal_requisition_preview'), json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['preview_format'], 'document')
        self.assertIsNone(data['workbook_preview'])
        self.assertEqual(data['ready'][0]['requisition_preview']['hbg_deposit'], '5000.00')

    def test_portal_requisition_preview_sets_jbl_deposit_to_zero(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.lead_source = 'JAWABU'
        self.farmer.actual_receipts = '7500'
        self.farmer.deposit_paid_hbg = None
        self.farmer.save()
        self.mark_requisition_location_ready()
        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-JBL-DEPOSIT-1',
            'requisition_date': '2026-07-06',
        }

        response = self.client.post(
            reverse('portal_requisition_preview'), json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        preview = response.json()['ready'][0]['requisition_preview']
        self.assertEqual(preview['hbg_deposit'], '')
        self.assertEqual(preview['jbl_deposit'], '0')

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

    def test_portal_requisition_preview_blocks_missing_constituency_and_village(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.sub_county = ''
        self.farmer.village = ''
        self.farmer.save()
        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-PREVIEW-LOCATION',
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
        self.assertIn('Constituency', data['blocked'][0]['missing'])
        self.assertIn('Village', data['blocked'][0]['missing'])

    def test_requisition_preview_merges_original_and_new_clients_for_existing_order(self):
        original = self.farmer
        original.final_decision = 'Approved'
        original.imab_created = 'Yes'
        original.customer_no = '15124'
        original.order_number = '001'
        original.requisition_date = date(2026, 7, 24)
        original.save()
        self.mark_requisition_location_ready(original)

        new_farmer = JawabuFarmerMaster.objects.create(
            customer_name='New order client',
            national_id='99999990',
            primary_phone='254799999990',
            county='Kiambu',
            branch='Ruiru',
            final_decision='Approved',
            imab_created='Yes',
            customer_no='15125',
            status='active',
        )
        self.mark_requisition_location_ready(new_farmer)

        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps({
                'farmer_ids': [str(new_farmer.id)],
                'order_number': '001',
                'requisition_date': '2026-07-24',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ready_count'], 2)
        self.assertEqual({row['id'] for row in data['ready']}, {str(original.id), str(new_farmer.id)})
        self.assertTrue(any('original clients and the newly selected clients' in warning['message'] for warning in data['warnings']))

    def test_batch_detail_recovers_original_clients_from_order_when_snapshot_is_stale(self):
        original = self.farmer
        original.order_number = '001'
        original.requisition_date = date(2026, 7, 24)
        original.save()
        extra = JawabuFarmerMaster.objects.create(
            customer_name='Later batch client',
            national_id='99999990',
            primary_phone='254799999990',
            order_number='001',
            requisition_date=date(2026, 7, 24),
            status='active',
        )
        # Simulate a batch row written by the old implementation with only the
        # latest client IDs.
        RequisitionBatch.objects.create(
            order_number='001',
            requisition_date=date(2026, 7, 24),
            farmer_ids=[str(extra.id)],
            farmer_count=1,
        )

        response = self.client.get(reverse('portal_requisition_batch_detail', args=['001']))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row['id'] for row in response.json()['batch']['farmers']},
            {str(original.id), str(extra.id)},
        )
        self.assertEqual(response.json()['batch']['farmer_count'], 2)

    def test_requisition_date_conflict_is_rejected_without_changing_existing_order(self):
        original = self.farmer
        original.final_decision = 'Approved'
        original.imab_created = 'Yes'
        original.customer_no = '15124'
        original.order_number = '001'
        original.requisition_date = date(2026, 7, 24)
        original.save()
        self.mark_requisition_location_ready(original)

        new_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Different date client',
            national_id='99999990',
            primary_phone='254799999990',
            county='Kiambu',
            branch='Ruiru',
            final_decision='Approved',
            imab_created='Yes',
            customer_no='15125',
            status='active',
        )
        self.mark_requisition_location_ready(new_farmer)

        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps({
                'farmer_ids': [str(new_farmer.id)],
                'order_number': '001',
                'requisition_date': '2026-07-25',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'requisition_date_conflict')
        self.assertIn('24-July-2026', response.json()['error'])
        new_farmer.refresh_from_db()
        self.assertEqual(new_farmer.order_number, '')
        self.assertIsNone(new_farmer.requisition_date)

    def test_same_date_is_allowed_when_batch_snapshot_has_a_stale_date(self):
        original = self.farmer
        original.final_decision = 'Approved'
        original.imab_created = 'Yes'
        original.customer_no = '15124'
        original.order_number = '001'
        original.requisition_date = date(2026, 7, 24)
        original.save()
        self.mark_requisition_location_ready(original)
        RequisitionBatch.objects.create(
            order_number='001',
            requisition_date=date(2026, 7, 25),
            farmer_ids=[str(original.id)],
            farmer_count=1,
        )

        new_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Same date client',
            national_id='99999990',
            primary_phone='254799999990',
            county='Kiambu',
            branch='Ruiru',
            final_decision='Approved',
            imab_created='Yes',
            customer_no='15125',
            status='active',
        )
        self.mark_requisition_location_ready(new_farmer)
        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps({
                'farmer_ids': [str(new_farmer.id)],
                'order_number': '001',
                'requisition_date': '2026-07-24',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

    def test_requisition_preview_repairs_inconsistent_order_when_known_date_is_selected(self):
        original = self.farmer
        original.final_decision = 'Approved'
        original.imab_created = 'Yes'
        original.customer_no = '15124'
        original.order_number = '001'
        original.requisition_date = date(2026, 7, 13)
        original.save()
        self.mark_requisition_location_ready(original)

        other = JawabuFarmerMaster.objects.create(
            customer_name='Older inconsistent client',
            national_id='99999990',
            primary_phone='254799999990',
            county='Kiambu',
            branch='Ruiru',
            final_decision='Approved',
            imab_created='Yes',
            customer_no='15125',
            order_number='001',
            requisition_date=date(2026, 7, 27),
            status='active',
        )
        self.mark_requisition_location_ready(other)

        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps({
                'farmer_ids': [str(original.id)],
                'order_number': '001',
                'requisition_date': '2026-07-13',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(any('inconsistent existing requisition dates' in item['message'] for item in data['warnings']))

    def test_batch_preview_rejects_different_date_for_existing_order(self):
        original = self.farmer
        original.final_decision = 'Approved'
        original.order_number = '001'
        original.requisition_date = date(2026, 7, 24)
        original.save()
        new_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Assignment date client',
            national_id='99999990',
            primary_phone='254799999990',
            final_decision='Approved',
            status='active',
        )

        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps({'farmer_ids': [str(new_farmer.id)], 'order_number': '001', 'requisition_date': '2026-07-25'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'requisition_date_conflict')
        new_farmer.refresh_from_db()
        self.assertEqual(new_farmer.order_number, '')
        self.assertIsNone(new_farmer.requisition_date)

    def test_batch_preview_allows_same_date_for_existing_order(self):
        original = self.farmer
        original.final_decision = 'Approved'
        original.order_number = '001'
        original.requisition_date = date(2026, 7, 24)
        original.save()
        new_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Same assignment date client',
            national_id='99999991',
            primary_phone='254799999991',
            final_decision='Approved',
            status='active',
        )

        response = self.client.post(
            reverse('portal_requisition_preview'),
            json.dumps({'farmer_ids': [str(new_farmer.id)], 'order_number': '001', 'requisition_date': '2026-07-24'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        new_farmer.refresh_from_db()
        self.assertEqual(new_farmer.order_number, '')
        self.assertIsNone(new_farmer.requisition_date)

    @patch('core.services.requisition.generate_requisition_excel', return_value=b'xlsx-bytes')
    @patch('core.services.portal_publication.reserve_farmer_publication', return_value=[])
    def test_portal_requisition_generate_success(self, mock_reserve_publication, mock_generate):
        """Generation commits locally; external publication is a later retry."""
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()
        self.mark_requisition_location_ready()
        RequisitionBatch.objects.create(
            order_number='REQ-BATCH-99',
            invoice_summary={
                'last_invoice_upload_status': 'success',
                'last_invoice_upload_error': '',
                'invoice_batch_id': 'upload-001',
            },
        )

        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'workflow_revisions': {str(self.farmer.id): self.farmer.workflow_revision},
            'order_number': 'REQ-BATCH-99',
            'requisition_date': '2026-07-06',
            'return_url': True,
            'client_request_id': 'requisition-generation-test-001',
        }
        url = reverse('portal_requisition_generate')
        response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['filename'], 'JBL_Requisition_Form_REQ-BATCH-99_v1.xlsx')
        self.assertEqual(data['drive_url'], '')
        self.assertTrue(data['drive_sync_pending'])
        self.assertEqual(data['batch']['invoice_summary']['last_invoice_upload_status'], 'success')
        self.assertEqual(data['batch']['invoice_summary']['invoice_batch_id'], 'upload-001')
        self.assertIn('/api/portal/requisition-download/', data['download_url'])
        self.assertTrue(RequisitionBatch.objects.filter(
            order_number='REQ-BATCH-99',
            generation_request_id='requisition-generation-test-001',
            drive_upload_error='Drive synchronization pending.',
        ).exists())

        download_response = self.client.get(data['download_url'])
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            download_response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('attachment; filename="JBL_Requisition_Form_REQ-BATCH-99_v1.xlsx"', download_response['Content-Disposition'])

        second_response = self.client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(second_response.status_code, 200)
        second_data = second_response.json()
        self.assertTrue(second_data['idempotent_replay'])
        self.assertEqual(second_data['filename'], 'JBL_Requisition_Form_REQ-BATCH-99_v1.xlsx')
        latest_batch = RequisitionBatch.objects.get(order_number='REQ-BATCH-99')
        self.assertEqual(latest_batch.version, 1)

        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, 'REQ-BATCH-99')
        self.assertEqual(self.farmer.requisition_date, date(2026, 7, 6))
        mock_reserve_publication.assert_called_once()
        self.assertEqual(mock_generate.call_count, 1)

    @patch('core.services.requisition.generate_requisition_excel', return_value=b'preview-xlsx')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_portal_requisition_workbook_preview_stores_drive_preview(self, mock_storage, mock_generate):
        mock_storage.return_value.upload.return_value = ('preview-drive-id', 'https://drive.test/requisition-preview')
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()
        self.mark_requisition_location_ready()

        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'order_number': 'REQ-PREVIEW-99',
            'requisition_date': '2026-07-06',
        }
        response = self.client.post(
            reverse('portal_requisition_workbook_preview'),
            json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['drive_url'], 'https://drive.test/requisition-preview')
        batch = RequisitionBatch.objects.get(order_number='REQ-PREVIEW-99')
        self.assertEqual(batch.status, 'preview')
        self.assertEqual(batch.preview_version, 1)
        self.assertEqual(batch.preview_filename, 'JBL_Requisition_Form_REQ-PREVIEW-99_preview_v1.xlsx')
        self.assertEqual(batch.preview_drive_file_id, 'preview-drive-id')
        self.assertEqual(batch.preview_drive_url, 'https://drive.test/requisition-preview')
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, '')
        second_response = self.client.post(
            reverse('portal_requisition_workbook_preview'),
            json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(second_response.status_code, 200)
        second_batch = RequisitionBatch.objects.get(order_number='REQ-PREVIEW-99')
        self.assertEqual(second_batch.preview_version, 2)
        self.assertEqual(second_batch.preview_filename, 'JBL_Requisition_Form_REQ-PREVIEW-99_preview_v2.xlsx')
        self.assertEqual(mock_generate.call_count, 2)

    @patch('core.services.requisition.generate_requisition_excel', return_value=b'new-xlsx')
    def test_requisition_generation_keeps_local_workbook_when_drive_publication_is_pending(self, mock_generate):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()
        self.mark_requisition_location_ready()
        RequisitionBatch.objects.create(
            order_number='REQ-RETRY-1',
            version=1,
            filename='JBL_Requisition_Form_REQ-RETRY-1_v1.xlsx',
            file_content=b'previous-xlsx',
            drive_file_id='previous-drive-id',
            drive_url='https://drive.test/previous-order',
            farmer_ids=[str(self.farmer.id)],
            farmer_count=1,
        )
        response = self.client.post(
            reverse('portal_requisition_generate'),
            json.dumps({
                'farmer_ids': [str(self.farmer.id)],
                'workflow_revisions': {str(self.farmer.id): self.farmer.workflow_revision},
                'order_number': 'REQ-RETRY-1',
                'requisition_date': '2026-07-06',
                'return_url': True,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['drive_sync_pending'])
        batch = RequisitionBatch.objects.get(order_number='REQ-RETRY-1')
        self.assertEqual(batch.drive_file_id, 'previous-drive-id')
        self.assertEqual(batch.drive_url, 'https://drive.test/previous-order')
        self.assertEqual(batch.file_content, b'new-xlsx')
        self.assertEqual(batch.drive_upload_error, 'Drive synchronization pending.')

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_requisition_batch_retry_uploads_stored_workbook(self, mock_storage):
        batch = RequisitionBatch.objects.create(
            order_number='REQ-RETRY-SUCCESS',
            filename='JBL_Requisition_Form_REQ-RETRY-SUCCESS_v1.xlsx',
            file_content=b'previous-xlsx',
            drive_upload_error='Drive upload failed; retry required.',
            drive_sync_attempts=1,
            farmer_ids=[str(self.farmer.id)],
            farmer_count=1,
        )
        mock_storage.return_value.upload.return_value = (
            'retry-drive-id', 'https://drive.test/retried-order',
        )

        response = self.client.post(
            reverse('portal_requisition_batch_retry_sync', args=[batch.order_number]),
        )

        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.drive_file_id, 'retry-drive-id')
        self.assertEqual(batch.drive_url, 'https://drive.test/retried-order')
        self.assertEqual(batch.drive_upload_error, '')
        self.assertEqual(batch.drive_sync_attempts, 2)
        self.assertIn('_retry2.xlsx', batch.filename)

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

        self.assertEqual(detail_data['batch']['drive_sync_status'], 'not_requested')

        download = self.client.get(reverse('portal_requisition_batch_download', args=['REQ-DETAIL-1']))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b'xlsx-bytes')

    @override_settings(BASE_DIR='C:/tmp/no-requisition-template')
    def test_portal_requisition_generate_reports_missing_template(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.save()
        self.mark_requisition_location_ready()
        payload = {
            'farmer_ids': [str(self.farmer.id)],
            'workflow_revisions': {str(self.farmer.id): self.farmer.workflow_revision},
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

    def test_portal_requisition_generate_requires_a_revision_for_each_new_assignment(self):
        self.farmer.jbl_visit_date = date(2026, 7, 1)
        self.farmer.jbl_visit_status = 'Approved'
        self.farmer.credit_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '15124'
        self.farmer.final_decision = 'Approved'
        self.farmer.save()
        self.mark_requisition_location_ready()

        response = self.client.post(
            reverse('portal_requisition_generate'),
            json.dumps({
                'farmer_ids': [str(self.farmer.id)],
                'order_number': 'REQ-REVISION-REQUIRED',
                'requisition_date': '2026-07-06',
                'return_url': True,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 428)
        self.assertEqual(response.json()['code'], 'workflow_revision_required')
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.order_number, '')

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
        self.assertEqual(db_farmer.case_comments.count(), 1)
        comment = db_farmer.case_comments.get()
        self.assertEqual(comment.comment, 'A comment')
        self.assertEqual(comment.role_label, 'JBL Officer')

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
    @patch('core.services.invoice_parser.parse_invoice_pdf_bytes')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_invoice_upload_updates_requisition_batch_status(self, mock_storage, mock_parse_pdf, mock_match):
        from core.api.portal_views import portal_upload_batch_invoices

        mock_storage.return_value.upload.return_value = ('drive-id', 'https://drive.test/invoices')
        mock_parse_pdf.return_value = ([{
            'page': 1,
            'invoice_no': 'INV-1',
            'customer_name': self.farmer.customer_name,
            'customer_id': self.farmer.national_id,
            'customer_phone': self.farmer.primary_phone,
            'invoice_amount': '54000',
        }], 1)
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
            return {
                'ok': True,
                'order_number': order_number,
                'total_parsed': 1,
                'matched_count': 1,
                'candidate_count': 1,
                'results': [{
                    'status': 'Matched',
                    'invoice_no': 'INV-1',
                    'matched_farmer_id': str(self.farmer.id),
                    'matched_order_number': order_number,
                    'customer_name': self.farmer.customer_name,
                }],
            }

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
        self.assertEqual(batch.status, 'needs_review')
        self.assertTrue(payload['requires_confirmation'])
        self.assertEqual(batch.invoice_summary['last_invoice_upload_status'], 'awaiting_confirmation')
        self.assertEqual(batch.invoice_summary['pending_invoice_count'], 1)
        self.assertEqual(batch.last_invoice_result['invoice_batch_status'], 'awaiting_confirmation')

    @patch('core.services.invoice_parser.PdfReader')
    @patch('core.services.invoice_parser.reserve_farmer_publication')
    def test_invoice_matching_updates_farmer_and_reserves_register_publication(self, mock_reserve_publication, mock_pdf_reader):
        from decimal import Decimal
        from core.services.invoice_parser import match_and_update_invoices
        from core.tests import FakeMasterDataSheet, FakeJawabuService

        # Setup mock sheet service
        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'Invoice Number', 'Invoice Date', 'Invoice Amount', 'Discount', 'Payment', 'Balance Due']
        fake_sheet = FakeMasterDataSheet(headers, [
            '1', 'DAVID MUGAMBI', '23215888', '254712345678', '', '', '', '', '', ''
        ])

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
        self.assertEqual(farmer.deposit_paid_hbg, Decimal('10000.00'))
        self.assertEqual(farmer.balance_due, Decimal('74900.00'))

        # The invoice transaction is canonical locally.  Google Sheets is a
        # separately retried operational register publication.
        mock_reserve_publication.assert_called_once()

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
        self.assertEqual(farmer.deposit_paid_hbg, Decimal('5000.00'))
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
    def test_invoice_register_failure_does_not_roll_back_canonical_invoice(self, mock_get_sheets, mock_pdf_reader):
        from decimal import Decimal
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

        self.assertTrue(res['ok'], msg=str(res))
        self.assertEqual(res['matched_count'], 1)
        self.assertEqual(res['results'][0]['status'], 'Matched')
        farmer.refresh_from_db()
        self.assertEqual(farmer.invoice_number, '9505')
        self.assertEqual(farmer.invoice_date, date(2026, 3, 16))
        self.assertEqual(farmer.invoice_amount, Decimal('51000.00'))

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


class JawabuIntegrityRulesTests(TestCase):
    def test_additional_unit_reuses_customer_and_allocates_next_number(self):
        from core.services.jawabu_identity import resolve_application_identity

        cleaned = {'national_id': '12345678', 'primary_phone': '254712345678'}
        customer, unit, _existing = resolve_application_identity(cleaned)
        self.assertEqual(unit, 1)
        first = JawabuFarmerMaster.objects.create(
            customer=customer,
            unit_number=unit,
            national_id='12345678',
            primary_phone='254712345678',
        )
        same_customer, second_unit, second_existing = resolve_application_identity(
            cleaned,
            action='create_additional_unit',
        )
        self.assertEqual(same_customer, customer)
        self.assertEqual(second_unit, 2)
        self.assertIsNone(second_existing)
        self.assertEqual(first.unit_number, 1)

    def test_additional_unit_requires_reason_and_does_not_overwrite_first_unit(self):
        from core.services.jawabu_master import upsert_farmer

        base = {
            'source': 'test',
            'source_name': 'test.csv',
            'source_row_number': 1,
            'source_fingerprint': 'repeat-unit-source',
            'customer_name': 'Repeat Client',
            'national_id': '12345678',
            'primary_phone': '254712345678',
            'sign_date': '24-June-2026',
            'duplicate_key': 'repeat-client-key',
            'status': 'active',
        }
        first_created, _ = upsert_farmer({**base, 'application_action': 'update_existing'})
        self.assertTrue(first_created)
        first = JawabuFarmerMaster.objects.get(duplicate_key='repeat-client-key')
        self.assertEqual(first.jbl_visit_status, 'JBL to Schedule Visit')
        self.assertTrue(first.pipeline_events.filter(action='jbl_visit_scheduled').exists())

        with self.assertRaisesMessage(ValueError, 'Additional Unit Reason is required'):
            upsert_farmer({
                **base,
                'source_row_number': 2,
                'source_fingerprint': 'repeat-unit-source-2',
                'application_action': 'create_additional_unit',
            })

        second_created, _ = upsert_farmer({
            **base,
            'source_row_number': 2,
            'source_fingerprint': 'repeat-unit-source-2',
            'application_action': 'create_additional_unit',
            'additional_unit_reason': 'Customer requested a second installation.',
        })
        units = list(JawabuFarmerMaster.objects.order_by('unit_number').values_list('unit_number', flat=True))
        self.assertTrue(second_created)
        self.assertEqual(units, [1, 2])

    def test_jbl_schedule_backfill_is_previewed_then_reverted_safely(self):
        candidate = JawabuFarmerMaster.objects.create(
            customer_name='Historical HBG Visit', national_id='12345679',
            primary_phone='254712345679', sign_date='24-June-2026', status='active',
        )
        already_visited = JawabuFarmerMaster.objects.create(
            customer_name='Already Visited', national_id='12345670',
            primary_phone='254712345670', sign_date='24-June-2026',
            jbl_visit_date=date(2026, 6, 25), jbl_visit_status='Approved', status='active',
        )
        preview = StringIO()
        call_command('backfill_jbl_schedule_status', stdout=preview)
        candidate.refresh_from_db()
        self.assertEqual(candidate.jbl_visit_status, '')
        self.assertIn('Dry run only', preview.getvalue())

        call_command('backfill_jbl_schedule_status', '--apply', '--run-id', 'test-schedule-run')
        candidate.refresh_from_db()
        already_visited.refresh_from_db()
        self.assertEqual(candidate.jbl_visit_status, 'JBL to Schedule Visit')
        self.assertEqual(already_visited.jbl_visit_status, 'Approved')
        self.assertTrue(candidate.pipeline_events.filter(
            action='jbl_visit_schedule_backfilled', metadata__backfill_run='test-schedule-run',
        ).exists())

        call_command('backfill_jbl_schedule_status', '--apply', '--revert-run', 'test-schedule-run')
        candidate.refresh_from_db()
        self.assertEqual(candidate.jbl_visit_status, '')

    def test_reappraisal_starts_at_beginning_of_day_91(self):
        from core.services.jawabu_pipeline import is_reappraisal_required

        farmer = JawabuFarmerMaster(deferred_until=timezone.localdate() + timedelta(days=1))
        self.assertFalse(is_reappraisal_required(farmer, today=timezone.localdate()))
        self.assertTrue(is_reappraisal_required(farmer, today=farmer.deferred_until))

    @patch('core.services.invoice_parser.reserve_farmer_publication', return_value=[])
    def test_invoice_batch_does_not_update_farmer_until_whole_batch_confirmed(self, _publication):
        from core.services.invoice_parser import confirm_invoice_batch

        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Draft Customer',
            order_number='ORDER-1',
        )
        batch = InvoiceUploadBatch.objects.create(
            order_number='ORDER-1',
            status='awaiting_confirmation',
            total_parsed=1,
        )
        ParsedInvoice.objects.create(
            batch=batch,
            status='draft',
            invoice_no='INV-1',
            invoice_date=date(2026, 7, 24),
            proposed_farmer=farmer,
            proposed_order_number='ORDER-1',
            invoice_amount='54000.00',
        )
        farmer.refresh_from_db()
        self.assertEqual(farmer.invoice_number, '')
        confirm_invoice_batch(batch, actor='tester')
        farmer.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(farmer.invoice_number, 'INV-1')
        self.assertEqual(batch.status, 'matched')
        self.assertEqual(batch.sync_status, 'pending')


class JawabuCase360Tests(TestCase):
    def test_case360_data_migration_is_idempotent(self):
        import importlib
        from django.apps import apps

        migration = importlib.import_module('core.migrations.0053_initialize_jawabu_case360')
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Legacy Customer', sign_date='24-June-2026', actual_receipts='KES 5,000',
        )

        migration.initialize_case360(apps, None)
        migration.initialize_case360(apps, None)
        farmer.refresh_from_db()

        self.assertEqual(str(farmer.deposit_paid_hbg), '5000.00')
        self.assertEqual(farmer.hbg_visit_date.isoformat(), '2026-06-24')
        self.assertEqual(
            farmer.pipeline_events.filter(action='tracking_started', source='migration').count(),
            1,
        )

    def test_tat_excludes_formal_deferral_minutes(self):
        from core.services.jawabu_case360 import calculate_case_tat, record_pipeline_event

        farmer = JawabuFarmerMaster.objects.create(customer_name='Timeline Customer')
        start = timezone.now() - timedelta(hours=3)
        record_pipeline_event(farmer, action='application_imported', stage_key='intake', occurred_at=start)
        record_pipeline_event(farmer, action='deferral_started', stage_key='jbl_visit', occurred_at=start + timedelta(minutes=30))
        record_pipeline_event(farmer, action='deferral_ended', stage_key='jbl_visit', occurred_at=start + timedelta(minutes=90))
        record_pipeline_event(farmer, action='jbl_visit_completed', stage_key='jbl_visit', occurred_at=start + timedelta(minutes=120))

        tat = calculate_case_tat(farmer, now=start + timedelta(minutes=180))

        self.assertEqual(tat['stages'][0]['minutes'], '60.00')
        self.assertEqual(tat['stages'][0]['excluded_deferred_minutes'], '60.00')

    def test_new_unit_application_starts_a_fresh_tat_cycle(self):
        from core.services.jawabu_case360 import calculate_case_tat, record_pipeline_event

        farmer = JawabuFarmerMaster.objects.create(customer_name='Repeat Customer')
        old_start = timezone.now() - timedelta(days=10)
        record_pipeline_event(farmer, action='application_imported', stage_key='intake', occurred_at=old_start)
        record_pipeline_event(farmer, action='jbl_visit_completed', stage_key='jbl_visit', occurred_at=old_start + timedelta(days=1))
        new_start = timezone.now() - timedelta(hours=2)
        record_pipeline_event(farmer, action='application_imported', stage_key='intake', occurred_at=new_start)

        tat = calculate_case_tat(farmer, now=new_start + timedelta(hours=2))

        self.assertEqual(tat['previous_cycle_count'], 1)
        self.assertEqual(tat['stages'][0]['completed_at'], None)
        self.assertEqual(tat['stages'][0]['minutes'], '120.00')

    def test_case360_exposes_business_sections_without_raw_payload(self):
        from core.services.jawabu_case360 import record_pipeline_event, serialize_case360

        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Case 360 Customer', national_id='12345678',
            primary_phone='254712345678', raw_data={'private_parser_value': 'hidden'},
            deposit_paid_hbg='5000.00', jbl_visit_date=date(2026, 7, 24),
        )
        record_pipeline_event(farmer, action='tracking_started', stage_key='tracking')

        payload = serialize_case360(farmer)

        self.assertEqual(payload['sections']['identity']['national_id'], '12345678')
        self.assertEqual(payload['sections']['intake']['deposit_paid_hbg'], '5000')
        self.assertNotIn('ward', payload['sections']['intake'])
        self.assertEqual(payload['sections']['jbl_visit']['visit_date'], '24-July-2026')
        self.assertEqual(payload['timeline'][0]['action'], 'tracking_started')
        self.assertNotIn('raw_data', str(payload))

    def test_order_request_id_is_idempotent(self):
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Idempotent Customer', final_decision='Approved',
        )
        first = assign_order(farmer, order_number='ORDER-IDEMP', request_id='request-1')
        second = assign_order(farmer, order_number='ORDER-CHANGED', request_id='request-1')
        farmer.refresh_from_db()

        self.assertEqual(first, (True, ''))
        self.assertEqual(second, (True, ''))
        self.assertEqual(farmer.order_number, 'ORDER-IDEMP')
        self.assertEqual(farmer.pipeline_events.filter(request_id='request-1').count(), 1)
