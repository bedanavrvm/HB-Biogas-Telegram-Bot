import uuid

from django.db import migrations, models


COMMENTS = {
    'worklist_id': 'Stable identifier joining immutable versions of one monthly Portal FarmUp worklist.',
    'period_month': 'First calendar day of the user-selected month represented by the FarmUp worklist.',
    'version_number': 'Monotonic immutable source-upload version within a FarmUp worklist.',
    'is_current_version': 'True only for the latest reviewable source version in a FarmUp worklist.',
    'reconciliation': 'Customer-data-free aggregate reconciliation counts for this source version.',
}


def populate_legacy_worklist_ids(apps, schema_editor):
    Batch = apps.get_model('core', 'JawabuFarmerUploadBatch')
    for pk in Batch.objects.filter(worklist_id__isnull=True).values_list('pk', flat=True).iterator():
        Batch.objects.filter(pk=pk).update(worklist_id=uuid.uuid4())


def add_postgresql_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    table = schema_editor.quote_name('core_jawabufarmeruploadbatch')
    with schema_editor.connection.cursor() as cursor:
        for column, comment in COMMENTS.items():
            cursor.execute(
                f'COMMENT ON COLUMN {table}.{schema_editor.quote_name(column)} IS %s',
                [comment],
            )


def remove_postgresql_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    table = schema_editor.quote_name('core_jawabufarmeruploadbatch')
    with schema_editor.connection.cursor() as cursor:
        for column in COMMENTS:
            cursor.execute(
                f'COMMENT ON COLUMN {table}.{schema_editor.quote_name(column)} IS NULL'
            )


class Migration(migrations.Migration):

    dependencies = [('core', '0171_portal_farmup_workflow')]

    operations = [
        migrations.AddField(
            model_name='jawabufarmeruploadbatch', name='worklist_id',
            field=models.UUIDField(db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='jawabufarmeruploadbatch', name='period_month',
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='jawabufarmeruploadbatch', name='version_number',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='jawabufarmeruploadbatch', name='is_current_version',
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddField(
            model_name='jawabufarmeruploadbatch', name='reconciliation',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(populate_legacy_worklist_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='jawabufarmeruploadbatch', name='worklist_id',
            field=models.UUIDField(db_index=True, default=uuid.uuid4),
        ),
        migrations.AddIndex(
            model_name='jawabufarmeruploadbatch',
            index=models.Index(fields=['worklist_id', 'version_number'], name='farmup_worklist_version_idx'),
        ),
        migrations.AddIndex(
            model_name='jawabufarmeruploadbatch',
            index=models.Index(fields=['group_id', 'period_month', 'is_current_version'], name='farmup_grp_period_cur_idx'),
        ),
        migrations.AddConstraint(
            model_name='jawabufarmeruploadbatch',
            constraint=models.UniqueConstraint(fields=('worklist_id', 'version_number'), name='farmup_uq_worklist_ver'),
        ),
        migrations.AddConstraint(
            model_name='jawabufarmeruploadbatch',
            constraint=models.UniqueConstraint(
                condition=models.Q(import_kind='farmers', is_current_version=True, period_month__isnull=False),
                fields=('group_id', 'period_month'), name='farmup_uq_current_period',
            ),
        ),
        migrations.RunPython(add_postgresql_comments, remove_postgresql_comments),
    ]
