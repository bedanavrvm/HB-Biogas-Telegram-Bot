from django.conf import settings
from django.db import models


class TatRecognitionPeriodSnapshot(models.Model):
    """One immutable, group-wide set of completed-stage facts for a settled period."""

    id = models.BigAutoField(primary_key=True, db_comment='Immutable final recognition snapshot identifier.')
    group_id = models.CharField(max_length=100, db_comment='TAT group whose settled results were captured.')
    scope_key = models.CharField(max_length=64, db_comment='Production or active Pilot cycle at capture time.')
    period_kind = models.CharField(max_length=8, db_comment='Month, quarter, or year aggregation.')
    period_key = models.CharField(max_length=12, db_comment='Canonical YYYY-MM, YYYY-QN, or YYYY period.')
    facts = models.JSONField(db_comment='Frozen stage facts for period actions and qualifying branch cases; contains staff identity and is never sent directly to clients.')
    captured_at = models.DateTimeField(auto_now_add=True, db_comment='Time the first eligible request froze this period.')

    class Meta:
        db_table = 'tat_recognition_period_snapshot'
        db_table_comment = 'Immutable final TAT recognition facts; current access is checked before any projection.'
        constraints = [models.UniqueConstraint(
            fields=['group_id', 'scope_key', 'period_kind', 'period_key'],
            name='unique_tat_recognition_period_snapshot',
        )]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('A final TAT recognition snapshot cannot be changed.')
        return super().save(*args, **kwargs)


class TatRecognitionLiveStanding(models.Model):
    """Short-lived per-viewer baseline for movement within one live standing."""

    id = models.BigAutoField(primary_key=True, db_comment='Live standing checkpoint identifier.')
    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tat_recognition_live_standings', db_comment='Viewer whose current access scope defines this standing.')
    group_id = models.CharField(max_length=100, db_comment='TAT group for reset and pilot cleanup.')
    scope_key = models.CharField(max_length=64, db_comment='Production or Pilot cycle represented by this standing.')
    context_key = models.CharField(max_length=64, unique=True, db_comment='SHA-256 of viewer, access grants, period, view, and selected filters.')
    ranks = models.JSONField(default=dict, db_comment='Last confirmed opaque participant keys mapped to competition ranks.')
    signature = models.CharField(max_length=64, blank=True, db_comment='SHA-256 of last confirmed scores and ranks; excludes names.')
    movement = models.JSONField(default=dict, db_comment='Current rank change against the previous confirmed standing.')
    observed_at = models.DateTimeField(db_comment='Time scoring began, used to reject stale concurrent results.')
    expires_at = models.DateTimeField(db_comment='Checkpoint expires after the live period settles.')

    class Meta:
        db_table = 'tat_recognition_live_standing'
        db_table_comment = 'Expiring per-viewer TAT recognition rank baselines; not an authoritative score or final award.'
        indexes = [models.Index(fields=['expires_at'], name='tat_live_expiry_idx')]
