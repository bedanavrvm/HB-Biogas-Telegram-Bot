import uuid

import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone


def allow_legacy_manual_drafts(apps, schema_editor):
    Batch = apps.get_model('core', 'InvoiceNameChangeBatch')
    Batch.objects.filter(status='draft').update(legacy_manual_letter_allowed=True)


class Migration(migrations.Migration):

    dependencies = [('core', '0115_portal_access_control_hardening')]

    operations = [
        migrations.CreateModel(
            name='InvoiceNameChangeLetterTemplate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('template_key', models.CharField(default='invoice_name_change', editable=False, max_length=64)),
                ('name', models.CharField(default='Request for Change of Invoice Names', max_length=255)),
                ('file', models.FileField(help_text='Upload a validated Microsoft Word (.docx) letter template.', upload_to='invoice_name_change_templates/')),
                ('original_filename', models.CharField(blank=True, default='', max_length=255)),
                ('content_type', models.CharField(default='application/vnd.openxmlformats-officedocument.wordprocessingml.document', max_length=255)),
                ('size', models.PositiveIntegerField(default=0)),
                ('checksum', models.CharField(blank=True, default='', max_length=64)),
                ('drive_file_id', models.CharField(blank=True, default='', max_length=255)),
                ('drive_url', models.URLField(blank=True, default='', max_length=1000)),
                ('drive_uploaded_at', models.DateTimeField(blank=True, null=True)),
                ('drive_upload_error', models.TextField(blank=True, default='')),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Invoice name change letter template',
                'verbose_name_plural': 'Invoice name change letter templates',
                'ordering': ['-is_active', '-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='InvoiceNameChangeLetterArtifact',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version', models.PositiveIntegerField()),
                ('status', models.CharField(choices=[('generated', 'Generated'), ('upload_failed', 'Drive upload failed')], db_index=True, default='generated', max_length=24)),
                ('filename', models.CharField(max_length=255)),
                ('content_type', models.CharField(default='application/vnd.openxmlformats-officedocument.wordprocessingml.document', max_length=255)),
                ('file_content', models.BinaryField(blank=True, default=bytes)),
                ('checksum', models.CharField(max_length=64)),
                ('template_checksum', models.CharField(max_length=64)),
                ('source_fingerprint', models.CharField(db_index=True, max_length=64)),
                ('payload_snapshot', models.JSONField(default=dict)),
                ('generated_by', models.CharField(max_length=255)),
                ('generated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('client_request_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('drive_file_id', models.CharField(blank=True, default='', max_length=255)),
                ('drive_url', models.URLField(blank=True, default='', max_length=1000)),
                ('drive_upload_error', models.TextField(blank=True, default='')),
                ('drive_sync_attempts', models.PositiveIntegerField(default=0)),
                ('drive_last_sync_at', models.DateTimeField(blank=True, null=True)),
                ('drive_next_retry_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='letter_artifacts', to='core.invoicenamechangebatch')),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='generated_artifacts', to='core.invoicenamechangelettertemplate')),
            ],
            options={
                'verbose_name': 'Invoice name change letter artifact',
                'verbose_name_plural': 'Invoice name change letter artifacts',
                'ordering': ['-version', '-created_at'],
            },
        ),
        migrations.AddField(
            model_name='invoicenamechangebatch', name='legacy_manual_letter_allowed',
            field=models.BooleanField(default=False, help_text='Migration-only compatibility for draft letters created before governed DOCX generation.'),
        ),
        migrations.AddField(
            model_name='invoicenamechangebatch', name='sent_artifact',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='sent_for_batches', to='core.invoicenamechangeletterartifact'),
        ),
        migrations.AddConstraint(
            model_name='invoicenamechangelettertemplate',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('template_key',), name='unique_active_invoice_name_change_template'),
        ),
        migrations.AddConstraint(
            model_name='invoicenamechangeletterartifact',
            constraint=models.UniqueConstraint(fields=('batch', 'version'), name='unique_invoice_name_change_letter_version'),
        ),
        migrations.AddConstraint(
            model_name='invoicenamechangeletterartifact',
            constraint=models.UniqueConstraint(condition=~models.Q(('client_request_id', '')), fields=('batch', 'client_request_id'), name='unique_invoice_name_change_letter_request'),
        ),
        migrations.RunPython(allow_legacy_manual_drafts, migrations.RunPython.noop),
    ]
