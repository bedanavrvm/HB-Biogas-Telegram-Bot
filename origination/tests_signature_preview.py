import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from core import tests_origination_esign
from origination.services.signature_appearance import preview_capture
from origination.services.origination_esign import record_consent_and_signature, issue_otp
from origination.services.origination_signing import _validated_signature_capture


@override_settings(**tests_origination_esign.ESIGN_SETTINGS)
class SignaturePreviewBoundaryTests(TestCase):
    def setUp(self):
        tests_origination_esign.OriginationVerifiedSigningTests.setUp(self)

    def session(self):
        return tests_origination_esign.OriginationVerifiedSigningTests._session(self)

    def test_missing_font_asset_returns_clear_503_without_losing_session(self):
        from origination.services.signature_appearance import SignatureAssetsUnavailable
        session, token, _ = self.session()
        with patch('origination.services.signature_appearance.preview_capture', side_effect=SignatureAssetsUnavailable()):
            response = self.client.post(reverse('loan_origination_signer_signature_preview'),
                json.dumps({'name':'Synthetic Signer','font':'caveat'}), content_type='application/json',
                HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_MINIAPP_MESSAGE_CONTRACT='2')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['code'],'signature_styles_unavailable')
        self.assertIn('Signature styles are unavailable',response.json()['message'])
        session.refresh_from_db()
        self.assertFalse(session.signature_capture)

    def test_public_preview_is_token_bound_private_and_does_not_sign(self):
        session,token,_ = self.session()
        url = reverse('loan_origination_signer_signature_preview')
        payload = {'name':'Wanjiku Mwangi-Kamau','font':'caveat'}
        denied=self.client.post(url,json.dumps(payload),content_type='application/json')
        self.assertIn(denied.status_code,(400,403,404))
        response=self.client.post(url,json.dumps(payload),content_type='application/json',HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Cache-Control'],'no-store, private')
        expected=preview_capture(**payload)
        self.assertEqual(response.json()['sha256'],expected['sha256'])
        session.refresh_from_db();self.assertEqual(session.signature_capture,{})
        self.assertFalse(self.package.actions.exists())

    def test_style_change_invalidates_pending_otp_and_preserves_legacy_path(self):
        session,token,_=self.session()
        def capture(font):
            result=preview_capture('Synthetic Borrower',font)
            return {'method':'typed','name':'Synthetic Borrower','font':font,
                    'appearance_version':2,'preview_sha256':result['sha256']}
        record_consent_and_signature(raw_token=token,signature_capture=capture('caveat'),consent=True,
            access_mode='self_service',ip_hash='synthetic',reviewed_pages=[1,2],request_id='capture-style-1')
        challenge,_code,_=issue_otp(raw_token=token,request_id='style-code',ip_hash='synthetic')
        record_consent_and_signature(raw_token=token,signature_capture=capture('yellowtail'),consent=True,
            access_mode='self_service',ip_hash='synthetic',reviewed_pages=[1,2],request_id='capture-style-2')
        challenge.refresh_from_db();self.assertIsNotNone(challenge.invalidated_at)
        session.refresh_from_db();self.assertEqual(session.signature_capture['font'],'yellowtail')
        self.assertEqual(_validated_signature_capture({'method':'typed','name':'Legacy name'}),
                         {'method':'typed','name':'Legacy name'})
