from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0172_farmup_monthly_worklists'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterField(
            model_name='jawabufarmermaster', name='jbl_visit_status',
            field=models.CharField(blank=True, choices=[
                ('JBL to Schedule Visit', 'JBL to Schedule Visit'),
                ('Visited, Awaiting Credit Analysis', 'Visited, Awaiting Credit Analysis'),
                ('Rescheduled', 'Rescheduled'), ('Deferred / On Hold', 'Deferred / On Hold'),
                ('Rejected by JBL', 'Rejected by JBL'), ('Opted for Cash', 'Opted for Cash'),
                ('Opted for Other Partner', 'Opted for Other Partner'),
            ], db_index=True, default='', help_text='Outcome recorded by the JBL officer after a visit.', max_length=80),
        ),
        migrations.AlterField(
            model_name='jawabufarmermaster', name='credit_decision',
            field=models.CharField(blank=True, choices=[('Approved', 'Approved'), ('Rejected', 'Rejected'), ('Deferred / On Hold', 'Deferred / On Hold')], db_index=True, default='', help_text='Credit Analysis decision from master data dropdown.', max_length=80),
        ),
        migrations.AlterField(
            model_name='jawabufarmermaster', name='final_decision',
            field=models.CharField(blank=True, choices=[('Approved', 'Approved'), ('Rejected', 'Rejected'), ('Deferred / On Hold', 'Deferred / On Hold')], db_index=True, default='', help_text='Head of Rural final decision. Approved records are ready for order batching.', max_length=80),
        ),
        migrations.AddField(model_name='requisitionbatch', name='content_checksum', field=models.CharField(blank=True, default='', max_length=64)),
        migrations.AddField(model_name='requisitionbatch', name='group_configuration', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='requisition_batches', to='core.groupsheetconfiguration')),
        migrations.AddField(model_name='requisitionbatch', name='membership_digest', field=models.CharField(blank=True, default='', max_length=64)),
        migrations.AddField(model_name='requisitionbatch', name='finalization_payload_digest', field=models.CharField(blank=True, default='', max_length=64)),
        migrations.AddField(model_name='requisitionbatch', name='finalized_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='requisitionbatch', name='finalized_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
    ]
