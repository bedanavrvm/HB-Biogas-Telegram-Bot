"""Aggregate and prune privacy-safe Mini App diagnostics."""

from django.core.management.base import BaseCommand

from core.services.miniapp_diagnostics import aggregate_and_prune


class Command(BaseCommand):
    help = (
        'Preview or apply Mini App diagnostic retention. Raw session/event rows '
        'are aggregated before deletion; customer and workflow records are never touched.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Aggregate and delete expired rows. Without this flag the command is read-only.',
        )

    def handle(self, *args, **options):
        applied = bool(options['apply'])
        result = aggregate_and_prune(apply=applied)
        detail = (
            f"{result['raw_sessions']} raw session(s), {result['raw_events']} raw event(s), "
            f"{result['aggregate_rows']} rollup row(s), and "
            f"{result['expired_aggregate_rows']} expired rollup row(s)."
        )
        if applied:
            self.stdout.write(self.style.SUCCESS(f'Applied Mini App diagnostic retention: {detail}'))
        else:
            self.stdout.write(self.style.WARNING(
                f'Dry run only: {detail} Re-run with --apply to make changes.'
            ))
