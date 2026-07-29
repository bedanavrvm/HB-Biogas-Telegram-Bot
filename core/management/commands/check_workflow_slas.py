"""Preview or record overdue workflow-stage escalations without notifications."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from core.services.workflow_sla import collect_sla_candidates, record_sla_candidates


class Command(BaseCommand):
    help = 'Preview overdue Jawabu/TAT workflow stages; --apply records pending follow-up only.'

    def add_arguments(self, parser):
        parser.add_argument('--workflow', choices=['all', 'jawabu_pipeline', 'tat_tracker'], default='all')
        parser.add_argument('--apply', action='store_true', help='Create idempotent pending escalation records; never sends notifications.')
        parser.add_argument('--json', action='store_true', help='Emit machine-readable candidates.')

    def handle(self, *args, **options):
        workflow = options['workflow']
        candidates = collect_sla_candidates(workflow=workflow)
        payload = [item.payload() for item in candidates]
        if options['apply']:
            _records, created = record_sla_candidates(candidates)
        else:
            created = 0
        if options['json']:
            self.stdout.write(json.dumps({
                'mode': 'apply' if options['apply'] else 'dry_run',
                'workflow': workflow,
                'candidate_count': len(payload),
                'created_count': created,
                'candidates': payload,
            }, indent=2, sort_keys=True))
            return
        self.stdout.write(f"Mode: {'apply' if options['apply'] else 'dry-run'}")
        self.stdout.write(f'Overdue stages: {len(payload)}')
        if options['apply']:
            self.stdout.write(f'Pending follow-up records created: {created}')
        for item in payload:
            self.stdout.write(
                f"{item['workflow']} {item['subject_id']} {item['stage_key']}: "
                f"{item['overdue_minutes']} minutes overdue "
                f"({item['threshold_percent']}% -> {item['routing_role']})"
            )
