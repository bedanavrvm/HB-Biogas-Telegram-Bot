"""Publish native Telegram command autocomplete menus."""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration
from core.services.telegram_command_menu import (
    bot_commands_for_workflow,
    private_chat_bot_commands,
)


class Command(BaseCommand):
    help = "Sync Telegram native bot command autocomplete menus."

    def add_arguments(self, parser):
        parser.add_argument(
            '--group-id',
            help='Only sync a specific configured Telegram chat scope.',
        )
        parser.add_argument(
            '--include-disabled',
            action='store_true',
            help='Include disabled GroupSheetConfiguration rows.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the scopes that would be synced without calling Telegram.',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=getattr(settings, 'API_REQUEST_TIMEOUT', 10),
            help='Telegram API timeout in seconds.',
        )

    def handle(self, *args, **options):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        dry_run = options['dry_run']
        group_id = options.get('group_id')

        if not token and not dry_run:
            raise CommandError('TELEGRAM_BOT_TOKEN is not configured.')

        scopes = []
        if not group_id:
            scopes.extend([
                ('all_private_chats', {'type': 'all_private_chats'}, private_chat_bot_commands()),
            ])

        queryset = GroupSheetConfiguration.objects.all()
        if not options['include_disabled']:
            queryset = queryset.filter(enabled=True)
        if group_id:
            queryset = queryset.filter(group_id=str(group_id))

        for config in queryset:
            workflow = config.workflow or {}
            workflow_type = str(workflow.get('type') or '')
            scopes.append((
                f"chat {config.group_id}",
                {'type': 'chat', 'chat_id': config.group_id},
                bot_commands_for_workflow(workflow_type),
            ))

        if group_id and not scopes:
            raise CommandError(f'No configured group found for {group_id}.')

        if not group_id:
            group_scope = {'type': 'all_group_chats'}
            if dry_run:
                self.stdout.write("Would clear all_group_chats command fallback")
            else:
                self._delete_commands(
                    token=token,
                    scope=group_scope,
                    timeout=options['timeout'],
                    label='all_group_chats',
                )
                self.stdout.write(self.style.SUCCESS("Cleared all_group_chats fallback"))

        for label, scope, commands in scopes:
            if dry_run:
                command_names = ', '.join(f"/{item['command']}" for item in commands)
                self.stdout.write(f"Would sync {label}: {command_names}")
                continue
            self._set_commands(
                token=token,
                scope=scope,
                commands=commands,
                timeout=options['timeout'],
                label=label,
            )
            self.stdout.write(self.style.SUCCESS(f"Synced {label}"))

    def _delete_commands(self, token: str, scope: dict, timeout: int, label: str) -> None:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/deleteMyCommands',
            json={'scope': scope},
            timeout=timeout,
        )
        self._validate_response(response, label, 'deleteMyCommands')

    def _set_commands(self, token: str, scope: dict, commands: list[dict], timeout: int, label: str) -> None:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/setMyCommands',
            json={
                'scope': scope,
                'commands': commands,
            },
            timeout=timeout,
        )
        self._validate_response(response, label, 'setMyCommands')

    def _validate_response(self, response, label: str, method: str) -> None:
        if response.status_code >= 400:
            raise CommandError(
                f'Telegram {method} failed for {label}: '
                f'{response.status_code} {response.text[:300]}'
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CommandError(
                f'Telegram {method} returned invalid JSON for {label}.'
            ) from exc
        if not payload.get('ok'):
            raise CommandError(
                f'Telegram {method} failed for {label}: {payload}'
            )
