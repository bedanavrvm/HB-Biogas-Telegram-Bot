from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from core.models import (
    CaseUpdate,
    ComplianceAuditChainState,
    ComplianceAuditCheckpoint,
    ComplianceAuditEvent,
    JawabuFarmerMaster,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
    SpinCreditRequest,
    TatTrackerCase,
)
from core.services.complaint_cases import ComplaintCaseActor, record_complaint_update
from core.services.compliance_audit import (
    create_daily_checkpoint,
    evidence_csv,
    ComplianceAuditError,
    deliver_checkpoint,
    record_event,
    record_sensitive_access,
    verify_integrity,
)
from core.services.jawabu_case360 import record_pipeline_event
from core.services.spin_credit import record_spin_event
from core.services.tat_tracker import record_tat_event


class ComplianceAuditServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('audit-user', password='not-used')

    def test_chain_is_idempotent_and_model_events_cannot_be_mutated(self):
        baseline_position = ComplianceAuditChainState.objects.get(pk=1).last_position
        event, created = record_event(
            workflow='portal', action='portal.case.updated', subject_type='jawabu_farmer', subject_id='farmer-1',
            deduplication_key='portal:case:farmer-1:request-1', actor=self.user, request_id='request-1',
            before_values={'status': 'Pending'}, after_values={'status': 'Approved'}, sensitive=True,
        )
        replay, replay_created = record_event(
            workflow='portal', action='portal.case.updated', subject_type='jawabu_farmer', subject_id='farmer-1',
            deduplication_key='portal:case:farmer-1:request-1', actor=self.user, request_id='request-1',
        )

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(event.pk, replay.pk)
        # Test databases may include immutable migration evidence.  The
        # ledger contract is that this event occupies the next position, not
        # that every test starts from an empty audit chain.
        self.assertEqual(event.chain_position, baseline_position + 1)
        self.assertEqual(ComplianceAuditChainState.objects.get(pk=1).last_hash, event.integrity_hash)
        self.assertTrue(verify_integrity().ok)

        event.action = 'changed'
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_all_workflow_adapters_project_into_one_ledger(self):
        farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic Farmer', national_id='10000001')
        record_pipeline_event(
            farmer, action='jbl_visit_logged', actor='Portal Officer', request_id='portal-audit-1',
            old_values={'jbl_visit_status': ''}, new_values={'jbl_visit_status': 'Approved'},
        )

        tat_case = TatTrackerCase.objects.create(
            group_id='audit-tat', case_id='JBL-AUD-001', product_key='business', client_name='Synthetic TAT',
        )
        record_tat_event(
            case=tat_case, group_id=tat_case.group_id, actor_name='TAT Officer', stage_key='created',
            stage_label='Case Created', new_value='created', source='mini_app', sheet_name='TRACKER-Business',
        )

        raw = RawMessage.objects.create(telegram_message_id='audit-complaint-1', content='Synthetic complaint')
        processed = ProcessedMessage.objects.create(message_hash='audit-complaint-hash', raw_message=raw)
        complaint = ParsedMessage.objects.create(
            processed_message=processed, message_id='CMP-AUD-001', raw_message='Synthetic complaint',
            group_id='audit-complaint', complaint_status='Open',
        )
        update = CaseUpdate.objects.create(
            parsed_message=complaint, group_id=complaint.group_id, updated_by='Complaint Officer',
            old_status='Open', new_status='In Progress', raw_update_text='Synthetic update',
            source='mini_app', client_request_id='complaint-audit-1', sync_status='success',
        )
        actor = ComplaintCaseActor(
            user=self.user, name='Complaint Officer', telegram_id='100', username='audit',
            role='OFFICER', capabilities=frozenset({'complaint.case.update'}),
        )
        record_complaint_update(update, complaint, actor, action='complaint.case.updated')

        spin = SpinCreditRequest.objects.create(
            group_id='audit-spin', request_type='spin', source_message_hash='audit-spin-hash',
            customer_name='Synthetic SPIN', import_status='review_needed',
        )
        record_spin_event(
            spin, action='spin.request.reviewed', actor=self.user, actor_label='Credit Analyst',
            source_event_id=f'{spin.pk}:review:1', before_values={'import_status': 'review_needed'},
            after_values={'import_status': 'imported'},
        )

        workflows = set(ComplianceAuditEvent.objects.values_list('workflow', flat=True))
        self.assertTrue(
            {'portal', 'tat_tracker', 'complaint_cases', 'spin'}.issubset(workflows)
        )
        self.assertTrue(verify_integrity().ok)

    @override_settings(COMPLIANCE_AUDIT_CHECKPOINT_DELIVERY_ENABLED=False, COMPLIANCE_AUDIT_CHECKPOINT_RECIPIENT='')
    def test_sensitive_access_and_checkpoint_are_retained_without_delivery(self):
        record_sensitive_access(
            workflow='portal', action='portal.crb_report.view', subject_type='spin_request', subject_id='spin-1',
            actor=self.user, request_id='read-1', metadata={'report_type': 'crb'},
        )
        checkpoint, created = create_daily_checkpoint()
        replay, replay_created = create_daily_checkpoint()

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(checkpoint.pk, replay.pk)
        self.assertEqual(checkpoint.status, ComplianceAuditCheckpoint.STATUS_DISABLED)
        self.assertTrue(
            ComplianceAuditEvent.objects.get(action='portal.crb_report.view').sensitive
        )
        self.assertIn('portal.crb_report.view', evidence_csv(ComplianceAuditEvent.objects.all()))

    def test_read_only_commands_report_integrity_and_sampling(self):
        record_event(
            workflow='portal', action='portal.case.viewed', subject_type='jawabu_farmer', subject_id='farmer-2',
            deduplication_key='portal:case:farmer-2:read', actor=self.user, sensitive=True,
        )
        output = StringIO()
        call_command('verify_compliance_audit', '--strict', stdout=output)
        self.assertIn('integrity verified', output.getvalue().lower())
        output = StringIO()
        call_command('sample_compliance_audit', '--strict', stdout=output)
        self.assertIn('Integrity: OK', output.getvalue())

    @override_settings(COMPLIANCE_AUDIT_CHECKPOINT_DELIVERY_ENABLED=False, COMPLIANCE_AUDIT_CHECKPOINT_RECIPIENT='')
    def test_export_is_denied_without_permission_and_checkpoint_cannot_send(self):
        from core.admin import ComplianceAuditEventAdmin

        regular = get_user_model().objects.create_user('no-audit-export', password='not-used', is_staff=True)
        request = RequestFactory().get('/admin/core/complianceauditevent/export/csv/')
        request.user = regular
        admin_view = ComplianceAuditEventAdmin(ComplianceAuditEvent, admin.site)
        self.assertFalse(admin_view._can_export(request))
        self.assertFalse(admin_view.has_change_permission(request))

        checkpoint, _created = create_daily_checkpoint()
        with self.assertRaises(ComplianceAuditError):
            deliver_checkpoint(checkpoint)
