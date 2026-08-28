from django.db import migrations


def repair_origination_availability(apps, schema_editor):
    ProductAvailability = apps.get_model('core', 'ProductAvailability')
    legacy_rows = list(ProductAvailability.objects.filter(
        workflow='loan_origination', channel='telegram', active=True,
    ).order_by('pk'))
    for legacy in legacy_rows:
        signature = (
            f'branch:{legacy.branch_id or "*"}|workflow:loan_origination|channel:portal'
        )
        canonical = ProductAvailability.objects.filter(
            product_id=legacy.product_id, scope_signature=signature,
        ).first()
        if canonical:
            if not canonical.active:
                ProductAvailability.objects.filter(pk=canonical.pk).update(active=True)
            ProductAvailability.objects.filter(pk=legacy.pk).update(active=False)
            continue
        ProductAvailability.objects.filter(pk=legacy.pk).update(
            channel='portal', scope_signature=signature,
        )


class Migration(migrations.Migration):

    dependencies = [('core', '0139_guided_tat_control_center')]

    operations = [migrations.RunPython(
        repair_origination_availability, migrations.RunPython.noop,
    )]
