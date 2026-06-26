import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_livesheetrecordchange'),
    ]

    operations = [
        migrations.CreateModel(
            name='JawabuVisitRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('group_id', models.CharField(db_index=True, max_length=100)),
                ('sheet_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('sheet_tab', models.CharField(blank=True, default='', max_length=255)),
                ('row_number', models.PositiveIntegerField(blank=True, null=True)),
                ('telegram_message_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('source_telegram_message_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('whatsapp_message_index', models.PositiveIntegerField(blank=True, null=True)),
                ('whatsapp_message_at', models.DateTimeField(blank=True, null=True)),
                ('sender', models.CharField(blank=True, default='', max_length=255)),
                ('national_id', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('primary_phone', models.CharField(blank=True, db_index=True, default='', max_length=32)),
                ('duplicate_key', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('duplicate_group_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('duplicate_status', models.CharField(choices=[('unique', 'Unique'), ('possible_duplicate', 'Possible Duplicate'), ('confirmed_duplicate', 'Confirmed Duplicate'), ('not_duplicate', 'Not Duplicate'), ('merged', 'Merged')], default='unique', max_length=32)),
                ('import_status', models.CharField(choices=[('pending', 'Pending'), ('imported', 'Imported'), ('duplicate_review', 'Duplicate Needs Review'), ('rejected', 'Rejected'), ('failed', 'Failed')], default='pending', max_length=32)),
                ('parsed_fields', models.JSONField(blank=True, default=dict)),
                ('raw_text', models.TextField(blank=True, default='')),
                ('sync_error', models.TextField(blank=True, default='')),
                ('review_notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Jawabu visit record',
                'verbose_name_plural': 'Jawabu visit records',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='jawabuvisitrecord',
            index=models.Index(fields=['group_id', 'created_at'], name='core_jawabu_group_i_7a5512_idx'),
        ),
        migrations.AddIndex(
            model_name='jawabuvisitrecord',
            index=models.Index(fields=['group_id', 'duplicate_key'], name='core_jawabu_group_i_07bb1d_idx'),
        ),
        migrations.AddIndex(
            model_name='jawabuvisitrecord',
            index=models.Index(fields=['national_id', 'primary_phone'], name='core_jawabu_nationa_7fbfe4_idx'),
        ),
        migrations.AddIndex(
            model_name='jawabuvisitrecord',
            index=models.Index(fields=['import_status', 'duplicate_status'], name='core_jawabu_import__4ddf7e_idx'),
        ),
    ]
