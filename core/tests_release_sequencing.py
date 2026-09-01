import io
import json
import os
from unittest.mock import Mock, call, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import ProductionReleaseAudit
from core.production import ReadinessIssue, production_readiness_issues
from core.services.origination_production import origination_signing_readiness_issues
from core.services.superuser_bootstrap import bootstrap_superuser_from_environment
from core.services.tat_production import tat_production_readiness_issues


RELEASE_SETTINGS = {
    'APP_RELEASE': 'release-20260831-a',
    'RELEASE_BACKUP_REFERENCE': 'render-backup-12345',
    'RELEASE_ALLOW_NO_BACKUP': False,
    'RELEASE_ACTOR': 'render-predeploy',
    'RELEASE_ENVIRONMENT': 'production',
    'TAT_NOTIFICATION_SCHEDULER_REQUIRED': True,
    'ORIGINATION_ESIGN_ENABLED': True,
}


@override_settings(**RELEASE_SETTINGS)
class ProductionReleaseCommandTests(TestCase):
    def _successful_patches(self, *, plans=None):
        stack = self.enterContext
        stack(patch(
            'core.management.commands.release_production.production_readiness_issues',
            return_value=[],
        ))
        tat = stack(patch(
            'core.management.commands.release_production.tat_production_readiness_issues',
            return_value=[],
        ))
        origination = stack(patch(
            'core.management.commands.release_production.origination_signing_readiness_issues',
            return_value=[],
        ))
        plan = stack(patch(
            'core.management.commands.release_production.migration_plan_names',
            side_effect=plans or [['core.0152_productionreleaseaudit:forward']],
        ))
        django_command = stack(patch(
            'core.management.commands.release_production.django_call_command',
        ))
        bootstrap = stack(patch(
            'core.management.commands.release_production.bootstrap_superuser_from_environment',
            return_value=Mock(outcome='existing'),
        ))
        return tat, origination, plan, django_command, bootstrap

    def test_enabled_readiness_runs_before_migration(self):
        events = []
        with patch(
            'core.management.commands.release_production.production_readiness_issues',
            side_effect=lambda *args, **kwargs: events.append('general') or [],
        ), patch(
            'core.management.commands.release_production.tat_production_readiness_issues',
            side_effect=lambda *args, **kwargs: events.append('tat') or [],
        ) as tat, patch(
            'core.management.commands.release_production.origination_signing_readiness_issues',
            side_effect=lambda *args, **kwargs: events.append('origination') or [],
        ), patch(
            'core.management.commands.release_production.migration_plan_names',
            side_effect=lambda: events.append('plan') or ['core.0152:forward'],
        ), patch(
            'core.management.commands.release_production.django_call_command',
            side_effect=lambda name, **kwargs: events.append(name),
        ), patch(
            'core.management.commands.release_production.bootstrap_superuser_from_environment',
            side_effect=lambda: events.append('bootstrap') or Mock(outcome='existing'),
        ):
            call_command('release_production', stdout=io.StringIO())

        self.assertEqual(
            events,
            ['general', 'tat', 'origination', 'plan', 'migrate', 'check', 'bootstrap'],
        )
        tat.assert_called_once_with(settings, allow_pending_migrations=True)

    def test_tat_failure_stops_before_plan_or_migration(self):
        with patch(
            'core.management.commands.release_production.production_readiness_issues',
            return_value=[],
        ), patch(
            'core.management.commands.release_production.tat_production_readiness_issues',
            return_value=[ReadinessIssue('error', 'tat-stale', 'Synthetic stale runner.')],
        ), patch(
            'core.management.commands.release_production.migration_plan_names',
        ) as plan, patch(
            'core.management.commands.release_production.django_call_command',
        ) as django_command:
            with self.assertRaises(CommandError):
                call_command('release_production', stdout=io.StringIO())
        plan.assert_not_called()
        django_command.assert_not_called()
        self.assertFalse(ProductionReleaseAudit.objects.exists())

    def test_missing_backup_evidence_blocks_migration(self):
        _, _, _, django_command, _ = self._successful_patches()
        with override_settings(RELEASE_BACKUP_REFERENCE=''):
            with self.assertRaisesMessage(CommandError, 'Backup reference'):
                call_command('release_production', stdout=io.StringIO())
        django_command.assert_not_called()
        self.assertFalse(ProductionReleaseAudit.objects.exists())

    def test_explicit_non_production_release_can_record_no_backup(self):
        _, _, _, django_command, _ = self._successful_patches()
        stdout = io.StringIO()
        with override_settings(
            RELEASE_BACKUP_REFERENCE='',
            RELEASE_ALLOW_NO_BACKUP=True,
            RELEASE_ENVIRONMENT='development',
        ):
            call_command('release_production', stdout=stdout)

        django_command.assert_any_call('migrate', interactive=False)
        audit = ProductionReleaseAudit.objects.get(pk=settings.APP_RELEASE)
        self.assertEqual(audit.backup_reference, 'no-backup:development')
        self.assertIn('No database backup is available', stdout.getvalue())

    def test_production_release_rejects_no_backup_override(self):
        _, _, _, django_command, _ = self._successful_patches()
        with override_settings(
            RELEASE_ALLOW_NO_BACKUP=True,
            RELEASE_ENVIRONMENT='production',
        ):
            with self.assertRaisesMessage(
                CommandError, 'may be enabled only for an explicitly non-production',
            ):
                call_command('release_production', stdout=io.StringIO())

        django_command.assert_not_called()
        self.assertFalse(ProductionReleaseAudit.objects.exists())

    def test_migration_failure_retains_the_reserved_plan(self):
        _, _, _, django_command, bootstrap = self._successful_patches()
        django_command.side_effect = CommandError('synthetic migration failure')

        with self.assertRaisesMessage(CommandError, 'automatic rollback was not attempted'):
            call_command('release_production', stdout=io.StringIO())

        bootstrap.assert_not_called()
        audit = ProductionReleaseAudit.objects.get(pk=settings.APP_RELEASE)
        self.assertEqual(audit.status, ProductionReleaseAudit.STATUS_MIGRATION_FAILED)
        self.assertEqual(
            audit.migration_names,
            ['core.0152_productionreleaseaudit:forward'],
        )
        self.assertEqual(audit.attempt_count, 1)

    def test_post_migration_failure_records_evidence_and_skips_bootstrap(self):
        _, _, _, django_command, bootstrap = self._successful_patches()
        django_command.side_effect = [None, CommandError('synthetic post-check failure')]

        with self.assertRaisesMessage(CommandError, 'bootstrap was not run'):
            call_command('release_production', stdout=io.StringIO())

        bootstrap.assert_not_called()
        audit = ProductionReleaseAudit.objects.get(pk=settings.APP_RELEASE)
        self.assertEqual(audit.status, ProductionReleaseAudit.STATUS_POST_CHECK_FAILED)
        self.assertFalse(audit.post_migration_check_passed)
        self.assertEqual(audit.failure_code, 'post_migration_check_failed')

    def test_completed_release_is_repeatable_and_retains_original_plan(self):
        _, _, _, django_command, _ = self._successful_patches(
            plans=[['core.0152_productionreleaseaudit:forward'], []],
        )

        call_command('release_production', stdout=io.StringIO())
        call_command('release_production', stdout=io.StringIO())

        self.assertEqual(
            django_command.call_args_list,
            [
                call('migrate', interactive=False),
                call('check', deploy=True, fail_level='ERROR'),
                call('check', deploy=True, fail_level='ERROR'),
            ],
        )
        audit = ProductionReleaseAudit.objects.get(pk=settings.APP_RELEASE)
        self.assertEqual(audit.status, ProductionReleaseAudit.STATUS_COMPLETED)
        self.assertEqual(audit.attempt_count, 2)
        self.assertEqual(
            audit.migration_names,
            ['core.0152_productionreleaseaudit:forward'],
        )
        self.assertEqual(len(audit.attempt_history), 2)

    def test_evidence_does_not_capture_bootstrap_secrets(self):
        self._successful_patches()
        secret = 'not-for-release-audit-987654'
        with patch.dict(os.environ, {
            'DJANGO_SUPERUSER_PASSWORD': secret,
            'TELEGRAM_BOT_TOKEN': f'token-{secret}',
        }):
            call_command('release_production', stdout=io.StringIO())
        audit = ProductionReleaseAudit.objects.get(pk=settings.APP_RELEASE)
        serialized = json.dumps({
            'backup_reference': audit.backup_reference,
            'readiness_results': audit.readiness_results,
            'attempt_history': audit.attempt_history,
        })
        self.assertNotIn(secret, serialized)


