import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_mediaattachment_content_hash'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiveSheetRecordChange',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('group_id', models.CharField(db_index=True, max_length=100)),
                ('sheet_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('sheet_tab', models.CharField(blank=True, default='', max_length=255)),
                ('row_number', models.PositiveIntegerField()),
                ('record_key', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('action', models.CharField(choices=[('update', 'Updated'), ('delete', 'Deleted')], max_length=20)),
                ('changed_by', models.CharField(blank=True, default='', max_length=255)),
                ('changes', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('success', 'Success'), ('failed', 'Failed')], max_length=20)),
                ('error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('group_configuration', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='live_sheet_changes', to='core.groupsheetconfiguration')),
            ],
            options={
                'verbose_name': 'Live sheet record change',
                'verbose_name_plural': 'Live sheet record changes',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='livesheetrecordchange',
            index=models.Index(fields=['group_id', 'created_at'], name='core_livesh_group_i_5fb404_idx'),
        ),
        migrations.AddIndex(
            model_name='livesheetrecordchange',
            index=models.Index(fields=['sheet_id', 'sheet_tab'], name='core_livesh_sheet_i_b266f3_idx'),
        ),
        migrations.AddIndex(
            model_name='livesheetrecordchange',
            index=models.Index(fields=['record_key'], name='core_livesh_record__b1b9dc_idx'),
        ),
    ]
