from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0032_tat_tracker_approval_certificates'),
    ]

    operations = [
        migrations.AddField(
            model_name='tattrackercase',
            name='national_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='tattrackercase',
            name='primary_phone',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
    ]