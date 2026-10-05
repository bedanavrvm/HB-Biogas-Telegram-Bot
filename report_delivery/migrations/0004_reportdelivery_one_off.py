import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def guard_reverse(apps, schema_editor):
    if apps.get_model('report_delivery', 'ReportDelivery').objects.filter(schedule__isnull=True).exists():
        raise RuntimeError('One-off delivery evidence exists. Restore the pre-release backup or retain this additive schema; rollback will not delete delivery evidence automatically.')


class Migration(migrations.Migration):
    dependencies = [
        ('report_delivery', '0003_remove_approvedrecipient_report_recipient_scope_unique_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name='reportdelivery', name='destination', field=models.EmailField(blank=True, db_comment='One-off email destination, retained with delivery evidence for 180 days; never grants recurring recipient approval.', max_length=254)),
        migrations.AddField(model_name='reportdelivery', name='requested_by', field=models.ForeignKey(blank=True, db_comment='One-off export actor; deletion revokes unsent delivery authority.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='requested_report_deliveries', to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name='reportdelivery', name='recipient', field=models.ForeignKey(blank=True, db_comment='Approved scheduled recipient; null for a one-off destination.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='deliveries', to='report_delivery.approvedrecipient')),
        migrations.AlterField(model_name='reportdelivery', name='schedule', field=models.ForeignKey(blank=True, db_comment='Recurring schedule; null for an independently authorized one-off export.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='deliveries', to='report_delivery.reportschedule')),
        migrations.AddConstraint(model_name='reportdelivery', constraint=models.UniqueConstraint(condition=models.Q(schedule__isnull=True), fields=('requested_by', 'occurrence'), name='report_oneoff_request_unique')),
        migrations.AddConstraint(model_name='reportdelivery', constraint=models.CheckConstraint(condition=(models.Q(schedule__isnull=False, recipient__isnull=False, destination='') | (models.Q(schedule__isnull=True, recipient__isnull=True) & ~models.Q(destination=''))), name='report_delivery_kind_valid')),
        migrations.RunPython(migrations.RunPython.noop, guard_reverse),
    ]
