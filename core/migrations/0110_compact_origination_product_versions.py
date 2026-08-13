from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0109_origination_field_catalogue'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='originationdocumenttemplate',
            name='unique_origination_document_version',
        ),
        migrations.AddConstraint(
            model_name='originationdocumenttemplate',
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=['ready', 'active']),
                fields=('document_type', 'version'),
                name='unique_ready_active_orig_document_version',
            ),
        ),
    ]
