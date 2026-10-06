from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0200_alter_accesscontrolchangerequest_workflow_and_more')]

    operations = [
        migrations.AlterField(
            model_name='portalvoicetranscriptionattempt',
            name='field_name',
            field=models.CharField(max_length=64, choices=[
                ('jbl_visit_comment', 'JBL visit comment'),
                ('credit_decision_comment', 'Credit decision comment'),
                ('final_decision_comment', 'Final decision after-call comment'),
                ('complaint_description', 'Complaint description'),
                ('complaint_resolution_note', 'Complaint resolution note'),
                ('complaint_resolution_comment', 'Complaint resolution comment'),
                ('complaint_reopen_reason', 'Complaint reopening reason'),
            ]),
        ),
    ]
