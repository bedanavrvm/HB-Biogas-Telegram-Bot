from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0163_it_override_tat_roles_complaint_categories')]

    operations = [
        migrations.AddField(
            model_name='complaintcaseevidence',
            name='storage_filename',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
