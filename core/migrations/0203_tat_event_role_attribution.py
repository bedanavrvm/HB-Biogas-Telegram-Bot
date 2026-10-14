from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0202_jawabufarmermaster_requisition_batch_and_more')]
    operations = [
        migrations.AlterField(
            model_name='tattrackerevent', name='actor_role',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
