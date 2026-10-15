"""Africa's Talking response contracts; all provider traffic is mocked."""

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from core.services.external_resilience import ExternalOperationError
from origination.services.origination_esign import _send_sms


@override_settings(
    AFRICASTALKING_USERNAME='synthetic-live-app',
    AFRICASTALKING_API_KEY='synthetic-key',
    AFRICASTALKING_SENDER_ID='SYNTHETIC',
)
class SmsSubmissionTests(SimpleTestCase):
    def test_provider_rejection_is_not_a_successful_send(self):
        sdk = Mock()
        sdk.SMS.send.return_value = {'SMSMessageData': {'Recipients': [{
            'statusCode': 405, 'status': 'InsufficientBalance', 'messageId': '',
        }]}}
        with patch.dict('sys.modules', {'africastalking': sdk}):
            with self.assertRaises(ExternalOperationError):
                _send_sms('Synthetic verification code', '254712345678')
        sdk.SMS.send.assert_called_once()

    def test_empty_response_is_not_assumed_accepted(self):
        sdk = Mock()
        sdk.SMS.send.return_value = {'SMSMessageData': {'Recipients': []}}
        with patch.dict('sys.modules', {'africastalking': sdk}):
            with self.assertRaises(ExternalOperationError):
                _send_sms('Synthetic verification code', '254712345678')

    def test_documented_acceptance_codes_require_a_message_id(self):
        for code, label in ((100, 'Processed'), (101, 'Success'), ('102', 'Queued')):
            with self.subTest(code=code):
                sdk = Mock()
                sdk.SMS.send.return_value = {'SMSMessageData': {'Recipients': [{
                    'statusCode': code, 'status': label, 'messageId': 'synthetic-message',
                }]}}
                with patch.dict('sys.modules', {'africastalking': sdk}):
                    result = _send_sms('Synthetic verification code', '254712345678')
                self.assertEqual(result, {'id': 'synthetic-message', 'status': label})
                sdk.initialize.assert_called_once_with('synthetic-live-app', 'synthetic-key')
                sdk.SMS.send.assert_called_once_with(
                    'Synthetic verification code', ['+254712345678'],
                    sender_id='SYNTHETIC', enqueue=False,
                )

    def test_code_only_or_legacy_status_only_acceptance_is_supported(self):
        for recipient, expected in (
            ({'statusCode': 100, 'messageId': 'synthetic-message'}, 'Processed'),
            ({'statusCode': 101, 'messageId': 'synthetic-message'}, 'Sent'),
            ({'statusCode': 102, 'messageId': 'synthetic-message'}, 'Queued'),
            ({'status': 'Success', 'message_id': 'synthetic-message'}, 'Success'),
        ):
            with self.subTest(recipient=recipient):
                sdk = Mock()
                sdk.SMS.send.return_value = {'SMSMessageData': {'Recipients': [recipient]}}
                with patch.dict('sys.modules', {'africastalking': sdk}):
                    self.assertEqual(_send_sms('Synthetic SMS', '254712345678')['status'], expected)

    def test_failure_codes_win_over_success_text_and_nonempty_message_id(self):
        for code in (401, 402, 403, 404, 405, 406, 407, 500, 501, 502):
            with self.subTest(code=code):
                sdk = Mock()
                sdk.SMS.send.return_value = {'SMSMessageData': {'Recipients': [{
                    'statusCode': code, 'status': 'Success', 'messageId': 'synthetic-rejected-message',
                }]}}
                with patch.dict('sys.modules', {'africastalking': sdk}):
                    with self.assertRaises(ExternalOperationError) as caught:
                        _send_sms('Sensitive synthetic code', '254712345678')
                self.assertNotIn('Sensitive synthetic code', str(caught.exception))
                self.assertNotIn('254712345678', str(caught.exception))
                self.assertTrue(caught.exception.rejected)

    def test_malformed_or_unconfirmed_responses_fail_closed(self):
        invalid_recipients = (
            {}, {'status': 'Success'}, {'statusCode': 101},
            {'statusCode': 101, 'messageId': ' '},
            {'statusCode': 101, 'messageId': 123},
            {'statusCode': 101, 'messageId': 'x' * 256},
            {'status': 'unrecognized', 'messageId': 'synthetic-message'},
            {'statusCode': 999, 'status': 'Success', 'messageId': 'synthetic-message'},
            {'statusCode': 101, 'status': 'Failed', 'messageId': 'synthetic-message'},
            {'statusCode': 101, 'status': 'RejectedByGateway', 'messageId': 'synthetic-message'},
        )
        responses = [None, [], 'invalid response', {}, {'SMSMessageData': []}]
        responses += [{'SMSMessageData': {'Recipients': value}} for value in (None, '', {}, [], [None], [{}, {}])]
        responses += [{'SMSMessageData': {'Recipients': [recipient]}} for recipient in invalid_recipients]
        for response in responses:
            with self.subTest(response=response):
                sdk = Mock()
                sdk.SMS.send.return_value = response
                with patch.dict('sys.modules', {'africastalking': sdk}):
                    with self.assertRaises(ExternalOperationError):
                        _send_sms('Synthetic verification code', '254712345678')

    @override_settings(AFRICASTALKING_SENDER_ID='')
    def test_optional_sender_id_does_not_change_response_validation(self):
        sdk = Mock()
        sdk.SMS.send.return_value = {'SMSMessageData': {'Recipients': [{
            'statusCode': 101, 'status': 'Success', 'messageId': 'synthetic-message',
        }]}}
        with patch.dict('sys.modules', {'africastalking': sdk}):
            _send_sms('Synthetic verification code', '254712345678')
        self.assertIsNone(sdk.SMS.send.call_args.kwargs['sender_id'])
