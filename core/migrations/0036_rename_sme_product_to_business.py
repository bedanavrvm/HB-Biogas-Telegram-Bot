from django.db import migrations


def rename_sme_to_business(apps, schema_editor):
    """Rename product key 'sme' -> 'business' and label 'SME' -> 'Business' in all TAT tracker records."""

    TatTrackerCase = apps.get_model('core', 'TatTrackerCase')
    TatTrackerStaffMember = apps.get_model('core', 'TatTrackerStaffMember')
    GroupSheetConfiguration = apps.get_model('core', 'GroupSheetConfiguration')

    # Update TatTrackerCase: product_key and product_label
    TatTrackerCase.objects.filter(product_key='sme').update(
        product_key='business',
        product_label='Business',
    )

    # Update TatTrackerCase: sheet_name
    TatTrackerCase.objects.filter(sheet_name='TRACKER-SME').update(
        sheet_name='TRACKER-Business',
    )

    # Update TatTrackerStaffMember: products CSV field (may contain 'sme' as one of multiple values)
    for member in TatTrackerStaffMember.objects.all():
        products = member.products
        parts = [p.strip() for p in (products or '').split(',') if p.strip()]
        updated = ['business' if p == 'sme' else p for p in parts]
        new_value = ','.join(updated) if updated else 'ALL'
        if new_value != products:
            TatTrackerStaffMember.objects.filter(pk=member.pk).update(products=new_value)

    # Update GroupSheetConfiguration: workflow JSON (products list and tat_targets_minutes keys)
    for config in GroupSheetConfiguration.objects.all():
        workflow = config.workflow
        if not isinstance(workflow, dict):
            continue

        changed = False

        # Update products list
        products = workflow.get('products')
        if isinstance(products, list) and 'sme' in products:
            workflow['products'] = ['business' if p == 'sme' else p for p in products]
            changed = True

        # Update tat_targets_minutes
        targets = workflow.get('tat_targets_minutes')
        if isinstance(targets, dict) and 'sme' in targets:
            targets['business'] = targets.pop('sme')
            changed = True

        # Update sheet_name in workflow config (if stored there)
        if workflow.get('sheet_name') == 'TRACKER-SME':
            workflow['sheet_name'] = 'TRACKER-Business'
            changed = True

        if changed:
            GroupSheetConfiguration.objects.filter(pk=config.pk).update(workflow=workflow)

    # Update GroupSheetConfiguration: sheet_name top-level field
    GroupSheetConfiguration.objects.filter(sheet_name='TRACKER-SME').update(
        sheet_name='TRACKER-Business',
    )


def reverse_rename(apps, schema_editor):
    """Reverse: rename 'business' -> 'sme'."""

    TatTrackerCase = apps.get_model('core', 'TatTrackerCase')
    TatTrackerStaffMember = apps.get_model('core', 'TatTrackerStaffMember')
    GroupSheetConfiguration = apps.get_model('core', 'GroupSheetConfiguration')

    TatTrackerCase.objects.filter(product_key='business').update(
        product_key='sme',
        product_label='SME',
    )
    TatTrackerCase.objects.filter(sheet_name='TRACKER-Business').update(
        sheet_name='TRACKER-SME',
    )

    for member in TatTrackerStaffMember.objects.all():
        products = member.products
        parts = [p.strip() for p in (products or '').split(',') if p.strip()]
        updated = ['sme' if p == 'business' else p for p in parts]
        new_value = ','.join(updated) if updated else 'ALL'
        if new_value != products:
            TatTrackerStaffMember.objects.filter(pk=member.pk).update(products=new_value)

    for config in GroupSheetConfiguration.objects.all():
        workflow = config.workflow
        if not isinstance(workflow, dict):
            continue

        changed = False
        products = workflow.get('products')
        if isinstance(products, list) and 'business' in products:
            workflow['products'] = ['sme' if p == 'business' else p for p in products]
            changed = True

        targets = workflow.get('tat_targets_minutes')
        if isinstance(targets, dict) and 'business' in targets:
            targets['sme'] = targets.pop('business')
            changed = True

        if workflow.get('sheet_name') == 'TRACKER-Business':
            workflow['sheet_name'] = 'TRACKER-SME'
            changed = True

        if changed:
            GroupSheetConfiguration.objects.filter(pk=config.pk).update(workflow=workflow)

    GroupSheetConfiguration.objects.filter(sheet_name='TRACKER-Business').update(
        sheet_name='TRACKER-SME',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_caseupdate_unique_complaint_case_update_request'),
    ]

    operations = [
        migrations.RunPython(rename_sme_to_business, reverse_code=reverse_rename),
    ]
