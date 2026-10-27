from django.db import migrations, models


def guard_purpose_reversal(apps,schema_editor):
    grants=apps.get_model('staff_auth','StaffBrowserSetupGrant').objects.using(schema_editor.connection.alias)
    if grants.exclude(purpose='initial_password').exists():
        raise RuntimeError('Keep migration 0005 while mailbox-verification grants exist; disabling browser access needs no schema reversal.')


class Migration(migrations.Migration):
    dependencies=[('staff_auth','0004_staffbrowsersecuritystate')]
    operations=[
        migrations.AddField(model_name='staffbrowsersetupgrant',name='purpose',field=models.CharField(
            max_length=20,default='initial_password',
            choices=[('initial_password','First password'),('verify_email','Verify existing account email')],
            db_comment='Captured setup purpose. Mailbox-only proof never replaces an existing password or grants login assurance.')),
        migrations.AlterField(model_name='staffbrowsersetupgrant',name='password_fingerprint',field=models.CharField(
            max_length=64,db_comment='Keyed fingerprint of the original password state; never a new-password verifier.')),
        migrations.AlterModelTableComment(name='staffbrowsersetupgrant',table_comment=
            'Expiring mailbox-proof and first-password capability for an existing admitted account; never login or workflow authority.'),
        migrations.AddConstraint(model_name='staffbrowsersetupgrant',constraint=models.CheckConstraint(
            condition=models.Q(purpose__in=['initial_password','verify_email']),name='staff_setup_known_purpose')),
        migrations.RunPython(migrations.RunPython.noop,guard_purpose_reversal),
    ]
