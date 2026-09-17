from datetime import timedelta

from django.db import migrations
from django.utils import timezone


MAX_DEFERRAL_DAYS = 60


def shorten_existing_deferrals(apps, schema_editor):
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    queryset = Farmer.objects.exclude(deferred_at__isnull=True).iterator(chunk_size=500)
    for farmer in queryset:
        policy_date = timezone.localdate(farmer.deferred_at) + timedelta(days=MAX_DEFERRAL_DAYS)
        if farmer.deferred_until is None or farmer.deferred_until > policy_date:
            Farmer.objects.filter(pk=farmer.pk).update(deferred_until=policy_date)


class Migration(migrations.Migration):
    dependencies = [('core', '0179_payment_sequence_operations_access')]

    operations = [
        migrations.RunPython(shorten_existing_deferrals, migrations.RunPython.noop),
    ]
