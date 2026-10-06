from django.db import migrations


def bind(apps, schema_editor):
    alias = schema_editor.connection.alias
    Batch = apps.get_model('payments', 'PaymentBatch')
    Sequence = apps.get_model('payments', 'PaymentSequenceState')
    Claim = apps.get_model('payments', 'PaymentNumberClaim')
    for batch in Batch.objects.using(alias).exclude(status='cancelled').exclude(payment_number=None).iterator():
        sequence = Sequence.objects.using(alias).filter(group_configuration_id=batch.group_configuration_id).first()
        if sequence:
            Claim.objects.using(alias).get_or_create(sequence_id=sequence.pk, number=batch.payment_number, defaults={'batch_id': batch.pk})


class Migration(migrations.Migration):
    dependencies = [('payments', '0005_paymentnumberclaim_and_more')]
    operations = [migrations.RunPython(bind, migrations.RunPython.noop)]
