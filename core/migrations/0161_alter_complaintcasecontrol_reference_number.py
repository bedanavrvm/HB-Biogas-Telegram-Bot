from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0160_origination_document_catalogue')]

    operations = [
        migrations.AlterField(
            model_name='complaintcasecontrol',
            name='reference_number',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Short global staff-facing complaint reference, for example CMP-1.',
                max_length=16,
                null=True,
                unique=True,
            ),
        ),
    ]
