"""TAT-specific local production gate tests; no external service calls."""

from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import GroupSheetConfiguration
from core.production import ReadinessIssue
from core.services.tat_production import tat_production_readiness_issues


@override_settings(
    TAT_TRACKER_MINI_APP_SHORT_NAME='tattracker',
    TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    TAT_NOTIFICATION_SCHEDULER_REQUIRED=True,
    TAT_NOTIFICATION_PROCESSOR_LOCK_SECONDS=240,
    TAT_NOTIFICATION_SCHEDULER_MAX_SILENCE_SECONDS=180,
    SENTRY_DSN='https://public@example.ingest.sentry.io/123',
)
class TatProductionReadinessTests(TestCase):
    def test_missing_operational_state_is_reported_without_external_calls(self):
        issues = tat_production_readiness_issues(settings)
        codes = {issue.code for issue in issues}

        self.assertIn('tat-data-mode', codes)
        self.assertIn('tat-group', codes)
        self.assertIn('tat-notification-scheduler-stale', codes)

    def test_group_requires_sheet_contract_access_and_responsibility_coverage(self):
        GroupSheetConfiguration.objects.create(
            group_id='-100-readiness', display_name='TAT readiness',
            sheet_id='sheet-test', sheet_name='TRACKER-Business',
            workflow={
                'type': 'tat_tracker', 'tat_notification_mode': 'hybrid',
                'branches': ['Nakuru'], 'products': ['business'],
            },
        )

        codes = {issue.code for issue in tat_production_readiness_issues(settings)}

        self.assertIn('tat-sheet-contract', codes)
        self.assertIn('tat-access-coverage', codes)
        self.assertIn('tat-responsibility-missing', codes)

    @override_settings(TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    def test_telegram_auth_cannot_be_disabled(self):
        codes = {issue.code for issue in tat_production_readiness_issues(settings)}
        self.assertIn('tat-telegram-auth', codes)

    @patch(
        'core.management.commands.check_tat_production_readiness.tat_production_readiness_issues',
        return_value=[],
    )
    def test_readiness_command_supports_json_success(self, _issues):
        output = StringIO()
        call_command('check_tat_production_readiness', '--strict', '--json', stdout=output)
        self.assertEqual(output.getvalue().strip(), '[]')

    @patch(
        'core.management.commands.check_tat_production_readiness.tat_production_readiness_issues',
        return_value=[ReadinessIssue('error', 'tat-test', 'Synthetic failure.')],
    )
    def test_readiness_command_fails_on_error(self, _issues):
        with self.assertRaises(CommandError):
            call_command('check_tat_production_readiness', '--strict', stdout=StringIO())
