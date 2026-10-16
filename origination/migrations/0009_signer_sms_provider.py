from django.db import migrations, models


def bound_existing_sms_attempts(apps, schema_editor):
    apps.get_model('core', 'IntegrationOperation').objects.using(schema_editor.connection.alias).filter(
        operation_type__in=['origination_signing_invitation', 'origination_signing_otp', 'origination_withdrawal_sms'],
    ).update(max_attempts=1)


class Migration(migrations.Migration):
    dependencies = [('origination', '0008_unsigned_application_completion'), ('core', '0206_advanta_integration')]
    operations = [migrations.AddField(
        model_name='originationsignersession', name='sms_provider',
        field=models.CharField(
            max_length=32, choices=[('africas_talking', "Africa's Talking"), ('advanta', 'Advanta')],
            default='africas_talking', editable=False,
            db_comment='Immutable SMS provider captured for this link; historical links use Africa\'s Talking.',
        ),
    ), migrations.RunPython(bound_existing_sms_attempts, migrations.RunPython.noop)]
