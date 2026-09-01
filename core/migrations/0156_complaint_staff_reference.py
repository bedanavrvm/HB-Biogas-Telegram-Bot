from django.db import migrations, models


GLOBAL_SCOPE = '__complaint_global__'


def backfill_references(apps, schema_editor):
    Control = apps.get_model('core', 'ComplaintCaseControl')
    Sequence = apps.get_model('core', 'ComplaintCaseSequence')
    number = 1
    for control in Control.objects.order_by('created_at', 'pk').iterator(chunk_size=500):
        control.reference_number = f'CMP{number:06d}'
        control.save(update_fields=['reference_number'])
        number += 1
    Sequence.objects.update_or_create(
        group_id=GLOBAL_SCOPE, year=0, defaults={'next_number': number},
    )


def remove_references(apps, schema_editor):
    apps.get_model('core', 'ComplaintCaseControl').objects.update(reference_number=None)
    apps.get_model('core', 'ComplaintCaseSequence').objects.filter(
        group_id=GLOBAL_SCOPE, year=0,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0155_complaint_role_and_viewer_policy')]

    operations = [
        migrations.AddField(
            model_name='complaintcasecontrol',
            name='reference_number',
            field=models.CharField(
                blank=True, db_index=True,
                help_text='Short global staff-facing complaint reference, for example CMP000001.',
                max_length=16, null=True, unique=True,
            ),
        ),
        migrations.RunPython(backfill_references, remove_references),
    ]
