from django.db import migrations, models


SEQUENCE_NAME = 'core_jawabu_case_reference_seq'


def backfill_case_references(apps, schema_editor):
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    rows = list(Farmer.objects.order_by('created_at', 'id').only('id'))
    for number, row in enumerate(rows, start=1):
        row.case_reference_number = number
    if rows:
        Farmer.objects.bulk_update(rows, ['case_reference_number'], batch_size=500)

    if schema_editor.connection.vendor == 'postgresql':
        next_number = len(rows) + 1
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f'CREATE SEQUENCE IF NOT EXISTS {SEQUENCE_NAME}')
            cursor.execute(
                f"SELECT setval('{SEQUENCE_NAME}', %s, false)",
                [next_number],
            )


def drop_case_reference_sequence(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f'DROP SEQUENCE IF EXISTS {SEQUENCE_NAME}')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0180_enforce_sixty_day_deferral_policy'),
    ]

    operations = [
        migrations.AddField(
            model_name='jawabufarmermaster',
            name='case_reference_number',
            field=models.PositiveBigIntegerField(
                blank=True,
                db_comment=(
                    'Immutable global sequence used only for the short staff-facing JBL case reference. '
                    'The UUID primary key remains the canonical integration identity.'
                ),
                editable=False,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(backfill_case_references, drop_case_reference_sequence),
        migrations.AlterField(
            model_name='jawabufarmermaster',
            name='case_reference_number',
            field=models.PositiveBigIntegerField(
                db_comment=(
                    'Immutable global sequence used only for the short staff-facing JBL case reference. '
                    'The UUID primary key remains the canonical integration identity.'
                ),
                editable=False,
                unique=True,
            ),
        ),
    ]
