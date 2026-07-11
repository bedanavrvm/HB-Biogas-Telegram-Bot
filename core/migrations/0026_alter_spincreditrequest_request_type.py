# Generated for SPIN/CRB request type choices.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_spincreditrequest_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='spincreditrequest',
            name='request_type',
            field=models.CharField(choices=[('spin_crb', 'SPIN/CRB'), ('spin', 'SPIN'), ('crb', 'CRB Report')], db_index=True, max_length=40),
        ),
    ]
