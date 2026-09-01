from django.db import migrations


KNOWN = {
    'complaint.queue.view', 'complaint.case.create', 'complaint.case.details.complete',
    'complaint.case.update', 'complaint.case.claim', 'complaint.case.assign',
    'complaint.case.close', 'complaint.case.reopen', 'complaint.case.source.view',
    'complaint.case.evidence.view', 'complaint.case.evidence.manage',
    'complaint.case.sync.retry', 'complaint.case.export', 'complaint.case.manage',
}


def _set_matrix(Capability, matrix):
    for role, allowed in matrix.items():
        for key in KNOWN:
            effect = 'allow' if key in allowed else 'deny'
            Capability.objects.update_or_create(
                workflow='complaint_cases', role=role, capability_key=key,
                defaults={'effect': effect, 'enabled': effect == 'allow'},
            )


def apply_policy(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    _set_matrix(Capability, {
        'OFFICER': {
            'complaint.queue.view', 'complaint.case.create', 'complaint.case.details.complete',
            'complaint.case.evidence.view', 'complaint.case.evidence.manage', 'complaint.case.export',
        },
        'MANAGER': {
            'complaint.queue.view', 'complaint.case.create', 'complaint.case.details.complete',
            'complaint.case.reopen', 'complaint.case.source.view',
            'complaint.case.evidence.view', 'complaint.case.evidence.manage',
            'complaint.case.sync.retry', 'complaint.case.export',
            'complaint.case.update', 'complaint.case.manage',
        },
        'HB_STAFF': {
            'complaint.queue.view', 'complaint.case.close',
            'complaint.case.evidence.view', 'complaint.case.evidence.manage',
        },
        'IT': {'complaint.queue.view', 'complaint.case.sync.retry', 'complaint.case.export'},
    })


def restore_policy(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    Capability.objects.filter(
        workflow='complaint_cases', role='HB_STAFF',
    ).delete()
    _set_matrix(Capability, {
        'OFFICER': {
            'complaint.queue.view', 'complaint.case.create', 'complaint.case.reopen',
            'complaint.case.evidence.view', 'complaint.case.evidence.manage', 'complaint.case.export',
        },
        'MANAGER': {
            'complaint.queue.view', 'complaint.case.update', 'complaint.case.close',
            'complaint.case.reopen', 'complaint.case.source.view',
            'complaint.case.evidence.view', 'complaint.case.evidence.manage',
            'complaint.case.sync.retry', 'complaint.case.export', 'complaint.case.manage',
        },
        'IT': {'complaint.queue.view', 'complaint.case.sync.retry', 'complaint.case.export'},
    })
    Capability.objects.filter(
        workflow='complaint_cases', capability_key='complaint.case.details.complete',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0154_complaint_category_catalogue')]
    operations = [migrations.RunPython(apply_policy, restore_policy)]
