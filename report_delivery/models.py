"""Approved configuration and durable, separately scoped email deliveries."""
import uuid
from datetime import time

from django.conf import settings
from django.db import models
from django.utils import timezone


class ScopedConfiguration(models.Model):
    workflow = models.CharField(max_length=24, default='jawabu_portal', choices=[('jawabu_portal', 'Portal'), ('tat_tracker', 'TAT'), ('complaint_cases', 'Complaints')], db_comment='Owning report workflow; approvals never transfer between Mini Apps.')
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Stable configuration identity.')
    group_configuration = models.ForeignKey('core.GroupSheetConfiguration', on_delete=models.PROTECT, related_name='%(class)s_report_configurations', db_comment='Owning Portal group; never inferred from an email address.')
    branch = models.CharField(max_length=120, blank=True, db_comment='Permitted branch; blank means all branches in the owning group.')
    product = models.CharField(max_length=120, blank=True, db_comment='Permitted product code; blank means all products in the owning group.')
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='authorized_%(class)s_reports', editable=False, db_comment='Approving actor whose current IT authority is rechecked before sending; deletion revokes delivery authority.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Configuration creation time.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Last configuration change time.')

    class Meta:
        abstract = True


class ApprovedRecipient(ScopedConfiguration):
    email = models.EmailField(db_comment='Explicitly approved recipient address, not a Portal identity.')
    active = models.BooleanField(default=True, db_comment='Operator approval remains active.')
    suppressed = models.BooleanField(default=False, db_comment='Bounce or complaint blocks all further messages pending IT review.')
    suppression_reason = models.CharField(max_length=40, blank=True, editable=False, db_comment='Provider event category; contains no customer data.')

    class Meta:
        db_table = 'report_delivery_recipient_root'
        db_table_comment = 'Authoritative approved email recipients and group/branch/product disclosure boundaries; retained until explicit administrative removal.'
        constraints = [models.UniqueConstraint(fields=['workflow', 'group_configuration', 'email', 'branch', 'product'], name='report_recipient_scope_unique')]
        ordering = ['email']

    def __str__(self):
        return self.email


class ReportSchedule(ScopedConfiguration):
    title = models.CharField(max_length=100, db_comment='Short operator-facing schedule name.')
    preset = models.CharField(max_length=12, choices=[(v, v.title()) for v in ('pipeline', 'outcomes', 'finance', 'tat', 'complaints')], db_comment='Allowlisted report preset for the owning workflow.')
    county = models.CharField(max_length=120, blank=True, db_comment='Optional narrowing county filter.')
    recipients = models.ManyToManyField(ApprovedRecipient, related_name='schedules', through='ScheduleRecipient')
    frequency = models.CharField(max_length=12, default='daily', choices=[(v, v.title()) for v in ('daily', 'weekly', 'monthly', 'quarterly')], db_comment='Completed Nairobi calendar period cadence.')
    send_time = models.TimeField(default=time(8), db_comment='Nairobi local dispatch time; weekly sends Monday, month/quarter on day one.')
    active = models.BooleanField(default=False, db_comment='Paused by default; runner processes only enabled schedules.')
    skip_empty = models.BooleanField(default=False, db_comment='Skip genuinely empty captured reports, never generation failures.')
    revision = models.PositiveIntegerField(default=1, editable=False, db_comment='Configuration revision; stale queued work is blocked.')
    next_run_at = models.DateTimeField(null=True, blank=True, editable=False, db_comment='Next scheduled UTC occurrence, derived from Nairobi cadence.')
    skipped_occurrences = models.PositiveIntegerField(default=0, editable=False, db_comment='Older due periods deliberately skipped after downtime.')

    class Meta:
        db_table = 'report_delivery_schedule_root'
        db_table_comment = 'Authoritative scoped Portal report schedules; retained until administrative removal; no workflow state ownership.'
        ordering = ['title']

    def __str__(self):
        return self.title


class ScheduleRecipient(models.Model):
    schedule = models.ForeignKey(ReportSchedule, on_delete=models.CASCADE, related_name='recipient_links', db_comment='Owning schedule.')
    recipient = models.ForeignKey(ApprovedRecipient, on_delete=models.PROTECT, related_name='schedule_links', db_comment='Approved destination; must encompass the entire schedule scope.')

    class Meta:
        db_table = 'report_delivery_recipient_link'
        db_table_comment = 'Explicit approved schedule membership; configuration link, retained with schedule.'
        constraints = [models.UniqueConstraint(fields=['schedule', 'recipient'], name='report_schedule_recipient_unique')]


