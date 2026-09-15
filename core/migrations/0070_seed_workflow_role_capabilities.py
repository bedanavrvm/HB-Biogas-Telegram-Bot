"""Seed the editable matrix with the role policy that existed before it."""

from django.db import migrations


# Keep the original pre-catalogue TAT stage policy self-contained. Importing
# ``capability_definitions()`` here used to resolve the *current* database
# catalogues while the historical schema was only at migration 0069. SQLite
# tolerated the caught missing-column error; PostgreSQL correctly left the
# surrounding migration transaction aborted.
LEGACY_TAT_STAGES = (
    ('mpesa_to_admin', 'MPESA sent to Admin', 'BRO'),
    ('mpesa_verified', 'MPESA verified by Business Admin and sent to CA', 'BUSINESS_ADMIN'),
    ('ca_analysis_sent', 'Credit analysis sent', 'CA'),
    ('bro_response', 'BRO response to CA', 'BRO'),
    ('bm_response', 'BM response to CA', 'BM'),
    ('valuation_ready', 'Valuation ready', 'BM'),
    ('bm_tat_request', 'BM TAT request sent', 'BM'),
    ('tat_scheduled', 'HOCC scheduled', 'SECRETARY'),
    ('tat_held', 'HOCC held', 'SECRETARY'),
    ('decision', 'Decision', 'CHAIR'),
    ('minutes_shared', 'Minutes shared', 'SECRETARY'),
    ('sanctions', 'Sanctions', 'LOAN_APPROVER'),
    ('bro_applied', 'BRO applied on system', 'BRO'),
    ('disbursement_register', 'Business Admin disbursement register', 'BUSINESS_ADMIN'),
    ('register_approved', 'Register approved', 'LOAN_APPROVER'),
    ('disbursement', 'Finance disbursement', 'FINANCE'),
)


def seed_capabilities(apps, schema_editor):
    # Import the reviewed, code-owned catalogue rather than accepting a data
    # value from an external system.  The migration creates explicit rows so
    # later Admin edits are immediately authoritative.
    from core.services.workflow_capabilities import _STATIC_CAPABILITIES

    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    for definition in _STATIC_CAPABILITIES:
        for role in definition.default_roles:
            Capability.objects.get_or_create(
                workflow=definition.workflow,
                role=role,
                capability_key=definition.key,
                defaults={'enabled': True},
            )
    for stage_key, _label, owner_role in LEGACY_TAT_STAGES:
        for role in {owner_role, 'IT'}:
            Capability.objects.get_or_create(
                workflow='tat_tracker',
                role=role,
                capability_key=f'tat.stage.{stage_key}.update',
                defaults={'enabled': True},
            )


class Migration(migrations.Migration):

    dependencies = [('core', '0069_workflowrolecapability_and_more')]

    operations = [migrations.RunPython(seed_capabilities, migrations.RunPython.noop)]
