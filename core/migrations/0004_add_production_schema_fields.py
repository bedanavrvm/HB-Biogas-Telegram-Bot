# Generated migration for production schema

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_parsedmessage_complaint_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='parsedmessage',
            name='branch_region',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='parsedmessage',
            name='loan_status',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='parsedmessage',
            name='loan_at_risk',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
