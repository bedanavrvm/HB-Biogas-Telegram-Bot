"""Add readable aliases without changing canonical references or captured documents."""
import re
from django.db import migrations, models


def assign_references(apps, schema_editor):
    using = schema_editor.connection.alias
    application = apps.get_model('origination', 'LoanOriginationApplication')
    sequence = apps.get_model('origination', 'OriginationApplicationReferenceSequence')
    rows = application.objects.using(using)
    last = sequence.objects.using(using).filter(pk=1).values_list('last_number', flat=True).first() or 0
    for reference in rows.exclude(display_reference__isnull=True).values_list('display_reference', flat=True).iterator():
        match = re.fullmatch(r'ORG-([1-9][0-9]*)', reference or '')
        if match:
            last = max(last, int(match[1]))
    # Preserve existing short canonical numbers first, then assign aliases in a
    # stable order. Only the new column is written: no revisions/timestamps/hash
    # inputs or signed document bytes are touched.
    for pk, reference in rows.values_list('pk', 'reference_number').iterator():
        match = re.fullmatch(r'ORG-([1-9][0-9]*)', reference or '')
        if match:
            last = max(last, int(match[1]))
            rows.filter(pk=pk, display_reference__isnull=True).update(display_reference=reference)
    for pk in rows.filter(display_reference__isnull=True).order_by('created_at', 'pk').values_list('pk', flat=True).iterator():
        last += 1
        rows.filter(pk=pk).update(display_reference=f'ORG-{last}')
    sequence.objects.using(using).update_or_create(pk=1, defaults={'last_number': last})


class Migration(migrations.Migration):
    dependencies = [('origination', '0011_phone_identity_pilot_capability')]
    operations = [
        migrations.CreateModel(
            name='OriginationApplicationReferenceSequence',
            fields=[
                ('id', models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False,
                    serialize=False, db_comment='Singleton allocator identity; always 1.')),
                ('last_number', models.PositiveBigIntegerField(default=0,
                    db_comment='Highest allocated ORG display number. Never reset or decremented by deletion.')),
            ],
            options={
                'db_table': 'origination_application_reference_state',
                'db_table_comment': 'Domain: origination. Purpose: Permanent global application reference allocator. Classification: processing_record. Source of truth: yes. Lifecycle: active. Retention: Permanent; never purged with applications or testing data. No parent or child relations.',
                'constraints': [models.CheckConstraint(condition=models.Q(id=1), name='orig_app_ref_singleton')],
            },
        ),
        migrations.AddField(model_name='loanoriginationapplication', name='display_reference',
            field=models.CharField('Application number', max_length=80, unique=True, null=True, blank=True, editable=False,
                db_comment='Permanent friendly ORG-N alias. Historical canonical references and signed bytes are unchanged.')),
        migrations.RunPython(assign_references, migrations.RunPython.noop),
    ]
