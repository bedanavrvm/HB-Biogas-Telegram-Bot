from django.db import migrations, models


def simplify_existing_actions(apps, schema_editor):
    Action = apps.get_model('hb_operations', 'HomeBiogasAction')
    for action in Action.objects.all().iterator():
        update_fields = []
        if action.installation_status not in {'installed', 'closed'}:
            if action.installation_date:
                action.planned_installation_date = action.installation_date
                action.installation_date = None
                update_fields.extend(['planned_installation_date', 'installation_date'])
            action.installation_status = 'open'
            update_fields.append('installation_status')
        if action.commissioning_status == 'done':
            action.commissioning_status = 'commissioned'
            update_fields.append('commissioning_status')
        elif action.commissioning_status != 'not_commissioned':
            action.commissioning_status = 'not_commissioned'
            update_fields.append('commissioning_status')
        if update_fields:
            action.save(update_fields=sorted(set(update_fields)))


class Migration(migrations.Migration):

    dependencies = [('hb_operations', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='homebiogasaction',
            name='planned_installation_date',
            field=models.DateField(blank=True, db_comment='Optional planned installation date while the installation remains open.', null=True),
        ),
        migrations.RunPython(simplify_existing_actions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='installation_status',
            field=models.CharField(choices=[('open', 'Open'), ('installed', 'Installed'), ('closed', 'Closed')], db_comment='Current server-validated installation state.', default='open', max_length=32),
        ),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='installation_date',
            field=models.DateField(blank=True, db_comment='Actual installation completion date; required only when installation is installed.', null=True),
        ),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='readiness_status',
            field=models.CharField(blank=True, choices=[('ready', 'Ready'), ('not_ready', 'Not ready'), ('not_confirmed', 'Not confirmed')], db_comment='Optional structured readiness state while installation remains open.', default='', max_length=24),
        ),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='pending_installation_comment',
            field=models.TextField(blank=True, db_comment='Optional installation note; required for a closed case or a known readiness blocker.', default=''),
        ),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='commissioning_status',
            field=models.CharField(choices=[('not_commissioned', 'Not commissioned'), ('commissioned', 'Commissioned')], db_comment='Whether the installed unit has actually been commissioned.', default='not_commissioned', max_length=24),
        ),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='commissioning_date',
            field=models.DateField(blank=True, db_comment='Actual commissioning completion date; required only when commissioned.', null=True),
        ),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='pending_commissioning_comment',
            field=models.TextField(blank=True, db_comment='Legacy operational note retained only for historical audit context.', default=''),
        ),
    ]
