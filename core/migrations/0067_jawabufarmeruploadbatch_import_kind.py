from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0066_alter_jawabufarmermaster_credit_decision'),
    ]

    operations = [
        migrations.AddField(
            model_name='jawabufarmeruploadbatch',
            name='import_kind',
            field=models.CharField(
                choices=[
                    ('farmers', 'Farmers CSV'),
                    ('system_export', 'Customers Without Loans export'),
                ],
                db_index=True,
                default='farmers',
                max_length=32,
            ),
        ),
    ]
