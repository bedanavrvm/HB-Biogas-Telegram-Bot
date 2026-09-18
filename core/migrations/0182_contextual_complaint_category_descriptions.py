from django.db import migrations


CATEGORY_DESCRIPTIONS = {
    'installation-delay': (
        'Problems or enquiries about installing a system, including scheduling, delays, '
        'readiness, incomplete work, or installation requirements.'
    ),
    'commissioning-delay': (
        'Problems or enquiries about getting an installed system ready for use, including '
        'scheduling, delays, readiness, incomplete work, or follow-up.'
    ),
    'system-performance': (
        'The system is producing little or no gas, not inflating, giving short cooking time, '
        'not supplying gas properly, or stopping unexpectedly.'
    ),
    'leakage': (
        'Gas is escaping or there is a gas smell from the stove, kitchen, pipes, joints, '
        'connections, digester, bag, burner, or cap.'
    ),
    'pipe-connection-fault': (
        'A pipe, joint, inlet, outlet, support, or connection is broken, cracked, loose, '
        'disconnected, blocked, burnt, sagging, or incorrectly positioned.'
    ),
    'burner-knob-fault': (
        'A burner or stove is not working, not lighting, going off, has a weak flame, or a '
        'knob is broken, stuck, or difficult to use.'
    ),
    'system-damage': (
        'The system or its components are physically damaged, for example by tearing, '
        'punctures, cracks, holes, fire, weather, animals, falling objects, or other damage.'
    ),
    'blockage': (
        'There is a blockage or feeding problem, including blocked inlets/outlets, backflow, '
        'scum, contaminated material, or difficulty feeding the system.'
    ),
    'accessories-delay': (
        'A customer needs, has not received, or has a damaged or unsuitable accessory or '
        'spare part, such as a filter, volcano, cover, stand, grill, burner, knob, or post.'
    ),
    'relocation-request': (
        'A customer wants to move or modify the system, stove, burner, or pipes, including '
        'changing the cooking point, pipe direction, or installation position.'
    ),
    'technical-support': (
        'Help is needed to diagnose, troubleshoot, operate, feed, or maintain the system, '
        'including technical visits, training, reinoculation, or follow-up.'
    ),
    'appraisal': (
        'Questions or problems related to system appraisal, including readiness, scheduling, '
        'delays, assessment results, or follow-up.'
    ),
    'payments-accounts': (
        'Questions about balances, repayments, payment status, confirmations, paybill, receipts, '
        'statements, or payments for repairs, replacements, accessories, or relocation.'
    ),
    'other-complaint': (
        'A complaint or enquiry that does not clearly fit any of the other complaint types.'
    ),
}


def update_descriptions(apps, schema_editor):
    ComplaintCategory = apps.get_model('core', 'ComplaintCategory')
    for key, description in CATEGORY_DESCRIPTIONS.items():
        ComplaintCategory.objects.filter(key=key).update(description=description)


class Migration(migrations.Migration):
    dependencies = [('core', '0181_jawabu_consecutive_case_reference')]
    operations = [
        migrations.RunPython(update_descriptions, migrations.RunPython.noop),
    ]
