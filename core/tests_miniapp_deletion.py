"""Synthetic-only coverage of manifest deletion, Admin and provider isolation."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
import uuid

from django.apps import apps
from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ComplianceAuditChainState, ComplianceAuditEvent, GroupSheetConfiguration, IntegrationOperation,
    JawabuFarmerMaster, JawabuFarmerUploadBatch, ParsedMessage, ProcessedMessage, RawMessage, Product, TatTrackerCase,
    WorkflowTimelineAnnotation,
)
from core.services.miniapp_deletion import CASCADE, KEEP, DeletionError, SelectionChanged, delete_selection, preview_selection
from core.services.miniapp_deletion_registry import REGISTRY
from core.services.miniapp_deletion_sheets import remove_rows, retry_cleanup, sheet_targets
from payments.models import PaymentBatch, PaymentBatchCase, PaymentNumberClaim, PaymentSequenceState
from requisitions.models import OrderNumberClaim, OrderSequenceState


@override_settings(MINIAPP_TEST_DELETION_ENABLED=True, TAT_TRACKER_SYNC_SECONDARY_SHEETS=False)
class MiniAppDeletionTests(TestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.root = get_user_model().objects.create_superuser('deletion-root', 'delete@example.test', 'password')
        self.group = GroupSheetConfiguration.objects.create(group_id='synthetic-deletion', workflow={'type': 'jawabu_homebiogas'})
        self.client.force_login(self.root)

    def plan(self, record, mode=CASCADE):
        return preview_selection(model_label=record._meta.label, ids=[record.pk], actor=self.root, mode=mode)

    def delete(self, record, mode=CASCADE, plan=None, key=None):
        plan = plan or self.plan(record, mode)
        return delete_selection(model_label=record._meta.label, ids=[record.pk], actor=self.root,
                                mode=mode, fingerprint=plan['fingerprint'], request_id=key or str(uuid.uuid4()))

    def complaint(self):
        raw = RawMessage.objects.create(telegram_message_id='synthetic-message', content='Synthetic complaint')
        processed = ProcessedMessage.objects.create(raw_message=raw, message_hash=uuid.uuid4().hex)
        return ParsedMessage.objects.create(processed_message=processed, message_id=uuid.uuid4().hex,
                                            raw_message='Synthetic complaint', group_id='synthetic-complaint')

    def tat(self):
        return TatTrackerCase.objects.create(group_id='synthetic-tat', case_id=uuid.uuid4().hex, product_key='synthetic')

    def test_registry_fields_and_all_registered_actions(self):
        from django.test import RequestFactory
        request = RequestFactory().get('/admin/')
        request.user = self.root
        for label, policy in REGISTRY.items():
            model = apps.get_model(label)
            for name in ([policy.owner] if policy.owner else []) + [key for key, value in policy.retire]:
                model._meta.get_field(name)
            self.assertIn('delete_testing_selection', admin.site._registry[model].get_actions(request), label)
        for label in ('core.RawMessage', 'core.ComplianceAuditEvent', 'core.JawabuCustomer'):
            self.assertNotIn('delete_testing_selection', admin.site._registry[apps.get_model(label)].get_actions(request))

    def test_gate_and_actor_are_enforced_server_side(self):
        product = Product.objects.create(code='delete-gate', name='Synthetic')
        with override_settings(MINIAPP_TEST_DELETION_ENABLED=False), self.assertRaises(PermissionDenied):
            self.plan(product)
        staff = get_user_model().objects.create_user('deletion-staff', is_staff=True)
        with self.assertRaises(PermissionDenied):
            preview_selection(model_label=product._meta.label, ids=[product.pk], actor=staff)
        with self.assertRaises(DeletionError):
            preview_selection(model_label='core.RawMessage', ids=[1], actor=self.root)
        with self.assertRaises(DeletionError):
            preview_selection(model_label='core.TatTrackerCase', ids=['invalid-uuid'], actor=self.root)
        for invalid in (True, 1.5):
            with self.assertRaises(DeletionError):
                preview_selection(model_label='core.Product', ids=[invalid], actor=self.root)
        with self.assertRaises(DeletionError):
            preview_selection(model_label='core.Product', ids=None, actor=self.root)

    def test_plain_configuration_deleted_with_audit_and_replay(self):
        product = Product.objects.create(code='delete-unused', name='Synthetic')
        plan = self.plan(product)
        self.assertEqual(preview_selection(model_label=product._meta.label, ids=(pk for pk in [product.pk]),
            actor=self.root, mode=CASCADE)['fingerprint'], plan['fingerprint'])
        first = self.delete(product, plan=plan, key='same-request')
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())
        self.assertTrue(self.delete(product, plan=plan, key='same-request')['replayed'])
        self.assertEqual(first['deleted'], 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='records.deleted').count(), 1)
        with self.assertRaises(DeletionError):
            self.delete(product, plan=plan, key='same-request', mode=KEEP)

    def test_complaint_keeps_raw_input_and_independent_history(self):
        case = self.complaint()
        raw_id = case.processed_message.raw_message_id
        self.delete(case)
        self.assertFalse(ParsedMessage.objects.filter(pk=case.pk).exists())
        self.assertTrue(RawMessage.objects.filter(pk=raw_id).exists())
        self.assertTrue(ProcessedMessage.objects.filter(pk=case.processed_message_id).exists())

    def test_farmup_exact_ledger_membership_not_other_worklists_or_sysup(self):
        batch = JawabuFarmerUploadBatch.objects.create(group_id=self.group.group_id, import_kind='farmers')
        own = JawabuFarmerMaster.objects.create(customer_name='Synthetic own')
        outside = JawabuFarmerMaster.objects.create(customer_name='Synthetic outside')
        for farmer, worklist in ((own, batch.worklist_id), (outside, uuid.uuid4())):
            IntegrationOperation.objects.create(integration='google_sheets', operation_type='synthetic',
                source_model='JawabuFarmerMaster', source_id=str(farmer.pk), deduplication_key=str(uuid.uuid4()),
                metadata={'farmup_worklist_id': str(worklist)})
        plan = self.plan(batch)
        self.assertIn((own._meta.label, str(own.pk)), plan['deleted'], plan['groups'])
        self.delete(batch, plan=plan)
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=own.pk).exists())
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=outside.pk).exists())
        sysup = JawabuFarmerUploadBatch.objects.create(group_id=self.group.group_id, import_kind='system_export')
        self.delete(sysup)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=outside.pk).exists())

    def test_new_child_after_preview_requires_updated_confirmation(self):
        case = self.tat()
        plan = self.plan(case)
        WorkflowTimelineAnnotation.objects.create(workflow='tat_tracker', subject_id=str(case.pk),
                                                  source_event_id='new-child', kind='correction')
        with self.assertRaises(SelectionChanged):
            self.delete(case, plan=plan)

    def test_surviving_unlinked_reference_is_part_of_confirmation(self):
        from origination.models import OriginationDocumentTemplate, OriginationProductDefinition
        definition = OriginationProductDefinition.objects.create(product_key='detach-synthetic', name='Synthetic', version=1)
        document = OriginationDocumentTemplate.objects.create(product_definition=definition,
            name='Synthetic shared', document_key='primary', version=1, source_byte_size=1, page_count=1, created_by=self.root)
        plan = self.plan(definition)
        OriginationDocumentTemplate.objects.filter(pk=document.pk).update(name='Changed shared document')
        with self.assertRaises(SelectionChanged):
            self.delete(definition, plan=plan)
        definition.refresh_from_db()
        self.assertEqual(document.product_definition_id, definition.pk)

    def test_access_grants_keep_configuration_without_broadening_scope(self):
        from core.models import AccessGrant
        product = Product.objects.create(code='access-synthetic', name='Synthetic')
        grant = AccessGrant.objects.create(user=self.root, workflow='tat_tracker', role='BRO',
                                          product_ref=product, group_configuration=self.group)
        self.delete(product)
        grant.refresh_from_db(); product.refresh_from_db()
        self.assertEqual(grant.product_ref_id, product.pk)
        self.assertFalse(product.active)

    def test_no_undisclosed_non_fk_projection_deletions(self):
        case = self.tat()
        annotation = WorkflowTimelineAnnotation.objects.create(workflow='tat_tracker', subject_id=str(case.pk),
                                                               source_event_id='synthetic', kind='correction')
        outside = WorkflowTimelineAnnotation.objects.create(workflow='jawabu_pipeline', subject_id=str(case.pk),
                                                            source_event_id='synthetic', kind='correction')
        plan = self.plan(case)
        self.assertIn((annotation._meta.label, str(annotation.pk)), plan['deleted'])
        self.delete(case, plan=plan)
        self.assertFalse(WorkflowTimelineAnnotation.objects.filter(pk=annotation.pk).exists())
        self.assertTrue(WorkflowTimelineAnnotation.objects.filter(pk=outside.pk).exists())

    def test_stale_confirmation_rolls_back_everything(self):
        case = self.tat()
        plan = self.plan(case)
        TatTrackerCase.objects.filter(pk=case.pk).update(client_name='Synthetic changed')
        with self.assertRaises(SelectionChanged):
            self.delete(case, plan=plan)
        self.assertTrue(TatTrackerCase.objects.filter(pk=case.pk).exists())
        self.assertFalse(IntegrationOperation.objects.filter(operation_type='miniapp_record_deleted').exists())

    def test_audit_failure_rolls_back_deletion_and_tombstones(self):
        case = self.tat()
        with patch('core.services.miniapp_deletion.record_event', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.delete(case)
        self.assertTrue(TatTrackerCase.objects.filter(pk=case.pk).exists())
        self.assertFalse(IntegrationOperation.objects.filter(operation_type='miniapp_record_deleted').exists())

    def test_cancellation_matches_model_and_id_pairs_not_cross_product(self):
        product = Product.objects.create(code='delete-pairs', name='Synthetic')
        case = self.tat()
        # An unrelated operation happens to use a deleted UUID under another model.
        op = IntegrationOperation.objects.create(integration='google_sheets', operation_type='synthetic',
            deduplication_key='pair-sentinel', source_model='Product', source_id=str(case.pk))
        own = IntegrationOperation.objects.create(integration='google_sheets', operation_type='synthetic',
            deduplication_key='own-sentinel', source_model='TatTrackerCase', source_id=str(case.pk))
        self.delete(case)
        op.refresh_from_db(); own.refresh_from_db()
        self.assertEqual(op.status, op.STATUS_PENDING)
        self.assertEqual(own.status, own.STATUS_DEAD_LETTER)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_deleted_loaded_record_cannot_be_republished(self):
        case = self.tat()
        self.delete(case)
        from core.services.tat_tracker import sync_case_to_sheet, sync_case_index, sync_audit_log
        with override_settings(MINIAPP_TEST_DELETION_ENABLED=False), patch('core.services.tat_tracker.get_sheets_service') as google:
            for function in (sync_case_to_sheet, sync_case_index, sync_audit_log):
                self.assertFalse(function(self.group, case))
        google.assert_not_called()

    def test_sheet_work_is_reserved_but_not_called_inside_transaction(self):
        case = self.tat()
        TatTrackerCase.objects.filter(pk=case.pk).update(sheet_id='synthetic-sheet', sheet_name='Synthetic TAT')
        case.refresh_from_db()
        with patch('core.services.sheets.get_sheets_service') as google, patch('core.services.miniapp_deletion_sheets.wake_cleanup') as wake:
            with self.captureOnCommitCallbacks(execute=True):
                result = self.delete(case)
            google.assert_not_called()
            wake.assert_called_once_with(result['sheet_operations'])
        self.assertEqual(len(result['sheet_operations']), 1)

    def test_keep_history_retires_product_but_leaves_case(self):
        product = Product.objects.create(code='delete-history', name='Synthetic')
        case = self.tat()
        TatTrackerCase.objects.filter(pk=case.pk).update(product=product)
        result = self.delete(product, mode=KEEP)
        product.refresh_from_db()
        self.assertFalse(product.active)
        self.assertEqual(result['deleted'], 0)
        self.assertTrue(TatTrackerCase.objects.filter(pk=case.pk).exists())

    def test_unreviewed_relationship_blocks_the_entire_selection(self):
        product = Product.objects.create(code='delete-new-relation', name='Synthetic')
        case = self.tat()
        TatTrackerCase.objects.filter(pk=case.pk).update(product=product)
        with patch.dict(REGISTRY):
            REGISTRY.pop('core.TatTrackerCase')
            plan = self.plan(product)
            self.assertTrue(plan['blockers'])
            with self.assertRaises(DeletionError):
                self.delete(product, plan=plan)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertTrue(TatTrackerCase.objects.filter(pk=case.pk).exists())

    def test_delete_payment_keeps_farmer_and_retires_number(self):
        farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic')
        batch = PaymentBatch.objects.create(group_configuration=self.group, payment_number=7)
        membership = PaymentBatchCase.objects.create(batch=batch, farmer=farmer, payment_mode='CASH')
        sequence = PaymentSequenceState.objects.create(group_configuration=self.group, next_number=8)
        claim = PaymentNumberClaim.objects.create(sequence=sequence, batch=batch, number=7)
        self.delete(membership)  # Ownership preview includes the whole payment.
        claim.refresh_from_db()
        self.assertTrue(claim.retired)
        self.assertIsNone(claim.batch_id)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        from payments.services import _allocate_payment_number_for_generation
        next_batch = PaymentBatch.objects.create(group_configuration=self.group)
        # Even an IT-adjusted counter must not revive the deleted claim.
        PaymentSequenceState.objects.filter(pk=sequence.pk).update(next_number=7)
        with transaction.atomic():
            self.assertEqual(_allocate_payment_number_for_generation(next_batch), 8)

    def test_delete_order_detaches_farmer_and_retires_number(self):
        from core.models import RequisitionBatch
        from requisitions.services import proposed_number
        sequence = OrderSequenceState.objects.create(group_configuration=self.group, partner='HB', next_number=8)
        batch = RequisitionBatch.objects.create(group_configuration=self.group, order_number='HB-7')
        claim = OrderNumberClaim.objects.create(sequence=sequence, batch=batch, number=7)
        farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic', requisition_batch=batch)
        self.delete(batch)
        claim.refresh_from_db(); farmer.refresh_from_db()
        self.assertTrue(claim.retired)
        self.assertIsNone(claim.batch_id)
        self.assertIsNone(farmer.requisition_batch_id)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        OrderSequenceState.objects.filter(pk=sequence.pk).update(next_number=7)
        sequence.refresh_from_db()
        self.assertEqual(proposed_number(sequence), 8)

    def test_admin_cleanup_retry_ignores_non_cleanup_operations(self):
        from django.test import RequestFactory
        op = IntegrationOperation.objects.create(integration='google_sheets', operation_type='miniapp_sheet_delete',
            deduplication_key='admin-retry-cleanup')
        outside = IntegrationOperation.objects.create(integration='google_sheets', operation_type='synthetic',
            deduplication_key='admin-retry-outside')
        request = RequestFactory().post('/admin/')
        request.user = self.root
        model_admin = admin.site._registry[IntegrationOperation]
        with override_settings(MINIAPP_TEST_DELETION_ENABLED=False), patch.object(model_admin, 'message_user'), \
                patch('core.services.miniapp_deletion_sheets.retry_cleanup') as retry:
            self.assertIn('retry_selected_sheet_cleanup', model_admin.get_actions(request))
            model_admin.retry_selected_sheet_cleanup(request, IntegrationOperation.objects.filter(pk__in=[op.pk, outside.pk]))
        retry.assert_called_once_with(operation_id=op.pk, actor=self.root)

    def test_admin_selection_has_explicit_preview_and_confirmation(self):
        product = Product.objects.create(code='delete-admin', name='Synthetic')
        url = reverse('admin:core_product_changelist')
        payload = {'action': 'delete_testing_selection', ACTION_CHECKBOX_NAME: str(product.pk)}
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Confirm permanent deletion')
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertNotContains(response, 'name="reason"')
        payload.update(deletion_token=response.context['deletion_token'], deletion_mode='keep', confirm_deletion='1')
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_admin_changed_mode_must_preview_again(self):
        product = Product.objects.create(code='delete-admin-mode', name='Synthetic')
        url = reverse('admin:core_product_changelist')
        payload = {'action': 'delete_testing_selection', ACTION_CHECKBOX_NAME: str(product.pk)}
        response = self.client.post(url, payload)
        payload.update(deletion_token=response.context['deletion_token'], deletion_mode='linked', confirm_deletion='1')
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())


@override_settings(MINIAPP_TEST_DELETION_ENABLED=True)
class MiniAppOriginationDeletionTests(TestCase):
    setUp = MiniAppDeletionTests.setUp
    plan = MiniAppDeletionTests.plan
    delete = MiniAppDeletionTests.delete
    # Reuse the deep existing synthetic application/signature graph.
    def test_keep_used_template_preserves_application_and_signed_bytes(self):
        from core.tests_origination_god_mode import OriginationGodModeTests
        OriginationGodModeTests.setUp(self)
        self.root = self.superuser
        source_hash = self.template.source_sha256
        self.signing_package.__class__.objects.filter(pk=self.signing_package.pk).update(
            pending_signed_document=b'synthetic-signed-packet', signed_document_hash='f' * 64)
        result = self.delete(self.template, mode=KEEP)
        self.template.refresh_from_db(); self.application.refresh_from_db(); self.signing_package.refresh_from_db()
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(self.template.status, 'retired')
        self.assertEqual(self.template.source_sha256, source_hash)
        self.assertEqual(bytes(self.signing_package.pending_signed_document), b'synthetic-signed-packet')
        self.assertEqual(self.signing_package.signed_document_hash, 'f' * 64)

    def test_deep_origination_application_deleted_shared_documents_survive(self):
        from core.tests_origination_god_mode import OriginationGodModeTests
        from origination.models import LoanOriginationApplication, OriginationDocumentTemplate, OriginationSigningPackage
        OriginationGodModeTests.setUp(self)
        self.root = self.superuser
        plan = self.plan(self.signing_package)
        self.assertFalse(plan['blockers'])
        self.delete(self.signing_package, plan=plan)
        self.assertFalse(LoanOriginationApplication.objects.filter(pk=self.application.pk).exists())
        self.assertFalse(OriginationSigningPackage.objects.filter(pk=self.signing_package.pk).exists())
        self.assertTrue(OriginationDocumentTemplate.objects.filter(pk=self.template.pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.global_product.pk).exists())

    def test_template_deletion_discloses_and_deletes_consuming_signed_application(self):
        from core.tests_origination_god_mode import OriginationGodModeTests
        from origination.models import LoanOriginationApplication, OriginationDocumentTemplate
        OriginationGodModeTests.setUp(self)
        self.root = self.superuser
        plan = self.plan(self.template)
        self.assertIn((self.application._meta.label, str(self.application.pk)), plan['deleted'])
        self.delete(self.template, plan=plan)
        self.assertFalse(LoanOriginationApplication.objects.filter(pk=self.application.pk).exists())
        self.assertFalse(OriginationDocumentTemplate.objects.filter(pk=self.template.pk).exists())
        self.assertTrue(OriginationDocumentTemplate.objects.filter(pk=self.supporting_template.pk).exists())


@skipUnless(connection.vendor == 'postgresql', 'Real PostgreSQL required for concurrent deletion.')
@override_settings(MINIAPP_TEST_DELETION_ENABLED=True)
class MiniAppDeletionConcurrencyTests(TransactionTestCase):
    def test_concurrent_confirmations_replay_one_deletion(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        root = get_user_model().objects.create_superuser('concurrent-delete', 'concurrent@example.test', 'password')
        product = Product.objects.create(code='concurrent-delete', name='Synthetic')
        plan = preview_selection(model_label=product._meta.label, ids=[product.pk], actor=root, mode=CASCADE)
        def confirm():
            close_old_connections()
            try:
                return delete_selection(model_label=product._meta.label, ids=[product.pk], actor=root, mode=CASCADE,
                                        fingerprint=plan['fingerprint'], request_id='concurrent-confirmation')
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: confirm(), range(2)))
        self.assertEqual(sum(bool(result.get('replayed')) for result in outcomes), 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='records.deleted').count(), 1)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())


class MiniAppSheetCleanupTests(TestCase):
    def target(self, **kwargs):
        return {'spreadsheet': 'synthetic-sheet', 'tab': 'Synthetic', 'headers': ['Case ID'],
                'header_row': 1, 'data_start_row': 2, 'model': 'core.TatTrackerCase',
                'group_id': 'synthetic', 'identities': ['remove'], **kwargs}

    def sheet(self, values):
        sheet = Mock()
        sheet.get_all_values.side_effect = lambda: [list(row) for row in values]
        sheet.row_values.side_effect = lambda number: list(values[number - 1])
        sheet.delete_rows.side_effect = lambda number: values.pop(number - 1)
        service = SimpleNamespace(is_available=lambda: True, _sheet=sheet)
        return sheet, service

    def test_exact_ids_remove_duplicates_bottom_up_and_keep_other_rows(self):
        values = [['Case ID'], ['remove'], ['keep'], ['remove']]
        sheet, service = self.sheet(values)
        with patch('core.services.sheets.get_sheets_service', return_value=service):
            result = remove_rows(self.target())
        self.assertEqual(values, [['Case ID'], ['keep']])
        self.assertEqual(result, {'rows_removed': 2, 'verified_absent': True})
        self.assertEqual([call.args[0] for call in sheet.delete_rows.call_args_list], [4, 2])
        with patch('core.services.sheets.get_sheets_service', return_value=service):
            self.assertEqual(remove_rows(self.target())['rows_removed'], 0)

    def test_missing_id_header_never_guesses_a_name_or_row_number(self):
        sheet, service = self.sheet([['Customer Name'], ['remove']])
        with patch('core.services.sheets.get_sheets_service', return_value=service), self.assertRaises(ValueError):
            remove_rows(self.target())
        sheet.delete_rows.assert_not_called()

    def test_custom_complaint_key_and_header_are_preserved(self):
        from core.models import ComplaintCaseControl
        # Schema v2 uses the canonical complaint reference, not the message ID.
        root_case = MiniAppDeletionTests.complaint(self)
        config = GroupSheetConfiguration.objects.create(group_id=root_case.group_id, sheet_id='synthetic-sheet',
            sheet_name='Complaints', sheet_schema={'schema_version': 2})
        control = ComplaintCaseControl.objects.create(parsed_message=root_case,
                                                      reference_number='CMP-SYNTHETIC')
        target = sheet_targets([root_case])[0]
        self.assertEqual(target['headers'], ['Complaint ID'])
        self.assertEqual(target['identities'], [control.reference_number])

    def test_conflicting_master_record_ids_are_not_deleted(self):
        sheet, service = self.sheet([['Case ID', 'Master Record ID'], ['remove', 'keep']])
        with patch('core.services.sheets.get_sheets_service', return_value=service), self.assertRaises(ValueError):
            remove_rows(self.target(headers=['Case ID', 'Master Record ID']))
        sheet.delete_rows.assert_not_called()

    def test_remaining_tat_row_pointers_follow_removed_rows(self):
        case = TatTrackerCase.objects.create(group_id='synthetic', case_id='keep', product_key='synthetic',
            sheet_id='synthetic-sheet', sheet_name='Synthetic', row_number=3)
        sheet, service = self.sheet([['Case ID'], ['remove'], ['keep']])
        with patch('core.services.sheets.get_sheets_service', return_value=service):
            remove_rows(self.target())
        case.refresh_from_db()
        self.assertEqual(case.row_number, 2)

    def test_provider_failure_records_retry_without_undoing_database_deletion(self):
        from core.services.miniapp_deletion_sheets import process_cleanup
        op = IntegrationOperation.objects.create(integration='google_sheets', operation_type='miniapp_sheet_delete',
            deduplication_key='failed-cleanup', metadata={'target': self.target()})
        with patch('core.services.sheets.get_sheets_service', side_effect=RuntimeError('synthetic unavailable')):
            with self.assertRaises(Exception):
                process_cleanup(op.pk)
        op.refresh_from_db()
        self.assertIn(op.status, [op.STATUS_RETRYABLE, op.STATUS_DEAD_LETTER])

    def test_concurrent_sheet_change_is_not_deleted(self):
        sheet, service = self.sheet([['Case ID'], ['remove']])
        sheet.row_values.side_effect = None
        sheet.row_values.return_value = ['keep']
        with patch('core.services.sheets.get_sheets_service', return_value=service), self.assertRaises(RuntimeError):
            remove_rows(self.target())
        sheet.delete_rows.assert_not_called()

    def test_retry_is_available_after_flag_is_disabled_and_running_lease_is_protected(self):
        root = get_user_model().objects.create_superuser('retry-root', 'retry@example.test', 'password')
        op = IntegrationOperation.objects.create(integration='google_sheets', operation_type='miniapp_sheet_delete',
            deduplication_key='retry-deletion', status='dead_letter', metadata={'target': self.target()})
        with override_settings(MINIAPP_TEST_DELETION_ENABLED=False), patch('core.services.miniapp_deletion_sheets.wake_cleanup') as wake:
            with self.captureOnCommitCallbacks(execute=True):
                retry_cleanup(operation_id=op.pk, actor=root)
            wake.assert_called_once()
        op.refresh_from_db()
        self.assertEqual(op.status, op.STATUS_PENDING)
        IntegrationOperation.objects.filter(pk=op.pk).update(status='running', last_attempt_at=timezone.now())
        with patch('core.services.miniapp_deletion_sheets.wake_cleanup') as wake:
            retry_cleanup(operation_id=op.pk, actor=root)
            wake.assert_not_called()
