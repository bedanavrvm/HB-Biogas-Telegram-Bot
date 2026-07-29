from django.db import migrations


DEFAULT_PRODUCTS = (
    ('Biogas', 'biogas'),
    ('Business', 'business'),
    ('Kilimo', 'kilimo'),
    ('Logbook', 'logbook'),
    ('Micro Asset', 'micro_asset'),
    ('Mjengo', 'mjengo'),
)


def seed_operational_products(apps, schema_editor):
    Product = apps.get_model('core', 'OperationalProduct')
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    names = {name for name, _code in DEFAULT_PRODUCTS}
    names.update(
        str(name).strip()
        for name in Farmer.objects.exclude(payment_product='').values_list('payment_product', flat=True)
        if str(name).strip()
    )
    default_codes = {name.casefold(): code for name, code in DEFAULT_PRODUCTS}
    for index, name in enumerate(sorted(names, key=str.casefold)):
        if Product.objects.filter(name__iexact=name).exists():
            continue
        Product.objects.create(
            name=name,
            code=default_codes.get(name.casefold(), ''),
            active=True,
            sort_order=index,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0076_governed_jawabu_data_quality'),
    ]

    operations = [
        migrations.RunPython(seed_operational_products, migrations.RunPython.noop),
    ]
