import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0103_portal_voice_language_metadata'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OriginationProductDefinition',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('product_key', models.SlugField(db_index=True, max_length=80)),
                ('name', models.CharField(max_length=160)),
                ('version', models.PositiveIntegerField(default=1)),
                ('form_schema', models.JSONField(default=dict)),
                ('signer_rules', models.JSONField(default=list)),
                ('document_type', models.CharField(max_length=80)),
                ('is_active', models.BooleanField(db_index=True, default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='created_origination_product_definitions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['product_key', '-version']},
        ),
        migrations.CreateModel(
            name='LoanOriginationApplication',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('reference_number', models.CharField(db_index=True, max_length=80, unique=True)),
                ('branch', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('ready_for_review', 'Ready for review'), ('reviewed', 'Reviewed'), ('signing_pending', 'Signing pending'), ('partially_signed', 'Partially signed'), ('fully_signed', 'Fully signed'), ('correction_required', 'Correction required'), ('declined', 'Declined'), ('expired', 'Expired'), ('cancelled', 'Cancelled')], db_index=True, default='draft', max_length=32)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('form_payload', models.JSONField(default=dict)),
                ('schema_snapshot', models.JSONField(default=dict)),
                ('signer_rules_snapshot', models.JSONField(default=list)),
                ('identity_snapshot', models.JSONField(blank=True, default=dict)),
                ('client_request_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='origination_applications', to='core.jawabucustomer')),
                ('officer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='loan_origination_applications', to=settings.AUTH_USER_MODEL)),
                ('product_definition', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='applications', to='core.originationproductdefinition')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reviewed_loan_origination_applications', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at']},
        ),
        migrations.CreateModel(
            name='OriginationApplicationEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(db_index=True, max_length=80)),
                ('revision', models.PositiveIntegerField()),
                ('request_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('before_values', models.JSONField(blank=True, default=dict)),
                ('after_values', models.JSONField(blank=True, default=dict)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('occurred_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='loan_origination_events', to=settings.AUTH_USER_MODEL)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='events', to='core.loanoriginationapplication')),
            ],
            options={'ordering': ['occurred_at', 'id']},
        ),
        migrations.CreateModel(
            name='OriginationSigningPackage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('application_revision', models.PositiveIntegerField()),
                ('external_reference', models.CharField(db_index=True, max_length=80, unique=True)),
                ('document_type', models.CharField(max_length=80)),
                ('template_version', models.PositiveIntegerField(blank=True, null=True)),
                ('context_snapshot', models.JSONField(default=dict)),
                ('participants_snapshot', models.JSONField(default=list)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('in_progress', 'In progress'), ('fully_signed', 'Fully signed'), ('declined', 'Declined'), ('expired', 'Expired'), ('cancelled', 'Cancelled'), ('failed', 'Failed')], db_index=True, default='pending', max_length=24)),
                ('unsigned_document_hash', models.CharField(blank=True, default='', max_length=64)),
                ('signed_document_hash', models.CharField(blank=True, default='', max_length=64)),
                ('final_document_reference', models.TextField(blank=True, default='')),
                ('remote_error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='signing_packages', to='core.loanoriginationapplication')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(model_name='originationproductdefinition', constraint=models.UniqueConstraint(fields=('product_key', 'version'), name='unique_origination_product_version')),
        migrations.AddConstraint(model_name='originationproductdefinition', constraint=models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('product_key',), name='one_active_origination_product_version')),
        migrations.AddIndex(model_name='originationproductdefinition', index=models.Index(fields=['product_key', 'is_active'], name='core_origin_product_67c040_idx')),
        migrations.AddConstraint(model_name='loanoriginationapplication', constraint=models.UniqueConstraint(condition=models.Q(('client_request_id', ''), _negated=True), fields=('officer', 'client_request_id'), name='unique_origination_create_request_per_officer')),
        migrations.AddIndex(model_name='loanoriginationapplication', index=models.Index(fields=['officer', 'status', 'updated_at'], name='core_loanor_officer_3c905e_idx')),
        migrations.AddIndex(model_name='loanoriginationapplication', index=models.Index(fields=['branch', 'status', 'updated_at'], name='core_loanor_branch_8c321c_idx')),
        migrations.AddConstraint(model_name='originationapplicationevent', constraint=models.UniqueConstraint(condition=models.Q(('request_id', ''), _negated=True), fields=('application', 'request_id'), name='unique_origination_event_request')),
        migrations.AddIndex(model_name='originationapplicationevent', index=models.Index(fields=['application', 'occurred_at'], name='core_origin_applica_ea7e72_idx')),
        migrations.AddConstraint(model_name='originationsigningpackage', constraint=models.UniqueConstraint(fields=('application', 'application_revision'), name='one_signing_package_per_origination_revision')),
        migrations.AddIndex(model_name='originationsigningpackage', index=models.Index(fields=['application', 'status', 'updated_at'], name='core_origin_applica_3a6bd3_idx')),
    ]
