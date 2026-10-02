"""Read-only, group-bounded inventory. Never retries uploads or changes Drive."""
from django.core.management.base import BaseCommand
from core.models import InvoiceUploadBatch


class Command(BaseCommand):
    help = 'List unfinished invoice recovery checkpoints without changing DB or external files.'

    def add_arguments(self, parser):
        parser.add_argument('--group-configuration-id', type=int, required=True)
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        rows = InvoiceUploadBatch.objects.filter(
            group_configuration_id=options['group_configuration_id'], status__in=['uploaded', 'parse_failed'],
        ).order_by('created_at', 'pk')
        self.stdout.write(f'Unfinished uploads: {rows.count()}; read-only inventory')
        for row in rows[:max(1, min(1000, options['limit']))]:
            metadata = row.metadata or {}
            stage = metadata.get('processing_stage') or 'legacy_unknown'
            self.stdout.write(f'{row.pk} status={row.status} stage={stage} '
                              f'file_checkpoint={bool(row.drive_file_id)} partial_rows={row.invoices.count()}')
