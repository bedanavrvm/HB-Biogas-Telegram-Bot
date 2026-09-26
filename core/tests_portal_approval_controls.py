"""Regression tests for Portal approval gates and controlled visit evidence."""

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import AccessGrant, JawabuApprovalRecord, JawabuFarmerMaster, MediaAttachment
from core.services.jawabu_approvals import (
    approval_is_effective,
    create_delegation,
    decision_code,
    invalidate_material_approvals,
    record_approval,
    revoke_delegation,
    require_effective_approval,
    validate_reason,
    visit_media_orphan_report,
)
from core.services.jawabu_pipeline import (
    JBL_FORWARD_STATUS, credit_queue, final_review_queue, log_jbl_visit,
    set_credit_decision, set_final_decision,
)
from core.services.telegram_identity import user_access


class PortalApprovalControlsTests(TestCase):
    def setUp(self):
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Approval Test Customer', national_id='90000001',
            primary_phone='254700000001', branch='EMBU', status='active',
            sign_date='01-July-2026', jbl_visit_date=date(2026, 7, 2),
            jbl_visit_status='Approved', workflow_state='credit',
        )
        self.admin = get_user_model().objects.create_superuser(
            username='approval-admin', email='approval@example.test', password='test-password',
        )
        # Django superuser status grants administration of the technical site,
        # not business approval authority inside the Portal.
        AccessGrant.objects.create(
            user=self.admin, workflow='jawabu_portal', role='BUSINESS_ADMIN', branch='EMBU', active=True,
        )
        self.delegate = get_user_model().objects.create_user(username='approval-delegate', is_active=True)
        AccessGrant.objects.create(
            user=self.delegate, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU', active=True,
        )

    def test_conditional_credit_approval_is_rejected(self):
        ok, error = set_credit_decision(
            self.farmer, decision='Approved with Conditions', imab_created='Yes',
            customer_no='9001', reason_code='affordability', sender='credit',
        )

        self.assertFalse(ok)
        self.assertIn('Invalid credit decision', error)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.credit_decision, '')
        self.assertFalse(self.farmer.approval_records.filter(gate='credit').exists())

    def test_on_hold_decision_uses_the_governed_deferred_approval_code(self):
        self.assertEqual(decision_code('Deferred / On Hold'), JawabuApprovalRecord.DECISION_DEFERRED)
        decision, reason = validate_reason(
            decision='Deferred / On Hold', reason_code='affordability', comment='',
        )
        self.assertEqual(decision, JawabuApprovalRecord.DECISION_DEFERRED)
        self.assertEqual(reason, 'affordability')

    def test_other_negative_decision_reason_requires_an_explanation(self):
        with self.assertRaisesRegex(ValidationError, 'Explain the decision'):
            validate_reason(decision='Rejected', reason_code='other', comment='')

    def test_unauthorized_staff_cannot_record_an_approval(self):
        with self.assertRaises(ValidationError):
            record_approval(
                farmer=self.farmer, gate='credit', decision='Approved',
                actor=self.delegate, access=user_access(self.delegate, 'jawabu_portal'),
            )

    def test_material_change_invalidates_current_approval(self):
        approval = record_approval(
            farmer=self.farmer, gate='credit', decision='Approved', actor=None, access=None,
        )
        changed = invalidate_material_approvals(
            farmer=self.farmer, changed_fields={'system_branch'},
            reason='Controlled system export changed branch.',
        )
        approval.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(approval.status, JawabuApprovalRecord.STATUS_INVALIDATED)
        self.assertFalse(approval_is_effective(self.farmer, 'credit'))

    def test_sysup_lgf_only_change_does_not_invalidate_final_review(self):
        self.farmer.final_decision = 'Approved'
        self.farmer.save(update_fields=['final_decision'])
        approval = record_approval(
            farmer=self.farmer, gate='final_review', decision='Approved', actor=None, access=None,
        )

        changed = invalidate_material_approvals(
            farmer=self.farmer, changed_fields={'system_deposit_paid_jbl'},
            reason='SysUp LGF balance changed.',
        )

        approval.refresh_from_db()
        self.assertEqual(changed, 0)
        self.assertEqual(approval.status, JawabuApprovalRecord.STATUS_ACTIVE)
        require_effective_approval(self.farmer, 'final_review')

    def test_order_validation_blocks_invalidated_final_review_with_reason(self):
        from core.api.portal_views import _validate_requisition_farmers

        self.farmer.final_decision = 'Approved'
        self.farmer.customer_no = '9001'
        self.farmer.imab_created = 'Yes'
        self.farmer.sub_county = 'Kieni'
        self.farmer.village = 'Test village'
        self.farmer.save(update_fields=[
            'final_decision', 'customer_no', 'imab_created', 'sub_county', 'village',
        ])
        record_approval(
            farmer=self.farmer, gate='final_review', decision='Approved', actor=None, access=None,
        )
        invalidate_material_approvals(
            farmer=self.farmer, changed_fields={'national_id'},
            reason='SysUp changed approved case details: National ID.',
        )

        ready, blocked, _warnings = _validate_requisition_farmers([self.farmer])

        self.assertFalse(ready)
        self.assertEqual(len(blocked), 1)
        self.assertIn('National ID', ' '.join(blocked[0]['missing']))

    def test_invalidated_unordered_case_can_repeat_credit_then_final_review(self):
        self.farmer.workflow_state = 'order'
        self.farmer.credit_decision = 'Approved'
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '9001'
        self.farmer.save(update_fields=[
            'workflow_state', 'credit_decision', 'final_decision', 'imab_created', 'customer_no',
        ])
        credit = record_approval(
            farmer=self.farmer, gate='credit', decision='Approved', actor=None, access=None,
        )
        final = record_approval(
            farmer=self.farmer, gate='final_review', decision='Approved', actor=None, access=None,
        )
        invalidate_material_approvals(
            farmer=self.farmer, changed_fields={'system_branch'},
            reason='SysUp changed approved case fields: system_branch.',
        )

        self.assertIn(self.farmer, credit_queue())
        ok, error = set_credit_decision(
            self.farmer, decision='Approved', imab_created='Yes', customer_no='9001',
            expected_revision=self.farmer.workflow_revision,
        )
        self.assertTrue(ok, error)
        self.farmer.refresh_from_db()
        credit.refresh_from_db()
        final.refresh_from_db()
        self.assertEqual(self.farmer.workflow_state, 'final_review')
        self.assertEqual(credit.status, JawabuApprovalRecord.STATUS_INVALIDATED)
        self.assertEqual(final.status, JawabuApprovalRecord.STATUS_INVALIDATED)
        self.assertIn(self.farmer, final_review_queue())

        ok, error = set_final_decision(
            self.farmer, final_decision='Approved', expected_revision=self.farmer.workflow_revision,
        )
        self.assertTrue(ok, error)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.workflow_state, 'order')
        require_effective_approval(self.farmer, 'credit')
        require_effective_approval(self.farmer, 'final_review')

    def test_credit_recheck_invalidates_still_active_final_review(self):
        self.farmer.workflow_state = 'order'
        self.farmer.credit_decision = 'Approved'
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '9001'
        self.farmer.save(update_fields=[
            'workflow_state', 'credit_decision', 'final_decision', 'imab_created', 'customer_no',
        ])
        record_approval(farmer=self.farmer, gate='credit', decision='Approved', actor=None, access=None)
        final = record_approval(
            farmer=self.farmer, gate='final_review', decision='Approved', actor=None, access=None,
        )
        self.farmer.approval_records.filter(gate='credit').update(
            status=JawabuApprovalRecord.STATUS_INVALIDATED,
        )

        ok, error = set_credit_decision(
            self.farmer, decision='Approved', imab_created='Yes', customer_no='9001',
            expected_revision=self.farmer.workflow_revision,
        )

        self.assertTrue(ok, error)
        final.refresh_from_db()
        self.assertEqual(final.status, JawabuApprovalRecord.STATUS_INVALIDATED)

    def test_final_review_can_be_repeated_from_order_before_order_assignment(self):
        self.farmer.workflow_state = 'order'
        self.farmer.credit_decision = 'Approved'
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '9001'
        self.farmer.save(update_fields=[
            'workflow_state', 'credit_decision', 'final_decision', 'imab_created', 'customer_no',
        ])
        record_approval(farmer=self.farmer, gate='credit', decision='Approved', actor=None, access=None)
        final = record_approval(
            farmer=self.farmer, gate='final_review', decision='Approved', actor=None, access=None,
        )
        final.status = JawabuApprovalRecord.STATUS_INVALIDATED
        final.invalidation_reason = 'Case identity changed.'
        final.save(update_fields=['status', 'invalidation_reason'])

        self.assertIn(self.farmer, final_review_queue())
        ok, error = set_final_decision(
            self.farmer, final_decision='Approved', expected_revision=self.farmer.workflow_revision,
        )
        self.assertTrue(ok, error)
        self.farmer.refresh_from_db()
        require_effective_approval(self.farmer, 'final_review')
        self.assertNotIn(self.farmer, final_review_queue())

    def test_approval_recheck_does_not_reopen_an_ordered_case(self):
        self.farmer.workflow_state = 'ordered'
        self.farmer.order_number = '104'
        self.farmer.credit_decision = 'Approved'
        self.farmer.final_decision = 'Approved'
        self.farmer.imab_created = 'Yes'
        self.farmer.customer_no = '9001'
        self.farmer.save(update_fields=[
            'workflow_state', 'order_number', 'credit_decision', 'final_decision',
            'imab_created', 'customer_no',
        ])
        credit = record_approval(farmer=self.farmer, gate='credit', decision='Approved', actor=None, access=None)
        final = record_approval(
            farmer=self.farmer, gate='final_review', decision='Approved', actor=None, access=None,
        )
        self.farmer.approval_records.update(status=JawabuApprovalRecord.STATUS_INVALIDATED)

        self.assertNotIn(self.farmer, credit_queue())
        self.assertNotIn(self.farmer, final_review_queue())
        ok, _error = set_credit_decision(
            self.farmer, decision='Approved', imab_created='Yes', customer_no='9001',
            expected_revision=self.farmer.workflow_revision,
        )
        self.assertFalse(ok)
        ok, _error = set_final_decision(
            self.farmer, final_decision='Approved', expected_revision=self.farmer.workflow_revision,
        )
        self.assertFalse(ok)
        credit.refresh_from_db()
        final.refresh_from_db()
        self.assertEqual(credit.status, JawabuApprovalRecord.STATUS_INVALIDATED)
        self.assertEqual(final.status, JawabuApprovalRecord.STATUS_INVALIDATED)

    def test_temporary_delegation_is_scoped_and_cannot_be_self_granted(self):
        admin_access = user_access(self.admin, 'jawabu_portal')
        with self.assertRaises(ValidationError):
            create_delegation(
                delegate=self.admin, gate='credit', authorized_by=self.admin,
                authorization_access=admin_access, reason='Invalid self grant',
            )
        with self.assertRaises(ValidationError):
            create_delegation(
                delegate=self.delegate, gate='credit', authorized_by=self.admin,
                authorization_access=admin_access, reason='Too long',
                expires_at=timezone.now() + timedelta(days=15),
            )
        with self.assertRaisesRegex(ValidationError, 'Choose a branch'):
            create_delegation(
                delegate=self.delegate, gate='credit', authorized_by=self.admin,
                authorization_access=admin_access, reason='Invalid all-branch hand-off',
                expires_at=timezone.now() + timedelta(days=2),
            )
        delegation = create_delegation(
            delegate=self.delegate, gate='credit', authorized_by=self.admin,
            authorization_access=admin_access, reason='Annual leave cover', branch='EMBU',
            expires_at=timezone.now() + timedelta(days=2),
        )
        self.assertTrue(delegation.active)

        other_admin = get_user_model().objects.create_user(username='other-approval-admin', is_active=True)
        AccessGrant.objects.create(
            user=other_admin, workflow='jawabu_portal', role='BUSINESS_ADMIN', branch='NAKURU', active=True,
        )
        with self.assertRaisesRegex(ValidationError, 'outside your Portal branch authority'):
            revoke_delegation(
                delegation_id=delegation.pk,
                actor=other_admin,
                access=user_access(other_admin, 'jawabu_portal'),
                reason='Not my branch.',
            )

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_forward_jbl_visit_requires_both_controlled_evidence_types(self, _master_sync, _order_sync):
        visit_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Visit Evidence Customer', national_id='90000002',
            primary_phone='254700000002', branch='EMBU', status='active', sign_date='01-July-2026',
        )
        ok, error = log_jbl_visit(
            visit_farmer, visit_date=date(2026, 7, 2), officer='BRO',
            visit_status=JBL_FORWARD_STATUS, village='Test Village', location_unavailable_reason='GPS disabled by device policy.',
            require_visit_evidence=True,
        )
        self.assertFalse(ok)
        self.assertIn('LAF document', error)

        for category in ('CLIENT_ID', 'LAF', 'JBL_VISIT_PHOTO'):
            MediaAttachment.objects.create(
                group_id='portal-test', jawabu_farmer=visit_farmer,
                file_type=category, upload_status='success',
                original_filename=f'{category}.jpg', drive_url=f'https://drive.example/{category}',
            )
        ok, error = log_jbl_visit(
            visit_farmer, visit_date=date(2026, 7, 2), officer='BRO',
            visit_status=JBL_FORWARD_STATUS, village='Test Village', location_unavailable_reason='GPS disabled by device policy.',
            require_visit_evidence=True,
        )
        self.assertTrue(ok, error)
        visit_farmer.refresh_from_db()
        self.assertEqual(visit_farmer.workflow_state, 'credit')

    def test_orphan_media_report_is_read_only_and_excludes_legacy_linkable_rows(self):
        MediaAttachment.objects.create(
            group_id='portal-test', file_type='LAF', upload_status='success',
            business_key_type='id_number', business_key_value=self.farmer.national_id,
        )
        orphan = MediaAttachment.objects.create(
            group_id='portal-test', file_type='JBL_VISIT_PHOTO', upload_status='success',
            business_key_type='case_reference', business_key_value='case-missing',
        )

        report = visit_media_orphan_report()

        self.assertEqual(report['legacy_linkable_count'], 1)
        self.assertEqual(report['orphan_candidate_count'], 1)
        self.assertEqual(report['orphan_candidates'][0]['attachment_id'], str(orphan.id))
        self.assertTrue(MediaAttachment.objects.filter(pk=orphan.pk).exists())
