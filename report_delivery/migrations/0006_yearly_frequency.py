from datetime import time

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('report_delivery', '0005_alter_reportschedule_preset')]
    operations = [
        migrations.AlterField(
            model_name='reportschedule', name='frequency',
            field=models.CharField(max_length=12, default='daily',
                choices=[(value, value.title()) for value in ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')],
                db_comment='Completed Nairobi calendar period cadence.'),
        ),
        migrations.AlterField(
            model_name='reportschedule', name='send_time',
            field=models.TimeField(default=time(8),
                db_comment='Nairobi local dispatch time; Monday weekly, day one monthly/quarterly, January 1 yearly.'),
        ),
    ]
