import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0140_repair_origination_availability_channel'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffLifecycleChangePlan',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(choices=[('onboard', 'Onboard staff'), ('access_change', 'Change role or scope'), ('transfer', 'Transfer staff'), ('leave', 'Temporary leave'), ('return', 'Return from leave'), ('offboard', 'Immediate offboarding'), ('telegram_identity_reset', 'Reset Telegram identity')], db_index=True, max_length=32)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('pending', 'Pending independent approval'), ('scheduled', 'Approved and scheduled'), ('applied', 'Applied'), ('rejected', 'Rejected'), ('stale', 'Stale'), ('cancelled', 'Cancelled'), ('failed', 'Failed')], db_index=True, default='draft', max_length=16)),
                ('before_snapshot', models.JSONField(blank=True, default=dict)),
                ('proposed_snapshot', models.JSONField(blank=True, default=dict)),
                ('impact', models.JSONField(blank=True, default=dict)),
                ('expected_policy_version', models.PositiveIntegerField(default=1)),
                ('reason', models.TextField()),
                ('request_key', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('requested_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('effective_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_comment', models.TextField(blank=True, default='')),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('error', models.CharField(blank=True, default='', max_length=500)),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='requested_staff_lifecycle_plans', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reviewed_staff_lifecycle_plans', to=settings.AUTH_USER_MODEL)),
                ('target_user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='staff_lifecycle_plans', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-requested_at']},
        ),
        migrations.CreateModel(
            name='TelegramStaffActivation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code_digest', models.CharField(max_length=128)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('failed_attempts', models.PositiveSmallIntegerField(default=0)),
                ('consumed_at', models.DateTimeField(blank=True, null=True)),
                ('invalidated_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_telegram_staff_activations', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='telegram_staff_activations', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='stafflifecyclechangeplan',
            constraint=models.UniqueConstraint(condition=models.Q(('status__in', ['draft', 'pending', 'scheduled'])), fields=('target_user',), name='unique_open_staff_lifecycle_plan'),
        ),
        migrations.AddConstraint(
            model_name='stafflifecyclechangeplan',
            constraint=models.UniqueConstraint(condition=models.Q(('request_key', ''), _negated=True), fields=('requested_by', 'request_key'), name='unique_staff_lifecycle_request_key'),
        ),
        migrations.AddIndex(
            model_name='telegramstaffactivation',
            index=models.Index(fields=['user', 'expires_at'], name='core_telegr_user_id_3a1f99_idx'),
        ),
    ]
