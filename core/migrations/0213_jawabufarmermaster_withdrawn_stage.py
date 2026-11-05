from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0212_complaint_verification_comments')]

    operations = [
        migrations.AddField(
            model_name='jawabufarmermaster', name='withdrawn_stage',
            field=models.CharField(blank=True, default='', max_length=32,
                db_comment='Canonical resume stage for an explicit client withdrawal; blank for historical unknowns and active cases.'),
        ),
    ]
