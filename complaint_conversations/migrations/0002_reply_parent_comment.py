import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('complaint_conversations', '0001_initial')]

    operations = [
        migrations.AlterField(
            model_name='commentcontext', name='reply_to',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='conversation_replies', to='core.caseupdate',
                db_comment='Exact same-case parent comment being answered; child text survives parent removal.'),
        ),
    ]
