from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0214_userminiapppreference_table_layouts')]

    operations = [
        migrations.AddField(
            model_name='jawabufarmermaster',
            name='jbl_next_visit_date',
            field=models.DateField(
                null=True, blank=True,
                db_comment='Next planned JBL visit for a rescheduled case; not evidence of a completed visit or a reappraisal deadline.',
            ),
        ),
    ]
