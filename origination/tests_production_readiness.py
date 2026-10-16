"""Read-only signing diagnostics distinguish migration state from DB failures."""
from io import StringIO
import json
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, ProgrammingError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import SimpleTestCase, TestCase, override_settings

from core.production import ReadinessIssue
from origination.services.origination_production import origination_signing_readiness_issues


SMS_MIGRATIONS = {('core', '0206_advanta_integration'), ('origination', '0009_signer_sms_provider')}


@override_settings(ORIGINATION_ESIGN_ENABLED=True, ORIGINATION_SMS_PROVIDER='advanta')
class SigningDeliveryReadinessTests(SimpleTestCase):
    def setUp(self):
        self.security = self.enterContext(patch(
            'origination.services.origination_production.production_security_readiness_issues', return_value=[]))
        self.applied = self.enterContext(patch(
            'django.db.migrations.recorder.MigrationRecorder.applied_migrations', return_value=SMS_MIGRATIONS))
        self.sessions = self.enterContext(patch('origination.models.OriginationSignerSession.objects.filter'))
        self.sessions.return_value.values_list.return_value.distinct.return_value = []
        self.health = self.enterContext(patch('origination.services.origination_sms_delivery.runner_health',
            return_value={'fresh': True, 'status': 'succeeded', 'due_lookups': 0, 'account_changed': 0}))
        self.http = self.enterContext(patch('requests.sessions.Session.request', side_effect=AssertionError('No provider calls')))

    def tearDown(self):
        self.http.assert_not_called()

    def test_connection_failure_is_not_reported_as_missing_migrations(self):
        self.sessions.side_effect = OperationalError('synthetic-password@database-host')
        issues = origination_signing_readiness_issues(settings)
        codes = {issue.code for issue in issues}
        self.assertNotIn('origination-esign-delivery-schema', codes)
        self.assertIn('origination-esign-delivery-database', codes)
        self.assertNotIn('synthetic-password', repr(issues))
        self.assertNotIn('database-host', repr(issues))

    def test_migration_register_failure_does_not_guess_that_migrations_are_pending(self):
        self.applied.side_effect = OperationalError('synthetic-sensitive-db-error')
        issues = origination_signing_readiness_issues(settings)
        self.assertEqual([issue.code for issue in issues], ['origination-esign-delivery-database'])
        self.sessions.assert_not_called()
        self.health.assert_not_called()
        self.assertNotIn('synthetic-sensitive', repr(issues))

    def test_pending_sms_migrations_are_named_without_querying_the_new_schema(self):
        self.applied.return_value = {('core', '0206_advanta_integration')}
        issues = origination_signing_readiness_issues(settings)
        self.assertEqual([issue.code for issue in issues], ['origination-esign-delivery-schema'])
        self.assertEqual(issues[0].severity, 'error')
        self.assertIn('origination.0009_signer_sms_provider', issues[0].message)
        self.assertNotIn('core.0206_advanta_integration', issues[0].message)
        self.assertIn('release.sh', issues[0].message)
        self.sessions.assert_not_called()
        self.health.assert_not_called()

    def test_predeploy_defers_only_pending_sms_schema_reads(self):
        self.applied.return_value = set()
        configuration_issue = ReadinessIssue('error', 'origination-esign-provider', 'Synthetic missing provider.')
        self.security.return_value = [configuration_issue]
        issues = origination_signing_readiness_issues(settings, allow_pending_migrations=True)
        self.assertEqual(issues, [configuration_issue])
        self.sessions.assert_not_called()
        self.health.assert_not_called()

    def test_predeploy_does_not_hide_database_failures_when_migrations_are_applied(self):
        self.sessions.side_effect = OperationalError('synthetic')
        issues = origination_signing_readiness_issues(settings, allow_pending_migrations=True)
        self.assertEqual([issue.code for issue in issues], ['origination-esign-delivery-database'])

    def test_schema_drift_after_applied_migrations_is_not_reported_as_pending(self):
        self.sessions.side_effect = ProgrammingError('synthetic missing column')
        issues = origination_signing_readiness_issues(settings)
        self.assertEqual([issue.code for issue in issues], ['origination-esign-delivery-database'])
        self.assertIn('migrations are recorded as applied', issues[0].message)

    def test_runner_query_failure_is_not_reported_as_missing_migrations(self):
        self.health.side_effect = OperationalError('synthetic-sensitive-query-error')
        issues = origination_signing_readiness_issues(settings)
        self.assertEqual([issue.code for issue in issues], ['origination-esign-delivery-database'])
        self.assertNotIn('synthetic-sensitive', repr(issues))

    def test_healthy_migrated_database_checks_runner_and_disabled_signing_queries_nothing(self):
        self.assertEqual(origination_signing_readiness_issues(settings), [])
        self.sessions.assert_called_once()
        self.health.assert_called_once()
        self.applied.reset_mock()
        self.sessions.reset_mock()
        self.health.reset_mock()
        with override_settings(ORIGINATION_ESIGN_ENABLED=False):
            self.assertEqual(origination_signing_readiness_issues(settings), [])
        self.applied.assert_not_called()
        self.sessions.assert_not_called()
        self.health.assert_not_called()

    def test_stale_runner_warning_survives_normal_predeploy_checks(self):
        self.health.return_value['fresh'] = False
        issues = origination_signing_readiness_issues(settings, allow_pending_migrations=True)
        self.assertIn('origination-esign-delivery-runner', {issue.code for issue in issues})

    def test_readiness_command_json_fails_on_pending_migrations_with_safe_details(self):
        self.applied.return_value = set()
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command('check_origination_signing_readiness', json=True, stdout=output)
        issues = json.loads(output.getvalue())
        self.assertEqual(issues[0]['code'], 'origination-esign-delivery-schema')
        self.assertIn('core.0206_advanta_integration', issues[0]['message'])
        self.assertIn('origination.0009_signer_sms_provider', issues[0]['message'])


@override_settings(ORIGINATION_ESIGN_ENABLED=True, ORIGINATION_SMS_PROVIDER='advanta')
class SigningDeliveryMigrationStateTests(TestCase):
    def setUp(self):
        self.enterContext(patch('origination.services.origination_production.production_security_readiness_issues', return_value=[]))
        self.http = self.enterContext(patch('requests.sessions.Session.request', side_effect=AssertionError('No provider calls')))

    def tearDown(self):
        self.http.assert_not_called()

    def test_applied_migrations_allow_real_delivery_health_queries(self):
        self.assertTrue(SMS_MIGRATIONS.issubset(MigrationRecorder(connection).applied_migrations()))
        issues = origination_signing_readiness_issues(settings)
        self.assertFalse(any(issue.severity == 'error' for issue in issues), issues)

    def test_real_pending_sms_migration_is_deferred_only_for_predeploy(self):
        MigrationRecorder.Migration.objects.filter(app='origination', name='0009_signer_sms_provider').delete()
        with patch('origination.models.OriginationSignerSession.objects.filter') as sessions:
            issues = origination_signing_readiness_issues(settings)
            self.assertEqual([issue.code for issue in issues], ['origination-esign-delivery-schema'])
            self.assertIn('origination.0009_signer_sms_provider', issues[0].message)
            self.assertEqual(origination_signing_readiness_issues(settings, allow_pending_migrations=True), [])
            sessions.assert_not_called()
