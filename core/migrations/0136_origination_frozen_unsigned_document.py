from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0135_miniapp_diagnostics'),
    ]

    operations = [
        migrations.AddField(
            model_name='originationsigningpackage',
            name='frozen_unsigned_document',
            field=models.BinaryField(blank=True, default=bytes, editable=False),
        ),
    ]
