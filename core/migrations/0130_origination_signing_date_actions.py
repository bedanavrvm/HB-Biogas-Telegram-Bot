from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0129_origination_staff_signing_roles')]
    operations = [
        migrations.AlterField(
            model_name='originationsigningaction',
            name='action_type',
            field=models.CharField(
                choices=[
                    ('signature', 'Signature'),
                    ('stamp', 'Stamp'),
                    ('date_signed', 'Signing date'),
                ],
                max_length=16,
            ),
        ),
    ]
