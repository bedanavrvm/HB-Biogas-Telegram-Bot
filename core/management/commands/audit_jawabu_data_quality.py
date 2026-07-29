import json

from django.core.management.base import BaseCommand, CommandError

from core.models import JawabuFarmerUploadBatch
from core.services.jawabu_data_quality import (
    active_jawabu_quality_report,
    system_export_batch_quality_report,
)


class Command(BaseCommand):
    help = 'Report active Jawabu and optional staged /sysup data-quality findings; never writes data.'

    def add_arguments(self, parser):
        parser.add_argument('--batch', help='Optional staged JawabuFarmerUploadBatch UUID for /sysup review reporting.')
        parser.add_argument('--limit', type=int, default=100, help='Maximum active-case findings to print.')
        parser.add_argument('--strict', action='store_true', help='Exit non-zero when any finding remains.')

    def handle(self, *args, **options):
        report = {'active_jawabu': active_jawabu_quality_report(limit=max(1, options['limit']))}
        if options['batch']:
            batch = JawabuFarmerUploadBatch.objects.filter(pk=options['batch']).first()
            if not batch:
                raise CommandError('Upload batch was not found.')
            if batch.import_kind != 'system_export':
                raise CommandError('The selected batch is not a /sysup system-export batch.')
            report['system_export_batch'] = system_export_batch_quality_report(batch)
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True, default=str))
        if options['strict'] and report['active_jawabu']['finding_count']:
            raise CommandError('Active Jawabu data-quality findings remain.')
