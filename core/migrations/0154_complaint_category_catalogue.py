from django.db import migrations


CATEGORY_CATALOGUE = (
    (
        'leakage',
        'Leakage',
        'Gas, bag, pipe, connection, valve, etc.',
    ),
    (
        'blockage',
        'Blockage',
        'Inlet or outlet blockage',
    ),
    (
        'burner-knob-fault',
        'Burner/Knob Fault',
        'Burner, knob, flame, ignition issues',
    ),
    (
        'pipe-connection-fault',
        'Pipe/Connection Fault',
        'Physical pipe/connection problems where leakage is NOT the primary complaint',
    ),
    (
        'system-performance',
        'System Performance',
        'Low/no gas production or poor system performance',
    ),
    (
        'installation-delay',
        'Installation Delay',
        "Installation hasn't happened/delayed",
    ),
    (
        'commissioning-delay',
        'Commissioning Delay',
        'Commissioning/start-up delayed',
    ),
    (
        'accessories-delay',
        'Accessories Delay',
        'Accessories requested but delayed',
    ),
    (
        'relocation-request',
        'Relocation Request',
        'Customer wants system relocated',
    ),
    (
        'other-complaint',
        'Other Complaint',
        "Doesn't fit any category",
    ),
)


def seed_complaint_categories(apps, schema_editor):
    ComplaintCategory = apps.get_model('core', 'ComplaintCategory')
    ComplaintCategoryAvailability = apps.get_model('core', 'ComplaintCategoryAvailability')
    canonical_ids = []
    for key, label, description in CATEGORY_CATALOGUE:
        category = ComplaintCategory.objects.filter(label__iexact=label).first()
        key_match = ComplaintCategory.objects.filter(key=key).first()
        if category is not None and key_match is not None and category.pk != key_match.pk:
            # Preserve both historical rows while freeing the governed key and
            # case-insensitive label for the row staff already knew by label.
            suffix = str(key_match.pk).replace('-', '')[:8]
            key_match.key = f'retired-{suffix}'
            key_match.label = f'{key_match.label[:140]} (legacy {suffix})'
            key_match.active = False
            key_match.save(update_fields=['key', 'label', 'active', 'updated_at'])
            key_match = None
        if category is None:
            category = key_match
        if category is None:
            category = ComplaintCategory.objects.create(
                key=key,
                label=label,
                description=description,
                default_priority='normal',
                default_sla_hours=72,
                active=True,
            )
        else:
            category.key = key
            category.label = label
            category.description = description
            category.default_priority = 'normal'
            category.default_sla_hours = 72
            category.active = True
            category.save(update_fields=[
                'key', 'label', 'description', 'default_priority', 'default_sla_hours',
                'active', 'updated_at',
            ])
        canonical_ids.append(category.pk)
    ComplaintCategory.objects.exclude(pk__in=canonical_ids).update(active=False)
    # The approved catalogue is global. Historical availability rows on a
    # reused category must not make one of the ten choices disappear in only
    # some complaint groups.
    ComplaintCategoryAvailability.objects.filter(category_id__in=canonical_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0153_complaint_global_register'),
    ]

    operations = [
        migrations.RunPython(seed_complaint_categories, migrations.RunPython.noop),
    ]
