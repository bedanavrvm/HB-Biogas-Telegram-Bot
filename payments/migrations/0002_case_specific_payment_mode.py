from django.db import migrations, models


def copy_batch_modes_to_cases(apps, schema_editor):
    PaymentBatchCase = apps.get_model('payments', 'PaymentBatchCase')
    for membership in PaymentBatchCase.objects.select_related('batch').iterator():
        membership.payment_mode = membership.batch.payment_mode
        membership.save(update_fields=['payment_mode'])


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentbatchcase',
            name='payment_mode',
            field=models.CharField(
                choices=[('LOAN-JAWABU', 'Loan - Jawabu'), ('CASH', 'Cash')],
                db_comment='Payment route selected specifically for this case.',
                default='LOAN-JAWABU',
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(copy_batch_modes_to_cases, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='paymentbatch',
            name='payment_mode',
        ),
        migrations.AlterField(
            model_name='paymentbatch',
            name='batch_digest',
            field=models.CharField(
                blank=True,
                db_comment='SHA-256 binding of case modes, number, membership, and case payment data.',
                default='',
                max_length=64,
            ),
        ),
        migrations.AddConstraint(
            model_name='paymentbatchcase',
            constraint=models.CheckConstraint(
                condition=models.Q(payment_mode__in=['LOAN-JAWABU', 'CASH']),
                name='payment_batch_case_mode_valid',
            ),
        ),
    ]
