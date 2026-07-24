from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
import uuid

from django.db import migrations
import django.utils.timezone


def initialize_case360(apps, schema_editor):
    """Backfill typed values and a non-inferred audit starting point.

    This is separate from 0052 so PostgreSQL commits deferred index creation
    before this function updates the indexed table. Existing migration events
    are skipped, making the backfill safe for databases where the original
    0052 already completed before the migrations were separated.
    """
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    Event = apps.get_model('core', 'JawabuPipelineEvent')
    now = django.utils.timezone.now()
    tracked_farmer_ids = set(
        Event.objects.filter(action='tracking_started', source='migration')
        .values_list('farmer_id', flat=True)
    )
    events = []

    for farmer in Farmer.objects.iterator(chunk_size=500):
        updates = []
        if farmer.hbg_visit_date is None:
            for fmt in ('%Y-%m-%d', '%d-%B-%Y', '%d-%b-%Y', '%d/%m/%Y', '%d/%m/%y'):
                try:
                    farmer.hbg_visit_date = datetime.strptime(
                        str(farmer.sign_date or '').strip(), fmt,
                    ).date()
                    updates.append('hbg_visit_date')
                    break
                except ValueError:
                    continue
        if farmer.deposit_paid_hbg is None:
            try:
                text = re.sub(r'[^0-9.\-]', '', str(farmer.actual_receipts or ''))
                amount = Decimal(text) if text else None
                if amount is not None and amount >= 0:
                    farmer.deposit_paid_hbg = amount.quantize(Decimal('0.01'))
                    updates.append('deposit_paid_hbg')
            except (InvalidOperation, ValueError):
                pass
        if updates:
            farmer.save(update_fields=updates)

        if farmer.id not in tracked_farmer_ids:
            events.append(Event(
                id=uuid.uuid4(), farmer_id=farmer.id,
                action='tracking_started', stage_key='tracking',
                source='migration', occurred_at=now,
                metadata={'historical_transitions_inferred': False},
            ))
        if len(events) >= 500:
            Event.objects.bulk_create(events)
            events = []
    if events:
        Event.objects.bulk_create(events)


class Migration(migrations.Migration):
    dependencies = [('core', '0052_jawabu_case360')]

    operations = [
        migrations.RunPython(initialize_case360, migrations.RunPython.noop),
    ]
