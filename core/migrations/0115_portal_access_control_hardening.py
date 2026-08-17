from django.db import migrations, models


def backfill_access_request_roles_and_publication_capability(apps, schema_editor):
    from core.services.access_policies import WORKFLOW_ROLES
    from core.services.workflow_capabilities import capabilities_for_workflow

    ChangeRequest = apps.get_model('core', 'AccessControlChangeRequest')
    for request in ChangeRequest.objects.exclude(role='').iterator():
        request.target_roles = [request.role]
        request.save(update_fields=['target_roles'])

    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    for role in ('OPERATIONS_ADMIN', 'IT'):
        Capability.objects.update_or_create(
            workflow='jawabu_portal', role=role,
            capability_key='portal.publication.retry',
            defaults={'enabled': True, 'effect': 'allow'},
        )
    # Materialize the complete fixed-role matrix. Missing rows already fail
    # closed, so explicit denies do not change live authority; they make Admin
    # customization and parity diagnostics deterministic for every code-owned
    # role/capability pair.
    for workflow, roles in WORKFLOW_ROLES.items():
        for role, _label in roles:
            for definition in capabilities_for_workflow(workflow):
                effect = 'allow' if role in definition.default_roles else 'deny'
                Capability.objects.get_or_create(
                    workflow=workflow, role=role,
                    capability_key=definition.key,
                    defaults={'enabled': effect == 'allow', 'effect': effect},
                )


def remove_publication_capability(apps, schema_editor):
    apps.get_model('core', 'WorkflowRoleCapability').objects.filter(
        workflow='jawabu_portal', capability_key='portal.publication.retry',
    ).delete()


class Migration(migrations.Migration):

    dependencies = [('core', '0114_alter_originationdatafield_data_type_and_more')]

    operations = [
        migrations.AddField(
            model_name='accesscontrolchangerequest', name='request_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='accesscontrolchangerequest', name='target_roles',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='emergencyaccessgrant', name='request_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='emergencyaccessgrant', name='revocation_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddConstraint(
            model_name='accesscontrolchangerequest',
            constraint=models.UniqueConstraint(
                condition=~models.Q(request_key=''),
                fields=('requested_by', 'request_key'),
                name='unique_access_change_request_key',
            ),
        ),
        migrations.AddConstraint(
            model_name='emergencyaccessgrant',
            constraint=models.UniqueConstraint(
                condition=~models.Q(request_id=''),
                fields=('activated_by', 'request_id'),
                name='unique_emergency_access_request_id',
            ),
        ),
        migrations.RunPython(
            backfill_access_request_roles_and_publication_capability,
            remove_publication_capability,
        ),
    ]
