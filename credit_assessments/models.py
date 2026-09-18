import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class CreditAssessment(models.Model):
    """Authoritative credit-assessment state linked to exactly one TAT case."""

    STATE_DRAFT = 'draft'
    STATE_PENDING_AUTHORIZATION = 'pending_authorization'
    STATE_RETURNED_PRE_ANALYSIS = 'returned_pre_analysis'
    STATE_ANALYSIS = 'analysis'
    STATE_BRO_REVIEW = 'bro_review'
    STATE_ANALYST_VALIDATION = 'analyst_validation'
    STATE_PENDING_DECISION = 'pending_decision'
    STATE_RETURNED_TO_BRO = 'returned_to_bro'
    STATE_APPROVED = 'approved'
    STATE_DECLINED = 'declined'
    STATE_CHOICES = [
        (STATE_DRAFT, 'Pre-appraisal draft'),
        (STATE_PENDING_AUTHORIZATION, 'Awaiting Branch Manager authorization'),
        (STATE_RETURNED_PRE_ANALYSIS, 'Returned for a full-year statement'),
        (STATE_ANALYSIS, 'Credit analysis in progress'),
        (STATE_BRO_REVIEW, 'Awaiting BRO review'),
        (STATE_ANALYST_VALIDATION, 'Awaiting analyst validation'),
        (STATE_PENDING_DECISION, 'Awaiting Branch Manager decision'),
        (STATE_RETURNED_TO_BRO, 'Returned to BRO'),
        (STATE_APPROVED, 'Approved'),
        (STATE_DECLINED, 'Declined'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable credit-assessment identifier.')
    tat_case = models.OneToOneField(
        'core.TatTrackerCase', on_delete=models.PROTECT, related_name='credit_assessment',
        db_comment='TAT case whose timing, product, branch, and operational identity govern this assessment.',
    )
    state = models.CharField(max_length=32, choices=STATE_CHOICES, default=STATE_DRAFT, db_index=True, db_comment='Current server-controlled assessment lifecycle state.')
    revision = models.PositiveBigIntegerField(default=1, db_comment='Optimistic concurrency revision incremented by every accepted mutation.')
    statement_receipt = models.ForeignKey(
        'StatementMailReceipt', null=True, blank=True, on_delete=models.PROTECT,
        related_name='linked_assessments', db_comment='Confirmed Gmail statement receipt linked to this case.',
    )
    statement_period_start = models.DateField(null=True, blank=True, db_comment='Chronologically earlier date parsed from the statement filename or subject.')
    statement_period_end = models.DateField(null=True, blank=True, db_comment='Chronologically later date parsed from the statement filename or subject.')
    statement_full_year = models.BooleanField(null=True, blank=True, db_comment='Whether statement coverage satisfies the twelve-calendar-month policy.')
    signed_laf_reference = models.CharField(max_length=255, blank=True, default='', db_comment='Governed Origination reference or historical LAF evidence reference relied on for consent.')
    signed_laf_hash = models.CharField(max_length=64, blank=True, default='', db_comment='SHA-256 of the exact signed LAF relied upon for consent.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='BRO who opened the assessment.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Server time when assessment tracking began.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Server time of the latest accepted assessment mutation.')

    class Meta:
        db_table = 'credit_assessment_case_root'
        db_table_comment = 'Django source of truth for the governed credit-assessment lifecycle attached to one TAT case.'
        indexes = [models.Index(fields=['state', 'updated_at'], name='credit_assessment_state_idx')]


class StatementMailReceipt(models.Model):
    STATUS_UNCLAIMED = 'unclaimed'
    STATUS_LINKED = 'linked'
    STATUS_AMBIGUOUS = 'ambiguous'
    STATUS_IGNORED = 'ignored'
    STATUS_INVALID = 'invalid'
    STATUS_CHOICES = [
        (STATUS_UNCLAIMED, 'Unclaimed'), (STATUS_LINKED, 'Linked'),
        (STATUS_AMBIGUOUS, 'Needs review'), (STATUS_IGNORED, 'Ignored'),
        (STATUS_INVALID, 'Invalid'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable mailbox-receipt identifier.')
    gmail_message_id = models.CharField(max_length=255, db_comment='Gmail message identifier used with the attachment identifier for idempotent ingestion.')
    gmail_attachment_id = models.CharField(max_length=255, db_comment='Gmail attachment identifier used with the message identifier for idempotent ingestion.')
    gmail_thread_id = models.CharField(max_length=255, blank=True, default='', db_comment='Gmail thread identifier retained for operational traceability.')
    forwarding_sender = models.EmailField(blank=True, default='', db_index=True, db_comment='Normalized staff email that forwarded the statement.')
    subject = models.CharField(max_length=998, blank=True, default='', db_comment='Forwarded subject containing only the provider supplied masked phone and period.')
    original_sent_at = models.DateTimeField(null=True, blank=True, db_comment='Original forwarded-message time when recoverable from message evidence.')
    inbox_received_at = models.DateTimeField(db_index=True, db_comment='Trusted time the dedicated Gmail inbox received the forward.')
    original_time_source = models.CharField(max_length=32, blank=True, default='', db_comment='Evidence quality label for original_sent_at.')
    attachment_name = models.CharField(max_length=255, db_comment='Validated M-PESA statement filename.')
    attachment_hash = models.CharField(max_length=64, db_index=True, db_comment='SHA-256 of the encrypted source PDF.')
    attachment_size = models.PositiveBigIntegerField(db_comment='Encrypted source PDF size in bytes.')
    masked_phone_pattern = models.CharField(max_length=32, blank=True, default='', db_comment='Provider-supplied masked phone pattern used only for candidate matching.')
    statement_period_start = models.DateField(null=True, blank=True, db_comment='Chronologically earlier statement date parsed without opening the PDF.')
    statement_period_end = models.DateField(null=True, blank=True, db_comment='Chronologically later statement date parsed without opening the PDF.')
    statement_full_year = models.BooleanField(null=True, blank=True, db_comment='Whether parsed dates cover at least twelve calendar months.')
    drive_file_id = models.CharField(max_length=255, blank=True, default='', db_comment='Restricted Google Drive source-file identifier.')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_UNCLAIMED, db_index=True, db_comment='Current server-controlled matching state.')
    error_code = models.CharField(max_length=80, blank=True, default='', db_comment='Privacy-safe ingestion or validation error code.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When Django ingested this mailbox receipt.')

    class Meta:
        db_table = 'credit_assessment_statement_receipt'
        db_table_comment = 'Immutable Gmail receipt metadata and restricted M-PESA statement artifact pointer.'
        constraints = [models.UniqueConstraint(fields=['gmail_message_id', 'gmail_attachment_id'], name='unique_credit_mail_attachment')]
        indexes = [
            models.Index(fields=['forwarding_sender', 'status', 'inbox_received_at'], name='credit_stmt_sender_status_idx'),
            models.Index(fields=['masked_phone_pattern', 'status'], name='credit_stmt_phone_status_idx'),
        ]


class MailboxCursor(models.Model):
    """Single durable Gmail history cursor and observable polling state."""

    singleton_key = models.CharField(max_length=32, primary_key=True, default='statement_inbox', editable=False, db_comment='Stable singleton key for the dedicated statement inbox.')
    history_id = models.CharField(max_length=255, blank=True, default='', db_comment='Last completely processed Gmail history identifier.')
    last_polled_at = models.DateTimeField(null=True, blank=True, db_comment='Most recent polling attempt time.')
    last_succeeded_at = models.DateTimeField(null=True, blank=True, db_comment='Most recent fully successful polling time.')
    last_error_code = models.CharField(max_length=80, blank=True, default='', db_comment='Privacy-safe code for the latest polling failure.')
    lease_owner = models.CharField(max_length=128, blank=True, default='', db_comment='Short-lived worker identifier holding the polling lease.')
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_comment='Server time when the polling lease expires.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When the cursor or worker health last changed.')

    class Meta:
        db_table = 'credit_assessment_mailbox_cursor'
        db_table_comment = 'Durable singleton cursor and worker-health evidence for the dedicated Gmail statement inbox.'


class AssessmentDocument(models.Model):
    TYPE_PRE_APPRAISAL = 'pre_appraisal'
    TYPE_SIGNED_LAF = 'signed_laf'
    TYPE_MPESA_STATEMENT = 'mpesa_statement'
    TYPE_SPIN_REPORT = 'spin_report'
    TYPE_CRB_REPORT = 'crb_report'
    TYPE_ANALYSIS_REPORT = 'analysis_report'
    TYPE_CHOICES = [
        (TYPE_PRE_APPRAISAL, 'Pre-appraisal form'), (TYPE_SIGNED_LAF, 'Signed LAF'),
        (TYPE_MPESA_STATEMENT, 'M-PESA statement'), (TYPE_SPIN_REPORT, 'SPIN report'),
        (TYPE_CRB_REPORT, 'Metropol CRB report'), (TYPE_ANALYSIS_REPORT, 'Credit analysis report'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable assessment-document version identifier.')
    assessment = models.ForeignKey(CreditAssessment, on_delete=models.PROTECT, related_name='documents', db_comment='Assessment owning this immutable evidence version.')
    document_type = models.CharField(max_length=32, choices=TYPE_CHOICES, db_index=True, db_comment='Governed semantic evidence type.')
    version = models.PositiveIntegerField(db_comment='Monotonic version within assessment and document type.')
    original_filename = models.CharField(max_length=255, db_comment='Sanitized staff-visible source filename.')
    mime_type = models.CharField(max_length=100, db_comment='Validated MIME type.')
    size = models.PositiveBigIntegerField(db_comment='File size in bytes.')
    content_hash = models.CharField(max_length=64, db_index=True, db_comment='SHA-256 binding decisions to exact file bytes.')
    drive_file_id = models.CharField(max_length=255, blank=True, default='', db_comment='Restricted Google Drive file identifier; never an authorization token.')
    source_reference = models.CharField(max_length=255, blank=True, default='', db_comment='Existing governed document or mailbox reference when bytes were not newly uploaded.')
    is_current = models.BooleanField(default=True, db_index=True, db_comment='Whether this is the active version for its semantic type.')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff actor who supplied this version.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When this immutable version was recorded.')

    class Meta:
        db_table = 'credit_assessment_document_evidence'
        db_table_comment = 'Immutable versioned file evidence for governed credit assessments.'
        constraints = [models.UniqueConstraint(fields=['assessment', 'document_type', 'version'], name='unique_credit_document_version')]
        indexes = [models.Index(fields=['assessment', 'document_type', 'is_current'], name='credit_document_current_idx')]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Assessment document versions are immutable.')
        return super().save(*args, **kwargs)


class AssessmentSecret(models.Model):
    assessment = models.OneToOneField(CreditAssessment, on_delete=models.PROTECT, related_name='statement_secret', db_comment='Assessment whose statement passcode is encrypted here.')
    ciphertext = models.TextField(db_comment='Versioned authenticated ciphertext; never plaintext.')
    key_version = models.CharField(max_length=32, db_comment='Configured encryption-key version required for controlled rotation.')
    reveal_count = models.PositiveIntegerField(default=0, db_comment='Number of authorized passcode reveals.')
    last_revealed_at = models.DateTimeField(null=True, blank=True, db_comment='Most recent authorized reveal time.')
    destroyed_at = models.DateTimeField(null=True, blank=True, db_comment='When ciphertext was irreversibly removed after use.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When this protected secret record last changed.')

    class Meta:
        db_table = 'credit_assessment_statement_secret'
        db_table_comment = 'Short-lived encrypted M-PESA statement passcode; excluded from every projection and log.'


class AnalysisPackage(models.Model):
    assessment = models.ForeignKey(CreditAssessment, on_delete=models.PROTECT, related_name='analysis_packages', db_comment='Assessment owning this frozen package revision.')
    revision = models.PositiveIntegerField(db_comment='Monotonic package revision.')
    analysis_document = models.ForeignKey(AssessmentDocument, on_delete=models.PROTECT, related_name='analysis_packages', db_comment='Mandatory consolidated analysis report bound to this package.')
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Credit Analyst who submitted the package.')
    content_digest = models.CharField(max_length=64, db_index=True, db_comment='Canonical digest of report and question revision content.')
    submitted_at = models.DateTimeField(auto_now_add=True, db_comment='When the analyst froze this package.')

    class Meta:
        db_table = 'credit_assessment_analysis_package'
        db_table_comment = 'Immutable analyst-submitted report and question-set revision.'
        constraints = [models.UniqueConstraint(fields=['assessment', 'revision'], name='unique_credit_package_revision')]


class AnalysisQuestion(models.Model):
    package = models.ForeignKey(AnalysisPackage, on_delete=models.PROTECT, related_name='questions', db_comment='Frozen analysis package containing this question.')
    sequence = models.PositiveIntegerField(db_comment='Stable display order within the package.')
    text = models.TextField(db_comment='Analyst question requiring BRO response.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Credit Analyst who raised the question.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When this immutable question was recorded.')

    class Meta:
        db_table = 'credit_assessment_question_item'
        db_table_comment = 'Immutable structured question raised in one frozen analysis package.'
        constraints = [models.UniqueConstraint(fields=['package', 'sequence'], name='unique_credit_question_sequence')]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Analysis questions are immutable.')
        return super().save(*args, **kwargs)


class QuestionResponse(models.Model):
    question = models.ForeignKey(AnalysisQuestion, on_delete=models.PROTECT, related_name='responses', db_comment='Question answered by this immutable response revision.')
    revision = models.PositiveIntegerField(db_comment='Monotonic response revision for this question.')
    text = models.TextField(db_comment='BRO response text.')
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='BRO who submitted this response.')
    responded_at = models.DateTimeField(auto_now_add=True, db_comment='When the response revision was submitted.')

    class Meta:
        db_table = 'credit_assessment_question_response'
        db_table_comment = 'Append-only BRO response revisions to analyst questions.'
        constraints = [models.UniqueConstraint(fields=['question', 'revision'], name='unique_credit_response_revision')]


class QuestionValidationEvent(models.Model):
    OUTCOME_ACCEPTED = 'accepted'
    OUTCOME_RETURNED = 'returned'
    OUTCOME_CHOICES = [(OUTCOME_ACCEPTED, 'Accepted'), (OUTCOME_RETURNED, 'Returned')]

    response = models.ForeignKey(QuestionResponse, on_delete=models.PROTECT, related_name='validation_events', db_comment='Exact response revision validated by the analyst.')
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES, db_comment='Analyst validation result.')
    comment = models.TextField(blank=True, default='', db_comment='Required explanation when a response is returned.')
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Credit Analyst responsible for validation.')
    request_id = models.CharField(max_length=128, unique=True, db_comment='Idempotency key for this append-only validation event.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When validation was recorded.')

    class Meta:
        db_table = 'credit_assessment_response_validation'
        db_table_comment = 'Append-only analyst validation of an exact BRO response revision.'


class AssessmentDecision(models.Model):
    GATE_AUTHORIZATION = 'authorization'
    GATE_FINAL = 'final'
    ACTION_APPROVED = 'approved'
    ACTION_RETURNED = 'returned'
    ACTION_DECLINED = 'declined'
    GATE_CHOICES = [(GATE_AUTHORIZATION, 'Analysis authorization'), (GATE_FINAL, 'Final decision')]
    ACTION_CHOICES = [(ACTION_APPROVED, 'Approved'), (ACTION_RETURNED, 'Returned'), (ACTION_DECLINED, 'Declined')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable decision event identifier.')
    assessment = models.ForeignKey(CreditAssessment, on_delete=models.PROTECT, related_name='decisions', db_comment='Assessment decided at this gate.')
    gate = models.CharField(max_length=20, choices=GATE_CHOICES, db_index=True, db_comment='Authorization or final-decision gate.')
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, db_comment='Server-validated manager action.')
    assessment_revision = models.PositiveBigIntegerField(db_comment='Exact assessment revision reviewed.')
    package = models.ForeignKey(AnalysisPackage, null=True, blank=True, on_delete=models.PROTECT, related_name='decisions', db_comment='Exact analysis package reviewed for a final action.')
    evidence_digest = models.CharField(max_length=64, db_comment='Canonical hash binding the action to reviewed evidence.')
    comment = models.TextField(blank=True, default='', db_comment='Manager explanation; mandatory for final actions and non-approval authorization actions.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Branch Manager responsible for this action.')
    request_id = models.CharField(max_length=128, unique=True, db_comment='Idempotency key for this immutable decision.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When the decision was recorded.')

    class Meta:
        db_table = 'credit_assessment_manager_decision'
        db_table_comment = 'Immutable Branch Manager action bound to exact assessment and evidence revisions.'


class AssessmentEvent(models.Model):
    assessment = models.ForeignKey(CreditAssessment, on_delete=models.PROTECT, related_name='events', db_comment='Assessment changed by this event.')
    action = models.CharField(max_length=64, db_index=True, db_comment='Stable machine-readable action.')
    revision = models.PositiveBigIntegerField(db_comment='Assessment revision produced or observed by this event.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff actor responsible for the event.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Idempotency key; blank only for system ingestion events.')
    metadata = models.JSONField(default=dict, blank=True, db_comment='Customer-data-minimized evidence needed to interpret the event.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When the immutable event was written.')

    class Meta:
        db_table = 'credit_assessment_audit_event'
        db_table_comment = 'Append-only customer-data-minimized audit history for credit assessments.'
        ordering = ['created_at', 'pk']
        constraints = [models.UniqueConstraint(fields=['assessment', 'request_id'], condition=~models.Q(request_id=''), name='unique_credit_assessment_request')]


class EngineJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [(STATUS_PENDING, 'Pending'), (STATUS_COMPLETED, 'Completed'), (STATUS_FAILED, 'Failed')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Future engine job identifier.')
    assessment = models.ForeignKey(CreditAssessment, on_delete=models.PROTECT, related_name='engine_jobs', db_comment='Assessment whose immutable evidence would be processed.')
    assessment_revision = models.PositiveBigIntegerField(db_comment='Assessment revision to which an engine result must bind.')
    source_digest = models.CharField(max_length=64, db_index=True, db_comment='Digest of exact source document identifiers and hashes.')
    contract_version = models.CharField(max_length=20, default='v1', db_comment='Versioned disabled-by-default engine interface contract.')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True, db_comment='Future engine job state.')
    result = models.JSONField(default=dict, blank=True, db_comment='Future structured result; never authoritative without analyst review.')
    error_code = models.CharField(max_length=80, blank=True, default='', db_comment='Privacy-safe future engine failure code.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When the future engine job was requested.')
    completed_at = models.DateTimeField(null=True, blank=True, db_comment='When the future engine result was accepted.')

    class Meta:
        db_table = 'credit_assessment_engine_job'
        db_table_comment = 'Dormant versioned job boundary for a future isolated extraction and report engine.'
        constraints = [models.UniqueConstraint(fields=['assessment', 'assessment_revision', 'source_digest'], name='unique_credit_engine_source_revision')]
