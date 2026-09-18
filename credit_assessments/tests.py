import base64

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import MagicMock, patch

from core.models import TatTrackerCase

from .models import AssessmentDecision, CreditAssessment, StatementMailReceipt
from .mailbox import _statement_metadata, ingest_message, poll_mailbox
from .services import (
    AssessmentError,
    confirm_statement,
    get_or_create_assessment,
    manager_authorize,
    masked_phone_matches,
    parse_statement_filename,
    submit_pre_appraisal,
)


@override_settings(
    GOOGLE_DRIVE_MEDIA_FOLDER_ID='test-folder',
)
class CreditAssessmentServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.bro = User.objects.create_user(username='assessment-bro', email='bro@example.com')
        self.manager = User.objects.create_user(username='assessment-bm', email='bm@example.com')
        self.case = TatTrackerCase.objects.create(
            group_id='-1001', case_id='TAT-1', product_key='business', product_label='Business',
            client_name='TEST CUSTOMER', national_id='12345678', primary_phone='254712345716',
            branch='EMBU', bro_name='BRO', stage_values={},
        )
        self.bro_context = {'roles': ['BRO'], '_canonical_user': self.bro}
        self.manager_context = {'roles': ['BM'], '_canonical_user': self.manager}

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

    def test_start_is_idempotent_per_tat_case(self):
        first = get_or_create_assessment(case=self.case, user=self.bro_context, request_id='start-1')
        second = get_or_create_assessment(case=self.case, user=self.bro_context, request_id='start-1')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.events.count(), 1)

    @override_settings(CREDIT_ASSESSMENT_GMAIL_USER='pool@example.com')
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
