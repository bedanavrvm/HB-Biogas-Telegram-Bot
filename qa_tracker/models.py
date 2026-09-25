import uuid

from django.conf import settings
from django.db import models


class TestCase(models.Model):
    """Stable human-verification instruction; Django is the source of truth."""

    id = models.CharField(max_length=32, primary_key=True, db_comment='Permanent app-prefixed test identifier; never reused.')
    app = models.CharField(max_length=32, db_comment='Workflow being verified, such as portal or tat_tracker.')
    journey = models.CharField(max_length=100, db_comment='User journey or cross-cutting area.')
    description = models.CharField(max_length=255, db_comment='Short human-readable verification objective.')
    steps = models.TextField(db_comment='Actions a tester performs manually.')
    expected = models.TextField(db_comment='Expected observable outcome and important alternative.')
    priority = models.CharField(max_length=12, choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')], default='normal', db_comment='Manual test ordering priority.')
    automation_gap = models.BooleanField(default=False, db_comment='Automatable check retained temporarily because CI coverage has not been verified.')
    active = models.BooleanField(default=True, db_comment='False retires the test without deleting its result history.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Registry creation timestamp.')

    class Meta:
        db_table = 'qa_tracker_test_case_root'
        db_table_comment = 'Stable QA test registry; retained after retirement; no customer data.'
        ordering = ['app', 'journey', 'id']

    def __str__(self):
        return f'{self.id} · {self.description}'


class TestCycle(models.Model):
    """One release/environment/scope against which tests are executed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable QA release-cycle identifier.')
    app = models.CharField(max_length=32, choices=[('portal', 'Portal'), ('tat_tracker', 'TAT Tracker'), ('complaints', 'Complaints'), ('spin', 'SPIN'), ('origination', 'Origination'), ('fca_review', 'FCA Review'), ('farmers_review', 'Farmers Review'), ('order_approval', 'Order Approval')], db_comment='Workflow covered by this release checklist.')
    release = models.CharField(max_length=80, db_comment='Release or deployed version label.')
    environment = models.CharField(max_length=24, choices=[('pilot', 'Pilot'), ('staging', 'Staging'), ('production', 'Production')], db_comment='Environment tested.')
    build_commit = models.CharField(max_length=40, blank=True, db_comment='Optional deployed commit SHA, not customer data.')
    group_configuration = models.ForeignKey('core.GroupSheetConfiguration', on_delete=models.PROTECT, related_name='qa_test_cycles', db_comment='Exact configured Telegram group covered by this QA run.')
    branch = models.CharField(max_length=120, blank=True, db_comment='Optional branch scope; blank means all branches in the group.')
    product = models.CharField(max_length=120, blank=True, db_comment='Optional product scope; blank means all products in the group.')
    case_ids = models.JSONField(default=list, blank=True, db_comment='Frozen active test IDs included when this release checklist was created.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff member who opened the QA cycle.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='QA cycle creation timestamp.')

    class Meta:
        db_table = 'qa_tracker_test_cycle_root'
        db_table_comment = 'Scoped release checklist; retained to compare QA results across releases.'
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['app', 'release', 'environment', 'group_configuration', 'branch', 'product'], name='qa_cycle_unique_scope_release')]

    def __str__(self):
        return f'{self.app} · {self.release} · {self.environment}'

    def save(self, *args, **kwargs):
        if self._state.adding and not self.case_ids:
            self.case_ids = list(TestCase.objects.filter(app=self.app, active=True).values_list('pk', flat=True))
        super().save(*args, **kwargs)


class TestRun(models.Model):
    """Append-only human result. A newer execution supersedes it for dashboards."""

    RESULT_CHOICES = [('pass', 'Pass'), ('fail', 'Fail'), ('blocked', 'Blocked')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable QA execution identifier.')
    cycle = models.ForeignKey(TestCycle, on_delete=models.PROTECT, related_name='runs', db_comment='Release and exact access scope of this execution.')
    test_case = models.ForeignKey(TestCase, on_delete=models.PROTECT, related_name='runs', db_comment='Permanent registry test identifier.')
    test_description = models.CharField(max_length=255, db_comment='Description snapshot at execution time.')
    test_steps = models.TextField(db_comment='Steps snapshot at execution time.')
    test_expected = models.TextField(db_comment='Expected result snapshot at execution time.')
    tester = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff member who recorded the observed result.')
    result = models.CharField(max_length=12, choices=RESULT_CHOICES, db_comment='Human Pass, Fail, or Blocked decision.')
    severity = models.CharField(max_length=12, choices=[('blocker', 'Blocker'), ('major', 'Major'), ('minor', 'Minor')], blank=True, db_comment='Impact of a failed check; blank for non-failures.')
    bug_reference = models.CharField(max_length=100, blank=True, db_comment='Optional issue tracker reference; no customer identifiers.')
    notes = models.TextField(blank=True, db_comment='Privacy-safe observation; not a place for customer data.')
    request_key = models.UUIDField(unique=True, db_comment='Client-generated idempotency key for double-submission and retry.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Execution timestamp; used to choose latest result.')

    class Meta:
        db_table = 'qa_tracker_test_run_event'
        db_table_comment = 'Append-only human QA executions; retained across releases for regression comparison.'
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['cycle', 'test_case', '-created_at'], name='qa_run_cycle_case_time_idx')]


class TestEvidence(models.Model):
    """Private Drive screenshot metadata linked to one immutable execution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable screenshot metadata identifier.')
    run = models.ForeignKey(TestRun, on_delete=models.PROTECT, related_name='evidence', db_comment='Execution evidenced by this screenshot.')
    drive_file_id = models.CharField(max_length=255, db_comment='Private Google Drive object ID; never a public URL.')
    filename = models.CharField(max_length=180, db_comment='Generated non-PII screenshot filename.')
    mime_type = models.CharField(max_length=32, db_comment='Validated PNG or JPEG media type.')
    size_bytes = models.PositiveIntegerField(db_comment='Validated original screenshot size.')
    sha256 = models.CharField(max_length=64, db_comment='Content digest for evidence integrity and duplicate recognition.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Screenshot upload timestamp.')

    class Meta:
        db_table = 'qa_tracker_test_evidence_link'
        db_table_comment = 'Private Drive screenshot references for QA runs; object retention follows approved Drive policy.'
        constraints = [models.UniqueConstraint(fields=['run', 'sha256'], name='qa_evidence_unique_run_hash')]
