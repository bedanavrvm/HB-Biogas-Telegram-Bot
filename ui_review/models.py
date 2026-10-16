"""Design evidence, not operational workflow state or permission grants."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ImmutableRecord(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Create a new revision; saved design records cannot be edited.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Design review history is retained.')


class ReviewRevision(ImmutableRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable design revision identifier.')
    pattern = models.SlugField(max_length=80, db_comment='Permanent catalogue pattern key, never a customer reference.')
    fingerprint = models.CharField(max_length=64, unique=True, db_comment='SHA256 of canonical source-bound revision manifest.')
    manifest = models.JSONField(db_comment='Frozen source, alternatives, fixture, evidence and proposal manifest.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', db_comment='Superuser who submitted this revision; no workflow authority is conferred.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Revision submission time in UTC.')

    class Meta:
        db_table = 'ui_review_revision_root'
        db_table_comment = 'Immutable source-bound design comparisons; retained indefinitely pending an approved retention policy.'
        ordering = ['-created_at', '-id']


class ReviewDecision(ImmutableRecord):
    CHOICES = [('adopt', 'Adopt as is'), ('changes', 'Adopt with changes'), ('decline', 'Reject all'),
               ('defer', 'Defer'), ('approve', 'Approve proposal'), ('device', 'Record device check')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable review event identifier.')
    revision = models.ForeignKey(ReviewRevision, on_delete=models.PROTECT, related_name='decisions', db_comment='Exact source and evidence revision reviewed.')
    decision = models.CharField(max_length=16, choices=CHOICES, db_comment='Human choice; changes and device checks are not design approval.')
    payload = models.JSONField(default=dict, db_comment='Selected variant, reason, use guidance and privacy-safe device observations.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', db_comment='Active Superuser who made the decision.')
    request_key = models.UUIDField(unique=True, db_comment='Idempotency key bound to actor, revision and exact decision meaning.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Decision time in UTC; earlier events remain available.')

    class Meta:
        db_table = 'ui_review_decision_event'
        db_table_comment = 'Append-only human design decisions and device checks; retained with reviewed revisions.'
        ordering = ['-created_at', '-id']


class StandardRelease(ImmutableRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable standard release identifier.')
    version = models.PositiveIntegerField(unique=True, db_comment='Monotonic standard version; publishing does not migrate applications.')
    manifest = models.JSONField(db_comment='Exact approved decisions, source hashes, theme IDs and migration hold.')
    fingerprint = models.CharField(max_length=64, unique=True, db_comment='Canonical release manifest digest.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', db_comment='Superuser who prepared this standard release.')
    request_key = models.UUIDField(unique=True, db_comment='Idempotency key for explicit standard release preparation.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Release creation time in UTC.')

    class Meta:
        db_table = 'ui_review_standard_root'
        db_table_comment = 'Immutable approved UI standard versions; no operational rollout side effects; retained indefinitely.'
        ordering = ['-version']
