from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [('core', '0131_simplify_complaint_cases')]

    operations = [
        migrations.AlterField(
            model_name='invoiceidentityreview', name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending verification'),
                    ('same_person_confirmed', 'Same person confirmed'),
                    ('different_person_confirmed', 'Different person confirmed'),
                    ('insufficient_information', 'Insufficient information'),
                    ('flagged_for_review', 'Flagged for specialist review'),
                    ('cancelled', 'Cancelled'),
                ], default='pending', max_length=40, db_index=True,
            ),
        ),
        migrations.AddField(model_name='invoicenamechangebatch', name='revision', field=models.PositiveIntegerField(default=1)),
        migrations.AlterField(
            model_name='invoicenamechangebatch', name='status',
            field=models.CharField(
                choices=[('draft', 'Draft'), ('sent_to_hb', 'Sent to HB'), ('awaiting_replacements', 'Awaiting replacements'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('withdrawn', 'Withdrawn')],
                default='draft', max_length=32, db_index=True,
            ),
        ),
        migrations.AddField(model_name='invoicenamechangeitem', name='client_request_id', field=models.CharField(blank=True, default='', max_length=128, db_index=True)),
        migrations.AddField(model_name='invoicenamechangeitem', name='closed_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='invoicenamechangeitem', name='closed_by', field=models.CharField(blank=True, default='', max_length=255)),
        migrations.AddField(model_name='invoicenamechangeitem', name='closed_reason', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='invoicenamechangeitem', name='follow_up_of', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='follow_ups', to='core.invoicenamechangeitem')),
        migrations.AddField(model_name='invoicenamechangeitem', name='hb_communication_reference', field=models.CharField(blank=True, default='', max_length=255)),
        migrations.AddField(model_name='invoicenamechangeitem', name='revision', field=models.PositiveIntegerField(default=1)),
        migrations.AlterField(
            model_name='invoicenamechangeitem', name='batch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='items', to='core.invoicenamechangebatch'),
        ),
        migrations.AlterField(
            model_name='invoicenamechangeitem', name='status',
            field=models.CharField(
                choices=[('draft', 'Draft'), ('awaiting_replacement', 'Awaiting replacement'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('withdrawn', 'Withdrawn')],
                default='draft', max_length=32, db_index=True,
            ),
        ),
        migrations.AddConstraint(
            model_name='invoicenamechangeitem',
            constraint=models.UniqueConstraint(condition=~models.Q(client_request_id=''), fields=('client_request_id',), name='unique_invoice_name_change_item_request'),
        ),
    ]
