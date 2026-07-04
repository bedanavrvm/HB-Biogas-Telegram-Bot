# Generated for FCA exact status dropdown values.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_jawabufarmeruploadbatch'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fcaimportrecord',
            name='fca_decision',
            field=models.CharField(blank=True, db_index=True, default='', max_length=80),
        ),
    ]
