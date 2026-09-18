from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0182_contextual_complaint_category_descriptions')]

    operations = [
        migrations.AlterField(
            model_name='portalvoicetranscriptionattempt',
            name='farmer',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='voice_transcription_attempts', to='core.jawabufarmermaster',
            ),
        ),
        migrations.AlterField(
            model_name='portalvoicetranscriptionattempt',
            name='field_name',
            field=models.CharField(
                choices=[
                    ('jbl_visit_comment', 'JBL visit comment'),
                    ('final_decision_comment', 'Final decision after-call comment'),
                    ('complaint_description', 'Complaint description'),
                    ('complaint_resolution_note', 'Complaint resolution note'),
                    ('complaint_reopen_reason', 'Complaint reopening reason'),
                ],
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name='portalvoicetranscriptionattempt',
            name='complaint_group',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='voice_transcription_attempts', to='core.groupsheetconfiguration',
                db_comment='Complaint group that owns this temporary transcription attempt.',
            ),
        ),
        migrations.AddField(
            model_name='portalvoicetranscriptionattempt',
            name='complaint_case',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='voice_transcription_attempts', to='core.parsedmessage',
                db_comment='Complaint case receiving this transcription; null until a new complaint is created.',
            ),
        ),
        migrations.AddConstraint(
            model_name='portalvoicetranscriptionattempt',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(farmer__isnull=False, complaint_group__isnull=True, complaint_case__isnull=True)
                    | models.Q(farmer__isnull=True, complaint_group__isnull=False)
                ),
                name='voice_attempt_has_one_workflow_subject',
            ),
        ),
        migrations.AddIndex(
            model_name='portalvoicetranscriptionattempt',
            index=models.Index(fields=['complaint_group', 'field_name', 'created_at'], name='voice_complaint_group_idx'),
        ),
        migrations.AddIndex(
            model_name='portalvoicetranscriptionattempt',
            index=models.Index(fields=['complaint_case', 'field_name', 'created_at'], name='voice_complaint_case_idx'),
        ),
    ]
