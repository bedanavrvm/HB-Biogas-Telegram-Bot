from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payments', '0007_invoicenameagreement')]
    operations = [migrations.AddField(model_name='paymentnumberclaim', name='retired',
        field=models.BooleanField(default=False,
            db_comment='Permanently consumed after testing deletion; never offered for reuse.'))]
