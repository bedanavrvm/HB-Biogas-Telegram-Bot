from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0148_miniapp_legacy_write_aggregate'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderapprovalupdate',
            name='client_request_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='orderapprovalupdate',
            name='request_fingerprint',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='orderapprovalupdate',
            name='response_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name='orderapprovalupdate',
            constraint=models.UniqueConstraint(
                condition=models.Q(('client_request_id', ''), _negated=True),
                fields=('group_id', 'client_request_id'),
                name='unique_order_approval_client_request',
            ),
        ),
    ]
