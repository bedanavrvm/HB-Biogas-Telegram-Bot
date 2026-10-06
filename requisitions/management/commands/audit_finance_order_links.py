"""Read-only, customer-free report; never repair historical finance automatically."""
import json
from django.core.management.base import BaseCommand, CommandError
from core.models import GroupSheetConfiguration, JawabuFarmerMaster
from requisitions.services import order_for_farmer, signed_order


class Command(BaseCommand):
    help = 'List finance cases without an exact signed current order; makes no changes.'

    def add_arguments(self, parser):
        parser.add_argument('--configuration', type=int, required=True)

    def handle(self, *args, **options):
        group = GroupSheetConfiguration.objects.filter(pk=options['configuration']).first()
        if not group or (group.workflow or {}).get('type') not in {'jawabu', 'jawabu_homebiogas'}:
            raise CommandError('Choose a saved Portal configuration.')
        issues = []
        for farmer in JawabuFarmerMaster.objects.filter(group_configuration=group).iterator():
            if not farmer.invoice_number and not farmer.payment_batch_memberships.exists():
                continue
            batch = order_for_farmer(farmer)
            if batch and batch.status != 'cancelled' and signed_order(batch):
                continue
            issues.append({'case_id': str(farmer.pk), 'order_id': str(batch.pk) if batch else None,
                'issue': 'unsigned_order' if batch else 'order_link_missing_or_ambiguous'})
        self.stdout.write(json.dumps({'configuration_id': group.pk, 'count': len(issues), 'issues': issues}, indent=2))
