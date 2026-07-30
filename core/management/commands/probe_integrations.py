"""Manually validate external integration configuration or safe metadata access.

No scheduler invokes this command. Without ``--execute`` it performs only a
configuration dry-run; with the explicit flag it makes read-only metadata
calls and records their redacted outcomes in IntegrationOperation.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.services.external_resilience import execute_operation, reserve_operation


INTEGRATIONS = ('google_sheets', 'google_drive', 'telegram')


class Command(BaseCommand):
    help = 'Dry-run or explicitly execute read-only Google Sheets, Drive, and Telegram readiness probes.'

    def add_arguments(self, parser):
        parser.add_argument('--integration', choices=(*INTEGRATIONS, 'all'), default='all')
        parser.add_argument(
            '--execute', action='store_true',
            help='Perform read-only external metadata probes. Omit for a configuration-only dry run.',
        )

    def handle(self, *args, **options):
        selected = INTEGRATIONS if options['integration'] == 'all' else (options['integration'],)
        execute = bool(options['execute'])
        for integration in selected:
            configured, detail = configuration_status(integration)
            if not configured:
                self.stdout.write(self.style.WARNING(f'{integration}: configuration incomplete ({detail})'))
                continue
            if not execute:
                self.stdout.write(f'{integration}: configuration ready; external call skipped (use --execute).')
                continue
            result = run_probe(integration)
            self.stdout.write(self.style.SUCCESS(f'{integration}: read-only metadata probe succeeded ({result}).'))


def configuration_status(integration: str) -> tuple[bool, str]:
    if integration == 'google_sheets':
        sheet_id, _ = _configured_sheet_target()
        return bool(sheet_id), 'GOOGLE_SHEET_ID and configured group sheet IDs are missing'
    if integration == 'google_drive':
        return bool(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '')), 'GOOGLE_DRIVE_MEDIA_FOLDER_ID is missing'
    if integration == 'telegram':
        return bool(getattr(settings, 'TELEGRAM_BOT_TOKEN', '')), 'TELEGRAM_BOT_TOKEN is missing'
    raise CommandError('Unsupported integration.')


def run_probe(integration: str):
    """Run one operator-authorized, read-only probe through the shared policy."""
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
    operation, _ = reserve_operation(
        integration=integration,
        operation_type='readiness_probe',
        deduplication_key=f'{integration}:readiness-probe:{timestamp}',
        source_model='management_command',
        source_id='probe_integrations',
        operation_payload={'at': timestamp},
        metadata={'manual': True, 'read_only': True},
    )
    return execute_operation(operation, lambda: _probe_once(integration))


def _probe_once(integration: str):
    if integration == 'google_sheets':
        from core.services.sheets import GoogleSheetsService
        sheet_id, sheet_name = _configured_sheet_target()
        service = GoogleSheetsService.get_instance(sheet_id=sheet_id, sheet_name=sheet_name)
        if not service.is_available():
            raise RuntimeError('Google Sheets metadata could not be reached.')
        return {'id': 'configured-sheet'}
    if integration == 'google_drive':
        from core.services.order_approval import GoogleDriveMediaStorage
        storage = GoogleDriveMediaStorage()
        result = storage.service.files().get(
            fileId=storage.parent_folder_id,
            fields='id',
            supportsAllDrives=True,
        ).execute()
        return {'id': result.get('id', '')}
    if integration == 'telegram':
        import requests
        token = settings.TELEGRAM_BOT_TOKEN
        response = requests.get(f'https://api.telegram.org/bot{token}/getMe', timeout=settings.API_REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not payload.get('ok'):
            error = RuntimeError('Telegram metadata probe failed.')
            error.status_code = response.status_code
            error.headers = response.headers
            raise error
        return {'id': str((payload.get('result') or {}).get('id') or '')}
    raise CommandError('Unsupported integration.')


def _configured_sheet_target() -> tuple[str, str]:
    """Find a local configured Sheet without probing it or loading its rows."""
    default_id = str(getattr(settings, 'GOOGLE_SHEET_ID', '') or '').strip()
    if default_id:
        return default_id, str(getattr(settings, 'GOOGLE_SHEET_TAB_NAME', '') or '').strip()
    from core.models import GroupSheetConfiguration
    group = (
        GroupSheetConfiguration.objects.filter(enabled=True)
        .exclude(sheet_id='')
        .order_by('id')
        .first()
    )
    if not group:
        return '', ''
    return str(group.sheet_id), str(group.sheet_name or '')
