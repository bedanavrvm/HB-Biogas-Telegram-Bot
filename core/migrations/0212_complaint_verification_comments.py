from django.db import migrations


def apply_policy(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    State = apps.get_model('core', 'AccessControlPolicyState')
    for role in ('OFFICER', 'MANAGER', 'HB_STAFF', 'IT'):
        additions = ['complaint.case.verification.comment', 'complaint.case.reopen']
        if role == 'IT':
            additions += ['complaint.case.evidence.view', 'complaint.case.evidence.manage']
        for capability in additions:
            Policy.objects.update_or_create(workflow='complaint_cases', role=role, capability_key=capability,
                defaults={'enabled':True, 'effect':'allow' if role != 'HB_STAFF' else 'deny'})
        Audit.objects.create(workflow='complaint_cases', role=role, source='complaint_verification_0212',
            changes={'reason':'JBL append-only verification notes and scoped reopening; HB retains resolution authority; existing IT technical override is unchanged', 'capabilities':additions})
    state, _ = State.objects.get_or_create(singleton=1)
    state.version += 1; state.save(update_fields=['version','updated_at'])
    # Stored complaint schemas must know the new named projection column too.
    Config = apps.get_model('core', 'GroupSheetConfiguration')
    for config in Config.objects.all().iterator():
        if (config.workflow or {}).get('type', 'case') != 'case': continue
        schema = dict(config.sheet_schema or {}) if isinstance(config.sheet_schema, dict) else None
        if schema and 'resolution_comments' in (schema.get('field_headers') or {}):
            schema['field_headers'] = {**schema['field_headers'], 'jbl_verification_comments':'JBL Verification Comments'}
            for key in ('field_order','case_update_fields','bot_writable_fields'):
                if isinstance(schema.get(key),list) and 'jbl_verification_comments' not in schema[key]:schema[key].append('jbl_verification_comments')
            if isinstance(schema.get('columns'), list) and 'JBL Verification Comments' not in schema['columns']:
                schema['columns'].append('JBL Verification Comments')
            config.sheet_schema = schema; config.save(update_fields=['sheet_schema'])


class Migration(migrations.Migration):
    dependencies = [('core','0211_jawabufarmermaster_legacy_fulfillment_partner')]
    operations = [migrations.RunPython(apply_policy)]
