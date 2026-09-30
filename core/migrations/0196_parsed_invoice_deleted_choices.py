from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0195_invoice_upload_content_sha256'),
    ]

    operations = [
        migrations.AlterField(
            model_name='parsedinvoice',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('unmatched', 'Unmatched'),
                    ('matched', 'Matched'),
                    ('ambiguous', 'Ambiguous'),
                    ('ignored', 'Ignored'),
                    ('superseded', 'Superseded'),
                    ('deleted', 'Deleted'),
                ],
                db_index=True,
                default='unmatched',
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='parsedinvoiceevent',
            name='action',
            field=models.CharField(
                choices=[
                    ('uploaded', 'Uploaded'),
                    ('parsed', 'Parsed'),
                    ('matched', 'Matched'),
                    ('unmatched', 'Unmatched'),
                    ('ignored', 'Ignored'),
                    ('restored', 'Restored'),
                    ('deleted', 'Deleted'),
                    ('note', 'Note'),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
