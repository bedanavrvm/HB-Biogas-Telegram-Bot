"""Join independent reference allocation and guarded legacy authoring cleanup."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('origination', '0012_application_display_references'),
        ('origination', '0012_remove_legacy_authoring_models'),
    ]

    operations = []
