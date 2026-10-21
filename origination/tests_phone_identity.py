"""Synthetic-only tests: no Safaricom requests or workflow side effects."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.test import Client, TestCase, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AccessGrant, IntegrationOperation, IntegrationCircuitState, UserProfile
from core.tests_telegram_authentication import BOT_TOKEN, signed_init_data
from origination.models import (
    LoanOriginationApplication, OriginationProductDefinition,
    OriginationPhoneIdentityCheck as Check, OriginationPhoneIdentityDailyUsage as Usage,
)
from origination.services import phone_identity as service, daraja_phone_identity as provider

CONFIG = dict(ORIGINATION_PHONE_ID_CHECK_ENABLED=True, ORIGINATION_PHONE_ID_CHECK_DAILY_LIMIT=50,
              DARAJA_ENVIRONMENT='sandbox', DARAJA_CONSUMER_KEY='synthetic-key',
              DARAJA_CONSUMER_SECRET='synthetic-secret', DARAJA_SHORTCODE='00000',
              DARAJA_PHONE_ID_HMAC_KEY='synthetic-only-digest-key-not-a-real-secret')


class Fixtures:
    def setup_data(self):
        cache.clear()
        users = get_user_model()
        self.actor = users.objects.create_user(username='synthetic-phone-it', is_superuser=True)
        self.officer = users.objects.create_user(username='synthetic-phone-officer')
        self.definition = OriginationProductDefinition.objects.create(product_key='synthetic-phone', name='Synthetic phone')
        self.app = self.make_app('ONE')

    def make_app(self, suffix):
        return LoanOriginationApplication.objects.create(product_definition=self.definition, officer=self.officer,
            reference_number=f'ORG-SYNTHETIC-PHONE-{suffix}', branch='Synthetic Branch', schema_snapshot={
                'sections': [{'key':'applicant', 'label':'Applicant'}], 'fields': [
                    {'key':'applicant_id_number', 'type':'national_id', 'section_key':'applicant'},
                    {'key':'applicant_phone', 'type':'phone', 'section_key':'applicant'},
                    {'key':'applicant_other_phone', 'type':'phone', 'section_key':'applicant'},
                    {'key':'next_of_kin_phone', 'type':'phone', 'section_key':'applicant'},
                ]}, form_payload={'applicant_id_number':'00099001', 'applicant_phone':'0700000001',
                                 'applicant_other_phone':'0100000001', 'next_of_kin_phone':'0700000002'})

    def body(self, app=None, target='primary'):
        app = app or self.app
        item = next(item for item in service.projection(app, self.actor)['targets'] if item['target'] == target)
        return {'target':target, 'revision':app.revision, 'subject_token':item['subject_token'],
                'confirmed':True, 'confirmation_version':1}

    def run_check(self, key='synthetic-check', app=None, target='primary', body=None):
        return service.request_check(application_id=(app or self.app).pk, actor=self.actor,
                                     request_id=key, body=body or self.body(app, target))

    @staticmethod
    def matched(**kwargs):
        kwargs['before_dispatch']()
        return provider.Outcome('matched', '4000', 'synthetic-reference')


class AdapterTests(SimpleTestCase):
    @override_settings(**CONFIG)
    @patch('origination.services.daraja_phone_identity.access_token', return_value='synthetic-bearer-token')
    @patch('origination.services.daraja_phone_identity._json_request')
    def test_exchange_diagnostics_show_structure_without_identifiers_or_credentials(self, http, token):
        http.return_value = (200, {'responseCode': '4001', 'status': 'false',
            'responseRefID': 'safe-provider-reference', 'phone': '254700000001',
            'idNumber': '00099001', 'access_token': 'synthetic-bearer-token',
            'responseMessage': 'Customer 00099001 has phone 254700000001'})
        with self.assertLogs(provider.__name__, level='INFO') as captured:
            outcome = provider.validate(phone='254700000001', national_id='00099001',
                request_ref='safe-request-reference', before_dispatch=lambda: None)
        diagnostic = outcome.diagnostics
        self.assertEqual(diagnostic['environment'], 'sandbox')
        self.assertEqual(diagnostic['http_status'], 200)
        self.assertEqual(diagnostic['request']['msisdn'], '<redacted>')
        self.assertEqual(diagnostic['request']['idNumber'], '<redacted>')
        self.assertEqual(diagnostic['response']['responseCode'], '4001')
        self.assertEqual(diagnostic['response']['status'], 'false')
        self.assertEqual(diagnostic['interpretation'], 'not_matched')
        text = json.dumps(diagnostic) + '\n'.join(captured.output)
        self.assertIn('safe-request-reference', text)
        self.assertIn('safe-provider-reference', text)
        for secret in ('254700000001', '00099001', 'synthetic-bearer-token',
                       CONFIG['DARAJA_CONSUMER_SECRET'], CONFIG['DARAJA_PHONE_ID_HMAC_KEY']):
            self.assertNotIn(secret, text)

    @override_settings(**CONFIG)
    @patch('origination.services.daraja_phone_identity.access_token', return_value='synthetic-bearer-token')
    @patch('origination.services.daraja_phone_identity._json_request')
    def test_invalid_response_and_timeout_keep_safe_diagnostics(self, http, token):
        cases = [
            (200, {'responseCode': '4000', 'status': 'synthetic-bearer-token',
                   'responseRefID': '00099001', 'errorMessage': '254700000001'}),
            provider.ProviderFailure('provider_transport_unavailable', uncertain=True),
        ]
        for response in cases:
            with self.subTest(response_type=type(response).__name__):
                http.side_effect = response if isinstance(response, Exception) else None
                http.return_value = response
                with self.assertLogs(provider.__name__, level='INFO') as captured:
                    with self.assertRaises(provider.ProviderFailure) as error:
                        provider.validate(phone='254700000001', national_id='00099001',
                            request_ref='safe-request-reference', before_dispatch=lambda: None)
                text = json.dumps(error.exception.diagnostics) + '\n'.join(captured.output)
                for sensitive in ('254700000001', '00099001', 'synthetic-bearer-token'):
                    self.assertNotIn(sensitive, text)
                self.assertEqual(error.exception.diagnostics['request']['idType'], '01')

    @override_settings(**CONFIG)
    @patch('origination.services.daraja_phone_identity.access_token', return_value='synthetic-bearer-token')
    @patch('origination.services.daraja_phone_identity._json_request')
    def test_echoed_identifier_reference_and_nested_bodies_are_not_retained(self, http, token):
        http.return_value = (200, {'responseCode': '4000', 'status': True, 'responseRefID': '00099001',
            'body': {'status': True, 'message': '00099001 254700000001', 'national_id': '00099001'}})
        with self.assertLogs(provider.__name__, level='INFO') as captured:
            outcome = provider.validate(phone='254700000001', national_id='00099001',
                request_ref='safe-request-reference', before_dispatch=lambda: None)
        self.assertEqual(outcome.response_ref, '')
        self.assertEqual(outcome.diagnostics['response']['body']['status'], True)
        for sensitive in ('00099001', '254700000001', 'synthetic-bearer-token'):
            self.assertNotIn(sensitive, json.dumps(outcome.diagnostics) + '\n'.join(captured.output))

    @patch('origination.services.daraja_phone_identity.requests.request')
    def test_http_transport_is_bounded_and_never_follows_redirects(self, request):
        response=request.return_value.__enter__.return_value
        response.status_code=200
        response.iter_content.return_value=[b'{"responseCode":"4001","status":"false"}']
        status,data=provider._json_request('POST','https://sandbox.safaricom.co.ke/v1/KYC-validation/validateID',json={})
        self.assertEqual(status,200); self.assertEqual(data['status'],'false')
        self.assertFalse(request.call_args.kwargs['allow_redirects'])
        self.assertEqual(request.call_count,1)
        response.iter_content.assert_called_with(1)
        response.iter_content.return_value=[b'x'*8193]
        with self.assertRaises(provider.ProviderFailure) as error:
            provider._json_request('POST','https://sandbox.safaricom.co.ke/v1/KYC-validation/validateID')
        self.assertTrue(error.exception.uncertain)

    def test_explicit_boolean_and_code_contract(self):
        for status in (True, 'true', ' TRUE '):
            self.assertEqual(provider.parse_outcome({'responseCode':'4000', 'status':status}).state, 'matched')
        for status in (False, 'false', ' FALSE '):
            self.assertEqual(provider.parse_outcome({'responseCode':'4001', 'status':status}).state, 'not_matched')
        for data in ({'responseCode':'4000', 'status':'false'}, {'responseCode':'4001', 'status':0},
                     {'status':'true'}, {'responseCode':'4001', 'status':'no'}):
            with self.assertRaises(provider.ProviderFailure): provider.parse_outcome(data)

    @override_settings(**CONFIG)
    def test_invalid_limits_and_missing_secrets_fail_closed(self):
        for limit in (0, -1, 51, 'unlimited'):
            with self.settings(ORIGINATION_PHONE_ID_CHECK_DAILY_LIMIT=limit):
                self.assertEqual(provider.configuration_error(), 'configuration_required')
        with self.settings(DARAJA_PHONE_ID_HMAC_KEY=''):
            self.assertEqual(provider.configuration_error(), 'configuration_required')

    @override_settings(**CONFIG)
    @patch('origination.services.daraja_phone_identity._json_request')
    def test_token_cache_and_auth_failure_never_resubmit_validation(self, http):
        cache.clear()
        http.side_effect = [(200, {'access_token':'synthetic-token', 'expires_in':'3600'}),
                            (401, {'errorCode':'401.001'})]
        dispatch = []
        with self.assertRaises(provider.ProviderFailure):
            provider.validate(phone='254700000001', national_id='00099001', request_ref='synthetic',
                              before_dispatch=lambda: dispatch.append(True))
        self.assertEqual(http.call_count, 2)
        self.assertEqual(len(dispatch), 1)
        payload = http.call_args.kwargs['json']
        self.assertEqual(payload['idNumber'], '00099001')
        self.assertEqual(payload['idType'], '01')


@override_settings(**CONFIG)
class PhoneIdentityTests(Fixtures, TestCase):
    def setUp(self): self.setup_data()

    def test_explicit_fresh_check_bypasses_cache_without_rewriting_history_or_rebilling_replay(self):
        before = LoanOriginationApplication.objects.values().get(pk=self.app.pk)
        outcomes = iter(('not_matched', 'matched'))
        def answer(**kwargs):
            kwargs['before_dispatch']()
            state = next(outcomes)
            return provider.Outcome(state, '4001' if state == 'not_matched' else '4000')
        with patch('origination.services.phone_identity.provider.validate', side_effect=answer) as validate:
            first, _ = self.run_check('synthetic-original')
            old = Check.objects.get()
            body = {**self.body(), 'fresh_check': True}
            second, status = self.run_check('synthetic-fresh', body=body)
            replay, replay_status = self.run_check('synthetic-fresh', body=body)
        self.assertEqual((status, replay_status), (200, 200))
        self.assertEqual((first['status'], second['status']), ('not_matched', 'matched'))
        self.assertFalse(second['reused'])
        self.assertNotEqual(first['receipt_id'], second['receipt_id'])
        self.assertEqual(second['receipt_id'], replay['receipt_id'])
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(Check.objects.count(), 2)
        self.assertEqual(Usage.objects.get().dispatch_count, 2)
        old.refresh_from_db()
        self.assertEqual(old.state, 'not_matched')
        self.assertEqual(LoanOriginationApplication.objects.values().get(pk=self.app.pk), before)
        self.assertTrue(self.app.events.get(request_id='synthetic-fresh').metadata['fresh_check'])

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_fresh_check_joins_existing_attempt_before_reusing_older_result(self, validate):
        self.run_check('synthetic-original')
        body = {**self.body(), 'fresh_check': True}
        _, _, pending = service._admit(self.app.pk, self.actor, 'synthetic-pending', body)
        self.assertIsNotNone(pending)
        for fresh in (True, False):
            result, status = self.run_check(f'synthetic-join-{fresh}', body={**self.body(), 'fresh_check': fresh})
            self.assertEqual(status, 202)
            self.assertEqual(result['status'], 'checking')
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(Check.objects.count(), 2)
        self.assertEqual(Usage.objects.get().dispatch_count, 1)

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_fresh_flag_requires_boolean_and_cannot_repurpose_a_request_key(self, validate):
        body = self.body()
        first, _ = self.run_check('synthetic-original', body=body)
        replay, status = self.run_check('synthetic-original', body={**body, 'fresh_check': False})
        self.assertEqual(status, 200)
        self.assertEqual(first['receipt_id'], replay['receipt_id'])
        for value in ('true', 1, 0, None, [], {}):
            with self.subTest(value=value), self.assertRaises(service.PhoneIdentityError):
                self.run_check('synthetic-invalid-fresh', body={**body, 'fresh_check': value})
        with self.assertRaises(service.PhoneIdentityError) as error:
            self.run_check('synthetic-original', body={**body, 'fresh_check': True})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(validate.call_count, 1)

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_fresh_check_still_requires_confirmation_scope_and_daily_allowance(self, validate):
        self.run_check('synthetic-original')
        body = {**self.body(), 'fresh_check': True}
        with self.assertRaises(service.PhoneIdentityError):
            self.run_check('synthetic-unconfirmed', body={**body, 'confirmed': False})
        with self.assertRaises(service.PhoneIdentityError) as error:
            service.request_check(application_id=self.app.pk, actor=self.officer,
                request_id='synthetic-unauthorized', body=body)
        self.assertEqual(error.exception.status, 403)
        Usage.objects.update(dispatch_count=50)
        result, status = self.run_check('synthetic-capped-fresh', body=body)
        self.assertEqual((status, result['code']), (429, 'daily_limit'))
        self.assertEqual(validate.call_count, 2)  # The adapter callback blocks before its paid POST.
        self.assertEqual(Usage.objects.get().dispatch_count, 50)

    @patch('origination.services.phone_identity.provider.access_token', return_value='synthetic-bearer-token')
    @patch('origination.services.phone_identity.provider._json_request', return_value=(
        200, {'responseCode': '4000', 'status': True, 'responseRefID': 'safe-provider-reference'}))
    def test_redacted_exchange_is_retained_in_existing_operation_metadata(self, http, token):
        result, status = self.run_check('synthetic-diagnostic')
        self.assertEqual(status, 200)
        self.assertEqual(result['environment'], 'sandbox')
        diagnostic = Check.objects.get().operation.metadata['provider_exchange']
        self.assertEqual(diagnostic['response']['responseRefID'], 'safe-provider-reference')
        self.assertEqual(diagnostic['http_status'], 200)
        self.assertNotIn('00099001', json.dumps(diagnostic))
        self.assertNotIn('254700000001', json.dumps(diagnostic))

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_match_replay_and_workflow_bytes_unchanged(self, validate):
        self.app.template_configuration_snapshot = {'field_overlay_manifest':{}}
        self.app.save(update_fields=['template_configuration_snapshot'])
        before = LoanOriginationApplication.objects.values().get(pk=self.app.pk)
        body = self.body()
        first, status = self.run_check(body=body)
        second, replay_status = self.run_check(body=body)
        self.assertEqual((status, replay_status), (200, 200))
        self.assertEqual(first['receipt_id'], second['receipt_id'])
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(Usage.objects.get().dispatch_count, 1)
        self.assertEqual(LoanOriginationApplication.objects.values().get(pk=self.app.pk), before)
        self.assertFalse(self.app.events.filter(metadata__form_projection_version=1).exists())
        event = self.app.events.get()
        self.assertNotIn('00099001', json.dumps(event.metadata))
        self.assertNotIn('254700000001', json.dumps(event.metadata))
        check = Check.objects.get()
        self.assertEqual(check.operation.max_attempts, 1)
        self.assertNotIn('00099001', json.dumps(check.operation.metadata))
        with self.assertRaises(ValidationError): check.save()
        with self.assertRaises(ValidationError): check.delete()

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_cross_application_and_alternate_slot_reuse(self, validate):
        first, _ = self.run_check()
        other = self.make_app('TWO')
        other.form_payload['applicant_other_phone'] = other.form_payload['applicant_phone']
        other.save(update_fields=['form_payload'])
        reused, status = self.run_check('synthetic-reuse', other, 'alternate')
        self.assertEqual(status, 200)
        self.assertTrue(reused['reused'])
        self.assertEqual(first['checked_at'], reused['checked_at'])
        self.assertNotEqual(first['receipt_id'], reused['receipt_id'])
        self.assertNotIn(str(self.app.pk), json.dumps(reused))
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(Check.objects.count(), 1)

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_expiry_changed_details_and_original_key_do_not_rebill(self, validate):
        body = self.body()
        self.run_check(body=body)
        check = Check.objects.get()
        at_expiry = check.reusable_until
        with patch('origination.services.phone_identity.timezone.now', return_value=at_expiry):
            self.assertEqual(service.projection(self.app, self.actor)['targets'][0]['freshness'], 'expired')
            self.run_check('synthetic-after-expiry')
        self.app.form_payload['applicant_phone'] = '0700000003'
        self.app.revision += 1
        self.app.save(update_fields=['form_payload','revision'])
        old, _ = self.run_check(body=body)
        self.assertFalse(old['applies_to_current_values'])
        self.assertEqual(validate.call_count, 2)
        with self.assertRaises(service.PhoneIdentityError) as error:
            self.run_check(body=self.body())
        self.assertEqual(error.exception.status, 409)

    def test_validation_confirmation_revision_arbitrary_inputs(self):
        baseline = self.body()
        for change in ({'confirmed':False}, {'confirmed':'true'}, {'revision':99},
                       {'subject_token':'forged'}, {'phone':'0700000001'}, {'target':'next_of_kin'}):
            with self.assertRaises(service.PhoneIdentityError):
                self.run_check(body={**baseline, **change})
        self.assertFalse(Check.objects.exists())
        self.assertEqual(set(service.targets(self.app)), {'primary','alternate'})
        self.assertEqual(service.pair(self.app,'alternate'), ('254100000001','00099001'))

    def test_pilot_roles_scope_and_active_account(self):
        self.assertFalse(service.allowed(self.app, self.officer))
        AccessGrant.objects.create(user=self.officer, workflow='jawabu_portal', role='IT')
        AccessGrant.objects.create(user=self.officer, workflow='loan_origination', role='JBL_OFFICER', branch='Synthetic Branch')
        self.assertFalse(service.allowed(self.app, self.officer))
        grant = AccessGrant.objects.create(user=self.officer, workflow='loan_origination', role='IT', branch='Other Branch')
        self.assertFalse(service.allowed(self.app, self.officer))
        grant.branch = 'Synthetic Branch'; grant.save()
        self.assertTrue(service.allowed(self.app, self.officer))
        self.officer.is_active = False; self.officer.save()
        self.assertFalse(service.allowed(self.app, self.officer))

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_daily_limit_and_nairobi_reset(self, validate):
        now = timezone.now()
        Usage.objects.create(environment='sandbox',business_date=now.astimezone(service.NAIROBI).date(),dispatch_count=49)
        self.run_check()
        result, status = self.run_check('synthetic-limit', target='alternate')
        self.assertEqual((status, result['code']), (429, 'daily_limit'))
        self.assertEqual(Usage.objects.get().dispatch_count, 50)
        self.assertGreater(result['retry_after'], 0)
        next_day = service._reset_at(now) + timedelta(seconds=1)
        with patch('origination.services.phone_identity.timezone.now', return_value=next_day):
            self.run_check('synthetic-next-day', target='alternate')
        self.assertEqual(Usage.objects.order_by('business_date').last().dispatch_count, 1)

    def test_auth_failure_and_timeout_never_retry_or_cache(self):
        def failed(**kwargs): raise provider.ProviderFailure('provider_auth_unavailable')
        with patch('origination.services.phone_identity.provider.validate', side_effect=failed) as call:
            first, status = self.run_check()
            self.run_check()
        self.assertEqual(call.call_count, 1)
        self.assertEqual(status, 503)
        self.assertFalse(Usage.objects.exists())
        def lost(**kwargs):
            kwargs['before_dispatch']()
            raise provider.ProviderFailure('provider_transport_unavailable', uncertain=True)
        with patch('origination.services.phone_identity.provider.validate', side_effect=lost) as call:
            result, status = self.run_check('synthetic-lost')
            self.run_check('synthetic-lost')
        self.assertEqual((result['status'], status), ('unknown', 503))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(Usage.objects.get().dispatch_count, 1)

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_disabled_and_circuit_block_calls_but_replay_is_read_only(self, validate):
        body = self.body()
        self.run_check(body=body)
        with self.settings(ORIGINATION_PHONE_ID_CHECK_ENABLED=False):
            self.run_check(body=body)
            with self.assertRaises(service.PhoneIdentityError): self.run_check('synthetic-disabled', target='alternate')
        self.assertEqual(validate.call_count, 1)

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_shared_result_is_not_exposed_before_app_local_confirmation(self, validate):
        self.run_check()
        other = self.make_app('PRIVATE')
        self.assertEqual(service.projection(other, self.actor)['targets'][0]['status'], 'not_checked')
        result, _ = self.run_check('synthetic-own-receipt', other)
        self.assertTrue(result['reused'])
        self.assertEqual(other.events.count(), 1)

    def test_mismatch_is_reusable_without_changing_any_status(self):
        def mismatch(**kwargs):
            kwargs['before_dispatch']()
            return provider.Outcome('not_matched','4001')
        self.app.status = 'approved'; self.app.save(update_fields=['status'])
        with patch('origination.services.phone_identity.provider.validate',side_effect=mismatch) as call:
            first, _ = self.run_check()
            second, _ = self.run_check('synthetic-mismatch-reuse')
        self.app.refresh_from_db()
        self.assertEqual((first['status'], second['status']), ('not_matched','not_matched'))
        self.assertTrue(second['reused']); self.assertEqual(call.call_count,1)
        self.assertEqual(self.app.status,'approved')

    def test_transport_failures_open_circuit_without_automatic_retries(self):
        def lost(**kwargs):
            kwargs['before_dispatch']()
            raise provider.ProviderFailure('provider_transport_unavailable', uncertain=True)
        with patch('origination.services.phone_identity.provider.validate',side_effect=lost) as call:
            for index in range(5): self.run_check(f'synthetic-transport-{index}')
            result, _ = self.run_check('synthetic-after-open')
        self.assertEqual(call.call_count,5)
        self.assertEqual(result['code'],'circuit_open')
        self.assertEqual(Usage.objects.get().dispatch_count,5)

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_expired_lease_never_replays_and_late_result_cannot_replace_it(self, validate):
        body = self.body()
        app,event,check = service._admit(self.app.pk,self.actor,'synthetic-abandoned',body)
        operation=check.operation
        operation.status='running'; operation.metadata={'attempt_token':'synthetic-lease'}; operation.save()
        future=check.created_at+timedelta(seconds=121)
        with patch('origination.services.phone_identity.timezone.now',return_value=future):
            old,_=self.run_check('synthetic-abandoned',body=body)
            self.assertEqual(old['status'],'unknown'); self.assertEqual(validate.call_count,0)
            self.run_check('synthetic-successor')
            service._finish(check,operation,outcome=provider.Outcome('matched','4000'))
        check.refresh_from_db()
        self.assertEqual(check.state,'unknown')
        self.assertEqual(validate.call_count,1)

    def test_offboarding_during_oauth_prevents_dispatch(self):
        def revoke(**kwargs):
            get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
            kwargs['before_dispatch']()
        with patch('origination.services.phone_identity.provider.validate',side_effect=revoke):
            with self.assertRaises(service.PhoneIdentityError) as error: self.run_check()
        self.assertEqual(error.exception.status,403)
        self.assertFalse(Usage.objects.exists())

    def test_duplicate_inflight_constraint(self):
        _,_,check=service._admit(self.app.pk,self.actor,'synthetic-reservation',self.body())
        operation=IntegrationOperation.objects.create(integration='daraja',operation_type='origination_phone_identity',
            deduplication_key='synthetic-constraint-operation')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Check.objects.create(subject=check.subject,operation=operation)

    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    def test_open_circuit_never_invokes_provider(self, validate):
        IntegrationCircuitState.objects.update_or_create(integration='daraja', defaults={
            'status':'open','next_probe_at':timezone.now()+timedelta(minutes=5)})
        result, status = self.run_check('synthetic-open', target='alternate')
        self.assertEqual((result['code'], status), ('circuit_open',503))
        self.assertEqual(validate.call_count, 0)

    @override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, DEBUG=True)
    @patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
    @patch('origination.services.origination_dispatch.resume_application_work')
    def test_authenticated_endpoint_and_pure_get(self, resume, validate):
        url = reverse('loan_origination_phone_identity_checks', args=[self.app.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.actor)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(validate.called); self.assertFalse(resume.called)
        body = {**self.body(), 'client_request_id':'synthetic-api'}
        self.assertEqual(self.client.post(url, json.dumps(body), content_type='application/json').status_code, 200)
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, json.dumps(body), content_type='application/json').status_code, 403)


@override_settings(
    **CONFIG,
    TELEGRAM_BOT_TOKEN=BOT_TOKEN,
    ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    ORIGINATION_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True,
    SECURE_SSL_REDIRECT=False,
)
class PhoneIdentityTelegramTransportTests(Fixtures, TestCase):
    """Exercise the mounted route with real Telegram HMAC and CSRF middleware."""

    def setUp(self):
        network = patch('socket.socket.connect', side_effect=AssertionError('External network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        validation = patch('origination.services.phone_identity.provider.validate', side_effect=Fixtures.matched)
        self.validate = validation.start()
        self.addCleanup(validation.stop)
        self.setup_data()
        self.actor.is_superuser = False
        self.actor.save(update_fields=['is_superuser'])
        AccessGrant.objects.create(
            user=self.actor, workflow='loan_origination', role='IT', branch='Synthetic Branch',
        )
        for user, telegram_id in ((self.actor, '731901'), (self.officer, '731902')):
            UserProfile.objects.update_or_create(user=user, defaults={'telegram_id': telegram_id})
        self.client = Client(enforce_csrf_checks=True)
        self.url = reverse('loan_origination_phone_identity_checks', args=[self.app.pk])
        self.headers = {'HTTP_X_TELEGRAM_INIT_DATA': signed_init_data(user={'id': 731901})}
        self.payload = {**self.body(), 'client_request_id': 'synthetic-telegram-phone-check'}

    def post(self, headers):
        return self.client.post(self.url, json.dumps(self.payload), content_type='application/json', **headers)

    def assert_no_dispatch(self):
        self.validate.assert_not_called()
        self.assertFalse(Check.objects.exists())
        self.assertFalse(Usage.objects.exists())

    def test_scoped_it_can_check_without_csrf_token_and_replay_does_not_rebill(self):
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assert_no_dispatch()
        first = self.post(self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['result']['status'], 'matched')
        self.assertIn('no-store', first['Cache-Control'])
        replay = self.post(self.headers)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.json()['result']['receipt_id'], replay.json()['result']['receipt_id'])
        self.assertEqual(self.validate.call_count, 1)
        self.assertEqual(Usage.objects.get().dispatch_count, 1)

    def test_active_superuser_can_check_with_signed_telegram_identity(self):
        self.actor.is_superuser = True
        self.actor.save(update_fields=['is_superuser'])
        response = self.post(self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.validate.call_count, 1)

    def test_signed_scoped_it_can_explicitly_request_a_fresh_check(self):
        self.assertEqual(self.post(self.headers).status_code, 200)
        self.payload = {**self.body(), 'fresh_check': True, 'client_request_id': 'synthetic-telegram-fresh-check'}
        first = self.post(self.headers)
        replay = self.post(self.headers)
        self.assertEqual((first.status_code, replay.status_code), (200, 200))
        self.assertFalse(first.json()['result']['reused'])
        self.assertEqual(first.json()['result']['receipt_id'], replay.json()['result']['receipt_id'])
        self.assertEqual(self.validate.call_count, 2)
        self.assertEqual(Usage.objects.get().dispatch_count, 2)

    def test_cookie_session_without_signed_telegram_identity_is_rejected(self):
        self.client.force_login(self.actor)
        response = self.post({})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'authentication_required')
        self.assert_no_dispatch()

    def test_invalid_or_expired_telegram_identity_is_rejected(self):
        invalid = {
            'missing': '',
            'unsigned': signed_init_data(user={'id': 731901}, include_hash=False),
            'expired': signed_init_data(auth_date=1, user={'id': 731901}),
            'tampered': signed_init_data(user={'id': 731901}, include_hash=False) + '&hash=' + '0' * 64,
        }
        for reason, init_data in invalid.items():
            with self.subTest(reason=reason):
                response = self.post({'HTTP_X_TELEGRAM_INIT_DATA': init_data})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['code'], 'authentication_required')
                self.assert_no_dispatch()

    def test_other_workflow_it_does_not_grant_origination_access(self):
        AccessGrant.objects.create(user=self.officer, workflow='jawabu_portal', role='IT')
        response = self.post({'HTTP_X_TELEGRAM_INIT_DATA': signed_init_data(user={'id': 731902})})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        self.assert_no_dispatch()

    def test_officer_or_wrong_branch_it_cannot_check(self):
        AccessGrant.objects.create(
            user=self.officer, workflow='loan_origination', role='JBL_OFFICER', branch='Synthetic Branch',
        )
        headers = {'HTTP_X_TELEGRAM_INIT_DATA': signed_init_data(user={'id': 731902})}
        for role in ('officer', 'other_branch_it'):
            with self.subTest(role=role):
                if role == 'other_branch_it':
                    AccessGrant.objects.create(
                        user=self.officer, workflow='loan_origination', role='IT', branch='Other Branch',
                    )
                response = self.post(headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['code'], 'forbidden')
                self.assert_no_dispatch()


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks and partial uniqueness')
@override_settings(**CONFIG)
class PhoneIdentityConcurrencyTests(Fixtures, TransactionTestCase):
    def setUp(self): self.setup_data()

    def test_two_applications_share_one_inflight_dispatch(self):
        other = self.make_app('CONCURRENT')
        first_body, second_body = self.body(), self.body(other)
        entered, release = Event(), Event()
        def slow(**kwargs):
            kwargs['before_dispatch'](); entered.set()
            if not release.wait(10): raise AssertionError('Concurrent fixture timed out')
            return provider.Outcome('matched','4000')
        def run():
            try: return self.run_check('synthetic-concurrent-one', body=first_body)
            finally: connections.close_all()
        with patch('origination.services.phone_identity.provider.validate', side_effect=slow) as call:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(run)
                try:
                    self.assertTrue(entered.wait(10))
                    result, status = self.run_check('synthetic-concurrent-two', other, body=second_body)
                    self.assertEqual(status, 202)
                finally: release.set()
                self.assertEqual(pending.result()[1], 200)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(Usage.objects.get().dispatch_count, 1)
        self.assertEqual(Check.objects.count(), 1)

    def test_different_subjects_cannot_race_past_daily_limit(self):
        from threading import Barrier
        barrier=Barrier(2)
        other=self.make_app('QUOTA-RACE')
        other.form_payload['applicant_phone']='0700000004';other.save(update_fields=['form_payload'])
        Usage.objects.create(environment='sandbox',business_date=timezone.now().astimezone(service.NAIROBI).date(),dispatch_count=49)
        bodies=[self.body(),self.body(other)]
        apps=[self.app,other]
        dispatched=[]
        def paid(**kwargs):
            barrier.wait(timeout=10)
            kwargs['before_dispatch']()
            dispatched.append(kwargs['request_ref'])
            return provider.Outcome('matched','4000')
        def run(index):
            try: return self.run_check(f'synthetic-quota-race-{index}',apps[index],body=bodies[index])[1]
            finally: connections.close_all()
        with patch('origination.services.phone_identity.provider.validate',side_effect=paid):
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses=list(pool.map(run,[0,1]))
        self.assertEqual(sorted(statuses),[200,429])
        self.assertEqual(len(dispatched),1)
        self.assertEqual(Usage.objects.get().dispatch_count,50)
