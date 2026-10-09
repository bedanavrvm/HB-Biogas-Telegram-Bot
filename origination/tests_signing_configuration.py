from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from core.checks import production_security_configuration_check
from core.production import production_security_readiness_issues
from origination.services.origination_esign import esign_enabled
from origination.services.origination_signing_configuration import provider_configuration_issues, signing_available


class SigningConfigurationTests(SimpleTestCase):
    def config(self, **changes):
        return SimpleNamespace(**{
            'ORIGINATION_ESIGN_ENABLED': True, 'AFRICASTALKING_SMS_ENVIRONMENT': 'production',
            'AFRICASTALKING_USERNAME': 'synthetic-account', 'AFRICASTALKING_API_KEY': 'synthetic-provider-key',
            'SENTRY_ENVIRONMENT': 'testing', 'RELEASE_ENVIRONMENT': 'staging', **changes,
        })

    def test_real_provider_is_independent_of_logging_and_release_labels(self):
        for environment in ('testing', 'production', '', 'unknown'):
            self.assertTrue(signing_available(self.config(SENTRY_ENVIRONMENT=environment, RELEASE_ENVIRONMENT=environment)))

    def test_sandbox_requires_sandbox_username_not_release_markers(self):
        self.assertTrue(signing_available(self.config(AFRICASTALKING_SMS_ENVIRONMENT='sandbox', AFRICASTALKING_USERNAME='sandbox')))
        self.assertFalse(signing_available(self.config(AFRICASTALKING_SMS_ENVIRONMENT='sandbox')))

    def test_unusable_credentials_and_disabled_master_gate_fail_closed(self):
        for changes in ({'ORIGINATION_ESIGN_ENABLED': False}, {'AFRICASTALKING_API_KEY': ''},
                        {'AFRICASTALKING_API_KEY': 'your-api-key'}, {'AFRICASTALKING_USERNAME': 'sandbox'},
                        {'AFRICASTALKING_SMS_ENVIRONMENT': 'invalid'}):
            self.assertFalse(signing_available(self.config(**changes)))

    @override_settings(ORIGINATION_ESIGN_ENABLED=True, AFRICASTALKING_SMS_ENVIRONMENT='production',
                       AFRICASTALKING_USERNAME='synthetic-account', AFRICASTALKING_API_KEY='synthetic-provider-key',
                       SENTRY_ENVIRONMENT='testing', RELEASE_ENVIRONMENT='testing')
    def test_runtime_and_readiness_share_verdict(self):
        self.assertTrue(esign_enabled())
        self.assertEqual(provider_configuration_issues(self.config()), [])

    @override_settings(DEBUG=False, ORIGINATION_ESIGN_ENABLED=True, AFRICASTALKING_SMS_ENVIRONMENT='production',
                       AFRICASTALKING_USERNAME='', AFRICASTALKING_API_KEY='')
    def test_django_setup_warnings_do_not_become_deployment_errors(self):
        results = production_security_configuration_check(None)
        provider = [item for item in results if item.id in {'core.W017', 'core.W018'}]
        self.assertEqual(len(provider), 2)
        self.assertTrue(all(item.level == 30 for item in provider))

    def test_authentication_errors_remain_errors(self):
        issues = production_security_readiness_issues(self.config(TELEGRAM_WEBHOOK_SECRET=''))
        self.assertEqual(next(i for i in issues if i.code == 'telegram-webhook-secret').severity, 'error')


@override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True)
class ConsentReadinessSeverityTests(TestCase):
    def test_missing_setup_is_warning_but_tampered_signed_wording_is_error(self):
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from origination.models import OriginationConsentPolicyVersion
        issues = production_security_readiness_issues(settings, check_database=True)
        self.assertEqual(next(i for i in issues if i.code == 'conditional-approval-consent-policy').severity, 'warning')
        actor = get_user_model().objects.create_superuser('consent-readiness-test', password='synthetic')
        policy = OriginationConsentPolicyVersion.objects.create(
            version='synthetic-readiness', status='active', packet_clause='Synthetic approved wording',
            signer_consent_text='Synthetic consent', signer_completion_text='Synthetic completion',
            resigning_text='Synthetic re-signing', approval_reference='synthetic-ref',
            approved_by=actor, approved_at=timezone.now(), created_by=actor,
        )
        OriginationConsentPolicyVersion.objects.filter(pk=policy.pk).update(packet_clause='Synthetic tampering')
        issues = production_security_readiness_issues(settings, check_database=True)
        self.assertEqual(next(i for i in issues if i.code == 'conditional-approval-consent-integrity').severity, 'error')
