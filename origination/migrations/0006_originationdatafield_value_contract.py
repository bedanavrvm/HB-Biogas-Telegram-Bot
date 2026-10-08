from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('origination', '0005_consent_sequence_isolation')]
    operations = [migrations.AddField(
        model_name='originationdatafield', name='value_contract',
        field=models.JSONField(
            default=dict, blank=True,
            help_text='Reviewed subject, ownership, units and non-executable value source; frozen with new documents.',
            db_comment='Versioned field meaning and allowlisted value source. Historical application snapshots remain authoritative.',
        ),
    )]
