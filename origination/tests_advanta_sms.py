"""Synthetic provider contracts; no SMS provider is contacted."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
from threading import Event
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import IntegrationOperation
from core.services.external_resilience import ExternalOperationError
from core import tests_origination_esign as signing_fixtures
from origination.models import OriginationOtpChallenge
from origination.services.origination_esign import (
    dispatch_otp, issue_otp, record_delivery_report, send_signing_invitation, verify_otp,
)
from origination.services.origination_signing_configuration import signing_available
from origination.services.origination_sms import (
    OriginationSmsSubmissionError, delivery_state, gsm7_units,
    lookup_delivery, submit,
)
from origination.services.origination_sms_delivery import reconcile_delivery, runner_health

SETTINGS = {
    'ORIGINATION_ESIGN_ENABLED': True, 'ORIGINATION_SMS_PROVIDER': 'advanta',
    'ORIGINATION_ADVANTA_PARTNER_ID': 'synthetic-partner',
    'ORIGINATION_ADVANTA_API_KEY': 'synthetic-secret', 'ORIGINATION_ADVANTA_SENDER_ID': 'SYNTHETIC',
    'AFRICASTALKING_SMS_ENVIRONMENT': 'sandbox', 'AFRICASTALKING_USERNAME': 'sandbox',
    'AFRICASTALKING_API_KEY': 'synthetic-at-key', 'APP_BASE_URL': 'https://example.test',
}


def accepted(message_id='synthetic-message', **changes):
    return {'responses': [{'response-code': 200, 'response-description': 'Success',
                           'mobile': '254712345678', 'messageid': message_id, **changes}]}


@override_settings(**SETTINGS)
class AdvantaTransportTests(SimpleTestCase):
    def test_transactional_post_contract(self):
        with patch('origination.services.origination_sms.requests.post', return_value=Mock(
                status_code=200, json=Mock(return_value=accepted()))) as post:
            result = submit('Synthetic verification', '0712345678', provider='advanta')
        self.assertEqual(result, {'id': 'synthetic-message', 'status': 'Accepted'})
        self.assertEqual(post.call_args.args[0], 'https://quicksms.advantasms.com/api/services/sendotp')
        self.assertEqual(post.call_args.kwargs['json'], {'apikey': 'synthetic-secret',
            'partnerID': 'synthetic-partner', 'mobile': '254712345678',
            'message': 'Synthetic verification', 'shortcode': 'SYNTHETIC'})
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertLessEqual(sum(post.call_args.kwargs['timeout']), 10)
        self.assertTrue(post.call_args.kwargs['verify'])

    def test_rejections_and_uncertain_responses_are_not_success(self):
        rows = [None, [], {}, {'responses': []}, {'responses': [{}, {}]},
                accepted(messageid=''), accepted(messageid=123), accepted(mobile='254700000001'),
                accepted(**{'response-description': 'Failed'}),
                accepted(**{'response-code': 200, 'respose-code': 1006}),
                {'response-code': 1006, **accepted()},
                accepted(**{'response-code': 4090}), accepted(messageid='x' * 256)]
        for body in rows:
            with self.subTest(body=body), patch('origination.services.origination_sms._advanta_post', return_value=body):
                with self.assertRaises(OriginationSmsSubmissionError):
                    submit('synthetic code', '0712345678', provider='advanta')

    def test_known_rejection_is_allowlisted_and_legacy_response_key_works(self):
        for code in (1001, 1002, 1003, 1004, 1006):
            with self.subTest(code=code), patch('origination.services.origination_sms._advanta_post',
                    return_value={'response-code': code, 'response-description': 'sensitive raw data'}):
                with self.assertRaises(OriginationSmsSubmissionError) as caught:
                    submit('sensitive synthetic code', '0712345678', provider='advanta')
                self.assertTrue(caught.exception.rejected)
                self.assertNotIn('sensitive', str(caught.exception))
        legacy = accepted()
        legacy['responses'][0]['respose-code'] = legacy['responses'][0].pop('response-code')
        with patch('origination.services.origination_sms._advanta_post', return_value=legacy):
            self.assertEqual(submit('Synthetic', '0712345678', provider='advanta')['status'], 'Accepted')

    def test_http_timeout_redirect_nonjson_and_body_errors_do_not_leak(self):
        values = [Mock(status_code=302), Mock(status_code=500),
                  Mock(status_code=200, json=Mock(side_effect=ValueError('secret'))),
                  Mock(status_code=200, json=Mock(return_value=[]))]
        for response in values:
            with patch('origination.services.origination_sms.requests.post', return_value=response) as post:
                with self.assertRaises(OriginationSmsSubmissionError) as caught:
                    submit('Synthetic', '0712345678', provider='advanta')
                self.assertFalse(caught.exception.rejected)
                post.assert_called_once()
        with patch('origination.services.origination_sms.requests.post', side_effect=TimeoutError('synthetic-secret')):
            with self.assertRaises(OriginationSmsSubmissionError) as caught:
                submit('Synthetic', '0712345678', provider='advanta')
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn('synthetic-secret', str(caught.exception))

    def test_delivery_contract_and_statuses(self):
        for status, expected in [('DeliveredToTerminal', 'delivered'), ('SentToNetwork', 'accepted'),
                ('Scheduled', 'accepted'), ('AbsentSubscriber', 'failed'), ('DeliveryImpossible', 'failed'),
                ('SenderName Blacklisted', 'failed'), ('Unknown', 'unknown'), ('new vendor state', 'unknown')]:
            self.assertEqual(delivery_state('advanta', status), expected)
        with patch('origination.services.origination_sms._advanta_post', return_value={
                'response-code': 200, 'message-id': 'synthetic-id', 'delivery-description': 'DeliveredToTerminal'}) as post:
            self.assertEqual(lookup_delivery('synthetic-id', provider='advanta')['state'], 'delivered')
        self.assertEqual(post.call_args.args[0], 'getdlr')
        self.assertEqual(post.call_args.args[1]['messageID'], 'synthetic-id')
        for code in (1008, 1009):
            with patch('origination.services.origination_sms._advanta_post', return_value={'response-code': code}):
                self.assertEqual(lookup_delivery('synthetic-id', provider='advanta')['state'], 'unknown')
        with patch('origination.services.origination_sms._advanta_post', return_value={
                'response-code': 200, 'message-id': 'someone-else'}):
            with self.assertRaises(OriginationSmsSubmissionError):
                lookup_delivery('synthetic-id', provider='advanta')

    @override_settings(AFRICASTALKING_USERNAME='', AFRICASTALKING_API_KEY='')
    def test_unused_provider_cannot_block_advanta_and_invalid_selector_never_falls_back(self):
        from django.conf import settings
        self.assertTrue(signing_available(settings))
        with override_settings(ORIGINATION_SMS_PROVIDER='unknown'):
            self.assertFalse(signing_available(settings))
        for name in ('ORIGINATION_ADVANTA_PARTNER_ID', 'ORIGINATION_ADVANTA_API_KEY', 'ORIGINATION_ADVANTA_SENDER_ID'):
            with override_settings(**{name: ''}):
                self.assertFalse(signing_available(settings))

    def test_encoding_counter_does_not_truncate_urls_or_miscount_extension_characters(self):
        self.assertEqual(gsm7_units('JBL code: 123456.'), 17)
        self.assertEqual(gsm7_units('a^{}'), 7)
        self.assertIsNone(gsm7_units('JBL — verification'))


@override_settings(**SETTINGS)
class AdvantaWorkflowTests(TestCase):
    # Reuse only synthetic fixture preparation, not all inherited tests.
    setUp = signing_fixtures.OriginationVerifiedSigningTests.setUp
    _session = signing_fixtures.OriginationVerifiedSigningTests._session
    _sms_session = signing_fixtures.OriginationVerifiedSigningTests._sms_session
    _otp_request = signing_fixtures.OriginationVerifiedSigningTests._otp_request

    def _send(self, key='advanta'):
        session, token = self._sms_session(f'{key}-session')
        with patch('origination.services.origination_sms._advanta_post', return_value=accepted()) as post:
            challenge, code, _ = issue_otp(raw_token=token, request_id=f'{key}-otp', ip_hash='synthetic-ip')
            dispatch_otp(challenge, code)
        self.assertEqual(post.call_count, 1)
        operation = IntegrationOperation.objects.get(operation_type='origination_signing_otp', source_id=str(challenge.pk))
        return session, token, challenge, code, operation

    def _due(self, operation, **changes):
        operation.refresh_from_db()
        metadata = dict(operation.metadata)
        metadata['sms'].update(lookup_due_at=(timezone.now() - timedelta(minutes=1)).isoformat(), **changes)
        operation.metadata = metadata
        operation.save(update_fields=['metadata'])

    def test_new_link_pins_provider_and_replay_survives_environment_switch(self):
        session, token, _ = self._session()
        self.assertEqual(session.sms_provider, 'advanta')
        with override_settings(ORIGINATION_SMS_PROVIDER='africas_talking', AFRICASTALKING_API_KEY=''):
            replay, same_token, repeated = self._session()
            self.assertTrue(repeated)
            self.assertEqual(replay.sms_provider, 'advanta')
            self.assertEqual(same_token, token)
            with patch('origination.services.origination_sms._advanta_post', return_value=accepted()) as post:
                send_signing_invitation(session, token, request_id='invite-one')
                send_signing_invitation(session, token, request_id='invite-one')
            post.assert_called_once()
        session.sms_provider = 'africas_talking'
        with self.assertRaises(ValidationError):
            session.save()

    def test_existing_africas_talking_link_is_not_rerouted_to_advanta(self):
        with override_settings(ORIGINATION_SMS_PROVIDER='africas_talking'):
            session, token = self._sms_session('original-at-link')
        with patch('origination.services.origination_esign._send_sms',
                return_value={'id': 'synthetic-at-id', 'status': 'Queued'}) as sms:
            challenge, code, _ = issue_otp(raw_token=token, request_id='original-at-otp', ip_hash='synthetic-ip')
            dispatch_otp(challenge, code)
        self.assertEqual(sms.call_args.kwargs['provider'], 'africas_talking')
        self.assertEqual(IntegrationOperation.objects.get(source_id=str(challenge.pk)).integration, 'africas_talking')

    def test_replacing_link_is_explicit_and_adopts_current_provider(self):
        from origination.services.origination_esign import reset_signer_session
        with override_settings(ORIGINATION_SMS_PROVIDER='africas_talking'):
            session, token, _ = self._session('old-provider-link')
        replacement, new_token = reset_signer_session(session_id=session.pk, actor=self.actor,
            request_id='replacement-provider-link', reason='Synthetic explicit replacement')
        self.assertEqual(replacement.sms_provider, 'advanta')
        self.assertNotEqual(token, new_token)
        session.refresh_from_db()
        self.assertFalse(session.is_active)

    def test_withdrawal_uncertainty_is_not_retried(self):
        from origination.services.origination_dispatch import _reserve, process_operations
        session, _, _ = self._session('withdrawal-link')
        self.package.status = 'cancelled'
        self.package.save(update_fields=['status'])
        operation = _reserve('origination_withdrawal_sms', session, self.actor)
        with patch('origination.services.origination_esign._send_sms',
                side_effect=OriginationSmsSubmissionError('send_unconfirmed')) as sms:
            process_operations([operation.pk])
            process_operations([operation.pk])
        sms.assert_called_once()
        self.assertEqual(sms.call_args.kwargs['provider'], 'advanta')
        operation.refresh_from_db()
        self.assertEqual((operation.attempts, operation.max_attempts), (1, 1))
        self.assertEqual(operation.status, 'dead_letter')
        self.assertEqual(operation.metadata['sms']['submission'], 'unknown')

    def test_transactional_message_copy_fits_one_gsm7_message(self):
        from origination.services.origination_dispatch import _reserve, process_operations
        session, token = self._sms_session('message-copy')
        with patch('origination.services.origination_esign._send_sms',
                return_value={'id': 'synthetic-copy', 'status': 'Accepted'}) as sms:
            send_signing_invitation(session, token, request_id='message-copy-invite')
            challenge, code, _ = issue_otp(raw_token=token, request_id='message-copy-otp', ip_hash='synthetic-ip')
            dispatch_otp(challenge, code)
            self.package.status = 'cancelled'
            self.package.save(update_fields=['status'])
            operation = _reserve('origination_withdrawal_sms', session, self.actor)
            process_operations([operation.pk])
        self.assertEqual(sms.call_count, 3)
        for call in sms.call_args_list:
            units = gsm7_units(call.args[0])
            self.assertIsNotNone(units)
            self.assertLessEqual(units, 160)

    def test_invitation_receipt_is_provider_scoped_and_recorded_on_its_operation(self):
        with override_settings(ORIGINATION_SMS_PROVIDER='africas_talking'):
            session, token, _ = self._session('at-invitation')
        with patch('origination.services.origination_esign._send_sms', return_value={
                'id': 'synthetic-invitation-id', 'status': 'Queued'}):
            send_signing_invitation(session, token, request_id='at-invitation-send')
        self.assertTrue(record_delivery_report(provider_message_id='synthetic-invitation-id', provider_status='Delivered'))
        operation = IntegrationOperation.objects.get(source_id=str(session.pk))
        self.assertEqual(operation.metadata['sms']['delivery'], 'delivered')
        self.assertFalse(record_delivery_report(provider='advanta', provider_message_id='synthetic-invitation-id', provider_status='Failed'))
        self.assertFalse(self.package.actions.exists())

    def test_otp_is_sent_once_retains_provider_and_contains_no_secret_metadata(self):
        session, token, challenge, code, operation = self._send()
        with override_settings(ORIGINATION_SMS_PROVIDER='africas_talking'), patch(
                'origination.services.origination_sms._advanta_post') as post:
            replay, raw_code, repeated = issue_otp(raw_token=token, request_id='advanta-otp', ip_hash='synthetic-ip')
            self.assertTrue(repeated)
            self.assertEqual(raw_code, '')
            dispatch_otp(replay, raw_code)
            post.assert_not_called()
        challenge.refresh_from_db()
        self.assertEqual(challenge.provider_message_id, 'synthetic-message')
        self.assertEqual(challenge.delivery_status, 'accepted')
        self.assertEqual(operation.integration, 'advanta')
        retained = json.dumps(operation.metadata)
        for secret in (token, code, 'synthetic-secret', session.phone_normalized):
            self.assertNotIn(secret, retained)
        self.assertEqual(operation.attempts, 1)

    def test_invitation_replay_recovers_acceptance_before_generic_operation_checkpoint(self):
        session, token, _ = self._session('checkpoint-link')
        with patch('origination.services.origination_sms._advanta_post', return_value=accepted()) as post:
            send_signing_invitation(session, token, request_id='checkpoint-invite')
            operation = IntegrationOperation.objects.get(source_id=str(session.pk))
            operation.status = 'running'
            operation.save(update_fields=['status'])
            result = send_signing_invitation(session, token, request_id='checkpoint-invite')
        post.assert_called_once()
        self.assertEqual(result['id'], 'synthetic-message')

    def test_unknown_send_keeps_verification_usable_and_retry_does_not_send(self):
        session, token = self._sms_session('uncertain-session')
        challenge, code, _ = issue_otp(raw_token=token, request_id='uncertain-otp', ip_hash='synthetic-ip')
        with patch('origination.services.origination_sms._advanta_post',
                side_effect=OriginationSmsSubmissionError('send_unconfirmed')) as post:
            with self.assertRaises(ExternalOperationError):
                dispatch_otp(challenge, code)
            with self.assertRaises(ExternalOperationError):
                dispatch_otp(challenge, code)
            post.assert_called_once()
        challenge.refresh_from_db()
        self.assertEqual(challenge.delivery_status, 'unknown')
        with patch('origination.services.origination_esign._archive_signed_package_after_commit'):
            verified = verify_otp(raw_token=token, code=code, request_id='uncertain-verify', ip_hash='synthetic-ip')
        self.assertEqual(verified.status, 'verified')

    def test_receipt_updates_only_delivery_and_cannot_downgrade(self):
        session, token, challenge, _, operation = self._send()
        self._due(operation)
        with patch('origination.services.origination_sms_delivery.lookup_delivery',
                return_value={'state': 'delivered', 'status': 'DeliveredToTerminal'}):
            self.assertTrue(reconcile_delivery(operation.pk))
        challenge.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(challenge.delivery_status, 'delivered')
        self.assertEqual(session.status, 'otp_sent')
        self.assertIsNone(challenge.verified_at)
        self.assertFalse(self.package.actions.exists())
        operation.refresh_from_db()
        self.assertTrue(operation.metadata['sms']['lookup_done'])
        self.assertEqual(operation.attempts, 1)
        # AT's endpoint cannot match an Advanta message, even with the same ID.
        self.assertFalse(record_delivery_report(provider_message_id=challenge.provider_message_id, provider_status='Failed'))

    def test_failed_delivery_is_terminal_and_does_not_invalidate_correct_code(self):
        _, token, challenge, code, operation = self._send()
        self._due(operation)
        with patch('origination.services.origination_sms_delivery.lookup_delivery',
                return_value={'state': 'failed', 'status': 'DeliveryImpossible'}):
            reconcile_delivery(operation.pk)
        challenge.refresh_from_db()
        self.assertEqual(challenge.delivery_status, 'failed')
        with patch('origination.services.origination_esign._archive_signed_package_after_commit'):
            self.assertEqual(verify_otp(raw_token=token, code=code, request_id='late-code', ip_hash='synthetic-ip').status, 'verified')

    def test_lookup_lease_account_change_and_stale_recovery(self):
        _, _, _, _, operation = self._send()
        self._due(operation, lookup_lease_until=(timezone.now() + timedelta(minutes=1)).isoformat())
        with patch('origination.services.origination_sms_delivery.lookup_delivery') as lookup:
            self.assertFalse(reconcile_delivery(operation.pk))
            lookup.assert_not_called()
        self._due(operation, lookup_lease_until=(timezone.now() - timedelta(minutes=1)).isoformat(), account='different-account')
        with patch('origination.services.origination_sms_delivery.lookup_delivery') as lookup:
            self.assertTrue(reconcile_delivery(operation.pk))
            lookup.assert_not_called()
        operation.refresh_from_db()
        self.assertEqual(operation.metadata['sms']['lookup_error'], 'account_changed')
        self.assertEqual(operation.attempts, 1)

    def test_missing_reports_exhaust_lookup_schedule_not_send_budget(self):
        _, _, challenge, _, operation = self._send()
        with patch('origination.services.origination_sms_delivery.lookup_delivery',
                return_value={'state': 'unknown', 'status': 'report_unavailable'}) as lookup:
            for _ in range(7):
                self._due(operation)
                self.assertTrue(reconcile_delivery(operation.pk))
        self.assertEqual(lookup.call_count, 7)
        operation.refresh_from_db()
        challenge.refresh_from_db()
        self.assertTrue(operation.metadata['sms']['lookup_done'])
        self.assertEqual(operation.attempts, 1)
        self.assertEqual(challenge.delivery_status, 'accepted')

    def test_runner_is_read_only_by_default_and_apply_works_without_browser(self):
        _, _, _, _, operation = self._send()
        self._due(operation)
        with patch('origination.services.origination_sms_delivery.lookup_delivery',
                return_value={'state': 'delivered', 'status': 'DeliveredToTerminal'}) as lookup:
            call_command('process_origination_deliveries', stdout=StringIO())
            lookup.assert_not_called()
            call_command('process_origination_deliveries', apply=True, stdout=StringIO())
            lookup.assert_called_once()
        self.assertTrue(runner_health()['fresh'])

    def test_runner_limits_work_and_zero_budget_does_not_call_provider(self):
        from origination.services.origination_sms_delivery import eligible_lookups, initial_metadata, process_due_lookups
        now = timezone.now()
        for index in range(6):
            metadata = initial_metadata('advanta')
            metadata['sms'].update(submission='accepted', message_id=f'synthetic-bounded-{index}',
                lookup_done=False, lookup_index=0, sent_at=now.isoformat(),
                lookup_due_at=(now - timedelta(minutes=1)).isoformat())
            IntegrationOperation.objects.create(integration='advanta', operation_type='origination_signing_invitation',
                deduplication_key=f'synthetic-bounded-{index}', status='succeeded', attempts=1, metadata=metadata)
        with patch('origination.services.origination_sms_delivery.lookup_delivery',
                return_value={'state': 'delivered', 'status': 'DeliveredToTerminal'}) as lookup:
            self.assertEqual(process_due_lookups(max_seconds=0), 0)
            lookup.assert_not_called()
            call_command('process_origination_deliveries', apply=True, stdout=StringIO())
            self.assertEqual(lookup.call_count, 5)
        self.assertEqual(eligible_lookups().count(), 1)

    def test_changing_environment_does_not_reset_phone_limits(self):
        session, token, _, _, _ = self._send()
        with override_settings(ORIGINATION_SMS_PROVIDER='africas_talking'):
            with self.assertRaisesRegex(Exception, '60 seconds'):
                issue_otp(raw_token=token, request_id='too-soon', ip_hash='synthetic-ip')
        self.assertEqual(session.otp_challenges.count(), 1)

    def test_duplicate_receipt_ids_are_ignored_within_one_provider(self):
        _, _, challenge, _, _ = self._send()
        OriginationOtpChallenge.objects.create(session=challenge.session, code_hash='synthetic', binding_sha256='a' * 64,
            provider_message_id=challenge.provider_message_id, send_sequence=2, request_id='ambiguous', expires_at=challenge.expires_at)
        self.assertFalse(record_delivery_report(provider='advanta', provider_message_id=challenge.provider_message_id,
                                               provider_status='DeliveredToTerminal'))
        challenge.refresh_from_db()
        self.assertEqual(challenge.delivery_status, 'accepted')

    def test_readiness_warns_for_stale_runner_and_original_provider_not_current_default(self):
        from django.conf import settings
        from origination.services.origination_production import origination_signing_readiness_issues
        with override_settings(ORIGINATION_SMS_PROVIDER='africas_talking'):
            self._session('at-configuration-history')
        with override_settings(AFRICASTALKING_API_KEY=''):
            codes = {item.code for item in origination_signing_readiness_issues(settings)}
            self.assertIn('origination-esign-existing-provider', codes)
            self.assertIn('origination-esign-delivery-runner', codes)
            self.assertNotIn('origination-esign-api-key', codes)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks.')
@override_settings(**SETTINGS)
class AdvantaConcurrencyTests(TransactionTestCase):
    setUp = signing_fixtures.OriginationVerifiedSigningTests.setUp
    _session = signing_fixtures.OriginationVerifiedSigningTests._session

    def test_two_workers_submit_one_invitation(self):
        session, token, _ = self._session('concurrent-link')
        entered = Event()
        release = Event()

        def send(*args, **kwargs):
            entered.set()
            if not release.wait(15):
                raise TimeoutError('Synthetic test coordination timed out.')
            return {'id': 'synthetic-concurrent', 'status': 'Accepted'}

        def worker():
            close_old_connections()
            try:
                return send_signing_invitation(session, token, request_id='concurrent-invitation')
            finally:
                connections.close_all()

        with patch('origination.services.origination_esign._send_sms', side_effect=send) as sms:
            with ThreadPoolExecutor(max_workers=2) as workers:
                first = workers.submit(worker)
                try:
                    self.assertTrue(entered.wait(10))
                    second = workers.submit(worker)
                    with self.assertRaises(ExternalOperationError):
                        second.result(timeout=10)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10)['id'], 'synthetic-concurrent')
            sms.assert_called_once()
        self.assertEqual(IntegrationOperation.objects.get(operation_type='origination_signing_invitation').attempts, 1)

    def test_two_workers_reconcile_one_receipt(self):
        from origination.services.origination_sms_delivery import initial_metadata, process_due_lookups
        metadata = initial_metadata('advanta')
        now = timezone.now()
        metadata['sms'].update(submission='accepted', message_id='synthetic-concurrent', lookup_done=False,
            lookup_due_at=(now - timedelta(minutes=1)).isoformat(), lookup_index=0, sent_at=now.isoformat())
        IntegrationOperation.objects.create(integration='advanta', operation_type='origination_signing_invitation',
            deduplication_key='concurrent-dlr', metadata=metadata, status='succeeded', attempts=1)
        entered = Event()
        release = Event()

        def lookup(*args, **kwargs):
            entered.set()
            if not release.wait(15):
                raise TimeoutError('Synthetic test coordination timed out.')
            return {'state': 'delivered', 'status': 'DeliveredToTerminal'}

        def worker():
            close_old_connections()
            try:
                return process_due_lookups()
            finally:
                connections.close_all()

        with patch('origination.services.origination_sms_delivery.lookup_delivery', side_effect=lookup) as read:
            with ThreadPoolExecutor(max_workers=2) as workers:
                first = workers.submit(worker)
                try:
                    self.assertTrue(entered.wait(10))
                    self.assertEqual(workers.submit(worker).result(timeout=10), 0)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10), 1)
            read.assert_called_once()
