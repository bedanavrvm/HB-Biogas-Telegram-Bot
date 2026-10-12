from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('report_delivery', '0004_reportdelivery_one_off')]
    operations = [migrations.AlterField(
        model_name='reportschedule', name='preset',
        field=models.CharField(max_length=12, choices=[('pipeline', 'Pipeline'), ('outcomes', 'Outcomes'),
            ('finance', 'Finance'), ('tat', 'Tat'), ('complaints', 'Summary'),
            ('cmp_tat', 'Turnaround performance'), ('cmp_open', 'Open-case follow-up')],
            db_comment='Allowlisted report preset for the owning workflow.'),
    )]
