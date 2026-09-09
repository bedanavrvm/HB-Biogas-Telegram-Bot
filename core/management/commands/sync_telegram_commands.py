"""Publish native Telegram command autocomplete menus."""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration


class Command(BaseCommand):
    help = "Clear archived Telegram command menus and stale default Web App buttons."

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
                (
                    'all_private_chats',
                    {'type': 'all_private_chats'},
                    None,
                ),
            ])

        queryset = GroupSheetConfiguration.objects.all()
        if not options['include_disabled']:
            queryset = queryset.filter(enabled=True)
        if group_id:
            queryset = queryset.filter(group_id=str(group_id))

        for config in queryset:
            scopes.append((
                f"chat {config.group_id}",
                {'type': 'chat', 'chat_id': config.group_id},
                config,
            ))

        if group_id and not scopes:
            raise CommandError(f'No configured group found for {group_id}.')

        if not group_id:
            if dry_run:
                self.stdout.write("Would reset the bot-profile menu button")
            else:
                self._reset_default_menu_button(token, options['timeout'])
                self.stdout.write(self.style.SUCCESS("Reset the bot-profile menu button"))
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

        for label, scope, config in scopes:
            if dry_run:
                self.stdout.write(f"Would clear {label} command menu")
                continue
            self._delete_commands(
                token=token,
                scope=scope,
                timeout=options['timeout'],
                label=label,
                config=config,
            )
            self.stdout.write(self.style.SUCCESS(f"Cleared {label} command menu"))

    def _reset_default_menu_button(self, token: str, timeout: int) -> None:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/setChatMenuButton',
            json={'menu_button': {'type': 'default'}},
            timeout=timeout,
        )
        self._validate_response(response, 'default bot profile', 'setChatMenuButton')

    def _delete_commands(
        self, token: str, scope: dict, timeout: int, label: str,
        config: GroupSheetConfiguration | None = None,
    ) -> None:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/deleteMyCommands',
            json={'scope': scope},
            timeout=timeout,
        )
        migrated_chat_id = self._migrated_chat_id(response)
        if migrated_chat_id and config and scope.get('type') == 'chat':
            old_group_id = str(config.group_id)
            new_group_id = str(migrated_chat_id)
            if not self._apply_migrated_chat_id(config, new_group_id):
                return
            self.stdout.write(self.style.WARNING(
                f"Updated migrated Telegram group {old_group_id} -> {new_group_id}"
            ))
            scope = {**scope, 'chat_id': new_group_id}
            response = requests.post(
                f'https://api.telegram.org/bot{token}/deleteMyCommands',
                json={'scope': scope}, timeout=timeout,
            )
        self._validate_response(response, label, 'deleteMyCommands')

    def _migrated_chat_id(self, response) -> str:
        if response.status_code != 400:
            return ''
        try:
            payload = response.json()
        except ValueError:
            return ''
        value = (payload.get('parameters') or {}).get('migrate_to_chat_id')
        return str(value) if value else ''

    def _apply_migrated_chat_id(self, config: GroupSheetConfiguration, new_group_id: str) -> bool:
        if str(config.group_id) == new_group_id:
            return False

        existing = (
            GroupSheetConfiguration.objects
            .filter(group_id=new_group_id)
            .exclude(pk=config.pk)
            .first()
        )
        metadata = dict(config.metadata or {})
        metadata['migrated_from_chat_id'] = str(config.group_id)
        metadata['migrated_to_chat_id'] = new_group_id
        if existing:
            metadata['migration_conflict_config_id'] = existing.pk
            config.enabled = False
            config.metadata = metadata
            config.save(update_fields=['enabled', 'metadata', 'updated_at'])
            self.stdout.write(
                self.style.WARNING(
                    f"Telegram group {config.group_id} migrated to {new_group_id}, "
                    f"but that group is already configured as row {existing.pk}. "
                    "Disabled the stale row."
                )
            )
            return False

        config.group_id = new_group_id
        config.metadata = metadata
        config.save(update_fields=['group_id', 'metadata', 'updated_at'])
        return True

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
