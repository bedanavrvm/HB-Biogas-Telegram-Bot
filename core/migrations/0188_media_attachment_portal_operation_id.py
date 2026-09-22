"""Group Portal visit files under the action that captured them."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('core', '0187_portal_settings_operations_scope')]

    operations = [
        migrations.AddField(
            model_name='mediaattachment',
            name='portal_operation_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
    ]
