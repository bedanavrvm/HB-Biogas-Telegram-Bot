from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0049_jawabu_customer_units_and_deferrals')]
    operations = [
        migrations.AddField(model_name='invoiceuploadbatch', name='order_number', field=models.CharField(blank=True, db_index=True, default='', max_length=128)),
        migrations.AddField(model_name='invoiceuploadbatch', name='sync_status', field=models.CharField(blank=True, db_index=True, default='', max_length=32)),
        migrations.AddField(model_name='invoiceuploadbatch', name='sync_error', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='parsedinvoice', name='proposed_farmer', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='proposed_invoices', to='core.jawabufarmermaster')),
        migrations.AddField(model_name='parsedinvoice', name='proposed_order_number', field=models.CharField(blank=True, db_index=True, default='', max_length=128)),
        migrations.AlterField(model_name='invoiceuploadbatch', name='status', field=models.CharField(choices=[('uploaded', 'Uploaded'), ('awaiting_confirmation', 'Awaiting Confirmation'), ('parsed', 'Parsed'), ('parse_failed', 'Parse Failed'), ('partially_matched', 'Partially Matched'), ('matched', 'Matched'), ('needs_review', 'Needs Review')], db_index=True, default='uploaded', max_length=32)),
        migrations.AlterField(model_name='parsedinvoice', name='status', field=models.CharField(choices=[('draft', 'Draft'), ('unmatched', 'Unmatched'), ('matched', 'Matched'), ('ambiguous', 'Ambiguous'), ('ignored', 'Ignored')], db_index=True, default='unmatched', max_length=32)),
    ]
