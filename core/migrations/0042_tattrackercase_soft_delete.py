from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_complaintcasesequence'),
    ]

    operations = [
        migrations.AddField(
            model_name='tattrackercase',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tattrackercase',
            name='deleted_by',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='tattrackercase',
            name='deletion_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='tattrackercase',
            name='is_deleted',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddIndex(
            model_name='tattrackercase',
            index=models.Index(fields=['group_id', 'is_deleted'], name='core_tattra_group_i_e05762_idx'),
        ),
    ]
