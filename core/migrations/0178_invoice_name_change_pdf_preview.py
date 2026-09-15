from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0177_invoice_inline_identity_and_lead_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoicenamechangeletterartifact',
            name='preview_content_type',
            field=models.CharField(default='application/pdf', max_length=255),
        ),
        migrations.AddField(
            model_name='invoicenamechangeletterartifact',
            name='preview_file_content',
            field=models.BinaryField(blank=True, default=bytes),
        ),
        migrations.AddField(
            model_name='invoicenamechangeletterartifact',
            name='preview_filename',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='invoicenamechangeletterartifact',
            name='preview_checksum',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
