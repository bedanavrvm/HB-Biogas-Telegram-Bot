from django.db import migrations


# Deliberately human-observed checks. Programmatically assertable cases remain
# in the existing suites or are marked below when CI coverage is incomplete.
PORTAL_CHECKS = [
    ('NAV-01', 'Launch and identity', 'Open Portal from the approved Telegram launcher on a phone.', 'The correct identity and landing screen load with understandable feedback; no unexpected external browser opens.'),
    ('NAV-03', 'Navigation', 'Go from a list to a case, preview evidence, then use Close and Back.', 'Each step returns to its immediate origin without losing useful list context.'),
    ('NAV-04', 'Navigation', 'Open the bell on a narrow phone and follow a case notification.', 'The bell remains compact and the target case stays visually focused after refresh.'),
    ('NAV-05', 'Feedback', 'Observe a success, warning, validation failure, and server failure.', 'Messages use plain language, do not duplicate, and give a useful recovery action.'),
    ('NAV-08', 'Lists', 'Inspect empty, one-item, and many-item lists; search and clear a query.', 'Counts, filters, row hierarchy, and pagination are visually coherent.'),
    ('NAV-09', 'Dates', 'Compare timestamps across cards, detail, history, and export.', 'Kenyan local display and day-month-year input presentation remain consistent.'),
    ('NAV-10', 'Documents', 'Open and close an in-app image and document preview.', 'The file is readable and closing returns to the exact prior screen.'),
    ('FARM-03', 'FarmUp', 'Search, filter, switch table/card view, and open a long row on a phone.', 'Text and frozen columns never overlap; enough rows fit without losing readability.'),
    ('SYS-01', 'SysUp', 'Stage a valid SysUp file and review column mapping and matched rows.', 'Source identity and proposed applicant and officer data are distinguishable and understandable.'),
    ('HB-01', 'HB action', 'Open an accepted signed-order case from the HB queue.', 'Installation and commissioning are separate, obvious workstreams with a full-width search.'),
    ('HB-03', 'HB action', 'Choose Mark as installed and inspect the resulting form before saving.', 'Only actual installation fields appear; planning and commissioning fields stay hidden.'),
    ('HB-05', 'HB action', 'Inspect the commissioning wait-period message on an installed case.', 'The 21-day readiness date and relative days agree and are understandable.'),
    ('PAY-02', 'Payment', 'Open and close an invoice-matched payment candidate card on a phone.', 'The compact card identifies the case; expanded identity and actions align without wasted space.'),
    ('PAY-08', 'Payment', 'Inspect a completed batch and a list containing many batches.', 'Completed cards stay compact; filters are clear; Back restores the right list.'),
    ('NAV-06', 'Resilience', 'Temporarily disconnect and reconnect while viewing a list.', 'Existing data stays readable; the app clearly identifies offline and restored states.'),
    ('NAV-07', 'Resilience', 'Background the app with an unfinished form, then return and refresh.', 'Unsaved input is not silently lost or overwritten by polling.'),
]


def seed(apps, schema_editor):
    TestCase = apps.get_model('qa_tracker', 'TestCase')
    for identifier, journey, steps, expected in PORTAL_CHECKS:
        TestCase.objects.get_or_create(
            id=identifier,
            defaults={
                'app': 'portal', 'journey': journey,
                'description': steps.rstrip('.'), 'steps': steps,
                'expected': expected, 'priority': 'high',
                'automation_gap': identifier in {'NAV-06', 'NAV-07'},
            },
        )


class Migration(migrations.Migration):
    dependencies = [('qa_tracker', '0002_alter_testcycle_app')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
