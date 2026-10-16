from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0205_tat_publication_retry_capability')]
    operations = [migrations.AlterField(
        model_name='integrationoperation', name='integration',
        field=models.CharField(max_length=32, db_index=True, choices=[
            ('google_sheets', 'Google Sheets'), ('google_drive', 'Google Drive'),
            ('telegram', 'Telegram'), ('africas_talking', "Africa's Talking"), ('advanta', 'Advanta'),
        ]),
    )]
