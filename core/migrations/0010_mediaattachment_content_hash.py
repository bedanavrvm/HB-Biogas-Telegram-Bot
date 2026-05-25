from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_orderapprovalupdate_mediaattachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediaattachment',
            name='content_hash',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
    ]
