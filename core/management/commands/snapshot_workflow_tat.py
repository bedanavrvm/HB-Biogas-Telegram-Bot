"""Preview or persist the current-day internal TAT trend projection."""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.services.workflow_sla import collect_tat_daily_metrics, record_tat_daily_metrics


class Command(BaseCommand):
    help = 'Preview current-day Jawabu/TAT SLA trend metrics; --apply writes idempotent internal snapshots only.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Upsert daily metric snapshots; never notifies, syncs, or changes case state.')
        parser.add_argument('--json', action='store_true', help='Emit machine-readable metric rows.')
        parser.add_argument('--date', dest='metric_date', help='Snapshot one date (YYYY-MM-DD).')
        parser.add_argument('--from', dest='date_from', help='First backfill date (YYYY-MM-DD).')
        parser.add_argument('--to', dest='date_to', help='Last backfill date (YYYY-MM-DD).')
        parser.add_argument('--process-rebuilds', action='store_true', help='Process up to 31 pending correction rebuild dates.')

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options['date_from'] or options['metric_date']) if (options['date_from'] or options['metric_date']) else timezone.localdate()
            end = date.fromisoformat(options['date_to']) if options['date_to'] else start
        except ValueError as exc:
            raise CommandError('Dates must use YYYY-MM-DD.') from exc
        if end < start:
            raise CommandError('--to must be on or after --from.')
        if (end - start).days > 365:
            raise CommandError('One invocation may process at most 366 dates.')
        all_metrics = []
        created = 0
        cursor = start
        while cursor <= end:
            metrics = collect_tat_daily_metrics(metric_date=cursor)
            all_metrics.extend(metrics)
            if options['apply']:
                from core.services.tat_reporting import replace_metric_date
                _records, day_created = replace_metric_date(cursor)
                created += day_created
            cursor += timedelta(days=1)
        rebuild_days = 0
        if options['apply'] and options['process_rebuilds']:
            from core.services.tat_reporting import process_metric_rebuilds
            rebuild_days = process_metric_rebuilds(max_days=31)
        payload = {
            'mode': 'apply' if options['apply'] else 'dry_run',
            'metric_date': start.isoformat() if start == end else '',
            'date_from': start.isoformat(), 'date_to': end.isoformat(),
            'metric_count': len(all_metrics),
            'created_count': created,
            'rebuild_days_processed': rebuild_days,
            'metrics': all_metrics,
        }
        if options['json']:
            self.stdout.write(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return
        self.stdout.write(f"Mode: {payload['mode']}")
        self.stdout.write(f"Metric dates: {start:%d-%b-%Y} to {end:%d-%b-%Y}")
        self.stdout.write(f"Metric rows: {len(all_metrics)}")
        if options['apply']:
            self.stdout.write(f'New rows created: {created}')
        if rebuild_days:
            self.stdout.write(f'Rebuild dates processed: {rebuild_days}')
        for item in all_metrics:
            self.stdout.write(
                f"{item['workflow']} {item['stage_key']} {item['branch'] or '-'}: "
                f"{item['active_count']} active, {item['overdue_count']} overdue"
            )
