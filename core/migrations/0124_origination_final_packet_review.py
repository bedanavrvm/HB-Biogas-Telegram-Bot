import hashlib
import json
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_existing_package_reviews(apps, schema_editor):
    Package = apps.get_model('core', 'OriginationSigningPackage')
    for package in Package.objects.select_related('application').all().iterator():
        application = package.application
        reviewer_id = application.reviewed_by_id
        if not reviewer_id:
            continue
        unsigned_hash = package.unsigned_document_hash or package.combined_document_hash or ''
        package.prepared_by_id = reviewer_id
        package.prepared_at = application.reviewed_at or package.created_at
        package.reviewed_by_id = reviewer_id
        package.reviewed_at = application.reviewed_at or package.created_at
        review_scope = {
            'unsigned_document_hash': unsigned_hash,
            'context_snapshot': package.context_snapshot,
            'participants_snapshot': package.participants_snapshot,
            'requirement_evidence_snapshot': package.requirement_evidence_snapshot,
            'document_manifest_snapshot': package.document_manifest_snapshot,
            'template_configuration_snapshot': package.template_configuration_snapshot,
        }
        review_scope_hash = hashlib.sha256(json.dumps(
            review_scope, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, default=str,
        ).encode('utf-8')).hexdigest()
        package.review_scope_sha256 = review_scope_hash
        package.approved_unsigned_document_hash = unsigned_hash
        package.approved_review_scope_sha256 = review_scope_hash
        package.save(update_fields=[
            'prepared_by', 'prepared_at', 'reviewed_by', 'reviewed_at',
            'review_scope_sha256', 'approved_unsigned_document_hash',
            'approved_review_scope_sha256',
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0123_origination_verified_signing'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='originationsigningpackage',
            name='approved_review_scope_sha256',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='approved_unsigned_document_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='prepared_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='prepared_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='prepared_origination_review_packages',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='review_scope_sha256',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='reviewed_origination_signing_packages',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name='OriginationReviewerNotice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('notice_type', models.CharField(choices=[('approval_invalidated', 'Approval invalidated by officer recall')], db_index=True, max_length=32)),
                ('message', models.CharField(max_length=500)),
                ('request_id', models.CharField(max_length=128)),
                ('seen_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='reviewer_notices', to='core.loanoriginationapplication')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_origination_reviewer_notices', to=settings.AUTH_USER_MODEL)),
                ('package', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reviewer_notices', to='core.originationsigningpackage')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='origination_reviewer_notices', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='originationreviewernotice',
            constraint=models.UniqueConstraint(fields=('application', 'recipient', 'request_id'), name='unique_orig_reviewer_notice_request'),
        ),
        migrations.RunPython(backfill_existing_package_reviews, migrations.RunPython.noop),
    ]
