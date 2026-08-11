import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0101_invoice_identity_name_change'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PortalVoiceTranscriptionAttempt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('field_name', models.CharField(choices=[('jbl_visit_comment', 'JBL visit comment'), ('final_decision_comment', 'Final decision after-call comment')], max_length=64)),
                ('request_id', models.CharField(max_length=128)),
                ('audio_hash', models.CharField(db_index=True, max_length=64)),
                ('audio_size', models.PositiveIntegerField(default=0)),
                ('audio_mime_type', models.CharField(blank=True, default='', max_length=80)),
                ('duration_ms', models.PositiveIntegerField(default=0)),
                ('provider', models.CharField(default='groq', max_length=32)),
                ('model_name', models.CharField(default='whisper-large-v3', max_length=80)),
                ('status', models.CharField(choices=[('processing', 'Processing'), ('transcribed', 'Transcribed'), ('accepted', 'Accepted'), ('cancelled', 'Cancelled'), ('failed', 'Failed'), ('expired', 'Expired')], db_index=True, default='processing', max_length=24)),
                ('transcript', models.TextField(blank=True, default='')),
                ('provider_request_id', models.CharField(blank=True, default='', max_length=128)),
                ('drive_file_id', models.CharField(blank=True, default='', max_length=255)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('edit_distance', models.PositiveIntegerField(blank=True, null=True)),
                ('deletion_status', models.CharField(blank=True, db_index=True, default='not_stored', max_length=24)),
                ('deletion_error', models.CharField(blank=True, default='', max_length=255)),
                ('error_code', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('farmer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='voice_transcription_attempts', to='core.jawabufarmermaster')),
                ('source_attempt', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='retries', to='core.portalvoicetranscriptionattempt')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='portal_voice_transcription_attempts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'created_at'], name='portal_voice_user_day_idx'), models.Index(fields=['status', 'expires_at'], name='portal_voice_status_exp_idx'), models.Index(fields=['farmer', 'field_name', 'created_at'], name='portal_voice_case_field_idx')],
                'constraints': [models.UniqueConstraint(fields=('user', 'request_id'), name='unique_portal_voice_request_per_user')],
            },
        ),
    ]
