from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('origination', '0003_independent_capabilities')]
    operations = [
        migrations.AlterField('originationreviewernotice', 'notice_type', models.CharField(
            max_length=32, db_index=True, db_comment='Notice type (CharField).',
            choices=[('approval_invalidated', 'Approval invalidated by officer recall'),
                     ('approval_ready', 'Ready for approval and signature')])),
        migrations.AddField('originationproductdefinition', 'approval_roles', models.JSONField(
            default=list, blank=True,
            help_text='Ordered approval signatures. Empty retains independent review; ["branch_manager"] enables BM approval and signing on a new published version.',
            db_comment='Versioned ordered final-approval roles; empty preserves legacy independent review.')),
        migrations.AddField('loanoriginationapplication', 'approval_roles_snapshot', models.JSONField(
            default=list, blank=True, db_comment='Immutable creation snapshot of the ordered approval signatures; never backfilled.')),
        migrations.AddField('originationconsentpolicyversion', 'approval_roles', models.JSONField(
            default=list, blank=True,
            help_text='Approval sequence explicitly covered by this compliance-approved wording. Empty means independent post-sign review.',
            db_comment='Approval sequence covered by the immutable consent wording; empty means legacy review.')),
    ]
