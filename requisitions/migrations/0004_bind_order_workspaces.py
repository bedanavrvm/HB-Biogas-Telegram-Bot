import re
from django.db import migrations


def bind(apps, schema_editor):
    alias = schema_editor.connection.alias
    Batch = apps.get_model('core', 'RequisitionBatch')
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    Sequence = apps.get_model('requisitions', 'OrderSequenceState')
    Claim = apps.get_model('requisitions', 'OrderNumberClaim')
    Version = apps.get_model('requisitions', 'OrderWorkbookVersion')
    for batch in Batch.objects.using(alias).exclude(status='cancelled').iterator():
        if batch.file_content and batch.version:
            Version.objects.using(alias).get_or_create(batch_id=batch.pk, version=batch.version, defaults={
                'filename': batch.filename, 'file_content': batch.file_content, 'checksum': batch.content_checksum,
                'farmer_ids': batch.farmer_ids, 'actor_id': batch.finalized_by_id,
            })
        if batch.group_configuration_id:
            sequence = Sequence.objects.using(alias).filter(group_configuration_id=batch.group_configuration_id, partner=batch.fulfillment_partner).first()
            match = re.fullmatch(r'(?:HB-|ECO-)?(\d+)', batch.order_number)
            if sequence and match:
                Claim.objects.using(alias).get_or_create(sequence_id=sequence.pk, number=int(match[1]), defaults={'batch_id': batch.pk})
        # No identity inference: exact retained member UUID, number and date.
        Farmer.objects.using(alias).filter(pk__in=batch.farmer_ids, order_number=batch.order_number,
            requisition_date=batch.requisition_date, requisition_batch__isnull=True).update(requisition_batch_id=batch.pk)


class Migration(migrations.Migration):
    dependencies = [('requisitions', '0003_ordernumberclaim_orderworkbookversion_and_more')]
    operations = [migrations.RunPython(bind, migrations.RunPython.noop)]
