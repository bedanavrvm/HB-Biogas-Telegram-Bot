from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0147_tat_presentation_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='MiniAppLegacyWriteDailyAggregate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True)),
                ('route_name', models.CharField(db_index=True, max_length=100)),
                ('method', models.CharField(max_length=8)),
                ('outcome', models.CharField(choices=[('accepted', 'Accepted during compatibility window'), ('rejected', 'Rejected by strict mode')], db_index=True, max_length=16)),
                ('request_count', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Mini App legacy-write daily aggregate',
                'verbose_name_plural': 'Mini App legacy-write daily aggregates',
                'ordering': ['-date', 'route_name', 'method', 'outcome'],
            },
        ),
        migrations.AddConstraint(
            model_name='miniapplegacywritedailyaggregate',
            constraint=models.UniqueConstraint(fields=('date', 'route_name', 'method', 'outcome'), name='unique_miniapp_legacy_write_daily_rollup'),
        ),
    ]