class ReleaseReadinessSideEffectTests(TestCase):
    @override_settings(
        TAT_NOTIFICATION_SCHEDULER_REQUIRED=True,
        ORIGINATION_ESIGN_ENABLED=True,
    )
    @patch('core.services.order_approval.GoogleDriveMediaStorage.upload')
    @patch('core.services.sheets.GoogleSheetsService.append_row')
    @patch('requests.sessions.Session.request')
    def test_readiness_performs_no_telegram_or_google_writes(
        self, http_request, append_row, drive_upload,
    ):
        production_readiness_issues(settings, check_database=True)
        tat_production_readiness_issues(settings, allow_pending_migrations=True)
        origination_signing_readiness_issues(settings)
        http_request.assert_not_called()
        append_row.assert_not_called()
        drive_upload.assert_not_called()


class SuperuserBootstrapTests(TestCase):
    def test_bootstrap_is_idempotent(self):
        environment = {
            'DJANGO_SUPERUSER_USERNAME': 'release-admin',
            'DJANGO_SUPERUSER_EMAIL': 'release-admin@example.invalid',
            'DJANGO_SUPERUSER_PASSWORD': 'synthetic-long-password',
        }
        with patch.dict(os.environ, environment, clear=False):
            first = bootstrap_superuser_from_environment()
            second = bootstrap_superuser_from_environment()
        self.assertEqual(first.outcome, 'created')
        self.assertEqual(second.outcome, 'existing')
        self.assertEqual(
            get_user_model().objects.filter(username='release-admin').count(), 1,
        )


class MigrationPlanCommandTests(TestCase):
    @patch(
        'core.management.commands.inspect_release_migration_plan.migration_plan_names',
        return_value=['core.0152_productionreleaseaudit:forward'],
    )
    def test_command_prints_machine_readable_plan(self, _plan):
        stdout = io.StringIO()
        call_command('inspect_release_migration_plan', json=True, stdout=stdout)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload['migrations'], ['core.0152_productionreleaseaudit:forward'])
        self.assertEqual(payload['count'], 1)
        self.assertEqual(len(payload['sha256']), 64)
