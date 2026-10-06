"""Synthetic acceptance tests at the signing, withdrawal and consent seams."""
import hashlib
from datetime import timedelta
from io import BytesIO
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from pypdf import PdfReader, PdfWriter

from core.models import AccessGrant, IntegrationOperation
from origination.models import (
    LoanOriginationApplication, OriginationApplicationDocument, OriginationDocumentTemplate,
    OriginationConsentPolicyVersion, OriginationProductDefinition,
    OriginationSignerSession, OriginationSigningAction, OriginationSigningPackage, OriginationStampAsset,
)
from origination.services.loan_origination import (
    OriginationConflict, OriginationError, _record_event, recall_application,
    serialize_application,
    confirm_and_start_conditional_signing,
)
from origination.services.origination_consent import active_consent_policy, policy_snapshot
from origination.services.origination_esign import apply_production_stamp, complete_staff_signatures, resolve_session
from origination.services.origination_signing import verified_packet_version
from origination.services.origination_approval import signing_progress


@override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True, ORIGINATION_ESIGN_ENABLED=True,
                   AFRICASTALKING_SMS_ENVIRONMENT='sandbox', AFRICASTALKING_USERNAME='sandbox',
                   AFRICASTALKING_API_KEY='synthetic-only', SENTRY_ENVIRONMENT='test')
class ApprovalSignatureTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.officer = users.objects.create_user(username='synthetic-maker', is_superuser=True)
        self.ca = users.objects.create_user(username='synthetic-ca', is_superuser=True)
        self.bm = users.objects.create_user(username='synthetic-bm', is_superuser=True)
        self.management = users.objects.create_user(username='synthetic-management', is_superuser=True)
        self.roles = ['branch_manager']
        rules = [{'role': role, 'required': True} for role in ['officer', 'credit_analyst', 'borrower', *self.roles]]
        self.definition = OriginationProductDefinition.objects.create(
            product_key='synthetic-approval', name='Synthetic approval', signer_rules=rules,
            approval_roles=self.roles, document_type='synthetic')
        self.application = LoanOriginationApplication.objects.create(
            reference_number='ORG-SYNTHETIC-APPROVAL', product_definition=self.definition,
            officer=self.officer, branch='Synthetic Branch', status='signing_pending',
            approval_roles_snapshot=self.roles, form_payload={'applicant_name': 'Synthetic Applicant'},
        )
        self.policy = OriginationConsentPolicyVersion.objects.create(
            version='synthetic-approval-v1', status='active', approval_roles=self.roles,
            packet_clause='Synthetic test only: earlier consent is provisional until BM approves and signs.',
            signer_consent_text='Synthetic provisional consent.', signer_completion_text='Synthetic pending approval.',
            resigning_text='Synthetic re-signing required.', approval_reference='SYNTHETIC-NOT-LEGAL-APPROVAL',
            approved_by=self.bm, approved_at=timezone.now(), created_by=self.bm,
        )
        stream = BytesIO()
        pdf = PdfWriter()
        pdf.add_blank_page(width=595, height=842)
        pdf.write(stream)
        content = stream.getvalue()
        self.package = OriginationSigningPackage.objects.create(
            application=self.application, application_revision=1, external_reference='SYNTHETIC-APPROVAL',
            document_type='synthetic', frozen_unsigned_document=content,
            unsigned_document_hash=hashlib.sha256(content).hexdigest(), conditional_approval=True,
            consent_policy=self.policy, consent_policy_snapshot=policy_snapshot(self.policy), context_snapshot={},
            participants_snapshot=[{'role': rule['role'], 'required': True,
                'slots': [{'key': f'{rule["role"]}_signature', 'document_key': 'primary', 'type': 'signature', 'required': True}]}
                for rule in rules], document_manifest_snapshot=[{'key': 'primary', 'page_count': 1}],
        )
        self.audit = patch('core.services.compliance_audit.record_event')
        self.audit.start()
        self.addCleanup(self.audit.stop)

    def sign(self, role, actor, *, request=None, version=''):
        self.application.refresh_from_db()
        result = complete_staff_signatures(package_id=self.package.pk, signer_role=role, actor=actor,
            signature_capture={'method': 'typed', 'name': actor.username},
            expected_revision=self.application.revision, request_id=request or f'sign-{role}', reviewed_packet_version=version)
        self.package.refresh_from_db()
        return result

    def borrower_signed(self):
        OriginationSigningAction.objects.create(package=self.package, signer_role='borrower', document_key='primary',
            slot_key='borrower_signature', action_type='signature', mode='verified', request_id='synthetic-borrower',
            metadata={'signature_capture': {'method': 'typed', 'name': 'Synthetic Applicant'}})

    def preceding_signatures(self):
        self.sign('credit_analyst', self.ca)  # Staff signatures are independent, not officer-first.
        self.borrower_signed()
        self.sign('officer', self.officer)

    def open_packet(self, actor=None):
        self.application.refresh_from_db()
        version = verified_packet_version(self.package)
        _record_event(self.application, 'approval_packet_opened', actor=actor or self.bm,
            request_id=f'synthetic-open:{self.application.revision}',
            after={'package_id': str(self.package.pk), 'packet_version': version, 'revision': self.application.revision})
        return version

    def test_bm_cannot_sign_before_other_participants(self):
        with self.assertRaisesMessage(OriginationError, 'preceding participants'):
            self.sign('branch_manager', self.bm)
        self.assertFalse(self.package.actions.exists())

    def test_bm_must_open_latest_packet_with_preceding_signatures(self):
        self.preceding_signatures()
        with self.assertRaisesMessage(OriginationError, 'Open the latest packet'):
            self.sign('branch_manager', self.bm)
        self.assertTrue(signing_progress(self.package)['approval_ready'])

    def test_approve_and_sign_is_atomic_finality_with_background_archive(self):
        self.preceding_signatures()
        version = self.open_packet()
        with patch('origination.services.origination_esign.archive_signed_package') as archive:
            self.sign('branch_manager', self.bm, version=version)
            archive.assert_not_called()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')
        self.assertEqual(self.application.final_reviewed_by, self.bm)
        self.assertEqual(self.package.final_approved_signed_document_hash, self.package.signed_document_hash)
        self.assertEqual(self.package.archive_status, 'pending')
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='origination_approved_archive').count(), 1)

    def test_final_approval_retry_is_idempotent_but_different_capture_is_rejected(self):
        self.preceding_signatures()
        version = self.open_packet()
        self.sign('branch_manager', self.bm, request='approval-idempotent', version=version)
        self.sign('branch_manager', self.bm, request='approval-idempotent', version=version)
        self.assertEqual(self.package.actions.filter(signer_role='branch_manager').count(), 1)
        self.bm.username = 'Different capture'
        with self.assertRaisesMessage(OriginationError, 'different data'):
            self.sign('branch_manager', self.bm, request='approval-idempotent', version=version)

    def test_officer_and_credit_analyst_cannot_be_the_same_person(self):
        with self.assertRaisesMessage(OriginationError, 'different people'):
            self.sign('credit_analyst', self.officer)

    def test_credit_analyst_and_bm_cannot_be_the_same_person_even_for_superuser(self):
        self.preceding_signatures()
        with self.assertRaisesMessage(OriginationError, 'different people'):
            self.sign('branch_manager', self.ca, version=self.open_packet(self.ca))

    def test_other_officer_cannot_sign_the_assigned_officer_slot(self):
        with self.assertRaisesMessage(OriginationError, 'assigned officer'):
            self.sign('officer', self.ca)

    def test_editing_withdraws_packet_invalidates_signatures_and_retains_fields(self):
        self.preceding_signatures()
        payload = self.application.form_payload
        self.application.refresh_from_db()
        recalled = recall_application(application_id=self.application.pk, actor=self.officer,
            expected_revision=self.application.revision, request_id='withdraw',
            confirmed_package_id=str(self.package.pk), confirmed_package_hash=self.package.unsigned_document_hash)
        self.package.refresh_from_db()
        self.assertEqual(recalled.status, 'draft')
        self.assertEqual(recalled.form_payload, payload)
        self.assertEqual(self.package.status, 'cancelled')
        self.assertEqual(self.package.actions.filter(invalidation__isnull=True).count(), 0)
        self.assertEqual(self.package.actions.count(), 3)

    def test_approved_application_cannot_be_withdrawn(self):
        self.preceding_signatures()
        self.sign('branch_manager', self.bm, version=self.open_packet())
        self.application.refresh_from_db()
        with self.assertRaisesMessage(OriginationError, 'no longer be recalled'):
            recall_application(application_id=self.application.pk, actor=self.officer,
                expected_revision=self.application.revision, request_id='withdraw-approved')

    def test_stale_signing_revision_does_not_write_a_signature(self):
        self.preceding_signatures()
        with self.assertRaises(OriginationConflict):
            complete_staff_signatures(package_id=self.package.pk, signer_role='branch_manager', actor=self.bm,
                signature_capture={'method': 'typed', 'name': 'Synthetic BM'}, expected_revision=1,
                request_id='stale-sign', reviewed_packet_version=self.open_packet())
        self.assertFalse(self.package.actions.filter(signer_role='branch_manager').exists())

    def test_consent_must_explicitly_cover_approval_sequence(self):
        self.package.consent_policy_snapshot['approval_roles'] = []
        self.package.save(update_fields=['consent_policy_snapshot'])
        with self.assertRaisesMessage(OriginationError, 'approved consent'):
            self.sign('officer', self.officer)

    def test_legacy_applications_do_not_adopt_definition_changes(self):
        self.application.approval_roles_snapshot = []
        self.application.save(update_fields=['approval_roles_snapshot'])
        self.application.refresh_from_db()
        self.assertNotIn('approval_roles', serialize_application(self.application, include_payload=False))
        self.assertEqual(self.application.approval_roles_snapshot, [])

    def test_future_management_approval_after_bm_is_not_premature_finality(self):
        roles = ['branch_manager', 'management_approver']
        OriginationConsentPolicyVersion.objects.filter(pk=self.policy.pk).update(status='retired')
        policy = OriginationConsentPolicyVersion.objects.create(
            version='synthetic-chain-v2', status='active', approval_roles=roles,
            packet_clause='Synthetic test only: BM approval followed by Management approval and signature.',
            signer_consent_text='Synthetic consent.', signer_completion_text='Synthetic pending approval.',
            resigning_text='Synthetic re-signing.', approval_reference='SYNTHETIC-NOT-LEGAL-APPROVAL',
            approved_by=self.management, approved_at=timezone.now(), created_by=self.management)
        self.application.approval_roles_snapshot = roles
        self.application.save(update_fields=['approval_roles_snapshot'])
        self.package.consent_policy = policy
        self.package.consent_policy_snapshot = policy_snapshot(policy)
        self.package.participants_snapshot.append({'role': 'management_approver', 'required': True,
            'slots': [{'key': 'management_signature', 'document_key': 'primary', 'type': 'signature', 'required': True}]})
        self.package.save(update_fields=['consent_policy', 'consent_policy_snapshot', 'participants_snapshot'])
        self.preceding_signatures()
        self.sign('branch_manager', self.bm, version=self.open_packet())
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'partially_signed')
        self.assertEqual(signing_progress(self.package)['next_approver'], 'management_approver')
        self.sign('management_approver', self.management, version=self.open_packet(self.management))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')

    def test_authorization_still_rejects_wrong_branch(self):
        outsider = get_user_model().objects.create_user(username='synthetic-outside-bm')
        AccessGrant.objects.create(user=outsider, workflow='loan_origination', role='BM', branch='Other Branch')
        with self.assertRaisesMessage(OriginationError, 'not authorized'):
            self.sign('branch_manager', outsider)

    def test_withdrawal_revokes_verified_link_and_queues_customer_notice(self):
        token = 'synthetic-withdrawal-token'
        session = OriginationSignerSession.objects.create(package=self.package, signer_role='borrower',
            token_hash=hashlib.sha256(token.encode()).hexdigest(), token_expires_at=timezone.now() + timedelta(hours=1),
            status='verified', verified_at=timezone.now(), created_by=self.officer)
        recalled = recall_application(application_id=self.application.pk, actor=self.officer,
            expected_revision=1, request_id='withdraw-customer', confirmed_package_id=str(self.package.pk),
            confirmed_package_hash=self.package.unsigned_document_hash)
        session.refresh_from_db()
        self.assertEqual(recalled.status, 'draft')
        self.assertFalse(session.is_active)
        with self.assertRaises(OriginationError):
            resolve_session(token)
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='origination_withdrawal_sms').count(), 1)

    def test_legacy_and_bm_consent_policies_coexist_without_hash_changes(self):
        legacy = OriginationConsentPolicyVersion.objects.create(
            version='synthetic-legacy', status='active', approval_roles=[],
            packet_clause='Synthetic independent review.', signer_consent_text='Synthetic consent.',
            signer_completion_text='Synthetic pending independent review.', resigning_text='Synthetic re-signing.',
            approval_reference='SYNTHETIC-NOT-LEGAL-APPROVAL', approved_by=self.bm,
            approved_at=timezone.now(), created_by=self.bm)
        self.assertEqual(active_consent_policy(), legacy)
        self.assertEqual(active_consent_policy(approval_roles=self.roles), self.policy)
        self.assertEqual(self.policy.status, 'active')
        # Legacy policy hashes retain the exact pre-migration content envelope.
        import json
        content = {key: getattr(legacy, key) for key in ['version', 'packet_clause', 'signer_consent_text',
                   'signer_completion_text', 'resigning_text']}
        self.assertEqual(legacy.content_sha256, hashlib.sha256(json.dumps(content, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest())

    def test_only_one_active_consent_per_approval_sequence(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OriginationConsentPolicyVersion.objects.create(
                version='synthetic-duplicate-active', status='active', approval_roles=self.roles,
                packet_clause='Synthetic duplicate.', signer_consent_text='Synthetic consent.',
                signer_completion_text='Synthetic pending.', resigning_text='Synthetic re-signing.',
                approval_reference='SYNTHETIC-NOT-LEGAL-APPROVAL', approved_by=self.bm,
                approved_at=timezone.now(), created_by=self.bm)

    def test_officer_submit_freezes_and_starts_without_operations_then_resubmits_fresh_packet(self):
        self.package.status = 'cancelled'
        self.package.save(update_fields=['status'])
        rules = self.package.participants_snapshot
        schema = {'fields': [{'key': 'applicant_name', 'type': 'text', 'required': True}]}
        self.application.status = 'draft'
        self.application.schema_snapshot = schema
        self.application.signer_rules_snapshot = rules
        self.application.primary_previewed_revision = 1
        self.application.save()
        source = bytes(self.package.frozen_unsigned_document)
        configuration = {'signature_overlay_manifest': {'slots': {
            f'{rule["role"]}.{rule["slots"][0]["key"]}': {
                'page_number': 1, 'x': 40, 'y': 90 + index * 90, 'width': 200, 'height': 50,
            } for index, rule in enumerate(rules)}}}
        template = OriginationDocumentTemplate.objects.create(document_type='synthetic', name='Synthetic LAF',
            version=1, source_filename='synthetic.pdf', source_sha256=hashlib.sha256(source).hexdigest(),
            source_byte_size=len(source), page_count=1, placement_config=configuration, created_by=self.officer)
        OriginationApplicationDocument.objects.create(application=self.application, template=template,
            document_key='primary', name='Synthetic LAF', document_role='primary',
            template_snapshot={'sha256': template.source_sha256, 'configuration': configuration},
            schema_snapshot=schema, signer_rules_snapshot=rules)
        # Mock only external template storage; validation, freeze, consent and rendering are real.
        with patch('origination.services.origination_templates.load_template_source', return_value=source):
            package, replay = confirm_and_start_conditional_signing(application_id=self.application.pk,
                actor=self.officer, expected_revision=1, request_id='officer-submit')
            repeated, replayed = confirm_and_start_conditional_signing(application_id=self.application.pk,
                actor=self.officer, expected_revision=1, request_id='officer-submit')
        self.assertFalse(replay)
        self.assertTrue(replayed)
        self.assertEqual(repeated.pk, package.pk)
        self.assertEqual(package.application.status, 'signing_pending')
        self.assertEqual(package.prepared_by, self.officer)
        self.assertIsNone(package.reviewed_by)
        self.assertEqual(package.consent_policy, self.policy)
        self.assertEqual(len(PdfReader(BytesIO(bytes(package.frozen_unsigned_document))).pages), 2)
        self.application.refresh_from_db()
        recalled = recall_application(application_id=self.application.pk, actor=self.officer,
            expected_revision=self.application.revision, request_id='withdraw-and-edit',
            confirmed_package_id=str(package.pk), confirmed_package_hash=package.unsigned_document_hash)
        recalled.primary_previewed_revision = recalled.revision
        recalled.save(update_fields=['primary_previewed_revision'])
        with patch('origination.services.origination_templates.load_template_source', return_value=source):
            replacement, _ = confirm_and_start_conditional_signing(application_id=recalled.pk,
                actor=self.officer, expected_revision=recalled.revision, request_id='officer-resubmit')
        self.assertNotEqual(replacement.pk, package.pk)
        self.assertFalse(replacement.actions.exists())
        package.refresh_from_db()
        self.assertEqual(package.status, 'cancelled')

    def test_drive_failure_retains_approval_and_retryable_durable_work(self):
        from origination.services.origination_dispatch import process_operations, queue_archive
        self.preceding_signatures()
        self.sign('branch_manager', self.bm, version=self.open_packet())
        operation = IntegrationOperation.objects.get(operation_type='origination_approved_archive')
        with patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.upload.side_effect = TimeoutError('timed out')
            process_operations([operation.pk])
        self.application.refresh_from_db()
        self.package.refresh_from_db()
        operation.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')
        self.assertEqual(self.package.archive_status, 'failed')
        self.assertEqual(operation.status, 'retryable_failure')
        queued = queue_archive(self.package, actor=self.officer, retry=True)
        self.assertEqual(queued.pk, operation.pk)
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='origination_approved_archive').count(), 1)

    def test_bm_required_stamp_must_precede_review_and_final_signature(self):
        self.package.participants_snapshot[-1]['slots'].append({
            'key': 'bm_stamp', 'document_key': 'primary', 'type': 'stamp', 'required': True})
        self.package.save(update_fields=['participants_snapshot'])
        self.preceding_signatures()
        with self.assertRaisesMessage(OriginationError, 'required stamp'):
            self.sign('branch_manager', self.bm, version=self.open_packet())
        self.assertFalse(self.package.actions.filter(signer_role='branch_manager').exists())

    def test_ready_inbox_is_deduplicated_and_excludes_wrong_branch(self):
        from origination.services.origination_dispatch import update_approval_notices
        eligible = get_user_model().objects.create_user(username='synthetic-scoped-bm')
        outside = get_user_model().objects.create_user(username='synthetic-other-branch')
        for user, branch in [(eligible, self.application.branch), (outside, 'Other Branch')]:
            AccessGrant.objects.create(user=user, workflow='loan_origination', role='BM', branch=branch)
        self.preceding_signatures()
        update_approval_notices(self.package)
        update_approval_notices(self.package)
        notices = self.application.reviewer_notices.filter(notice_type='approval_ready')
        self.assertEqual(list(notices.values_list('recipient_id', flat=True)), [eligible.pk])
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='origination_approval_alert').count(), 1)

    def test_bm_can_stamp_and_approve_without_operations_permission(self):
        bm = get_user_model().objects.create_user(username='synthetic-bm-not-operations')
        AccessGrant.objects.create(user=bm, workflow='loan_origination', role='BM', branch=self.application.branch)
        self.package.participants_snapshot[-1]['slots'].append({
            'key': 'bm_stamp', 'document_key': 'primary', 'type': 'stamp', 'required': True})
        self.package.save(update_fields=['participants_snapshot'])
        self.preceding_signatures()
        from PIL import Image
        stream = BytesIO()
        Image.new('RGB', (10, 10), 'green').save(stream, format='PNG')
        content = stream.getvalue()
        stamp = OriginationStampAsset.objects.create(name='Synthetic stamp', environment='production', active=True,
            image_png=content, byte_size=len(content), content_sha256=hashlib.sha256(content).hexdigest(), created_by=self.bm)
        self.application.refresh_from_db()
        apply_production_stamp(package_id=self.package.pk, signer_role='branch_manager', actor=bm,
            document_key='primary', slot_key='bm_stamp', stamp_asset_id=stamp.pk,
            expected_revision=self.application.revision, request_id='bm-own-stamp')
        self.sign('branch_manager', bm, version=self.open_packet(bm))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')
        self.assertEqual(self.application.final_reviewed_by, bm)

    def test_archive_replay_does_not_reset_uploaded_state(self):
        from origination.services.origination_dispatch import queue_archive
        self.preceding_signatures()
        self.sign('branch_manager', self.bm, version=self.open_packet())
        self.package.archive_status = 'uploaded'
        self.package.final_drive_file_id = 'synthetic-drive-id'
        self.package.save(update_fields=['archive_status', 'final_drive_file_id'])
        queue_archive(self.package, retry=True)
        self.package.refresh_from_db()
        self.assertEqual(self.package.archive_status, 'uploaded')

    @override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    def test_api_packet_view_is_audited_and_approval_retry_is_idempotent(self):
        self.preceding_signatures()
        self.client.force_login(self.bm)
        preview = self.client.get(reverse('loan_origination_current_signing_packet', args=[self.application.pk]),
                                  {'package_id': str(self.package.pk), 'page': 1})
        self.assertEqual(preview.status_code, 200)
        version = preview['X-Signing-Packet-Version']
        self.assertTrue(self.application.events.filter(action='approval_packet_opened', actor=self.bm,
                                                       after_values__packet_version=version).exists())
        self.application.refresh_from_db()
        payload = {'package_id': str(self.package.pk), 'signer_role': 'branch_manager',
                   'signature_capture': {'method': 'typed', 'name': 'Synthetic BM'},
                   'revision': self.application.revision, 'reviewed_packet_version': version,
                   'client_request_id': 'synthetic-api-approve'}
        url = reverse('loan_origination_staff_signature', args=[self.application.pk])
        first = self.client.post(url, payload, content_type='application/json')
        repeated = self.client.post(url, payload, content_type='application/json')
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(first.json()['application']['status'], 'approved')
        self.assertEqual(self.package.actions.filter(signer_role='branch_manager').count(), 1)

    def test_customer_withdrawal_notification_is_durable_and_not_duplicated(self):
        from origination.services.origination_dispatch import process_operations
        OriginationSignerSession.objects.create(package=self.package, signer_role='borrower',
            token_hash=hashlib.sha256(b'synthetic-notification').hexdigest(),
            token_expires_at=timezone.now() + timedelta(hours=1),
            phone_normalized='254700000000', status='verified', verified_at=timezone.now(), created_by=self.officer)
        recall_application(application_id=self.application.pk, actor=self.officer,
            expected_revision=1, request_id='withdraw-notify', confirmed_package_id=str(self.package.pk),
            confirmed_package_hash=self.package.unsigned_document_hash)
        operation = IntegrationOperation.objects.get(operation_type='origination_withdrawal_sms')
        with patch('origination.services.origination_esign._send_sms', return_value={'id': 'synthetic-sms', 'status': 'Success'}) as sms:
            process_operations([operation.pk])
            process_operations([operation.pk])
        sms.assert_called_once()
        self.assertIn('not rejected', sms.call_args.args[0])
        operation.refresh_from_db()
        self.assertEqual(operation.status, 'succeeded')


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row-lock semantics.')
@override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True, ORIGINATION_ESIGN_ENABLED=True,
                   AFRICASTALKING_SMS_ENVIRONMENT='sandbox', AFRICASTALKING_USERNAME='sandbox',
                   AFRICASTALKING_API_KEY='synthetic-only', SENTRY_ENVIRONMENT='test')
