from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('requisitions', '0004_bind_order_workspaces')]
    operations = [migrations.AddField(model_name='ordernumberclaim', name='retired',
        field=models.BooleanField(default=False,
            db_comment='Permanently consumed after testing deletion; never offered for reuse.'))]
