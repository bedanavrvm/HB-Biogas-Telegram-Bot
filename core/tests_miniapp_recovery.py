"""Synthetic owner/scope/lease regression tests; no provider is contacted."""
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, TransactionTestCase, override_settings
from django.db import connection
from core.models import GroupSheetConfiguration, IntegrationOperation, JawabuFarmerMaster, TatTrackerCase, TatUpdateSideEffectDispatch
from core.services.miniapp_recovery import page_payload
from core.services.tat_recovery import status_payload, retry_sheet_dispatch, can_retry_targets


def grant(role='IT', branch='', product='', group=None):
    return SimpleNamespace(pk='synthetic', role=role, branch=branch, product=product,
                           group_configuration_id=group.pk if group else None, group_configuration=group)


@override_settings(REPORT_EMAIL_DELIVERY_ENABLED=True, RESEND_API_KEY='synthetic', REPORT_EMAIL_FROM='test@example.invalid')
class RecoveryTests(TestCase):
    def setUp(self):
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_user(username='recovery-training')
        self.group = GroupSheetConfiguration.objects.create(group_id='recovery-training', sheet_id='synthetic',
            enabled=True, tat_sheet_projection_enabled=True, workflow={'type': 'tat_tracker'})
        self.case = TatTrackerCase.objects.create(group_id=self.group.group_id, case_id='RECOVERY-1',
            client_name='Training applicant', branch='Nakuru', product_key='business', workflow_revision=2,
            configuration_binding_status=TatTrackerCase.CONFIG_LEGACY_ASSUMED)
        self.dispatch = TatUpdateSideEffectDispatch.objects.create(case=self.case, workflow_revision=2,
            effect_type=TatUpdateSideEffectDispatch.EFFECT_SHEET, status='needs_attention',
            last_error_code='network', last_error_message='Retained failure evidence')

    def access(self, *grants):
        return {'authorized': True, 'roles': [g.role for g in grants], 'grants': list(grants)}

    def test_status_is_ten_per_page(self):
        payload = page_payload(list(range(23)), 2)
        self.assertEqual(payload['items'], list(range(10, 20)))
        self.assertEqual(payload['pagination'], {'page': 2, 'pages': 3, 'total': 23})

    def test_tat_it_can_retry_only_its_complete_scope_and_no_business_revision_changes(self):
        access = self.access(grant(branch='Nakuru', product='business', group=self.group))
        with patch('core.services.tat_recovery.user_access', return_value=access):
            self.assertEqual(retry_sheet_dispatch(self.dispatch.pk, actor=self.actor), 'pending')
            self.assertEqual(retry_sheet_dispatch(self.dispatch.pk, actor=self.actor), 'pending')
        self.case.refresh_from_db(); self.dispatch.refresh_from_db()
        self.assertEqual(self.case.workflow_revision, 2)
        self.assertEqual(self.dispatch.last_error_message, 'Retained failure evidence')
        self.assertEqual(self.dispatch.manual_retry_by, self.actor)
        self.assertFalse(self.case.events.exists())

    def test_cannot_union_branch_from_one_grant_and_product_from_another(self):
        access = self.access(grant(branch='Nakuru', product='other'), grant(branch='Embu', product='business'))
        with patch('core.services.tat_recovery.user_access', return_value=access), self.assertRaises(PermissionDenied):
            retry_sheet_dispatch(self.dispatch.pk, actor=self.actor)

    def test_non_sheet_effect_and_stale_revision_cannot_be_retried(self):
        access = self.access(grant())
        with patch('core.services.tat_recovery.user_access', return_value=access):
            self.dispatch.effect_type = self.dispatch.EFFECT_SIGNATURE
            self.dispatch.save()
            with self.assertRaises(PermissionDenied): retry_sheet_dispatch(self.dispatch.pk, actor=self.actor)
            self.dispatch.effect_type = self.dispatch.EFFECT_SHEET
            self.dispatch.workflow_revision = 1
            self.dispatch.save()
            with self.assertRaises(ValueError): retry_sheet_dispatch(self.dispatch.pk, actor=self.actor)

    def test_running_lease_is_not_reset_by_retry(self):
        import uuid
        token = uuid.uuid4()
        self.dispatch.status = 'running'; self.dispatch.lease_token = token; self.dispatch.save()
        with patch('core.services.tat_recovery.user_access', return_value=self.access(grant())):
            self.assertEqual(retry_sheet_dispatch(self.dispatch.pk, actor=self.actor), 'running')
        self.dispatch.refresh_from_db()
        self.assertEqual(self.dispatch.lease_token, token)

    def test_only_group_wide_tat_it_can_retry_targets(self):
        self.assertFalse(can_retry_targets(self.actor, self.group, access=self.access(grant(branch='Nakuru', group=self.group))))
        self.assertTrue(can_retry_targets(self.actor, self.group, access=self.access(grant(group=self.group))))
        other = GroupSheetConfiguration.objects.create(group_id='other-recovery')
        self.assertFalse(can_retry_targets(self.actor, self.group, access=self.access(grant(group=other))))

    def test_tat_status_omits_out_of_scope_and_replaced_work(self):
        access = self.access(grant(branch='Embu'))
        self.assertEqual(status_payload(self.actor, self.group, access=access)['items'], [])
        access = self.access(grant(branch='Nakuru'))
        self.assertEqual(status_payload(self.actor, self.group, access=access)['items'][0]['action']['label'], 'Retry sync')
        self.dispatch.status = 'succeeded'; self.dispatch.save()
        self.assertEqual(status_payload(self.actor, self.group, access=access)['items'], [])

    def test_setup_failure_has_specific_handoff_and_confirmed_retry_after_repair(self):
        self.dispatch.last_error_code = 'sheet_column_missing'; self.dispatch.save()
        rows = status_payload(self.actor, self.group, access=self.access(grant(branch='Nakuru')))['items']
        self.assertIn('Repair the Sheet', rows[0]['action']['confirmation'])
        self.assertEqual(rows[0]['status'], 'Configuration required')
        self.assertIn('unique column', rows[0]['steps'][0])
        self.case.configuration_binding_status = self.case.CONFIG_UNRESOLVED; self.case.save()
        rows = status_payload(self.actor, self.group, access=self.access(grant(branch='Nakuru')))['items']
        self.assertIsNone(rows[0]['action'])

    def test_portal_does_not_leak_tat_or_origination_operations_and_success_clears_failure(self):
        from core.services.portal_recovery import status_payload as portal_status
        farmer = JawabuFarmerMaster.objects.create(customer_name='Training Portal case', branch='Nakuru', status='active', workflow_revision=2)
        values = dict(integration='google_sheets', source_model='JawabuFarmerMaster', source_id=str(farmer.pk),
                      operation_type='jawabu_master_publish', metadata={'workflow_revision': 2})
        first = IntegrationOperation.objects.create(**values, deduplication_key='training-first', status='dead_letter')
        IntegrationOperation.objects.create(integration='google_drive', source_model='origination.OriginationSigningPackage',
            source_id=str(farmer.pk), operation_type='origination_approved_archive', deduplication_key='training-other', status='dead_letter')
        access = self.access(grant(branch='Nakuru'))
        self.assertEqual([r['key'] for r in portal_status(self.actor, access)['items']], [str(first.pk)])
        IntegrationOperation.objects.create(**values, deduplication_key='training-replacement', status='succeeded')
        self.assertEqual(portal_status(self.actor, access)['items'], [])
        self.assertEqual(portal_status(self.actor, self.access(grant(branch='Embu')))['items'], [])

    def test_inactive_actor_cannot_retry(self):
        self.actor.is_active = False; self.actor.save()
        with self.assertRaises(PermissionDenied): retry_sheet_dispatch(self.dispatch.pk, actor=self.actor)

    def test_tat_read_and_retry_routes_require_authentication(self):
        response = self.client.post('/api/tat-tracker/settings/recovery/', data={}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/tat-tracker/settings/recovery/retry/', data={'client_request_id': 'synthetic-recovery-1'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_complaint_status_uses_own_group_and_failed_sync_retry_is_idempotent(self):
        from core.models import RawMessage, ProcessedMessage, ParsedMessage, ComplaintCaseControl
        from core.services.complaint_cases import ComplaintCaseActor, retry_case_sync
        from core.services.complaint_recovery import status_payload as complaint_status
        raw = RawMessage.objects.create(telegram_message_id='recovery-complaint', content='Synthetic complaint')
        processed = ProcessedMessage.objects.create(message_hash='recovery-training-hash', raw_message=raw)
        case = ParsedMessage.objects.create(processed_message=processed, message_id='recovery-cmp-1',
            group_id=self.group.group_id, customer_name='Training complainant', complaint_status='Open', synced_to_sheets=True)
        control = ComplaintCaseControl.objects.create(parsed_message=case,
            reference_number='CMP-RECOVERY-TEST', revision=1, sync_status='failed')
        actor = ComplaintCaseActor(self.actor, 'Training actor', '', '', 'MANAGER', frozenset({'complaint.case.sync.retry'}))
        with patch('core.services.complaint_recovery.actor_can', return_value=True):
            rows = complaint_status(self.group, actor)['items']
            self.assertEqual(len(rows), 1)
            self.assertIn('/api/complaints/', rows[0]['action']['endpoint'])
            other = GroupSheetConfiguration.objects.create(group_id='recovery-cmp-other')
            self.assertEqual(complaint_status(other, actor)['items'], [])
        def detail(*args):
            return {'sync_status': ComplaintCaseControl.objects.get(pk=control.pk).sync_status}
        with patch('core.services.complaint_cases.actor_can', return_value=True), \
             patch('core.services.complaint_cases.case_detail', side_effect=detail), \
             patch('core.services.complaint_cases.update_sheet_case', return_value=True) as publish:
            retry_case_sync(self.group, actor, case.message_id, request_id='same-retry-key')
            retry_case_sync(self.group, actor, case.message_id, request_id='same-retry-key')
        self.assertEqual(publish.call_count, 1)
        control.refresh_from_db()
        self.assertEqual(control.revision, 1)
        self.assertEqual(control.events.filter(action='sync_retried').count(), 1)
        self.assertFalse(control.events.filter(action__in=['resolved', 'commented']).exists())

    @override_settings(ORIGINATION_ESIGN_ENABLED=True, AFRICASTALKING_SMS_ENVIRONMENT='sandbox',
                       AFRICASTALKING_USERNAME='sandbox', AFRICASTALKING_API_KEY='synthetic')
    def test_origination_storage_preserves_approved_bytes_and_hides_other_officers(self):
        from origination.models import OriginationProductDefinition, LoanOriginationApplication, OriginationSigningPackage
        from origination.services.recovery import status_payload as origination_status
        from core.models import WorkflowRoleCapability
        for key in ('origination.view', 'origination.create'):
            WorkflowRoleCapability.objects.get_or_create(workflow='loan_origination', role='JBL_OFFICER',
                capability_key=key, defaults={'enabled':True, 'effect':'allow'})
        definition = OriginationProductDefinition.objects.create(product_key='recovery-training-product', name='Training product')
        application = LoanOriginationApplication.objects.create(reference_number='ORG-RECOVERY-TEST',
            product_definition=definition, officer=self.actor, branch='Nakuru', status='approved', approval_roles_snapshot=['branch_manager'])
        package = OriginationSigningPackage.objects.create(application=application, application_revision=1,
            external_reference='recovery-training-pkg', document_type='synthetic', status='fully_signed',
            signed_document_hash='synthetic-hash', final_approved_signed_document_hash='synthetic-hash',
            archive_status='failed', pending_signed_document=b'unchanged-synthetic-document')
        access = self.access(grant('JBL_OFFICER', branch='Nakuru'))
        rows = origination_status(self.actor, access)['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['action']['label'], 'Retry saving')
        stranger = get_user_model().objects.create_user(username='recovery-other-officer')
        self.assertEqual(origination_status(stranger, access)['items'], [])
        package.archive_status = 'uploaded'; package.save()
        self.assertEqual(origination_status(self.actor, access)['items'], [])
        package.refresh_from_db(); application.refresh_from_db()
        self.assertEqual(bytes(package.pending_signed_document), b'unchanged-synthetic-document')
        self.assertEqual(application.status, 'approved')

    def test_policy_migration_preserves_explicit_admin_deny(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from core.models import WorkflowRoleCapability, AccessControlPolicyState
        migration = import_module('core.migrations.0205_tat_publication_retry_capability')
        policy, _ = WorkflowRoleCapability.objects.update_or_create(workflow='tat_tracker', role='IT',
            capability_key=migration.CAPABILITY, defaults={'effect':'deny', 'enabled':False})
        state, _ = AccessControlPolicyState.objects.get_or_create(singleton=1)
        version = state.version
        migration.forward(apps, SimpleNamespace(connection=connection))
        policy.refresh_from_db(); state.refresh_from_db()
        self.assertEqual(policy.effect, 'deny')
        self.assertEqual(state.version, version)

    def test_policy_migration_reverse_keeps_later_admin_edits_and_evidence(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from core.models import WorkflowRoleCapability, WorkflowRoleCapabilityAuditEvent, AccessControlPolicyState
        migration = import_module('core.migrations.0205_tat_publication_retry_capability')
        WorkflowRoleCapability.objects.filter(workflow='tat_tracker', role='IT', capability_key=migration.CAPABILITY).delete()
        editor = SimpleNamespace(connection=connection)
        migration.forward(apps, editor)
        self.assertTrue(WorkflowRoleCapability.objects.filter(workflow='tat_tracker', role='IT', capability_key=migration.CAPABILITY).exists())
        state = AccessControlPolicyState.objects.get(singleton=1)
        version = state.version
        migration.backward(apps, editor)
        self.assertFalse(WorkflowRoleCapability.objects.filter(workflow='tat_tracker', role='IT', capability_key=migration.CAPABILITY).exists())
        state.refresh_from_db(); self.assertEqual(state.version, version + 1)
        migration.forward(apps, editor)
        WorkflowRoleCapabilityAuditEvent.objects.create(workflow='tat_tracker', role='IT', source='admin_matrix', changes={'reviewed':True})
        migration.backward(apps, editor)
        self.assertTrue(WorkflowRoleCapability.objects.filter(workflow='tat_tracker', role='IT', capability_key=migration.CAPABILITY).exists())
        self.assertTrue(WorkflowRoleCapabilityAuditEvent.objects.filter(source=migration.SOURCE).exists())

    def test_failed_report_is_checked_not_resent_and_clears_after_delivery(self):
        from report_delivery.models import ReportSchedule, ApprovedRecipient, ReportDelivery
        from report_delivery.recovery import recovery_rows
        admin = get_user_model().objects.create_user(username='recovery-email-admin', is_superuser=True)
        schedule = ReportSchedule.objects.create(workflow='tat_tracker', group_configuration=self.group, title='Training report', preset='tat', authorized_by=admin)
        recipient = ApprovedRecipient.objects.create(workflow='tat_tracker', group_configuration=self.group, email='training@example.invalid', authorized_by=admin)
        delivery = ReportDelivery.objects.create(schedule=schedule, recipient=recipient, occurrence='training', status='uncertain')
        rows = recovery_rows(admin, 'tat_tracker', group=self.group)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['action']['payload']['action'], 'status')
        self.assertEqual(recovery_rows(admin, 'jawabu_portal'), [])
        delivery.status = 'delivered'; delivery.save()
        self.assertEqual(recovery_rows(admin, 'tat_tracker', group=self.group), [])

    def test_scoped_health_does_not_count_other_branches_or_mixed_documents(self):
        from core.models import RequisitionBatch
        from core.services.portal_health import portal_sync_health
        here = JawabuFarmerMaster.objects.create(customer_name='Training A', branch='Nakuru', status='active')
        elsewhere = JawabuFarmerMaster.objects.create(customer_name='Training B', branch='Embu', status='active')
        RequisitionBatch.objects.create(order_number='SYN-ORDER-A', farmer_ids=[str(here.pk)], drive_upload_error='Synthetic failure')
        RequisitionBatch.objects.create(order_number='SYN-ORDER-B', farmer_ids=[str(elsewhere.pk)], drive_upload_error='Synthetic failure')
        RequisitionBatch.objects.create(order_number='SYN-ORDER-C', farmer_ids=[str(here.pk), str(elsewhere.pk)], drive_upload_error='Synthetic failure')
        result = portal_sync_health(actor=self.actor, access=self.access(grant(branch='Nakuru')))
        self.assertEqual(result['failed_order_syncs'], 1)

    def test_bad_uuid_retry_is_not_a_server_error(self):
        staff = {'_canonical_user': self.actor, '_access': self.access(grant()), 'capabilities':['tat.home.view']}
        with patch('core.api.views._tat_context', return_value=(self.group.group_id, self.group, {}, staff, None)):
            response = self.client.post('/api/tat-tracker/settings/recovery/retry/',
                data={'dispatch_id':'not-a-uuid', 'client_request_id':'synthetic-bad-recovery'}, content_type='application/json')
        self.assertEqual(response.status_code, 404)


@skipUnless(connection.vendor == 'postgresql', 'Concurrent row-lock parity requires PostgreSQL')
class RecoveryConcurrencyTests(TransactionTestCase):
    def test_two_first_retries_queue_one_sheet_update_and_one_audit_event(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from core.models import ComplianceAuditChainState, ComplianceAuditEvent
        from core.services.workflow_data_mode import mode_snapshot, WORKFLOW_TAT
        actor = get_user_model().objects.create_user(username='concurrent-recovery-training')
        group = GroupSheetConfiguration.objects.create(group_id='concurrent-recovery-training', enabled=True, tat_sheet_projection_enabled=True)
        case = TatTrackerCase.objects.create(group_id=group.group_id, case_id='RECOVERY-CONCURRENT',
            client_name='Training applicant', branch='Nakuru', product_key='business', workflow_revision=1)
        dispatch = TatUpdateSideEffectDispatch.objects.create(case=case, workflow_revision=1, effect_type='sheet_projection', status='needs_attention')
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        mode_snapshot(WORKFLOW_TAT)
        access = {'roles':['IT'], 'grants':[grant(branch='Nakuru', group=group)]}
        barrier = Barrier(2)
        def retry():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return retry_sheet_dispatch(dispatch.pk, actor=actor)
            finally:
                close_old_connections()
        with patch('core.services.tat_recovery.user_access', return_value=access), ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(retry) for _ in range(2)]
            self.assertEqual([future.result(timeout=20) for future in futures], ['pending', 'pending'])
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='tat.sheet_projection.retry', subject_id=str(dispatch.pk)).count(), 1)
