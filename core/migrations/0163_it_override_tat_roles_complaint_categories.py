from django.db import migrations
from django.utils import timezone


TAT_ROLES = (
    'BRO', 'BUSINESS_ADMIN', 'CA', 'BM', 'SECRETARY', 'CHAIR',
    'LOAN_APPROVER', 'FINANCE', 'IT', 'MANAGEMENT',
)

TAT_CREATE_ROLES = {'BRO', 'BUSINESS_ADMIN', 'IT'}
TAT_REPORT_ROLES = {'MANAGEMENT', 'IT'}

CATEGORY_CHANGES = (
    ('installation-delay', 'Installation', 'Installation-related complaints of any kind', 'Installation Delay'),
    ('commissioning-delay', 'Commissioning', 'Commissioning and system start-up complaints', 'Commissioning Delay'),
    ('accessories-delay', 'Accessories', 'Accessory supply, condition, compatibility, or support complaints', 'Accessories Delay'),
    ('system-damage', 'System Damage', 'Damage affecting the digester, appliance, or installed system', ''),
    ('technical-support', 'Technical Support', 'Technical guidance, diagnosis, or support requests', ''),
    ('appraisal', 'Appraisal', 'Appraisal, assessment, or valuation-related complaints', ''),
    ('payments-accounts', 'Payments & Accounts', 'Payments, balances, receipts, statements, or account-related complaints', ''),
)


def apply_policy_and_catalogue(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    ChangeRequest = apps.get_model('core', 'AccessControlChangeRequest')
    Category = apps.get_model('core', 'ComplaintCategory')
    Alias = apps.get_model('core', 'ComplaintCategoryAlias')

    Capability.objects.filter(
        workflow='complaint_cases',
        capability_key__in=['complaint.case.claim', 'complaint.case.assign'],
    ).delete()

    # Backfill an explicit allow row for every capability already known to the
    # database. Runtime policy also makes this a permanent invariant for new
    # capabilities introduced after this migration.
    for workflow in ('jawabu_portal', 'complaint_cases', 'tat_tracker', 'spin_credit_analysis'):
        known_keys = Capability.objects.filter(workflow=workflow).values_list(
            'capability_key', flat=True,
        ).distinct()
        for key in known_keys.iterator():
            Capability.objects.update_or_create(
                workflow=workflow, role='IT', capability_key=key,
                defaults={'enabled': True, 'effect': 'allow'},
            )

    for role in TAT_ROLES:
        for key, allowed_roles in (
            ('tat.case.create', TAT_CREATE_ROLES),
            ('tat.reports.view', TAT_REPORT_ROLES),
            ('tat.reports.people.view', TAT_REPORT_ROLES),
        ):
            allowed = role in allowed_roles
            Capability.objects.update_or_create(
                workflow='tat_tracker', role=role, capability_key=key,
                defaults={
                    'enabled': allowed,
                    'effect': 'allow' if allowed else 'deny',
                },
            )

    # An old pending request must not be able to remove the mandatory IT
    # invariant after deployment.
    for request in ChangeRequest.objects.filter(
        change_type='capability_policy', status__in=['draft', 'pending', 'approved'],
    ).iterator(chunk_size=200):
        roles = {str(role or '').strip().upper() for role in (request.target_roles or [request.role])}
        if 'IT' not in roles:
            continue
        request.status = 'cancelled'
        request.reviewed_at = timezone.now()
        request.review_comment = (
            'Cancelled by migration: IT is now the mandatory scoped override role.'
        )
        request.save(update_fields=['status', 'reviewed_at', 'review_comment'])

    for key, label, description, legacy_label in CATEGORY_CHANGES:
        category = Category.objects.filter(key=key).first()
        label_match = Category.objects.filter(label__iexact=label).first()
        if category is not None and label_match is not None and label_match.pk != category.pk:
            suffix = str(label_match.pk).replace('-', '')[:8]
            label_match.label = f'{label_match.label[:140]} (legacy {suffix})'
            label_match.active = False
            label_match.save(update_fields=['label', 'active', 'updated_at'])
            label_match = None
        if category is None:
            category = label_match
        if category is None:
            category = Category.objects.create(
                key=key, label=label, description=description,
                default_priority='normal', default_sla_hours=72, active=True,
            )
        else:
            category.key = key
            category.label = label
            category.description = description
            category.active = True
            category.save(update_fields=['key', 'label', 'description', 'active', 'updated_at'])
        if legacy_label:
            normalized = ' '.join(legacy_label.casefold().split())
            Alias.objects.update_or_create(
                normalized_alias=normalized,
                defaults={'category': category, 'alias': legacy_label, 'active': True},
            )


class Migration(migrations.Migration):
    dependencies = [('core', '0162_complaint_register_cutover')]
    operations = [migrations.RunPython(apply_policy_and_catalogue, migrations.RunPython.noop)]
