"""Migration-only helpers; frozen adopted model names, no runtime service imports."""
MODEL_NAMES = (
    'originationdatafield', 'originationdatafieldevent', 'originationproductdefinition',
    'originationproductdefinitionevent', 'originationfieldreviewissue', 'originationdocumenttemplate',
    'originationdocumentproducteligibility', 'originationproductdocumentassignment',
    'originationdocumenttemplateevent', 'originationtemplateconfigurationrevision',
    'loanoriginationapplication', 'originationcommercialexception', 'originationreportingvalue',
    'originationapplicationevent', 'originationreviewernotice', 'originationcorrectionrequest',
    'originationcorrectionitem', 'originationrequirementevidence', 'originationapplicationdocument',
    'originationconsentpolicyversion', 'originationsigningpackage', 'originationstampasset',
    'originationsignersession', 'originationotpchallenge', 'originationsigningrequestevent',
    'originationsigningaction', 'originationsigningactioninvalidation',
)


def transfer(apps, schema_editor, source, target):
    types = apps.get_model('contenttypes', 'ContentType').objects.using(schema_editor.connection.alias)
    for name in MODEL_NAMES:
        original = types.filter(app_label=source, model=name).first()
        if original is None:
            continue
        if types.filter(app_label=target, model=name).exists():
            raise RuntimeError('Conflicting Origination content types require audited reconciliation.')
        # Permission, user/group membership and admin LogEntry retain their FKs.
        types.filter(pk=original.pk).update(app_label=target)


def forward(apps, schema_editor):
    transfer(apps, schema_editor, 'core', 'origination')


def reverse(apps, schema_editor):
    transfer(apps, schema_editor, 'origination', 'core')


def comment_forward(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for name in MODEL_NAMES:
        model = apps.get_model('origination', name)
        schema_editor.alter_db_table_comment(model, None, model._meta.db_table_comment)
        for field in model._meta.concrete_fields:
            schema_editor.execute(schema_editor.sql_alter_column_comment % {
                'table': schema_editor.quote_name(model._meta.db_table),
                'column': schema_editor.quote_name(field.column),
                'comment': schema_editor.quote_value(field.db_comment or ''),
            })


def comment_reverse(apps, schema_editor):
    # Metadata is informative and safe to retain during a code rollback.
    pass
