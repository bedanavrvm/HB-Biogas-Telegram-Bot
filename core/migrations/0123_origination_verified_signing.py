import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0122_origination_workflow_hardening'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='integrationoperation', name='integration',
            field=models.CharField(
                choices=[
                    ('google_sheets', 'Google Sheets'), ('google_drive', 'Google Drive'),
                    ('telegram', 'Telegram'), ('africas_talking', "Africa's Talking"),
                ], db_index=True, max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='originationsigningpackage', name='archive_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='originationsigningpackage', name='archive_status',
            field=models.CharField(
                choices=[('not_ready', 'Not ready'), ('pending', 'Pending'), ('uploaded', 'Uploaded'), ('failed', 'Failed')],
                db_index=True, default='not_ready', max_length=24,
            ),
        ),
        migrations.AddField(
            model_name='originationsigningpackage', name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='originationsigningpackage', name='final_drive_file_id',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='originationsigningpackage', name='finalized_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='originationsigningpackage', name='pending_signed_document',
            field=models.BinaryField(blank=True, default=bytes, editable=False),
        ),
        migrations.AlterField(
            model_name='originationsigningaction', name='actor',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='origination_signing_actions', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name='OriginationSignerSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('signer_role', models.CharField(max_length=80)),
                ('identity_snapshot', models.JSONField(blank=True, default=dict)),
                ('phone_normalized', models.CharField(blank=True, default='', max_length=16)),
                ('phone_hash', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('phone_last4', models.CharField(blank=True, default='', max_length=4)),
                ('token_hash', models.CharField(db_index=True, max_length=64, unique=True)),
                ('token_expires_at', models.DateTimeField(db_index=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('otp_sent', 'OTP sent'), ('verified', 'Verified'), ('locked', 'Locked'), ('expired', 'Expired'), ('cancelled', 'Cancelled')], db_index=True, default='pending', max_length=24)),
                ('access_mode', models.CharField(choices=[('self_service', 'Self service'), ('assisted', 'Assisted by staff')], default='self_service', max_length=24)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('consent_version', models.CharField(blank=True, default='', max_length=32)),
                ('consented_at', models.DateTimeField(blank=True, null=True)),
                ('reviewed_pages', models.JSONField(blank=True, default=list)),
                ('signature_capture', models.JSONField(blank=True, default=dict)),
                ('signature_capture_sha256', models.CharField(blank=True, default='', max_length=64)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('locked_until', models.DateTimeField(blank=True, null=True)),
                ('invalidated_at', models.DateTimeField(blank=True, null=True)),
                ('shared_phone_override_reason', models.TextField(blank=True, default='')),
                ('shared_phone_approved_at', models.DateTimeField(blank=True, null=True)),
                ('request_id', models.CharField(blank=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assisted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='assisted_origination_signer_sessions', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_origination_signer_sessions', to=settings.AUTH_USER_MODEL)),
                ('package', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='signer_sessions', to='core.originationsigningpackage')),
                ('shared_phone_approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='approved_origination_shared_phone_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['package', 'signer_role', '-created_at']},
        ),
        migrations.AddConstraint(
            model_name='originationsignersession',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('package', 'signer_role'), name='one_active_origination_signer_session'),
        ),
        migrations.AddConstraint(
            model_name='originationsignersession',
            constraint=models.UniqueConstraint(condition=models.Q(('request_id', ''), _negated=True), fields=('package', 'request_id'), name='unique_origination_signer_session_request'),
        ),
        migrations.CreateModel(
            name='OriginationOtpChallenge',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code_hash', models.CharField(max_length=255)),
                ('binding_sha256', models.CharField(max_length=64)),
                ('provider_message_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('delivery_status', models.CharField(choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('delivered', 'Delivered'), ('failed', 'Failed'), ('unknown', 'Unknown')], db_index=True, default='pending', max_length=24)),
                ('provider_status', models.CharField(blank=True, default='', max_length=80)),
                ('send_sequence', models.PositiveSmallIntegerField()),
                ('attempts_remaining', models.PositiveSmallIntegerField(default=5)),
                ('request_id', models.CharField(max_length=128)),
                ('source_ip_hash', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('invalidated_at', models.DateTimeField(blank=True, null=True)),
                ('last_attempt_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='otp_challenges', to='core.originationsignersession')),
            ],
            options={'ordering': ['session', '-send_sequence']},
        ),
        migrations.AddConstraint(
            model_name='originationotpchallenge',
            constraint=models.UniqueConstraint(fields=('session', 'send_sequence'), name='unique_origination_otp_sequence'),
        ),
        migrations.AddConstraint(
            model_name='originationotpchallenge',
            constraint=models.UniqueConstraint(fields=('session', 'request_id'), name='unique_origination_otp_request'),
        ),
        migrations.CreateModel(
            name='OriginationSigningRequestEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('action', models.CharField(choices=[('mutate', 'Signer write'), ('send', 'OTP send'), ('verify', 'OTP verification')], db_index=True, max_length=16)),
                ('request_id', models.CharField(blank=True, default='', max_length=128)),
                ('payload_digest', models.CharField(blank=True, default='', max_length=64)),
                ('token_hash', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('source_ip_hash', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='request_events', to='core.originationsignersession')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='originationsigningrequestevent',
            index=models.Index(fields=['action', 'token_hash', 'created_at'], name='core_osre_token_created_idx'),
        ),
        migrations.AddIndex(
            model_name='originationsigningrequestevent',
            index=models.Index(fields=['action', 'source_ip_hash', 'created_at'], name='core_osre_ip_created_idx'),
        ),
        migrations.AddConstraint(
            model_name='originationsigningrequestevent',
            constraint=models.UniqueConstraint(condition=models.Q(('request_id', ''), _negated=True), fields=('session', 'action', 'request_id'), name='unique_origination_signing_request_event'),
        ),
        migrations.AddField(
            model_name='originationsigningaction', name='signer_session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='actions', to='core.originationsignersession'),
        ),
    ]
