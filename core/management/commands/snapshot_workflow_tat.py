"""Preview or persist the current-day internal TAT trend projection."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.services.workflow_sla import collect_tat_daily_metrics, record_tat_daily_metrics


class Command(BaseCommand):
    help = 'Preview current-day Jawabu/TAT SLA trend metrics; --apply writes idempotent internal snapshots only.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Upsert daily metric snapshots; never notifies, syncs, or changes case state.')
        parser.add_argument('--json', action='store_true', help='Emit machine-readable metric rows.')

    def handle(self, *args, **options):
        metric_date = timezone.localdate()
        metrics = collect_tat_daily_metrics(metric_date=metric_date)
        if options['apply']:
            _records, created = record_tat_daily_metrics(metrics, metric_date=metric_date)
        else:
            created = 0
        payload = {
            'mode': 'apply' if options['apply'] else 'dry_run',
            'metric_date': metric_date.isoformat(),
            'metric_count': len(metrics),
            'created_count': created,
            'metrics': metrics,
        }
        if options['json']:
            self.stdout.write(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return
        self.stdout.write(f"Mode: {payload['mode']}")
        self.stdout.write(f"Metric date: {metric_date:%d-%b-%Y}")
        self.stdout.write(f"Metric rows: {len(metrics)}")
        if options['apply']:
            self.stdout.write(f'New rows created: {created}')
        for item in metrics:
            self.stdout.write(
                f"{item['workflow']} {item['stage_key']} {item['branch'] or '-'}: "
                f"{item['active_count']} active, {item['overdue_count']} overdue"
            )
