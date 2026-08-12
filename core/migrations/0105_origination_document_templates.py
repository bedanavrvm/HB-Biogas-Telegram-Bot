import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0104_loan_origination_foundation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OriginationDocumentTemplate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('document_type', models.SlugField(db_index=True, max_length=80)),
                ('name', models.CharField(max_length=180)),
                ('version', models.PositiveIntegerField()),
                ('status', models.CharField(choices=[('ready', 'Ready for review'), ('active', 'Active'), ('retired', 'Retired'), ('upload_failed', 'Upload failed')], db_index=True, default='ready', max_length=24)),
                ('source_filename', models.CharField(max_length=255)),
                ('source_sha256', models.CharField(db_index=True, max_length=64)),
                ('source_byte_size', models.PositiveBigIntegerField()),
                ('page_count', models.PositiveIntegerField()),
                ('placement_config', models.JSONField(default=dict)),
                ('drive_file_id', models.CharField(blank=True, default='', max_length=255)),
                ('drive_url', models.URLField(blank=True, default='', max_length=1000)),
                ('upload_error', models.TextField(blank=True, default='')),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('activated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='activated_origination_document_templates', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_origination_document_templates', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['document_type', '-version']},
        ),
        migrations.CreateModel(
            name='OriginationDocumentTemplateEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(db_index=True, max_length=40)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('occurred_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='origination_document_template_events', to=settings.AUTH_USER_MODEL)),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='events', to='core.originationdocumenttemplate')),
            ],
            options={'ordering': ['occurred_at', 'id']},
        ),
        migrations.AddConstraint(
            model_name='originationdocumenttemplate',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'upload_failed'), _negated=True), fields=('document_type', 'version'), name='unique_origination_document_version'),
        ),
        migrations.AddConstraint(
            model_name='originationdocumenttemplate',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'active')), fields=('document_type',), name='one_active_origination_document'),
        ),
    ]
