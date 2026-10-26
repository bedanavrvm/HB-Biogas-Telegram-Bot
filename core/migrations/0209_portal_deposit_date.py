from datetime import date
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import migrations, models


def backfill_dates(apps, schema_editor):
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    Event = apps.get_model('core', 'JawabuPipelineEvent')
    database = schema_editor.connection.alias
    for farmer in Farmer.objects.using(database).filter(hb_deposit_date__isnull=True).iterator(chunk_size=200):
        try:
            current = Decimal(str(farmer.deposit_paid_hbg if farmer.deposit_paid_hbg is not None else farmer.actual_receipts).replace(',', ''))
        except (InvalidOperation, ValueError):
            continue
        if not current.is_finite():
            continue
        events = Event.objects.using(database).filter(farmer_id=farmer.pk, action__in=[
            'hb_deposit_updated', 'application_imported', 'application_updated', 'office_lead_saved_on_deposit_hold',
        ]).order_by('-occurred_at', '-pk')
        for event in events:
            before = (event.old_values or {}).get('deposit_paid_hbg')
            after = (event.new_values or {}).get('deposit_paid_hbg')
            if after in (None, '') or before == after:
                continue
            try:
                if Decimal(str(after)) != current:
                    break
                if before not in (None, '') and Decimal(str(before)) == current:
                    continue
            except InvalidOperation:
                break
            if 'deposit_paid_hbg' not in (event.old_values or {}) and event.action not in {'application_imported', 'office_lead_saved_on_deposit_hold'}:
                continue
            retained = (event.new_values or {}).get('hb_deposit_date')
            initial = event.action == 'application_imported' and before in (None, '')
            try:
                if initial:
                    retained = retained or (event.new_values or {}).get('hbg_visit_date')
                if retained:
                    value = date.fromisoformat(retained)
                else:
                    value = None if initial else event.occurred_at.astimezone(ZoneInfo('Africa/Nairobi')).date()
            except (TypeError, ValueError):
                break
            if value:
                Farmer.objects.using(database).filter(pk=farmer.pk, hb_deposit_date__isnull=True).update(hb_deposit_date=value)
            break


class Migration(migrations.Migration):
    dependencies = [('core', '0208_hb_deposit_capabilities')]
    operations = [
        migrations.AddField(
            model_name='jawabufarmermaster', name='hb_deposit_date',
            field=models.DateField(null=True, blank=True, db_comment='Initial FarmUp visit date or Nairobi date of the latest accepted HB deposit change; prior dates remain in audit history.'),
        ),
        migrations.RunPython(backfill_dates, migrations.RunPython.noop),
    ]
