"""Run the production release sequence with no preflight schema mutation."""

from __future__ import annotations

from django.conf import settings
from django.core.management import call_command as django_call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import ProductionReleaseAudit
from core.production import NON_PRODUCTION_ENVIRONMENTS, production_readiness_issues
from core.services.origination_production import origination_signing_readiness_issues
from core.services.production_release import (
    existing_release,
    migration_plan_names,
    migration_plan_sha256,
    record_release_evidence,
    reserve_release_evidence,
    serialize_readiness,
    validate_release_reference,
)
from core.services.superuser_bootstrap import (
    SuperuserBootstrapError,
    bootstrap_superuser_from_environment,
)
from core.services.tat_production import tat_production_readiness_issues


class Command(BaseCommand):
    help = 'Run preflight, migration, post-check, bootstrap, and release evidence in order.'

    def add_arguments(self, parser):
        parser.add_argument('--release-id', default='')
        parser.add_argument('--backup-reference', default='')
        parser.add_argument('--actor', default='')
        parser.add_argument('--environment', default='')

    def _check(self, label: str, issues, readiness: dict) -> None:
        readiness[label] = serialize_readiness(issues)
        if issues:
            for issue in issues:
                self.stdout.write(f'[{issue.severity.upper()}] {issue.code}: {issue.message}')
            raise CommandError(f'{label.replace("_", " ").title()} readiness checks failed.')
        self.stdout.write(self.style.SUCCESS(f'{label.replace("_", " ").title()} readiness passed.'))

    def _record_failure(self, *, status, failure_code, context) -> None:
        try:
            record_release_evidence(
                **context, status=status, failure_code=failure_code,
            )
        except Exception as exc:
            self.stderr.write(
                f'Release failure evidence could not be persisted ({type(exc).__name__}).'
            )

    def handle(self, *args, **options):
        started_at = timezone.now()
        readiness = {}

        self.stdout.write('1/9 General production readiness')
        self._check(
            'general', production_readiness_issues(settings, check_database=True), readiness,
        )

        self.stdout.write('2/9 TAT scheduler/readiness')
        if getattr(settings, 'TAT_NOTIFICATION_SCHEDULER_REQUIRED', False):
            self._check(
                'tat',
                tat_production_readiness_issues(settings, allow_pending_migrations=True),
                readiness,
            )
        else:
            readiness['tat'] = {'passed': True, 'skipped': True, 'issues': []}
            self.stdout.write('TAT scheduler readiness skipped because it is not enabled.')

        self.stdout.write('3/9 Origination signing readiness')
        if getattr(settings, 'ORIGINATION_ESIGN_ENABLED', False):
            self._check(
                'origination_signing',
                origination_signing_readiness_issues(settings),
                readiness,
            )
        else:
            readiness['origination_signing'] = {
                'passed': True, 'skipped': True, 'issues': [],
            }
            self.stdout.write('Origination signing readiness skipped because it is not enabled.')

        self.stdout.write('4/9 Migration-plan inspection')
        planned = migration_plan_names()
        for name in planned:
            self.stdout.write(f'  - {name}')
        self.stdout.write(f'Migration plan SHA-256: {migration_plan_sha256(planned)}')

        self.stdout.write('5/9 Backup evidence verification')
        try:
            release_id = validate_release_reference(
                options['release_id'] or getattr(settings, 'APP_RELEASE', ''),
                field_name='Release ID',
                min_length=3,
                max_length=160,
            )
            actor = validate_release_reference(
                options['actor'] or getattr(settings, 'RELEASE_ACTOR', ''),
                field_name='Release actor',
                max_length=160,
            )
            environment = validate_release_reference(
                options['environment'] or getattr(settings, 'RELEASE_ENVIRONMENT', ''),
                field_name='Release environment',
                max_length=80,
            )
            allow_no_backup = bool(
                getattr(settings, 'RELEASE_ALLOW_NO_BACKUP', False)
            )
            if allow_no_backup and environment.casefold() not in NON_PRODUCTION_ENVIRONMENTS:
                raise ValueError(
                    'RELEASE_ALLOW_NO_BACKUP may be enabled only for an explicitly '
                    'non-production release environment.'
                )
            raw_backup_reference = (
                options['backup_reference']
                or getattr(settings, 'RELEASE_BACKUP_REFERENCE', '')
            )
            if not str(raw_backup_reference or '').strip() and allow_no_backup:
                backup_reference = f'no-backup:{environment.casefold()}'
            else:
                backup_reference = validate_release_reference(
                    raw_backup_reference,
                    field_name='Backup reference',
                    min_length=8,
                    max_length=255,
                )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        previous = existing_release(release_id)
        if previous:
            if (
                previous.backup_reference != backup_reference
                or previous.actor != actor
                or previous.environment != environment
            ):
                raise CommandError('The existing release evidence has different immutable attribution.')
            if planned and previous.migration_names and previous.migration_names != planned:
                raise CommandError('Use a new release ID for a different migration plan.')
        if backup_reference.startswith('no-backup:'):
            self.stdout.write(self.style.WARNING(
                'No database backup is available for this explicitly non-production '
                f'release. Audit reference recorded: {backup_reference}'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f'Backup evidence accepted: {backup_reference}'))

        context = {
            'release_id': release_id,
            'backup_reference': backup_reference,
            'actor': actor,
            'environment': environment,
            'migration_names': planned,
            'readiness_results': readiness,
            'started_at': started_at,
        }
        try:
            reservation = reserve_release_evidence(**context)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if reservation is not None:
            self.stdout.write('Reviewed migration plan reserved in release evidence.')

        self.stdout.write('6/9 Apply migrations')
        migrations_completed_at = None
        try:
            if planned:
                django_call_command('migrate', interactive=False)
            else:
                self.stdout.write('No pending migrations; schema mutation skipped.')
            migrations_completed_at = timezone.now()
            context['migrations_completed_at'] = migrations_completed_at
        except Exception as exc:
            self._record_failure(
                status=ProductionReleaseAudit.STATUS_MIGRATION_FAILED,
                failure_code='migration_failed', context=context,
            )
            raise CommandError('Migration application failed; automatic rollback was not attempted.') from exc

        self.stdout.write('7/9 Post-migration Django check')
        try:
            django_call_command('check', deploy=True, fail_level='ERROR')
        except Exception as exc:
            self._record_failure(
                status=ProductionReleaseAudit.STATUS_POST_CHECK_FAILED,
                failure_code='post_migration_check_failed', context=context,
            )
            raise CommandError(
                'Post-migration checks failed; bootstrap was not run. Keep the application release blocked.'
            ) from exc

        self.stdout.write('8/9 Controlled Superuser bootstrap')
        try:
            bootstrap = bootstrap_superuser_from_environment()
        except SuperuserBootstrapError as exc:
            self._record_failure(
                status=ProductionReleaseAudit.STATUS_BOOTSTRAP_FAILED,
                failure_code='superuser_bootstrap_failed', context={
                    **context, 'post_check_passed': True,
                },
            )
            raise CommandError(str(exc)) from exc

        self.stdout.write('9/9 Record release evidence')
        try:
            audit = record_release_evidence(
                **context,
                status=ProductionReleaseAudit.STATUS_COMPLETED,
                post_check_passed=True,
                bootstrap_result=bootstrap.outcome,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'Release {audit.release_id} completed; evidence recorded '
            f'for {len(audit.migration_names)} migration(s).'
        ))