class ReportDelivery(models.Model):
    STATUSES = [(v, v.replace('_', ' ').title()) for v in ('queued', 'processing', 'retry', 'accepted', 'delivered', 'delayed', 'bounced', 'complained', 'failed', 'blocked', 'skipped', 'uncertain')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Durable provider idempotency identity.')
    schedule = models.ForeignKey(ReportSchedule, on_delete=models.PROTECT, related_name='deliveries', db_comment='Schedule configuration retained for 180-day evidence.')
    recipient = models.ForeignKey(ApprovedRecipient, on_delete=models.PROTECT, related_name='deliveries', db_comment='Single approved recipient; addresses are never shared.')
    occurrence = models.CharField(max_length=100, db_comment='Scheduled occurrence or client-supplied manual action UUID.')
    configuration = models.JSONField(default=dict, db_comment='Frozen group, filters, revision, report period and authorization context.')
    status = models.CharField(max_length=12, choices=STATUSES, default='queued', db_comment='Authoritative delivery state; delivered does not imply read.')
    payload = models.JSONField(default=dict, editable=False, db_comment='Exact Resend request and base64 attachments; erased after 30 days.')
    payload_hash = models.CharField(max_length=64, blank=True, editable=False, db_comment='SHA-256 of frozen request bytes retained as evidence.')
    snapshot = models.JSONField(default=dict, editable=False, db_comment='Captured report shared by summary/PDF/XLSX; erased after 30 days.')
    provider_id = models.CharField(max_length=100, blank=True, editable=False, db_comment='Resend email identity for webhook correlation.')
    attempts = models.PositiveSmallIntegerField(default=0, editable=False, db_comment='Bounded submission attempt count.')
    first_attempt_at = models.DateTimeField(null=True, editable=False, db_comment='Start of provider 24-hour idempotency window.')
    next_attempt_at = models.DateTimeField(default=timezone.now, db_comment='Next eligible retry time.')
    lease_token = models.UUIDField(null=True, editable=False, db_comment='Current worker ownership token.')
    lease_until = models.DateTimeField(null=True, editable=False, db_comment='Bounded lease expiry for restart recovery.')
    error_code = models.CharField(max_length=60, blank=True, editable=False, db_comment='Safe error category; never raw provider content.')
    last_event_at = models.DateTimeField(null=True, editable=False, db_comment='Provider event timestamp for ordering evidence.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Reservation time; metadata expires after 180 days.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Most recent status change.')

    @property
    def issue(self):
        return {
            'scope_or_recipient_changed': 'Review report access and approved recipients.',
            'idempotency_window_expired': 'Check delivery in Resend before sending again.',
            'report_generation_failed': 'Report could not be built. Ask IT to check the renderer and data.',
            'attachments_too_large': 'Narrow the report scope; attachments are too large.',
            'empty_report': 'No matching cases; skipped by this schedule.',
            'delivery_not_configured': 'Configure email delivery before retrying.',
            'submission_network_error': 'Connection failed; retry is scheduled.',
            'provider_temporarily_unavailable': 'Email provider unavailable; retry is scheduled.',
            'provider_rejected_request': 'Check the verified sender and delivery settings in Resend.',
            'provider_response_unreadable': 'Provider reply could not be read; retry uses the same key.',
            'idempotency_payload_conflict': 'Submission conflict. Ask IT to review the retained payload.',
        }.get(self.error_code, '')

    class Meta:
        db_table = 'report_delivery_message_root'
        db_table_comment = 'Durable per-recipient report delivery and retry evidence; payload 30 days, metadata 180 days; source of truth for delivery only.'
        constraints = [models.UniqueConstraint(fields=['schedule', 'recipient', 'occurrence'], name='report_delivery_occurrence_unique')]
        indexes = [models.Index(fields=['status', 'next_attempt_at'], name='report_delivery_due_idx'),
                   models.Index(fields=['provider_id'], name='report_delivery_provider_idx')]
        ordering = ['-created_at']


class WebhookReceipt(models.Model):
    event_id = models.CharField(max_length=100, primary_key=True, db_comment='Verified Svix message identity; replay deduplication key.')
    provider_id = models.CharField(max_length=100, db_comment='Resend email identity; no recipient address retained.')
    event_type = models.CharField(max_length=40, db_comment='Allowlisted delivery event category.')
    occurred_at = models.DateTimeField(db_comment='Signed provider event time.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Receipt time; evidence expires after 180 days.')

    class Meta:
        db_table = 'report_delivery_webhook_event'
        db_table_comment = 'Immutable verified provider event receipt, deduplicated by Svix identity; metadata retained 180 days.'
        indexes = [models.Index(fields=['provider_id', 'occurred_at'], name='report_webhook_provider_idx')]
