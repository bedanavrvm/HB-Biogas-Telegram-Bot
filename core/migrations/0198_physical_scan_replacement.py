from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0197_complaint_resolution_comments')]
    operations = [migrations.AlterField(
        model_name='documentphysicalsignoff', name='status',
        field=models.CharField(max_length=32, db_index=True, default='upload_pending', choices=[
            ('upload_pending', 'Upload pending'), ('signed_approved', 'Signed scan approved'),
            ('upload_failed', 'Upload retry required'), ('rejected', 'Rejected'),
            ('superseded', 'Replaced scan retained'),
        ]),
    ), migrations.AlterField(
        model_name='documentphysicalsignoffevent', name='action',
        field=models.CharField(max_length=32, db_index=True, choices=[
            ('replaced', 'Replaced scan'), ('submitted', 'Submitted'), ('approved', 'Approved'),
            ('upload_failed', 'Upload failed'), ('retry_started', 'Retry started'), ('rejected', 'Rejected'),
        ]),
    )]
