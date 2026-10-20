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


class StaffBrowserSetupGrant(models.Model):
    PREPARED = 'prepared'
    VERIFIED = 'verified'
    COMPLETED = 'completed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Opaque initial-setup identifier; never sufficient to authenticate.')
    admission = models.ForeignKey(
        StaffBrowserAdmission, on_delete=models.PROTECT, related_name='initial_setup_grants',
        db_comment='Existing browser admission retained on user deletion; no new staff identity or workflow grant.',
    )
    admission_revision = models.PositiveBigIntegerField(db_comment='Exact admission generation authorized for this setup; later changes revoke it.')
    email_address_id = models.PositiveBigIntegerField(db_comment='Native address ID, deliberately not an FK so native credential deletion remains independent; rechecked on every request.')
    email_fingerprint = models.CharField(max_length=64, db_comment='Keyed fingerprint of the approved current canonical address; no plaintext address.')
    password_fingerprint = models.CharField(max_length=64, db_comment='Keyed fingerprint of the original unusable encoded password; never a new-password verifier.')
    confirmation_cipher = models.TextField(db_comment='Dedicated-key ciphertext of the issued native mailbox proof; erased on completion, never exported to operators.')
    prepared_audit_id = models.UUIDField(db_comment='Immutable preparation receipt ID; resolved against the compliance ledger without deletion coupling.')
    state = models.CharField(max_length=12, default=PREPARED, choices=[(PREPARED, 'Prepared'), (VERIFIED, 'Verified'), (COMPLETED, 'Completed')], db_comment='Server-owned initial-setup progress; never login or MFA assurance.')
    verify_request_key = models.CharField(max_length=36, blank=True, default='', db_comment='Mailbox verification request UUID; exact retry only.')
    verify_audit_id = models.UUIDField(null=True, blank=True, db_comment='Successful mailbox-proof audit receipt; not a browser login receipt.')
    session_digest = models.CharField(max_length=64, blank=True, default='', db_comment='Keyed binding to the anonymous setup session; no raw session credential.')
    completed_request_key = models.CharField(max_length=36, blank=True, default='', db_comment='First-password completion request UUID; exact retry only.')
    completed_audit_id = models.UUIDField(null=True, blank=True, db_comment='Atomic first-password receipt; native password and workflow grants remain separate.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Preparation time for this bounded setup capability.')
    expires_at = models.DateTimeField(db_comment='Absolute setup expiry, including verification and completion retries.')

    class Meta:
        db_table = 'staff_auth_browser_setup_grant'
        db_table_comment = 'Temporary closed initial-setup capability for an existing admitted non-Admin account; no operational mail delivery or login authority.'
        indexes = [models.Index(fields=['expires_at'], name='staff_setup_expiry_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(admission_revision__gte=1), name='staff_setup_revision_positive'),
            models.CheckConstraint(condition=Q(email_address_id__gte=1), name='staff_setup_address_positive'),
            models.CheckConstraint(condition=Q(state__in=['prepared', 'verified', 'completed']), name='staff_setup_known_state'),
            models.CheckConstraint(
                condition=Q(state='prepared') | (Q(verify_audit_id__isnull=False) & ~Q(verify_request_key='') & ~Q(session_digest='')),
                name='staff_setup_verified_receipt',
            ),
            models.CheckConstraint(
                condition=~Q(state='completed') | (Q(completed_audit_id__isnull=False) & ~Q(completed_request_key='') & Q(confirmation_cipher='')),
                name='staff_setup_completed_receipt',
            ),
        ]
