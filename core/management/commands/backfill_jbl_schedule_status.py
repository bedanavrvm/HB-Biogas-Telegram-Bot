"""Safely label existing HBG-visited cases awaiting a JBL visit."""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import JawabuFarmerMaster
from core.services.jawabu_case360 import record_pipeline_event
from core.services.jawabu_validation import parse_business_date


DEFAULT_STATUS = 'JBL to Schedule Visit'
BACKFILL_ACTION = 'jbl_visit_schedule_backfilled'


def is_schedule_candidate(farmer: JawabuFarmerMaster) -> bool:
    """Return whether a historical record has not yet received a JBL outcome."""
    has_hbg_visit = bool(farmer.hbg_visit_date or parse_business_date(farmer.sign_date))
    return bool(
        has_hbg_visit
        and not farmer.jbl_visit_date
        and not str(farmer.jbl_visit_status or '').strip()
    )


class Command(BaseCommand):
    help = (
        'Preview or backfill the JBL to Schedule Visit status for HBG-visited '
        'records that have no JBL visit or existing JBL outcome. No Sheet/Drive write occurs.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Persist the displayed status changes.')
        parser.add_argument('--run-id', default='', help='Optional auditable run identifier; generated when omitted.')
        parser.add_argument(
            '--revert-run', default='', metavar='RUN_ID',
            help='Safely clear only unchanged statuses written by the named successful run.',
        )
        parser.add_argument('--limit', type=int, default=0, help='Limit candidates for a cautious staged run.')

    def handle(self, *args, **options):
        apply_changes = bool(options['apply'])
        revert_run = str(options['revert_run'] or '').strip()
        if revert_run:
            return self._revert(revert_run, apply_changes)
        return self._backfill(apply_changes, str(options['run_id'] or '').strip(), int(options['limit'] or 0))

    def _backfill(self, apply_changes: bool, requested_run_id: str, limit: int):
        candidates = [
            farmer for farmer in JawabuFarmerMaster.objects.order_by('created_at', 'pk').iterator()
            if is_schedule_candidate(farmer)
        ]
        if limit > 0:
            candidates = candidates[:limit]
        self.stdout.write(f'JBL scheduling candidates: {len(candidates)}')
        for farmer in candidates[:20]:
            self.stdout.write(f'- {farmer.pk}: {farmer.customer_name or "Unnamed customer"}')
        if len(candidates) > 20:
            self.stdout.write(f'... and {len(candidates) - 20} more')
        if not apply_changes:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --apply after reviewing this list.'))
            return

        run_id = requested_run_id or uuid.uuid4().hex
        changed = skipped = 0
        for candidate in candidates:
            with transaction.atomic():
                farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=candidate.pk)
                if not is_schedule_candidate(farmer):
                    skipped += 1
                    continue
                farmer.jbl_visit_status = DEFAULT_STATUS
                farmer.save(update_fields=['jbl_visit_status', 'updated_at'])
                record_pipeline_event(
                    farmer,
                    action=BACKFILL_ACTION,
                    stage_key='jbl_visit',
                    source='system',
                    request_id=f'jbl-schedule-backfill:{run_id}:{farmer.pk}',
                    new_values={'jbl_visit_status': DEFAULT_STATUS},
                    metadata={'backfill_run': run_id, 'reason': 'Historical HBG visit awaiting JBL scheduling.'},
                )
                changed += 1
        self.stdout.write(self.style.SUCCESS(
            f'Backfill run {run_id} applied: {changed} status(es) set; {skipped} record(s) skipped after recheck.'
        ))
        self.stdout.write('No Google Sheets or Drive write was performed. Publish via the normal controlled sync only if approved.')

    def _revert(self, run_id: str, apply_changes: bool):
        event_qs = JawabuFarmerMaster.objects.filter(
            pipeline_events__action=BACKFILL_ACTION,
            pipeline_events__metadata__backfill_run=run_id,
        ).distinct().order_by('pk')
        candidates = list(event_qs)
        self.stdout.write(f'Revert candidates from run {run_id}: {len(candidates)}')
        if not apply_changes:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --apply --revert-run RUN_ID to persist this safe revert.'))
            return

        reverted = skipped = 0
        for candidate in candidates:
            with transaction.atomic():
                farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=candidate.pk)
                if farmer.jbl_visit_date or farmer.jbl_visit_status != DEFAULT_STATUS:
                    skipped += 1
                    continue
                farmer.jbl_visit_status = ''
                farmer.save(update_fields=['jbl_visit_status', 'updated_at'])
                record_pipeline_event(
                    farmer,
                    action='jbl_visit_schedule_backfill_reverted',
                    stage_key='jbl_visit',
                    source='system',
                    request_id=f'jbl-schedule-backfill-revert:{run_id}:{farmer.pk}',
                    old_values={'jbl_visit_status': DEFAULT_STATUS},
                    new_values={'jbl_visit_status': ''},
                    metadata={'backfill_run': run_id, 'reason': 'Safe revert of unchanged JBL scheduling default.'},
                )
                reverted += 1
        self.stdout.write(self.style.SUCCESS(f'Run {run_id}: {reverted} status(es) cleared; {skipped} changed record(s) protected.'))
