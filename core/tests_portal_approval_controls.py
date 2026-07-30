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
    clear_condition,
    create_delegation,
    invalidate_material_approvals,
    record_approval,
    require_effective_approval,
    visit_media_orphan_report,
)
from core.services.jawabu_pipeline import log_jbl_visit, set_credit_decision
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

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_conditional_credit_approval_blocks_then_advances_when_evidenced(self, _master_sync, _order_sync):
        ok, error = set_credit_decision(
            self.farmer, decision='Approved with Conditions', imab_created='Yes',
            customer_no='9001', reason_code='affordability',
            conditions=['Confirm current income document.'], sender='credit',
        )

        self.assertTrue(ok, error)
        self.farmer.refresh_from_db()
        approval = self.farmer.approval_records.get(gate='credit')
        self.assertEqual(approval.status, JawabuApprovalRecord.STATUS_CONDITIONS_PENDING)
        self.assertFalse(approval_is_effective(self.farmer, 'credit'))
        with self.assertRaises(ValidationError):
            require_effective_approval(self.farmer, 'credit')

        condition = approval.conditions.get()
        clear_condition(
            condition_id=condition.pk,
            actor=self.admin,
            access=user_access(self.admin, 'jawabu_portal'),
            note='Income document reviewed.',
        )
        self.farmer.refresh_from_db()
        approval.refresh_from_db()
        self.assertEqual(approval.status, JawabuApprovalRecord.STATUS_ACTIVE)
        self.assertEqual(self.farmer.credit_decision, 'Approved')
        self.assertEqual(self.farmer.workflow_state, 'final_review')

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
        delegation = create_delegation(
            delegate=self.delegate, gate='credit', authorized_by=self.admin,
            authorization_access=admin_access, reason='Annual leave cover', branch='EMBU',
            expires_at=timezone.now() + timedelta(days=2),
        )
        self.assertTrue(delegation.active)

    @patch('core.services.jawabu_pipeline.sync_farmer_to_internal_order_sheet')
    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_forward_jbl_visit_requires_both_controlled_evidence_types(self, _master_sync, _order_sync):
        visit_farmer = JawabuFarmerMaster.objects.create(
            customer_name='Visit Evidence Customer', national_id='90000002',
            primary_phone='254700000002', branch='EMBU', status='active', sign_date='01-July-2026',
        )
        ok, error = log_jbl_visit(
            visit_farmer, visit_date=date(2026, 7, 2), officer='BRO',
            visit_status='Approved', location_unavailable_reason='GPS disabled by device policy.',
            require_visit_evidence=True,
        )
        self.assertFalse(ok)
        self.assertIn('signed LAF document', error)

        for category in ('LAF', 'JBL_VISIT_PHOTO'):
            MediaAttachment.objects.create(
                group_id='portal-test', jawabu_farmer=visit_farmer,
                file_type=category, upload_status='success',
                original_filename=f'{category}.jpg', drive_url=f'https://drive.example/{category}',
            )
        ok, error = log_jbl_visit(
            visit_farmer, visit_date=date(2026, 7, 2), officer='BRO',
            visit_status='Approved', location_unavailable_reason='GPS disabled by device policy.',
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
