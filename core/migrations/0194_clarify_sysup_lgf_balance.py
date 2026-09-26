from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0193_role_tailored_portal_home')]

    operations = [
        migrations.AlterField(
            model_name='jawabufarmermaster',
            name='system_deposit_paid_jbl',
            field=models.DecimalField(
                max_digits=12, decimal_places=2, null=True, blank=True,
                help_text='LGF balance from the IMAB/SysUp export for payment preparation; not a deposit paid to JBL.',
            ),
        ),
    ]
