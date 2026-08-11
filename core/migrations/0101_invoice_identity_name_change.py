import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def seed_invoice_identity_capability(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    Capability.objects.update_or_create(
        workflow='jawabu_portal',
        role='OPERATIONS_ADMIN',
        capability_key='portal.invoice_identity.manage',
        defaults={'effect': 'allow'},
    )


def unseed_invoice_identity_capability(apps, schema_editor):
    apps.get_model('core', 'WorkflowRoleCapability').objects.filter(
        workflow='jawabu_portal', role='OPERATIONS_ADMIN',
        capability_key='portal.invoice_identity.manage',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0100_portal_import_working_list_archival')]

    operations = [
        migrations.AlterField(
            model_name='parsedinvoice', name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('unmatched', 'Unmatched'), ('matched', 'Matched'), ('ambiguous', 'Ambiguous'), ('ignored', 'Ignored'), ('superseded', 'Superseded')], db_index=True, default='unmatched', max_length=32),
        migrations.CreateModel(
            name='InvoiceIdentityReview',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('pending', 'Pending verification'), ('same_person_confirmed', 'Same person confirmed'), ('different_person_confirmed', 'Different person confirmed'), ('insufficient_information', 'Insufficient information'), ('cancelled', 'Cancelled')], db_index=True, default='pending', max_length=40)),
                ('discrepancy_codes', models.JSONField(blank=True, default=list)),
                ('invoice_identity', models.JSONField(blank=True, default=dict)),
                ('applicant_identity', models.JSONField(blank=True, default=dict)),
                ('decision_note', models.TextField(blank=True, default='')),
                ('decided_by', models.CharField(blank=True, default='', max_length=255)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('client_request_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('farmer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoice_identity_reviews', to='core.jawabufarmermaster')),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='identity_reviews', to='core.parsedinvoice')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='JawabuRelatedPerson',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('full_name', models.CharField(max_length=255)),
                ('national_id', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('primary_phone', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('source', models.CharField(blank=True, default='operations_verification', max_length=255)),
                ('created_by', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('linked_customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='related_person_profiles', to='core.jawabucustomer')),
            ],
        ),
        migrations.CreateModel(
            name='InvoiceNameChangeBatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('reference', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('sent_to_hb', 'Sent to HB'), ('awaiting_replacements', 'Awaiting replacements'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], db_index=True, default='draft', max_length=32)),
                ('letter_file_reference', models.CharField(blank=True, default='', max_length=1000)),
                ('letter_checksum', models.CharField(blank=True, default='', max_length=128)),
                ('sent_reference', models.CharField(blank=True, default='', max_length=255)),
                ('created_by', models.CharField(max_length=255)),
                ('sent_by', models.CharField(blank=True, default='', max_length=255)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('client_request_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ], options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='JawabuHouseholdRelationship',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('relationship_type', models.CharField(choices=[('spouse', 'Spouse'), ('household_member', 'Household member')], default='spouse', max_length=32)),
                ('status', models.CharField(choices=[('confirmed', 'Confirmed'), ('revoked', 'Revoked')], db_index=True, default='confirmed', max_length=16)),
                ('attestation_note', models.TextField()),
                ('evidence_reference', models.CharField(max_length=1000)),
                ('confirmed_by', models.CharField(max_length=255)),
                ('confirmed_at', models.DateTimeField(default=timezone.now)),
                ('revoked_by', models.CharField(blank=True, default='', max_length=255)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('revocation_reason', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('farmer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='household_relationships', to='core.jawabufarmermaster')),
                ('related_person', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='relationships', to='core.jawaburelatedperson')),
            ],
        ),
        migrations.CreateModel(
            name='InvoiceNameChangeItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('awaiting_replacement', 'Awaiting replacement'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], db_index=True, default='draft', max_length=32)),
                ('original_identity', models.JSONField(blank=True, default=dict)),
                ('requested_identity', models.JSONField(blank=True, default=dict)),
                ('completed_by', models.CharField(blank=True, default='', max_length=255)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='items', to='core.invoicenamechangebatch')),
                ('farmer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='invoice_name_changes', to='core.jawabufarmermaster')),
                ('original_invoice', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='name_change_requests', to='core.parsedinvoice')),
                ('relationship', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='invoice_name_changes', to='core.jawabuhouseholdrelationship')),
                ('replacement_invoice', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='replacement_for_name_changes', to='core.parsedinvoice')),
                ('review', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='name_change_item', to='core.invoiceidentityreview')),
            ],
        ),
        migrations.AddConstraint(model_name='invoiceidentityreview', constraint=models.UniqueConstraint(condition=models.Q(status='pending'), fields=('invoice',), name='unique_pending_invoice_identity_review')),
        migrations.AddConstraint(model_name='invoiceidentityreview', constraint=models.UniqueConstraint(condition=~models.Q(client_request_id=''), fields=('client_request_id',), name='unique_invoice_identity_review_request')),
        migrations.AddConstraint(model_name='invoicenamechangebatch', constraint=models.UniqueConstraint(condition=~models.Q(client_request_id=''), fields=('client_request_id',), name='unique_invoice_name_change_batch_request')),
        migrations.AddConstraint(model_name='jawabuhouseholdrelationship', constraint=models.UniqueConstraint(condition=models.Q(status='confirmed'), fields=('farmer', 'related_person', 'relationship_type'), name='unique_confirmed_household_relationship')),
        migrations.AddConstraint(model_name='invoicenamechangeitem', constraint=models.UniqueConstraint(condition=models.Q(status__in=['draft', 'awaiting_replacement']), fields=('original_invoice',), name='unique_open_invoice_name_change')),
        migrations.RunPython(seed_invoice_identity_capability, unseed_invoice_identity_capability),
    ]
