from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0127_tat_responsibility_canonical_routing'),
    ]

    operations = [
        migrations.AddField(
            model_name='userminiapppreference',
            name='show_business_hours_time',
            field=models.BooleanField(default=True),
        ),
    ]
