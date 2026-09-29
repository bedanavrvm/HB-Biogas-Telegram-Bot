from django.conf import settings
from django.db import models


class PortalRecognitionPeriodSnapshot(models.Model):
    """Frozen, configuration-owned Portal performance facts for a settled period."""

    id = models.BigAutoField(primary_key=True, db_comment='Immutable Portal performance snapshot identifier.')
    group_configuration_id = models.BigIntegerField(db_comment='Owning Portal group configuration identifier.')
    period_kind = models.CharField(max_length=8, db_comment='Month, quarter, or year.')
    period_key = models.CharField(max_length=12, db_comment='Canonical calendar period key.')
    facts = models.JSONField(db_comment='Frozen attributed action facts; never returned directly to a client.')
    captured_at = models.DateTimeField(auto_now_add=True, db_comment='When the settled period was first captured.')

    class Meta:
        db_table = 'portal_recognition_period_snapshot'
        db_table_comment = 'Immutable settled Portal performance facts; current grants still govern visibility.'
        constraints = [models.UniqueConstraint(
            fields=['group_configuration_id', 'period_kind', 'period_key'],
            name='unique_portal_recognition_period_snapshot',
        )]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('A final Portal performance snapshot cannot be changed.')
        return super().save(*args, **kwargs)


class PortalRecognitionLiveStanding(models.Model):
    """Expiring per-viewer rank baseline, not an authoritative score."""

    id = models.BigAutoField(primary_key=True, db_comment='Live Portal rank checkpoint identifier.')
    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+', db_comment='Viewer whose grants scoped the standing.')
    context_key = models.CharField(max_length=64, unique=True, db_comment='Digest of viewer, grants, period and filters.')
    group_configuration_ids = models.JSONField(default=list, db_comment='Portal configurations represented by this checkpoint.')
    ranks = models.JSONField(default=dict, db_comment='Opaque participant keys and last observed competition ranks.')
    signature = models.CharField(max_length=64, blank=True, db_comment='Digest of last observed standing scores and ranks.')
    movement = models.JSONField(default=dict, db_comment='Movement from the previous distinct standing.')
    observed_at = models.DateTimeField(db_comment='Time the standing calculation began.')
    expires_at = models.DateTimeField(db_comment='Checkpoint expiry for bounded on-demand cleanup.')

    class Meta:
        db_table = 'portal_recognition_live_standing'
        db_table_comment = 'Expiring per-viewer Portal performance movement baseline, never a final award.'
        indexes = [models.Index(fields=['expires_at'], name='portal_live_expiry_idx')]
