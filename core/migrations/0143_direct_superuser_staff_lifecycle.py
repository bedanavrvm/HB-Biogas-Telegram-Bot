from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0142_user_hard_delete_audit'),
    ]

    operations = [
        migrations.AddField(
            model_name='stafflifecyclechangeplan',
            name='decision_mode',
            field=models.CharField(
                choices=[
                    ('checker_review', 'Independent checker review'),
                    ('superuser_direct', 'Direct Superuser decision'),
                ],
                db_index=True,
                default='checker_review',
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name='stafflifecyclechangeplan',
            name='request_fingerprint',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
