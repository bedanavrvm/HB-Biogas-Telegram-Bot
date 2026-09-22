from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('hb_operations', '0002_simplify_fulfilment_states')]

    operations = [
        migrations.AlterField(
            model_name='homebiogasactionevent',
            name='reason',
            field=models.TextField(
                blank=True,
                default='',
                db_comment='Optional legacy context for an audited correction; actor and before/after values are always recorded.',
            ),
        ),
    ]