class ApprovalConcurrencyTests(TransactionTestCase):
    # Reuse the same synthetic packet; only this transaction race needs PostgreSQL.
    setUp = ApprovalSignatureTests.setUp
    sign = ApprovalSignatureTests.sign
    borrower_signed = ApprovalSignatureTests.borrower_signed
    preceding_signatures = ApprovalSignatureTests.preceding_signatures
    open_packet = ApprovalSignatureTests.open_packet

    def test_withdrawal_racing_final_signature_has_only_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        with patch('origination.services.origination_dispatch.wake_operations'):
            self.preceding_signatures()
            version = self.open_packet()
            self.application.refresh_from_db()
            revision = self.application.revision
            barrier = Barrier(2)
            def change(action):
                try:
                    barrier.wait(timeout=10)
                    if action == 'approve':
                        complete_staff_signatures(package_id=self.package.pk, signer_role='branch_manager', actor=self.bm,
                            signature_capture={'method': 'typed', 'name': 'Synthetic BM'}, expected_revision=revision,
                            request_id='race-approval', reviewed_packet_version=version)
                    else:
                        recall_application(application_id=self.application.pk, actor=self.officer,
                            expected_revision=revision, request_id='race-withdrawal',
                            confirmed_package_id=str(self.package.pk), confirmed_package_hash=self.package.unsigned_document_hash)
                    return 'won'
                except OriginationError:
                    return 'lost'
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(change, action) for action in ['approve', 'withdraw']]
                outcomes = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(outcomes), ['lost', 'won'])
        self.application.refresh_from_db()
        self.package.refresh_from_db()
        if self.application.status == 'approved':
            self.assertEqual(self.package.status, 'fully_signed')
            self.assertEqual(self.package.actions.filter(signer_role='branch_manager', invalidation__isnull=True).count(), 1)
        else:
            self.assertEqual(self.application.status, 'draft')
            self.assertEqual(self.package.status, 'cancelled')
            self.assertFalse(self.package.actions.filter(invalidation__isnull=True).exists())
