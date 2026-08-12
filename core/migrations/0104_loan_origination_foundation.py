import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


PARTNERSHIP_LAF_FIELDS = (
    'acknowledgement_amount', 'acknowledgement_recipient_name', 'amount_advanced',
    'applicant_dob', 'applicant_email', 'applicant_first_name', 'applicant_id_number',
    'applicant_middle_name', 'applicant_next_of_kin', 'applicant_next_of_kin_id',
    'applicant_next_of_kin_phone', 'applicant_other_phone', 'applicant_phone',
    'applicant_postal_address', 'applicant_postal_code', 'applicant_residence_address',
    'applicant_surname', 'applicant_town', 'approval_amount', 'borrower_full_name',
    'branch_manager_name', 'bro_1_name', 'bro_2_name', 'business_location', 'business_type',
    'commissioner_location', 'commissioner_oath_day', 'commissioner_oath_month',
    'commissioner_oath_year', 'deponent_full_name', 'deponent_id_number',
    'employer_business_address', 'guarantor_1_business_location', 'guarantor_1_employer',
    'guarantor_1_id_number', 'guarantor_1_name', 'guarantor_1_phone',
    'guarantor_1_relationship', 'guarantor_1_residence_location', 'guarantor_1_years_known',
    'guarantor_2_id_number', 'guarantor_2_name', 'guarantor_2_phone',
    'guarantor_2_relationship', 'installment_amount', 'interest_rate',
    'loan_agreement_repayment_period', 'loan_amount', 'loan_product', 'loan_product_other',
    'loan_purpose', 'monthly_expenses', 'monthly_household_expenses', 'monthly_income',
    'net_income', 'number_of_weeks', 'own_contribution', 'penalty_rate', 'project_cost',
    'repayment_period', 'security_1_current_value', 'security_1_description',
    'security_1_serial_number', 'security_1_year_of_purchase',
)


def seed_partnership_laf(apps, schema_editor):
    product_model = apps.get_model('core', 'OriginationProductDefinition')
    money_fields = {
        'acknowledgement_amount', 'amount_advanced', 'approval_amount', 'installment_amount',
        'loan_amount', 'monthly_expenses', 'monthly_household_expenses', 'monthly_income',
        'net_income', 'own_contribution', 'project_cost', 'security_1_current_value',
    }
    required_fields = {
        'applicant_first_name', 'applicant_surname', 'applicant_id_number', 'applicant_phone',
        'applicant_residence_address', 'business_location', 'business_type', 'loan_amount',
        'loan_product', 'loan_purpose', 'repayment_period', 'guarantor_1_name',
        'guarantor_1_id_number', 'guarantor_1_phone', 'borrower_full_name',
    }
    fields = []
    for key in PARTNERSHIP_LAF_FIELDS:
        field_type = 'money' if key in money_fields else 'text'
        if key.endswith('_phone') or key in {'applicant_phone', 'applicant_other_phone'}:
            field_type = 'phone'
        elif key.endswith('_id_number') or key in {'applicant_id_number', 'applicant_next_of_kin_id', 'deponent_id_number'}:
            field_type = 'national_id'
        elif key == 'applicant_dob':
            field_type = 'date'
        field = {
            'key': key,
            'label': key.replace('_', ' ').title().replace('Bro ', 'BRO '),
            'type': field_type,
            'required': key in required_fields,
        }
        if key == 'loan_product':
            field.update({'type': 'choice', 'options': ['Jawabu Express', 'Jawabu Advantage', 'Almasi', 'Landlord', 'Other']})
        fields.append(field)
    product_model.objects.update_or_create(
        product_key='partnership_laf', version=1,
        defaults={
            'name': 'JBL Partnership Loan Application',
            'form_schema': {'fields': fields},
            'signer_rules': [
                {'role': 'borrower', 'required': True, 'slots': ['loan_request', 'loan_agreement_signature', 'affidavit_deponent_signature', 'acknowledgement_signature']},
                {'role': 'guarantor_1', 'required': True},
                {'role': 'guarantor_2', 'required': False},
                {'role': 'bro_1', 'required': True},
                {'role': 'bro_2', 'required': False},
                {'role': 'branch_manager', 'required': True},
                {'role': 'commissioner_for_oaths', 'required': False, 'slot_type': 'stamp'},
            ],
            'document_type': 'partnership_loan_application',
            'document_template_name': 'Jawabu Partnership LAF.pdf',
            'document_template_version': 1,
            'document_template_sha256': '5e7d264c0cf3e4264e9ab768fd89a4fd1dab131eedd733cce439ce11c6e345f1',
            'is_active': True,
        },
    )


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
                ('document_template_name', models.CharField(blank=True, default='', max_length=180)),
                ('document_template_version', models.PositiveIntegerField(default=1)),
                ('document_template_sha256', models.CharField(blank=True, default='', max_length=64)),
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
        migrations.RunPython(seed_partnership_laf, migrations.RunPython.noop),
    ]
