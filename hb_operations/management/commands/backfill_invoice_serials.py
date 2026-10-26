"""Recover only serials retained in the current accepted invoice's extraction."""
from django.core.management.base import BaseCommand
from django.db import transaction
from uuid import UUID

from core.models import JawabuFarmerMaster, ParsedInvoice
from core.services.portal_publication import reserve_farmer_publication
from hb_operations.models import HomeBiogasAction
from hb_operations.services import apply_invoice_serial


class Command(BaseCommand):
    help = 'Review retained accepted-invoice serials; --apply queues Master Data publication without contacting Drive or Sheets.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--limit', type=int, default=200)
        parser.add_argument('--after', type=UUID, help='Continue after the last action UUID printed by the previous page.')

    def handle(self, *args, **options):
        from django.core.management.base import CommandError
        if not 1 <= options['limit'] <= 1000:
            raise CommandError('Use a limit between 1 and 1000.')
        counts = {'reviewed': 0, 'recoverable': 0, 'unchanged': 0, 'unresolved': 0}
        actions = HomeBiogasAction.objects.order_by('pk')
        if options['after']:
            actions = actions.filter(pk__gt=options['after'])
        ids = list(actions.values_list('pk', 'farmer_id')[:options['limit']])
        for action_id, farmer_id in ids:
            with transaction.atomic():
                farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer_id)
                invoices = list(ParsedInvoice.objects.select_for_update().filter(
                    matched_farmer=farmer, status='matched', invoice_no=farmer.invoice_number,
                ).select_related('batch')[:2]) if farmer.invoice_number else []
                counts['reviewed'] += 1
                serial = str((invoices[0].raw_payload or {}).get('serial_number') or '').strip() if len(invoices) == 1 else ''
                if not serial or len(serial) > 128:
                    counts['unresolved'] += 1
                    continue
                action = HomeBiogasAction.objects.select_for_update().get(farmer=farmer)
                if action.serial_number == serial:
                    counts['unchanged'] += 1
                    continue
                counts['recoverable'] += 1
                if options['apply']:
                    apply_invoice_serial(farmer, invoices[0])
                    reserve_farmer_publication(farmer,
                        request_id=f'invoice-serial-backfill:{invoices[0].pk}:{invoices[0].revision}',
                        deduplication_namespace='invoice-serial-backfill',
                        requested_by_label='Retained invoice serial backfill')
        self.stdout.write(('Applied' if options['apply'] else 'Dry run') + ': ' + ', '.join(f'{key}={value}' for key, value in counts.items()))
        if ids:
            self.stdout.write(f'Next page: --after {ids[-1][0]}')
