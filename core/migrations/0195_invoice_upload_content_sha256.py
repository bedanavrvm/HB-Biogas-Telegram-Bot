from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0194_clarify_sysup_lgf_balance'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceuploadbatch',
            name='content_sha256',
            field=models.CharField(blank=True, db_comment='SHA-256 of the original invoice PDF; duplicate uploads are rejected within one Portal group.', default='', max_length=64),
        ),
        migrations.AddConstraint(
            model_name='invoiceuploadbatch',
            constraint=models.UniqueConstraint(condition=~Q(content_sha256=''), fields=('group_configuration', 'content_sha256'), name='unique_group_invoice_pdf_hash'),
        ),
    ]
