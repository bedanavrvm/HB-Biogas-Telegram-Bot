# Generated for TAT tracker create idempotency.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_tattrackerstaffmember'),
    ]

    operations = [
        migrations.AddField(
            model_name='tattrackercase',
            name='create_request_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
        migrations.AddConstraint(
            model_name='tattrackercase',
            constraint=models.UniqueConstraint(
                condition=~models.Q(create_request_id=''),
                fields=('group_id', 'create_request_id'),
                name='unique_tat_create_request_per_group',
            ),
        ),
    ]
