from copy import deepcopy

from django.db import migrations


FORWARD_OPTIONS = {
    'bm_response': ['Approved', 'Declined'],
    'decision': ['Approved', 'Rejected', 'Deferred'],
    'minutes_shared': ['Yes', 'No'],
    'sanctions': ['Met', 'Not Met'],
    'bro_applied': ['Met', 'Not Met'],
    'register_approved': ['Approved', 'Declined'],
}

REVERSE_OPTIONS = {
    **FORWARD_OPTIONS,
    'sanctions': ['Pending', 'Met', 'Not Met'],
    'bro_applied': ['Pending', 'Met', 'Not Met'],
    'register_approved': ['Approved', 'Pending'],
}


def update_configuration_options(apps, schema_editor, options):
    Configuration = apps.get_model('core', 'ProductTatConfiguration')
    for configuration in Configuration.objects.only('pk', 'stages').iterator():
        stages = deepcopy(configuration.stages or [])
        changed = False
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            stage_options = options.get(str(stage.get('key') or ''))
            if stage_options is not None and stage.get('options') != stage_options:
                stage['options'] = list(stage_options)
                changed = True
        if changed:
            Configuration.objects.filter(pk=configuration.pk).update(stages=stages)


def forwards(apps, schema_editor):
    update_configuration_options(apps, schema_editor, FORWARD_OPTIONS)


def backwards(apps, schema_editor):
    update_configuration_options(apps, schema_editor, REVERSE_OPTIONS)


class Migration(migrations.Migration):
    dependencies = [('core', '0169_tat_global_register_and_amount_path')]

    operations = [migrations.RunPython(forwards, backwards)]
