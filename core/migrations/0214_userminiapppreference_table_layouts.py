from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0213_jawabufarmermaster_withdrawn_stage')]
    operations = [migrations.AddField(
        model_name='userminiapppreference', name='table_layouts',
        field=models.JSONField(blank=True, default=dict, help_text='Personal column order and frozen prefix, keyed by table. Never grants data access.'),
    )]
