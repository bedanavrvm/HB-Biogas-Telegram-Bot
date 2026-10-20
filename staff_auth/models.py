"""Company-browser admission, separate from authentication and workflow grants."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from .governance import require_mutation


class AdmissionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        require_mutation()
        return super().update(**kwargs)

    def delete(self):
        require_mutation()
        return super().delete()

    def bulk_create(self, *args, **kwargs):
        require_mutation()
        return super().bulk_create(*args, **kwargs)

    def bulk_update(self, *args, **kwargs):
        require_mutation()
        return super().bulk_update(*args, **kwargs)


class StaffBrowserAdmission(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False,
        db_comment='Immutable company-browser admission identifier; never a workflow grant.',
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='browser_login_admission',
        db_comment='Existing staff identity; detached by governed user deletion, never rebound.',
    )
    subject_user_id = models.PositiveBigIntegerField(
        unique=True, editable=False,
        db_comment='Original numeric staff identity retained after user deletion; no personal contact data.',
    )
    enabled = models.BooleanField(
        default=False, db_comment='Explicit browser-channel admission only; MFA and workflow authority remain required.',
    )
    revision = models.PositiveBigIntegerField(
        default=1, db_comment='Browser-only revocation generation; incremented on every accepted lifecycle action.',
    )
    created_at = models.DateTimeField(
        auto_now_add=True, db_comment='When the first audited browser admission was created.',
    )
    updated_at = models.DateTimeField(
        auto_now=True, db_comment='Latest lifecycle boundary; earlier-started authentication cannot qualify.',
    )

    objects = AdmissionQuerySet.as_manager()

    class Meta:
        db_table = 'staff_auth_browser_admission'
        db_table_comment = 'Explicit company-browser opt-in and revocation state, independent of Telegram and workflow grants.'
        constraints = [
            models.CheckConstraint(condition=Q(revision__gte=1), name='staff_browser_revision_positive'),
            models.CheckConstraint(condition=Q(subject_user_id__gte=1), name='staff_browser_subject_positive'),
            models.CheckConstraint(
                condition=Q(user__isnull=True) | Q(user=F('subject_user_id')),
                name='staff_browser_original_user_match',
            ),
        ]

    def save(self, *args, **kwargs):
        require_mutation()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        require_mutation()
        return super().delete(*args, **kwargs)


class StaffTOTPReplayState(models.Model):
    key_digest = models.CharField(
        primary_key=True, max_length=64, editable=False,
        db_comment='Purpose-separated factor-seed HMAC of factor identity and normalized accepted code; no plaintext credential.',
    )
    expires_at = models.DateTimeField(
        db_comment='Earliest safe reuse or cleanup time; live claims must never be evicted.',
    )

    class Meta:
        db_table = 'staff_auth_totp_replay_state'
        db_table_comment = 'Shared one-use TOTP claims for the closed browser MFA adapter; not login assurance or workflow authority.'
        indexes = [models.Index(fields=['expires_at'], name='staff_totp_replay_expiry_idx')]
