from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [('core', '0031_rename_core_spincr_group_i_1f2945_idx_core_spincr_group_i_76ce4a_idx_and_more')]
    operations = [
        migrations.AddField(model_name='tattrackerstaffmember', name='signing_email', field=models.EmailField(blank=True, default='', max_length=254)),
        migrations.AddField(model_name='tattrackerstaffmember', name='signing_national_id', field=models.CharField(blank=True, default='', max_length=40)),
        migrations.AddField(model_name='tattrackerstaffmember', name='signing_phone_number', field=models.CharField(blank=True, default='', max_length=20)),
        migrations.CreateModel(name='TatTrackerApprovalCertificate', fields=[('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ('stage_key', models.CharField(db_index=True, max_length=120)), ('external_reference', models.CharField(max_length=80, unique=True)), ('status', models.CharField(choices=[('awaiting_signature', 'Awaiting signature'), ('signed', 'Signed'), ('declined', 'Declined'), ('expired', 'Expired'), ('delivery_failed', 'Delivery failed'), ('failed', 'Failed')], db_index=True, default='awaiting_signature', max_length=32)), ('signed_document_hash', models.CharField(blank=True, default='', max_length=64)), ('signed_document_path', models.TextField(blank=True, default='')), ('webhook_delivery_id', models.CharField(blank=True, default='', max_length=64, null=True, unique=True)), ('error', models.TextField(blank=True, default='')), ('signed_at', models.DateTimeField(blank=True, null=True)), ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)), ('case', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='approval_certificates', to='core.tattrackercase')), ('event', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='approval_certificate', to='core.tattrackerevent')), ('staff_member', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='approval_certificates', to='core.tattrackerstaffmember'))]),
        migrations.AddIndex(model_name='tattrackerapprovalcertificate', index=models.Index(fields=['case', 'stage_key'], name='core_tattra_case_id_61a8f6_idx')),
        migrations.AddIndex(model_name='tattrackerapprovalcertificate', index=models.Index(fields=['status', 'updated_at'], name='core_tattra_status_a6367e_idx')),
    ]
