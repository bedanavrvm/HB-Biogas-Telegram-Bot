import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='ReviewRevision', fields=[
            ('id', models.UUIDField(db_comment='Immutable design revision identifier.', default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('pattern', models.SlugField(db_comment='Permanent catalogue pattern key, never a customer reference.', max_length=80)),
            ('fingerprint', models.CharField(db_comment='SHA256 of canonical source-bound revision manifest.', max_length=64, unique=True)),
            ('manifest', models.JSONField(db_comment='Frozen source, alternatives, fixture, evidence and proposal manifest.')),
            ('created_at', models.DateTimeField(auto_now_add=True, db_comment='Revision submission time in UTC.')),
            ('created_by', models.ForeignKey(db_comment='Superuser who submitted this revision; no workflow authority is conferred.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
        ], options={'db_table': 'ui_review_revision_root', 'db_table_comment': 'Immutable source-bound design comparisons; retained indefinitely pending an approved retention policy.', 'ordering': ['-created_at', '-id']}),
        migrations.CreateModel(name='ReviewDecision', fields=[
            ('id', models.UUIDField(db_comment='Immutable review event identifier.', default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('decision', models.CharField(choices=[('adopt', 'Adopt as is'), ('changes', 'Adopt with changes'), ('decline', 'Reject all'), ('defer', 'Defer'), ('approve', 'Approve proposal'), ('device', 'Record device check')], db_comment='Human choice; changes and device checks are not design approval.', max_length=16)),
            ('payload', models.JSONField(db_comment='Selected variant, reason, use guidance and privacy-safe device observations.', default=dict)),
            ('request_key', models.UUIDField(db_comment='Idempotency key bound to actor, revision and exact decision meaning.', unique=True)),
            ('created_at', models.DateTimeField(auto_now_add=True, db_comment='Decision time in UTC; earlier events remain available.')),
            ('actor', models.ForeignKey(db_comment='Active Superuser who made the decision.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ('revision', models.ForeignKey(db_comment='Exact source and evidence revision reviewed.', on_delete=django.db.models.deletion.PROTECT, related_name='decisions', to='ui_review.reviewrevision')),
        ], options={'db_table': 'ui_review_decision_event', 'db_table_comment': 'Append-only human design decisions and device checks; retained with reviewed revisions.', 'ordering': ['-created_at', '-id']}),
        migrations.CreateModel(name='StandardRelease', fields=[
            ('id', models.UUIDField(db_comment='Immutable standard release identifier.', default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('version', models.PositiveIntegerField(db_comment='Monotonic standard version; publishing does not migrate applications.', unique=True)),
            ('manifest', models.JSONField(db_comment='Exact approved decisions, source hashes, theme IDs and migration hold.')),
            ('fingerprint', models.CharField(db_comment='Canonical release manifest digest.', max_length=64, unique=True)),
            ('request_key', models.UUIDField(db_comment='Idempotency key for explicit standard release preparation.', unique=True)),
            ('created_at', models.DateTimeField(auto_now_add=True, db_comment='Release creation time in UTC.')),
            ('actor', models.ForeignKey(db_comment='Superuser who prepared this standard release.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
        ], options={'db_table': 'ui_review_standard_root', 'db_table_comment': 'Immutable approved UI standard versions; no operational rollout side effects; retained indefinitely.', 'ordering': ['-version'],}),
    ]
