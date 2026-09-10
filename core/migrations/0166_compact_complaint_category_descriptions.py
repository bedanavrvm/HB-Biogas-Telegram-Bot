from django.db import migrations


CATEGORY_DESCRIPTIONS = {
    'installation-delay': 'Installation dates/scheduling, delays, readiness, holds, incomplete work, requirements, follow-up.',
    'commissioning-delay': 'Commissioning dates/scheduling, delays, readiness, incomplete work, multi-unit commissioning, follow-up.',
    'system-performance': 'No/low gas, short cooking time, no inflation, gas not reaching stove, weak/unstable performance, unexpected stopping.',
    'leakage': 'Gas escape/smell at stove, kitchen, pipe, joint, connection, digester, bag, burner, cap.',
    'pipe-connection-fault': 'Broken/cracked/loose/disconnected/sagging/burnt/blocked/misaligned pipes, joints, inlets, outlets, supports, connections.',
    'burner-knob-fault': 'Burner/stove not working/lighting/staying on, weak flame, blockage, looseness, broken/stuck knob.',
    'system-damage': 'Tears, punctures, cracks, holes, bursts, fire/weather/animal/falling-object damage to system/components.',
    'blockage': 'Blocked inlet/outlet/pipe/system, backflow, scum, feeding difficulty, contamination.',
    'accessories-delay': 'Accessory/spare-part requests, non-delivery, delays, damage, incompatibility, replacement.',
    'relocation-request': 'System/stove/burner/pipe relocation, rerouting, cooking-point/position/direction changes, decommissioning, scheduling.',
    'technical-support': 'Diagnosis, troubleshooting, technical visits, follow-up, phone support, usage/feeding guidance, training, reinoculation.',
    'appraisal': 'Appraisal readiness, scheduling, delays, pending assessments, valuation questions, outcomes, follow-up.',
    'payments-accounts': 'Balances, repayments, payment status/confirmation, paybill, receipts/statements, outstanding amounts, related payments.',
    'other-complaint': 'Complaints/enquiries outside the listed types.',
}


def update_descriptions(apps, schema_editor):
    ComplaintCategory = apps.get_model('core', 'ComplaintCategory')
    for key, description in CATEGORY_DESCRIPTIONS.items():
        ComplaintCategory.objects.filter(key=key).update(description=description)


class Migration(migrations.Migration):
    dependencies = [('core', '0165_complaint_identity_and_sheet_contract')]
    operations = [
        migrations.RunPython(update_descriptions, migrations.RunPython.noop),
    ]
