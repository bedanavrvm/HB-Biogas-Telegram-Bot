from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_case_specific_payment_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paymentbatch',
            name='payment_number',
            field=models.PositiveBigIntegerField(
                blank=True,
                db_comment='Official immutable number allocated only when a fully reviewed workbook is generated.',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='paymentbatch',
            name='submitted_at',
            field=models.DateTimeField(
                blank=True,
                db_comment='When the batch was first submitted for Head of Rural review.',
                null=True,
            ),
        ),
    ]
