"""Publish pinned, group-specific JBL Apps launchers."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration
from core.services.telegram_launchers import (
    TelegramLauncherError,
    preview_group_launcher,
    publish_group_launcher,
)


class Command(BaseCommand):
    help = 'Publish pinned JBL Apps Mini App launchers for configured Telegram groups.'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', help='Only publish one configured Telegram group.')
        parser.add_argument('--include-disabled', action='store_true', help='Include disabled group configurations.')
        parser.add_argument('--dry-run', action='store_true', help='Preview launchers without calling Telegram.')
        parser.add_argument(
            '--timeout',
            type=int,
            default=getattr(settings, 'API_REQUEST_TIMEOUT', 10),
            help='Telegram API timeout in seconds.',
        )

    def handle(self, *args, **options):
        queryset = GroupSheetConfiguration.objects.all()
        if not options['include_disabled']:
            queryset = queryset.filter(enabled=True)
        if options.get('group_id'):
            queryset = queryset.filter(group_id=str(options['group_id']))
        configs = list(queryset)
        if options.get('group_id') and not configs:
            raise CommandError(f"No configured group found for {options['group_id']}.")
        if not options['dry_run'] and not getattr(settings, 'TELEGRAM_BOT_TOKEN', ''):
            raise CommandError('TELEGRAM_BOT_TOKEN is not configured.')

        failures = []
        for config in configs:
            try:
                preview = preview_group_launcher(config)
                labels = ', '.join(
                    button['text']
                    for row in preview['reply_markup']['inline_keyboard']
                    for button in row
                )
                if options['dry_run']:
                    self.stdout.write(f'Would publish chat {config.group_id}: {labels}')
                    continue
                result = publish_group_launcher(
                    config,
                    timeout=options['timeout'],
                    allow_disabled=options['include_disabled'],
                )
                self.stdout.write(self.style.SUCCESS(
                    f"Published chat {config.group_id}: {result['action']} launcher message {result['message_id']}"
                ))
            except TelegramLauncherError as exc:
                failures.append(f'{config.group_id}: {exc}')
                self.stderr.write(self.style.ERROR(f'Failed {config.group_id}: {exc}'))

        if failures:
            raise CommandError('One or more launcher publishes failed.')
