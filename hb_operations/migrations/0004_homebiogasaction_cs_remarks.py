from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('hb_operations', '0003_correction_reason_is_optional_context')]

    operations = [
        migrations.AddField(
            model_name='homebiogasaction',
            name='cs_remarks',
            field=models.TextField(
                blank=True,
                db_comment='Optional additional HomeBiogas remarks projected to the existing Master Data CS Remarks column; retained after commissioning.',
                default='',
            ),
        ),
        migrations.AlterField(
            model_name='homebiogasaction',
            name='pending_commissioning_comment',
            field=models.TextField(
                blank=True,
                db_comment='Optional operational explanation while commissioning remains outstanding; cleared when commissioning is recorded.',
                default='',
            ),
        ),
    ]
