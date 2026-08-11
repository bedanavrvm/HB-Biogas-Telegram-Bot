from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0102_portal_voice_transcription_attempt'),
    ]

    operations = [
        migrations.AddField(
            model_name='portalvoicetranscriptionattempt',
            name='average_log_probability',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='portalvoicetranscriptionattempt',
            name='detected_language',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='portalvoicetranscriptionattempt',
            name='requested_language',
            field=models.CharField(db_index=True, default='auto', max_length=8),
        ),
    ]
