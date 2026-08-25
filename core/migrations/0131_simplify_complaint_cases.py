import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


def apply_simplified_capabilities(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    allowed = {
        'OFFICER': {
            'complaint.queue.view', 'complaint.case.create', 'complaint.case.reopen',
            'complaint.case.evidence.view', 'complaint.case.evidence.manage',
        },
        'MANAGER': {
            'complaint.queue.view', 'complaint.case.update', 'complaint.case.close',
            'complaint.case.reopen', 'complaint.case.source.view',
            'complaint.case.evidence.view', 'complaint.case.evidence.manage',
            'complaint.case.sync.retry', 'complaint.case.manage',
        },
        'IT': {'complaint.queue.view', 'complaint.case.sync.retry'},
    }
    known = {
        'complaint.queue.view', 'complaint.case.create', 'complaint.case.update',
        'complaint.case.claim', 'complaint.case.assign', 'complaint.case.close',
        'complaint.case.reopen', 'complaint.case.source.view',
        'complaint.case.evidence.view', 'complaint.case.evidence.manage',
        'complaint.case.sync.retry', 'complaint.case.manage',
    }
    for role, role_allowed in allowed.items():
        for key in known:
            effect = 'allow' if key in role_allowed else 'deny'
            Capability.objects.update_or_create(
                workflow='complaint_cases', role=role, capability_key=key,
                defaults={'effect': effect, 'enabled': effect == 'allow'},
            )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0130_origination_signing_date_actions'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ComplaintCaseImportBatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('group_id', models.CharField(db_index=True, max_length=100)),
                ('source_telegram_message_id', models.CharField(max_length=255)),
                ('actor_label', models.CharField(blank=True, default='', max_length=255)),
                ('telegram_user_id_snapshot', models.CharField(blank=True, default='', max_length=64)),
                ('source_hash', models.CharField(db_index=True, max_length=64)),
                ('status', models.CharField(choices=[('processing', 'Processing'), ('complete', 'Complete'), ('partial', 'Partial'), ('failed', 'Failed')], db_index=True, default='processing', max_length=16)),
                ('source_count', models.PositiveIntegerField(default=0)),
                ('created_count', models.PositiveIntegerField(default=0)),
                ('matched_count', models.PositiveIntegerField(default=0)),
                ('rejected_count', models.PositiveIntegerField(default=0)),
                ('error_count', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('initiated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='complaint_case_import_batches', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at'], 'verbose_name': 'Complaint case import batch', 'verbose_name_plural': 'Complaint case import batches'},
        ),
        migrations.CreateModel(
            name='ComplaintCaseImportItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_index', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='items', to='core.complaintcaseimportbatch')),
                ('parsed_message', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='complaint_import_item', to='core.parsedmessage')),
            ],
            options={'ordering': ['source_index'], 'verbose_name': 'Complaint case import item', 'verbose_name_plural': 'Complaint case import items'},
        ),
        migrations.AddConstraint(
            model_name='complaintcaseimportbatch',
            constraint=models.UniqueConstraint(fields=('group_id', 'source_telegram_message_id'), name='unique_complaint_import_source_message'),
        ),
        migrations.AddConstraint(
            model_name='complaintcaseimportitem',
            constraint=models.UniqueConstraint(fields=('batch', 'source_index'), name='unique_complaint_import_source_index'),
        ),
        migrations.RunPython(apply_simplified_capabilities, migrations.RunPython.noop),
    ]
