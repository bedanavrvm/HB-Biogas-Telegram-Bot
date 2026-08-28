import json
from pathlib import Path
import re

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from core.services.miniapp_messages import (
    CLIENT_HANDLED_CODES,
    MESSAGE_CATALOG,
    MESSAGE_CONTRACT_HEADER,
    MESSAGE_CONTRACT_VERSION,
    miniapp_error_response,
    normalize_miniapp_response,
)


class MiniAppMessageContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_current_client_receives_safe_message_without_legacy_error_mirror(self):
        request = self.factory.post(
            '/api/example/', HTTP_X_REQUEST_ID='request-12345678',
            HTTP_X_MINIAPP_MESSAGE_CONTRACT='2',
        )
        response = normalize_miniapp_response(
            request,
            JsonResponse({'ok': False, 'error': 'DatabaseError: secret internal detail'}, status=500),
            workflow='test',
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload['code'], 'unexpected_error')
        self.assertEqual(payload['request_id'], 'request-12345678')
        self.assertEqual(payload['presentation']['tone'], 'error')
        self.assertEqual(payload['presentation']['persistence'], 'until_resolved')
        self.assertNotIn('error', payload)
        self.assertNotIn('DatabaseError', payload['message'])
        self.assertIn('request-12345678', payload['message'])
        self.assertEqual(response[MESSAGE_CONTRACT_HEADER], MESSAGE_CONTRACT_VERSION)

    def test_cached_client_receives_only_safe_legacy_mirror_and_is_instrumented(self):
        request = self.factory.post('/api/example/', HTTP_X_REQUEST_ID='legacy-12345678')
        with self.assertLogs('core.services.miniapp_messages', level='INFO') as captured:
            response = normalize_miniapp_response(
                request,
                JsonResponse({'ok': False, 'error': 'raw internal exception'}, status=400),
                workflow='test',
            )
        payload = json.loads(response.content)

        self.assertEqual(payload['message'], payload['error'])
        self.assertNotIn('raw internal exception', payload['message'])
        self.assertTrue(any('legacy_error_mirror=True' in item for item in captured.output))

    def test_shared_phone_message_contains_only_safe_role_context(self):
        request = self.factory.post(
            '/api/origination/api/applications/example/signer-sessions/',
            HTTP_X_REQUEST_ID='shared-12345678',
            HTTP_X_MINIAPP_MESSAGE_CONTRACT='2',
        )
        response = miniapp_error_response(
            request,
            'origination_shared_signer_phone',
            workflow='origination',
            details={'roles': 'Borrower and Guarantor 1', 'phone_last4': '5678', 'full_phone': '+254700005678'},
        )
        payload = json.loads(response.content)

        self.assertIn('Borrower and Guarantor 1', payload['message'])
        self.assertIn('ending 5678', payload['message'])
        self.assertNotIn('+254700005678', response.content.decode())
        self.assertEqual(payload['details'], {'roles': 'Borrower and Guarantor 1', 'phone_last4': '5678'})
        self.assertEqual(payload['presentation']['tone'], 'warning')

    def test_frontend_specific_codes_match_backend_catalogue(self):
        source = Path('core/static/miniapp/utils.js').read_text(encoding='utf-8')
        match = re.search(r"handledMessageCodes\s*=\s*Object\.freeze\(\[([^]]*)\]\)", source)
        self.assertIsNotNone(match)
        frontend_codes = set(re.findall(r"['\"]([a-z][a-z0-9_]+)['\"]", match.group(1)))
        self.assertEqual(frontend_codes, set(CLIENT_HANDLED_CODES))
        self.assertTrue(frontend_codes.issubset(MESSAGE_CATALOG))

    def test_review_screens_use_shared_message_contract_parser(self):
        for relative_path in (
            'core/static/miniapp/farmup_review.js',
            'core/static/miniapp/fca_review.js',
            'core/static/miniapp/system_export_review.js',
        ):
            with self.subTest(path=relative_path):
                source = Path(relative_path).read_text(encoding='utf-8')
                self.assertIn('utils.messageHeaders', source)
                self.assertIn('utils.normalizeResponsePayload', source)

        utilities = Path('core/static/miniapp/utils.js').read_text(encoding='utf-8')
        draft_request = utilities[utilities.index('async function request(method, payload)'):]
        self.assertIn('normalizeResponsePayload(', draft_request)
        self.assertIn('apiError(response, data', draft_request)

    def test_operational_catalogue_does_not_own_consent_copy(self):
        self.assertFalse(any('consent' in code for code in MESSAGE_CATALOG))
        guide = Path('docs/miniapp-message-catalogue.md').read_text(encoding='utf-8')
        self.assertIn('OriginationConsentPolicyVersion', guide)
        self.assertIn('compliance', guide.casefold())
