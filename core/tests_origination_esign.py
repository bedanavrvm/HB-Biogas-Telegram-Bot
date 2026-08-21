from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import (
    LoanOriginationApplication,
    OriginationOtpChallenge,
    OriginationProductDefinition,
    OriginationSignerSession,
    OriginationSigningAction,
    OriginationSigningPackage,
)
from core.services.loan_origination import OriginationError
from core.services.origination_esign import (
    create_signer_session,
    esign_enabled,
    issue_otp,
    reset_signer_session,
    record_consent_and_signature,
    verify_otp,
)


ESIGN_SETTINGS = {
    'ORIGINATION_ESIGN_ENABLED': True,
    'AFRICASTALKING_SMS_ENVIRONMENT': 'sandbox',
    'AFRICASTALKING_USERNAME': 'sandbox',
    'AFRICASTALKING_API_KEY': 'synthetic-key',
    'SENTRY_ENVIRONMENT': 'test',
    'APP_BASE_URL': 'https://example.test',
}


@override_settings(**ESIGN_SETTINGS)
class OriginationVerifiedSigningTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.actor = user_model.objects.create_user(username='esign-operations', is_superuser=True, is_staff=True)
        self.product = OriginationProductDefinition.objects.create(
            product_key='esign-synthetic', name='E-sign synthetic', version=1,
            form_schema={'fields': [{'key': 'applicant_name', 'type': 'text'}]},
            signer_rules=[], document_type='synthetic', document_template_name='synthetic.pdf',
            document_template_version=1, document_template_sha256='a' * 64,
        )
        self.application = LoanOriginationApplication.objects.create(
            reference_number='ORG-ESIGN-SYNTHETIC', product_definition=self.product,
            officer=self.actor, branch='Synthetic Branch', status='signing_pending', revision=1,
        )
        self.package = OriginationSigningPackage.objects.create(
            application=self.application, application_revision=1,
            external_reference='ESIGN-SYNTHETIC', document_type='synthetic',
            unsigned_document_hash='b' * 64, combined_document_hash='b' * 64,
            document_manifest_snapshot=[
                {'key': 'main', 'name': 'Main LAF', 'page_count': 1},
                {'key': 'support', 'name': 'Supporting form', 'page_count': 1},
            ],
            participants_snapshot=[{
                'role': 'borrower', 'required': True,
                'identity': {'name': 'Synthetic Borrower', 'phone': '0712345678', 'national_id': '00000000'},
                'slots': [
                    {'key': 'borrower_signature_main', 'document_key': 'main', 'type': 'signature', 'required': True},
                    {'key': 'borrower_signature_support', 'document_key': 'support', 'type': 'signature', 'required': True},
                ],
            }],
        )
        self.audit = patch('core.services.compliance_audit.record_event')
        self.audit.start()
        self.addCleanup(self.audit.stop)

    def _session(self, request_id='session-1'):
        return create_signer_session(
            package_id=self.package.pk, signer_role='borrower', actor=self.actor,
            request_id=request_id,
        )

    def test_sandbox_readiness_fails_closed_outside_non_production(self):
        self.assertTrue(esign_enabled())
        with override_settings(SENTRY_ENVIRONMENT='production'):
            self.assertFalse(esign_enabled())
        with override_settings(AFRICASTALKING_USERNAME='not-sandbox'):
            self.assertFalse(esign_enabled())

    def test_one_otp_completes_every_signature_slot_and_bad_attempt_persists(self):
        session, token, replayed = self._session()
        self.assertFalse(replayed)
        with self.assertRaisesRegex(OriginationError, 'every page'):
            record_consent_and_signature(
                raw_token=token, consent=True, access_mode='self_service', ip_hash='ip-one',
                request_id='consent-incomplete',
                reviewed_pages=[1],
                signature_capture={'method': 'typed', 'name': 'Synthetic Borrower'},
            )
        record_consent_and_signature(
            raw_token=token, consent=True, access_mode='self_service', ip_hash='ip-one',
            request_id='consent-one',
            reviewed_pages=[1, 2],
            signature_capture={'method': 'typed', 'name': 'Synthetic Borrower'},
        )
        challenge, code, replayed = issue_otp(raw_token=token, request_id='otp-1', ip_hash='ip-one')
        self.assertFalse(replayed)
        bad_code = '999999' if code != '999999' else '888888'
        with self.assertRaisesRegex(OriginationError, '4 attempt'):
            verify_otp(raw_token=token, code=bad_code, request_id='verify-bad', ip_hash='ip-one')
        with self.assertRaisesRegex(OriginationError, 'already processed'):
            verify_otp(raw_token=token, code=bad_code, request_id='verify-bad', ip_hash='ip-one')
        challenge.refresh_from_db()
        self.assertEqual(challenge.attempts_remaining, 4)

        with patch('core.services.origination_esign.render_verified_package', return_value=b'synthetic-signed-pdf'):
            verified = verify_otp(
                raw_token=token, code=code, request_id='verify-good', ip_hash='ip-one',
            )
        self.assertEqual(verified.status, OriginationSignerSession.STATUS_VERIFIED)
        actions = OriginationSigningAction.objects.filter(package=self.package, mode='verified')
        self.assertEqual(actions.count(), 2)
        self.assertEqual(set(actions.values_list('slot_key', flat=True)), {
            'borrower_signature_main', 'borrower_signature_support',
        })
        self.application.refresh_from_db()
        self.package.refresh_from_db()
        self.assertEqual(self.application.status, 'fully_signed')
        self.assertEqual(self.package.archive_status, 'pending')
        self.assertNotEqual(self.package.signed_document_hash, '')

    def test_consent_change_invalidates_existing_otp(self):
        session, token, _ = self._session()
        record_consent_and_signature(
            raw_token=token, consent=True, access_mode='self_service', ip_hash='ip-two',
            request_id='consent-before-change',
            reviewed_pages=[1, 2],
            signature_capture={'method': 'typed', 'name': 'First Name'},
        )
        challenge, _code, _ = issue_otp(raw_token=token, request_id='otp-change', ip_hash='ip-two')
        record_consent_and_signature(
            raw_token=token, consent=True, access_mode='self_service', ip_hash='ip-two',
            request_id='consent-after-change',
            reviewed_pages=[1, 2],
            signature_capture={'method': 'typed', 'name': 'Changed Name'},
        )
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.invalidated_at)

    def test_shared_phone_requires_reasoned_superuser_override(self):
        self.package.participants_snapshot.append({
            'role': 'guarantor_1', 'required': True,
            'identity': {'name': 'Synthetic Guarantor', 'phone': '0712345678'},
            'slots': [{'key': 'guarantor_signature', 'document_key': 'support', 'type': 'signature', 'required': True}],
        })
        self.package.save(update_fields=['participants_snapshot'])
        ordinary = get_user_model().objects.create_user(username='ordinary-operations')
        with self.assertRaisesRegex(OriginationError, 'Superuser override'):
            create_signer_session(
                package_id=self.package.pk, signer_role='borrower', actor=ordinary,
                request_id='shared-denied',
            )
        session, _token, _ = create_signer_session(
            package_id=self.package.pk, signer_role='borrower', actor=self.actor,
            request_id='shared-approved', shared_phone_override_reason='Synthetic supervised exception.',
        )
        self.assertEqual(session.shared_phone_approved_by, self.actor)
        self.assertEqual(session.shared_phone_override_reason, 'Synthetic supervised exception.')

    def test_session_request_is_idempotent_and_rotates_old_token(self):
        first, token, replayed = self._session('stable-session-request')
        repeated, repeated_token, replayed = self._session('stable-session-request')
        self.assertTrue(replayed)
        self.assertEqual(first.pk, repeated.pk)
        self.assertEqual(token, repeated_token)
        replacement, _replacement_token, _ = self._session('replacement-session-request')
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(replacement.is_active)

    def test_session_recovers_phone_from_frozen_product_mapping(self):
        self.application.signer_rules_snapshot = [{
            'role': 'borrower',
            'identity_fields': {'phone': 'applicant_mobile'},
        }]
        self.application.save(update_fields=['signer_rules_snapshot'])
        self.package.context_snapshot = {'applicant_mobile': '254787998883'}
        self.package.participants_snapshot[0]['identity'].pop('phone')
        self.package.save(update_fields=['context_snapshot', 'participants_snapshot'])

        session, _token, _replayed = self._session('mapped-phone-recovery')

        self.assertEqual(session.phone_normalized, '254787998883')
        self.assertEqual(session.identity_snapshot['phone'], '254787998883')

    def test_public_session_uses_authorization_header_not_token_path(self):
        _session, token, _ = self._session('public-header-session')
        missing = self.client.get('/origination/sign/api/session/')
        self.assertEqual(missing.status_code, 404)
        response = self.client.get(
            '/origination/sign/api/session/', HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['session']['reference'], 'ESIGN-SYNTHETIC')
        shell = self.client.get('/origination/sign/')
        self.assertEqual(shell.status_code, 200)
        self.assertEqual(shell['Referrer-Policy'], 'no-referrer')
        self.assertNotContains(shell, token)

    def test_delivery_receipt_is_informational_only(self):
        session, token, _ = self._session('delivery-session')
        record_consent_and_signature(
            raw_token=token, consent=True, access_mode='self_service', ip_hash='delivery-ip',
            request_id='delivery-consent',
            reviewed_pages=[1, 2],
            signature_capture={'method': 'typed', 'name': 'Synthetic Borrower'},
        )
        challenge, _code, _ = issue_otp(
            raw_token=token, request_id='delivery-otp', ip_hash='delivery-ip',
        )
        challenge.provider_message_id = 'synthetic-provider-message'
        challenge.save(update_fields=['provider_message_id'])
        response = self.client.post(
            '/origination/webhooks/africastalking/delivery/',
            {'id': 'synthetic-provider-message', 'status': 'Delivered'},
        )
        self.assertEqual(response.status_code, 200)
        challenge.refresh_from_db()
        session.refresh_from_db()
        self.application.refresh_from_db()
        self.assertEqual(challenge.delivery_status, OriginationOtpChallenge.DELIVERY_DELIVERED)
        self.assertIsNone(challenge.verified_at)
        self.assertEqual(session.status, OriginationSignerSession.STATUS_OTP_SENT)
        self.assertEqual(self.application.status, 'signing_pending')
        self.client.post(
            '/origination/webhooks/africastalking/delivery/',
            {'id': 'synthetic-provider-message', 'status': 'Unknown'},
        )
        challenge.refresh_from_db()
        self.assertEqual(challenge.delivery_status, OriginationOtpChallenge.DELIVERY_DELIVERED)

    def test_audited_reset_revokes_old_session(self):
        old, _token, _ = self._session('reset-old')
        replacement, replacement_token = reset_signer_session(
            session_id=old.pk, actor=self.actor, reason='Signer changed device.',
            request_id='reset-new',
        )
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        self.assertEqual(old.status, OriginationSignerSession.STATUS_CANCELLED)
        self.assertTrue(replacement.is_active)
        self.assertNotEqual(replacement.token_hash, old.token_hash)
        self.assertTrue(replacement_token)
