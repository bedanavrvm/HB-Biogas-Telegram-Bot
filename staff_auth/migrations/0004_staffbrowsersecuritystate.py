from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('staff_auth', '0003_staffbrowsersetupgrant')]
    operations = [migrations.CreateModel(
        name='StaffBrowserSecurityState',
        fields=[
            ('key_digest', models.CharField(primary_key=True, max_length=64, editable=False, serialize=False,
                db_comment='Purpose-separated HMAC of a pinned native authentication key; no raw identity or code.')),
            ('payload', models.JSONField(db_comment='Bounded native timestamp history or opaque lease/use marker; no pickle or credential.')),
            ('expires_at', models.DateTimeField(db_comment='Database-clock expiry. Live rows must never be globally cleared or culled.')),
        ],
        options={
            'db_table':'staff_auth_browser_security_state',
            'db_table_comment':'PostgreSQL-only shared native browser security cache; temporary state, never login assurance or workflow authority.',
            'indexes':[models.Index(fields=['expires_at'], name='staff_security_expiry_idx')],
        },
    )]
