from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credit_assessments', '0002_expand_gmail_attachment_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='statementmailreceipt',
            name='customer_name',
            field=models.CharField(
                blank=True,
                db_comment='Customer name parsed from the provider email body when available.',
                default='',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='statementmailreceipt',
            name='statement_metadata_source',
            field=models.CharField(
                blank=True,
                db_comment='Source used to derive the statement phone and period: body, subject, or filename.',
                default='filename',
                max_length=32,
            ),
        ),
    ]
