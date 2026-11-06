from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal_legacy', '0006_selected_register')]
    operations = [
        migrations.AddField(model_name='legacyupload', name='mode', field=models.CharField(
            choices=[('initial', 'Initial import'), ('updates', 'Update existing cases')], default='initial', max_length=12,
            db_comment='Immutable import intent. Update sessions never authorize deletion, replacement or a register fence.')),
        migrations.RemoveConstraint(model_name='legacyupload', name='portal_legacy_upload_source_unique'),
        migrations.AddConstraint(model_name='legacyupload', constraint=models.UniqueConstraint(
            fields=['batch', 'digest', 'source_sheet', 'mode'], name='portal_legacy_upload_mode_unique')),
        migrations.AddConstraint(model_name='legacyupload', constraint=models.CheckConstraint(
            condition=models.Q(mode__in=['initial', 'updates']), name='portal_legacy_upload_mode_valid')),
    ]
