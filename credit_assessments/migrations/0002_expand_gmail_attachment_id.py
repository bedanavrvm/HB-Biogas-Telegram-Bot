from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credit_assessments', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='statementmailreceipt',
            name='gmail_attachment_id',
            field=models.CharField(
                db_comment='Gmail attachment identifier used with the message identifier for idempotent ingestion.',
                max_length=2048,
            ),
        ),
    ]
