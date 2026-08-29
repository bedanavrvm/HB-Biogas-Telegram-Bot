from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


INITIAL_REASON = 'Initial migration — business-hours TAT retained as enabled.'


def seed_tat_presentation_settings(apps, schema_editor):
    TatPresentationSettings = apps.get_model('core', 'TatPresentationSettings')
    TatConfigurationEvent = apps.get_model('core', 'TatConfigurationEvent')
    row, created = TatPresentationSettings.objects.get_or_create(
        singleton=1,
        defaults={
            'business_time_enabled': True,
            'revision': 1,
            'change_reason': INITIAL_REASON,
        },
    )
    if created:
        TatConfigurationEvent.objects.create(
            action='tat.presentation.initialized',
            reason=INITIAL_REASON,
            before_snapshot={},
            after_snapshot={
                'business_time_enabled': True,
                'revision': 1,
            },
            metadata={'scope': 'global', 'source': 'migration'},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0146_tat_finality_additional_workflow_onboarding'),
    ]

    operations = [
        migrations.CreateModel(
            name='TatPresentationSettings',
            fields=[
                ('singleton', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('business_time_enabled', models.BooleanField(default=True)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('change_reason', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_tat_presentation_settings', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'TAT presentation setting',
                'verbose_name_plural': 'TAT presentation settings',
            },
        ),
        migrations.AddConstraint(
            model_name='tatpresentationsettings',
            constraint=models.CheckConstraint(condition=models.Q(('singleton', 1)), name='tat_presentation_singleton_one'),
        ),
        migrations.RunPython(seed_tat_presentation_settings, migrations.RunPython.noop),
    ]
