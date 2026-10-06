from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('origination', '0004_approval_signature_sequence')]
    operations = [
        migrations.RemoveConstraint(
            model_name='originationconsentpolicyversion',
            name='one_active_origination_consent_policy',
        ),
        migrations.AddConstraint(
            model_name='originationconsentpolicyversion',
            constraint=models.UniqueConstraint(
                fields=('status', 'approval_roles'), condition=models.Q(status='active'),
                name='one_active_orig_consent_sequence',
            ),
        ),
    ]
