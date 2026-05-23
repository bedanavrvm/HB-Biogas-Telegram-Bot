import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_groupsheetconfiguration_parsedmessage_sheet_id_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrderApprovalUpdate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('group_id', models.CharField(db_index=True, max_length=100)),
                ('sheet_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('sheet_tab', models.CharField(blank=True, default='', max_length=255)),
                ('row_number', models.PositiveIntegerField(blank=True, null=True)),
                ('id_number', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('sender', models.CharField(blank=True, default='', max_length=255)),
                ('telegram_message_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('reply_to_telegram_message_id', models.CharField(blank=True, default='', max_length=255)),
                ('raw_text', models.TextField(blank=True, default='')),
                ('parsed_fields', models.JSONField(blank=True, default=dict)),
                ('update_status', models.CharField(choices=[('pending', 'Pending'), ('success', 'Synced'), ('failed', 'Failed'), ('no_match', 'No Matching Row'), ('duplicate', 'Duplicate Sheet Rows')], default='pending', max_length=20)),
                ('sync_error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MediaAttachment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('group_id', models.CharField(db_index=True, max_length=100)),
                ('telegram_message_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('reply_to_telegram_message_id', models.CharField(blank=True, default='', max_length=255)),
                ('telegram_file_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('sender', models.CharField(blank=True, default='', max_length=255)),
                ('file_type', models.CharField(blank=True, default='', max_length=50)),
                ('original_filename', models.CharField(blank=True, default='', max_length=255)),
                ('mime_type', models.CharField(blank=True, default='', max_length=255)),
                ('size', models.PositiveIntegerField(blank=True, null=True)),
                ('storage_provider', models.CharField(blank=True, default='', max_length=50)),
                ('drive_file_id', models.CharField(blank=True, default='', max_length=255)),
                ('drive_url', models.URLField(blank=True, default='', max_length=1000)),
                ('upload_status', models.CharField(choices=[('pending', 'Pending'), ('success', 'Uploaded'), ('failed', 'Failed'), ('skipped', 'Skipped')], default='pending', max_length=20)),
                ('upload_error', models.TextField(blank=True, default='')),
                ('business_key_type', models.CharField(blank=True, default='', max_length=100)),
                ('business_key_value', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('order_update', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='media_attachments', to='core.orderapprovalupdate')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='orderapprovalupdate',
            index=models.Index(fields=['group_id', 'created_at'], name='core_ordera_group_i_f0e030_idx'),
        ),
        migrations.AddIndex(
            model_name='orderapprovalupdate',
            index=models.Index(fields=['group_id', 'id_number'], name='core_ordera_group_i_54dc47_idx'),
        ),
        migrations.AddIndex(
            model_name='orderapprovalupdate',
            index=models.Index(fields=['telegram_message_id'], name='core_ordera_telegra_f2187c_idx'),
        ),
        migrations.AddIndex(
            model_name='mediaattachment',
            index=models.Index(fields=['group_id', 'created_at'], name='core_mediaa_group_i_f5fd79_idx'),
        ),
        migrations.AddIndex(
            model_name='mediaattachment',
            index=models.Index(fields=['business_key_type', 'business_key_value'], name='core_mediaa_busines_834b9d_idx'),
        ),
        migrations.AddIndex(
            model_name='mediaattachment',
            index=models.Index(fields=['telegram_file_id'], name='core_mediaa_telegra_027c57_idx'),
        ),
    ]
