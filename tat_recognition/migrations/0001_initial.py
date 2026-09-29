from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='TatRecognitionPeriodSnapshot',
            fields=[
                ('id', models.BigAutoField(db_comment='Immutable final recognition snapshot identifier.', primary_key=True, serialize=False)),
                ('group_id', models.CharField(db_comment='TAT group whose settled results were captured.', max_length=100)),
                ('scope_key', models.CharField(db_comment='Production or active Pilot cycle at capture time.', max_length=64)),
                ('period_kind', models.CharField(db_comment='Month, quarter, or year aggregation.', max_length=8)),
                ('period_key', models.CharField(db_comment='Canonical YYYY-MM, YYYY-QN, or YYYY period.', max_length=12)),
                ('facts', models.JSONField(db_comment='Frozen stage facts for period actions and qualifying branch cases; contains staff identity and is never sent directly to clients.')),
                ('captured_at', models.DateTimeField(auto_now_add=True, db_comment='Time the first eligible request froze this period.')),
            ],
            options={'db_table': 'tat_recognition_period_snapshot', 'db_table_comment': 'Immutable final TAT recognition facts; current access is checked before any projection.'},
        ),
        migrations.AddConstraint(
            model_name='tatrecognitionperiodsnapshot',
            constraint=models.UniqueConstraint(fields=('group_id', 'scope_key', 'period_kind', 'period_key'), name='unique_tat_recognition_period_snapshot'),
        ),
    ]
