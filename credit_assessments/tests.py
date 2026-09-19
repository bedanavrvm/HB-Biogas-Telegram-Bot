import base64
import hashlib
import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import MagicMock, patch

from core.models import GroupSheetConfiguration, TatTrackerCase
from core.services.tat_tracker import update_case

from .models import AssessmentDecision, CreditAssessment, StatementMailReceipt
from .mailbox import _statement_metadata, ingest_message, poll_mailbox
from .services import (
    AssessmentError,
    bro_review,
    confirm_statement,
    get_or_create_assessment,
    manager_authorize,
    manager_decide,
    masked_phone_matches,
    parse_statement_filename,
    submit_analysis,
    submit_pre_appraisal,
)


@override_settings(
    GOOGLE_DRIVE_MEDIA_FOLDER_ID='test-folder',
    CREDIT_ASSESSMENT_GMAIL_ENABLED=True,
)
class CreditAssessmentServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.bro = User.objects.create_user(username='assessment-bro', email='bro@example.com')
        self.manager = User.objects.create_user(username='assessment-bm', email='bm@example.com')
        self.admin = User.objects.create_user(username='assessment-admin', email='admin@example.com')
        self.analyst = User.objects.create_user(username='assessment-ca', email='ca@example.com')
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-1001', display_name='Credit assessment TAT',
            workflow={'type': 'tat_tracker', 'products': ['business'], 'branches': ['EMBU']},
        )
        self.case = TatTrackerCase.objects.create(
            group_id='-1001', case_id='TAT-1', product_key='business', product_label='Business',
            client_name='TEST CUSTOMER', national_id='12345678', primary_phone='254712345716',
            branch='EMBU', bro_name='BRO', stage_values={},
        )
        self.bro_context = {'roles': ['BRO'], '_canonical_user': self.bro, 'user_id': self.bro.pk, 'name': 'BRO'}
        self.manager_context = {
            'roles': ['BM'], '_canonical_user': self.manager, 'user_id': self.manager.pk,
            'name': 'Branch Manager', 'signing_national_id': '12345678',
            'signing_phone_number': '254700000001', 'signing_email': self.manager.email,
        }
        self.admin_context = {
            'roles': ['BUSINESS_ADMIN'], '_canonical_user': self.admin,
            'user_id': self.admin.pk, 'name': 'Business Admin',
        }
        self.analyst_context = {'roles': ['CA'], '_canonical_user': self.analyst, 'user_id': self.analyst.pk, 'name': 'Analyst'}

    def _receipt(self, *, full_year=True):
        return StatementMailReceipt.objects.create(
            gmail_message_id='mail-1', gmail_attachment_id='attachment-1',
            forwarding_sender=self.bro.email,
            inbox_received_at=timezone.now(),
            attachment_name='MPESA_Statement_2026-03-13_to_2025-03-13_2547xxxxxx716.pdf',
            attachment_hash='a' * 64, attachment_size=100,
            masked_phone_pattern='2547xxxxxx716', statement_period_start='2025-03-13',
            statement_period_end='2026-03-13', statement_full_year=full_year,
        )

    def test_filename_accepts_provider_reverse_date_order(self):
        parsed = parse_statement_filename('MPESA_Statement_2026-03-13_to_2025-03-13_2547xxxxxx716.pdf')
        self.assertEqual(parsed.period_start.isoformat(), '2025-03-13')
        self.assertEqual(parsed.period_end.isoformat(), '2026-03-13')
        self.assertTrue(parsed.full_year)
        self.assertTrue(masked_phone_matches(parsed.masked_phone, self.case.primary_phone))

    def test_gmail_attachment_identifier_allows_provider_opaque_values(self):
        field = StatementMailReceipt._meta.get_field('gmail_attachment_id')
        self.assertEqual(field.max_length, 2048)

    def test_email_body_metadata_overrides_unredacted_filename_phone(self):
        metadata = _statement_metadata(
            'MPESA_Statement_2026-09-18_to_2025-09-18_254712345716.pdf',
            body=(
                'Dear Name One Name Two,\n\nPlease find attached M-PESA Statement for '
                'Name One Name Two, mobile number 254712***716 for period '
                '18 Sep 2025 - 18 Sep 2026.'
            ),
        )
        self.assertEqual(metadata['masked_phone'], '254712***716')
        self.assertEqual(metadata['customer_name'], 'Name One Name Two')
        self.assertEqual(metadata['period_start'].isoformat(), '2025-09-18')
        self.assertEqual(metadata['period_end'].isoformat(), '2026-09-18')
        self.assertTrue(metadata['full_year'])
        self.assertEqual(metadata['source'], 'body')

    def test_repoll_enriches_existing_filename_only_receipt(self):
        receipt = self._receipt()
        receipt.masked_phone_pattern = '254712345716'
        receipt.statement_metadata_source = 'filename'
        receipt.save(update_fields=['masked_phone_pattern', 'statement_metadata_source'])
        body = (
            'Please find attached M-PESA Statement for Name One Name Two, '
            'mobile number 254712***716 for period 18 Sep 2025 - 18 Sep 2026.'
        )
        service = MagicMock()
        service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            'id': 'mail-1',
            'threadId': 'thread-1',
            'internalDate': str(int(timezone.now().timestamp() * 1000)),
            'payload': {
                'headers': [{'name': 'Subject', 'value': 'Fwd: M-PESA Statement'}],
                'parts': [
                    {'mimeType': 'text/plain', 'body': {'data': base64.urlsafe_b64encode(body.encode()).decode()}},
                    {'filename': receipt.attachment_name, 'body': {'attachmentId': 'attachment-1'}},
                ],
            },
        }

        result = ingest_message(service, 'mail-1', commit=True)

        receipt.refresh_from_db()
        self.assertEqual(result['enriched'], 1)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(receipt.masked_phone_pattern, '254712***716')
        self.assertEqual(receipt.customer_name, 'Name One Name Two')
        self.assertEqual(receipt.statement_metadata_source, 'body')

    def test_repoll_uses_message_and_content_hash_when_attachment_id_changes(self):
        data = b'%PDF-1.4\nsame encrypted statement bytes'
        receipt = self._receipt()
        receipt.attachment_hash = hashlib.sha256(data).hexdigest()
        receipt.save(update_fields=['attachment_hash'])
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.get.return_value.execute.return_value = {
            'id': 'mail-1',
            'threadId': 'thread-1',
            'internalDate': str(int(timezone.now().timestamp() * 1000)),
            'payload': {
                'headers': [{'name': 'Subject', 'value': 'Fwd: M-PESA Statement'}],
                'parts': [{
                    'filename': receipt.attachment_name,
                    'body': {'attachmentId': 'replacement-provider-id'},
                }],
            },
        }
        messages.attachments.return_value.get.return_value.execute.return_value = {
            'data': base64.urlsafe_b64encode(data).decode('ascii'),
        }

        with patch('core.services.order_approval.GoogleDriveMediaStorage.upload') as upload:
            result = ingest_message(service, 'mail-1', commit=True)

        self.assertEqual(result['ingested'], 0)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(StatementMailReceipt.objects.count(), 1)
        upload.assert_not_called()

    def test_mobile_pdf_preview_accepts_statement_password(self):
        from pypdf import PdfWriter
        from core.services.secure_media_preview import pdf_preview_html

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.encrypt('123456')
        encrypted = io.BytesIO()
        writer.write(encrypted)

        preview = pdf_preview_html(
            encrypted.getvalue(), 'statement.pdf', password='123456',
        )

        self.assertIn(b'data:image/jpeg;base64,', preview)

    def test_short_statement_reaches_manager_and_only_return_is_available(self):
        assessment = get_or_create_assessment(case=self.case, user=self.bro_context, request_id='start-1')
        receipt = self._receipt(full_year=False)
        assessment = confirm_statement(
            assessment=assessment, receipt_id=receipt.pk, user=self.bro_context,
            expected_revision=assessment.revision, request_id='statement-1',
        )
        with patch('core.services.order_approval.GoogleDriveMediaStorage.upload', return_value=('drive-1', '')):
            assessment = submit_pre_appraisal(
                assessment=assessment, user=self.bro_context, expected_revision=assessment.revision,
                request_id='pre-1', pre_appraisal_file=SimpleUploadedFile('pre.pdf', b'%PDF-1.4\ntest'),
                signed_laf_reference='', signed_laf_hash='', passcode='123456',
            )
        self.assertEqual(assessment.state, CreditAssessment.STATE_PENDING_AUTHORIZATION)
        self.case.refresh_from_db()
        self.assertEqual(self.case.current_stage, 'mpesa_verified')
        with self.assertRaises(AssessmentError):
            manager_authorize(
                assessment=assessment, user=self.manager_context, expected_revision=assessment.revision,
                request_id='approve-1', action=AssessmentDecision.ACTION_APPROVED, comment='',
            )
        assessment = manager_authorize(
            assessment=assessment, user=self.manager_context, expected_revision=assessment.revision,
            request_id='return-1', action=AssessmentDecision.ACTION_RETURNED,
            comment='Request the full twelve-month statement.',
        )
        self.assertEqual(assessment.state, CreditAssessment.STATE_RETURNED_PRE_ANALYSIS)
        self.case.refresh_from_db()
        self.assertEqual(self.case.current_stage, 'mpesa_verified')

    def test_assessment_milestones_advance_and_route_canonical_tat(self):
        from core.services.tat_tracker import (
            can_user_edit_stage, next_action, next_role_alert, serialize_case_summary,
        )
        from .services import serialize_assessment

        assessment = get_or_create_assessment(case=self.case, user=self.bro_context, request_id='start-flow')
        receipt = self._receipt(full_year=True)
        assessment = confirm_statement(
            assessment=assessment, receipt_id=receipt.pk, user=self.bro_context,
            expected_revision=assessment.revision, request_id='statement-flow',
        )
        with patch('core.services.order_approval.GoogleDriveMediaStorage.upload', return_value=('drive-1', '')):
            assessment = submit_pre_appraisal(
                assessment=assessment, user=self.bro_context, expected_revision=assessment.revision,
                request_id='pre-flow', pre_appraisal_file=SimpleUploadedFile('pre.pdf', b'%PDF-1.4\ntest'),
                signed_laf_reference='', signed_laf_hash='', passcode='123456',
            )
        self.case.refresh_from_db()
        self.assertEqual(self.case.current_stage, 'mpesa_verified')
        self.assertEqual(next_action(self.case).role, 'BM')
        self.assertFalse(can_user_edit_stage(self.admin_context, self.case, next_action(self.case)))
        summary = serialize_case_summary(self.case, self.manager_context)
        self.assertEqual(summary['next_stage_role'], 'BM')
        self.assertEqual(next_role_alert(self.config, {'summary': summary})['role'], 'BM')

        assessment = manager_authorize(
            assessment=assessment, user=self.manager_context, expected_revision=assessment.revision,
            request_id='authorize-flow', action='approved', comment='',
        )
        self.case.refresh_from_db()
        self.assertEqual(self.case.current_stage, 'mpesa_verified')
        self.assertEqual(next_action(self.case).role, 'BUSINESS_ADMIN')
        self.assertTrue(can_user_edit_stage(self.admin_context, self.case, next_action(self.case)))
        admin_payload = serialize_assessment(assessment, self.admin_context)
        self.assertEqual(admin_payload['state_label'], 'Awaiting Admin M-PESA verification')
        self.assertFalse(admin_payload['can_act'])

        update_case(
            self.config, self.admin_context, self.case.case_id,
            [{'field': 'mpesa_verified', 'value': ''}],
            expected_revision=self.case.workflow_revision,
            request_id='admin-verify-flow',
        )
        self.case.refresh_from_db()
        self.assertEqual(self.case.current_stage, 'ca_analysis_sent')
        self.assertEqual(next_action(self.case).role, 'CA')

        with patch('core.services.order_approval.GoogleDriveMediaStorage.upload', return_value=('drive-2', '')):
            assessment = submit_analysis(
                assessment=assessment, user=self.analyst_context, expected_revision=assessment.revision,
                request_id='analysis-flow', analysis_file=SimpleUploadedFile('analysis.pdf', b'%PDF-1.4\nanalysis'),
                questions=[],
            )
        self.case.refresh_from_db()
        self.assertEqual(self.case.current_stage, 'bro_response')
        self.assertEqual(next_action(self.case).role, 'BRO')

        assessment = bro_review(
            assessment=assessment, user=self.bro_context, expected_revision=assessment.revision,
            request_id='bro-flow', responses={},
        )
        self.case.refresh_from_db()
        self.assertEqual(assessment.state, CreditAssessment.STATE_PENDING_DECISION)
        self.assertEqual(self.case.current_stage, 'bm_response')
        self.assertEqual(next_action(self.case).role, 'BM')

        assessment = manager_decide(
            assessment=assessment, user=self.manager_context,
            expected_revision=assessment.revision, request_id='final-bm-flow',
            action='approved', comment='Approved after review.',
        )
        self.case.refresh_from_db()
        self.assertEqual(assessment.state, CreditAssessment.STATE_APPROVED)
        self.assertEqual(self.case.stage_values['bm_response'], 'Approved')

    def test_start_is_idempotent_per_tat_case(self):
        first = get_or_create_assessment(case=self.case, user=self.bro_context, request_id='start-1')
        second = get_or_create_assessment(case=self.case, user=self.bro_context, request_id='start-1')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.events.count(), 1)

    @override_settings(CREDIT_ASSESSMENT_GMAIL_ENABLED=False)
    def test_disabled_flag_removes_assessment_routing_override(self):
        get_or_create_assessment(case=self.case, user=self.bro_context, request_id='start-disabled')
        from core.services.tat_tracker import credit_assessment_required_role

        self.assertEqual(credit_assessment_required_role(self.case), '')

    @override_settings(
        CREDIT_ASSESSMENT_GMAIL_ENABLED=True,
        CREDIT_ASSESSMENT_GMAIL_USER='pool@example.com',
    )
    @patch('credit_assessments.mailbox._gmail_service')
    def test_mailbox_searches_for_recent_pdfs_before_strict_filename_validation(self, service_factory):
        service = MagicMock()
        service_factory.return_value = service
        users = service.users.return_value
        users.getProfile.return_value.execute.return_value = {'emailAddress': 'pool@example.com'}
        users.messages.return_value.list.return_value.execute.return_value = {'messages': []}

        result = poll_mailbox(commit=False, limit=50)

        self.assertEqual(result['messages'], 0)
        users.messages.return_value.list.assert_called_once_with(
            userId='me',
            q='has:attachment filename:pdf newer_than:180d',
            maxResults=50,
        )

    @override_settings(
        CREDIT_ASSESSMENT_GMAIL_ENABLED=False,
        CREDIT_ASSESSMENT_GMAIL_USER='pool@example.com',
    )
    def test_disabled_flag_prevents_mailbox_polling(self):
        with self.assertRaisesRegex(RuntimeError, 'credit_mailbox_disabled'):
            poll_mailbox(commit=False, limit=50)

    @override_settings(CREDIT_ASSESSMENT_GMAIL_ENABLED=False)
    def test_disabled_flag_closes_credit_assessment_http_boundaries(self):
        for route_name in (
            'credit_assessment_detail',
            'credit_assessment_action',
            'credit_assessment_document',
        ):
            response = self.client.post(reverse(route_name), data={})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()['code'], 'credit_assessment_disabled')
