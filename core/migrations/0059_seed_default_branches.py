from django.db import migrations


DEFAULT_BRANCHES = (
    'Corporate',
    'East Nairobi',
    'West Nairobi',
    'Thika Road',
    'Limuru',
    'Embu',
    'Nakuru',
    'Biogas Unit',
    'Eco Conserve',
)


def seed_default_branches(apps, schema_editor):
    OperationalLocation = apps.get_model('core', 'OperationalLocation')
    for sort_order, name in enumerate(DEFAULT_BRANCHES):
        OperationalLocation.objects.update_or_create(
            location_type='branch',
            name=name,
            defaults={'sort_order': sort_order, 'active': True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0058_operationallocation'),
    ]

    operations = [
        migrations.RunPython(seed_default_branches, migrations.RunPython.noop),
    ]
