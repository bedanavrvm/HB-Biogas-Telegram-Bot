"""Regression tests for the controlled Mini App capability matrix."""

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.test.client import RequestFactory
from django.test import TestCase

from core.api.portal_views import portal_meta
from core.models import (
    AccessControlChangeRequest,
    AccessControlCheckerAssignment,
    AccessGrant,
    ComplianceAuditEvent,
    EmergencyAccessGrant,
    WorkflowRoleCapability,
    WorkflowRoleCapabilityAuditEvent,
)
from core.services.access_control import (
    APPROVER_GROUP_NAME,
    appoint_access_control_checker,
    approve_request,
    can_approve_access_change,
    create_capability_request,
    create_emergency_grant,
    revoke_access_control_checker,
)
from core.services.access_policies import WORKFLOW_ROLES
from core.services.business_admin import legacy_business_admin_cutover_issues
from core.services.telegram_identity import user_access
from core.services.workflow_capabilities import (
    capabilities_for_workflow,
    dependency_closure,
    effective_capability_keys,
)


class WorkflowCapabilityPolicyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='matrix-user', is_active=True)
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )

    def test_access_grant_not_django_group_is_the_mini_app_role_source(self):
        self.user.groups.add(Group.objects.create(name='ADMIN'))
        access = user_access(self.user, 'jawabu_portal')
        self.assertEqual(access['roles'], ['JBL_OFFICER'])
        self.assertTrue(access['authorized'])

    def test_legacy_approver_group_membership_no_longer_grants_checker_authority(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.user.groups.add(Group.objects.get_or_create(name=APPROVER_GROUP_NAME)[0])

        self.assertFalse(can_approve_access_change(self.user))

    def test_django_superuser_has_no_miniapp_bypass_but_business_admin_grant_is_effective(self):
        superuser = get_user_model().objects.create_superuser(
            username='technical-only', email='technical@example.test', password='password',
        )
        no_grant_access = user_access(superuser, 'jawabu_portal')
        self.assertFalse(no_grant_access['authorized'])
        self.assertEqual(
            effective_capability_keys(superuser, 'jawabu_portal', access=no_grant_access),
            set(),
        )

        AccessGrant.objects.create(
            user=superuser, workflow='jawabu_portal', role='BUSINESS_ADMIN', branch='EMBU',
        )
        business_access = user_access(superuser, 'jawabu_portal')
        self.assertIn('BUSINESS_ADMIN', business_access['roles'])
        self.assertIn(
            'portal.payment.review',
            effective_capability_keys(superuser, 'jawabu_portal', access=business_access),
        )

    def test_business_admin_cutover_preflight_flags_pending_legacy_request(self):
        AccessControlChangeRequest.objects.create(
            change_type=AccessControlChangeRequest.TYPE_GRANT,
            workflow='tat_tracker', role='ADMIN', reason='Legacy request awaiting approval.',
            status=AccessControlChangeRequest.STATUS_PENDING, requested_by=self.user,
        )
        issue_codes = {issue.code for issue in legacy_business_admin_cutover_issues()}
        self.assertIn('pending-legacy-policy-request', issue_codes)
        with self.assertRaises(CommandError):
            call_command('check_business_admin_cutover', '--strict')

    def test_seeded_policy_preserves_existing_jbl_officer_capabilities(self):
        access = user_access(self.user, 'jawabu_portal')
        capabilities = effective_capability_keys(self.user, 'jawabu_portal', access=access)
        self.assertIn('portal.jbl_queue.view', capabilities)
        self.assertIn('portal.jbl_visit.write', capabilities)
        self.assertNotIn('portal.credit.write', capabilities)

    def test_disabling_a_matrix_row_is_immediate_and_fail_closed(self):
        policy = WorkflowRoleCapability.objects.get(
            workflow='jawabu_portal', role='JBL_OFFICER', capability_key='portal.jbl_visit.write',
        )
        policy.enabled = False
        policy.save(update_fields=['enabled', 'updated_at'])
        access = user_access(self.user, 'jawabu_portal')
        self.assertNotIn(
            'portal.jbl_visit.write',
            effective_capability_keys(self.user, 'jawabu_portal', access=access),
        )

    def test_shared_portal_metadata_does_not_require_dashboard_capability(self):
        WorkflowRoleCapability.objects.filter(
            workflow='jawabu_portal', role='JBL_OFFICER', capability_key='portal.dashboard.view',
        ).update(enabled=False, effect='deny')
        access = user_access(self.user, 'jawabu_portal')
        request = RequestFactory().get('/api/portal/meta/')
        request.portal_user = self.user
        request.portal_access = access

        response = portal_meta(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertNotIn('portal.dashboard.view', payload['capabilities'])
        self.assertIn('portal.jbl_queue.view', payload['capabilities'])

    def test_dependency_closure_keeps_required_screen_visible(self):
        keys = dependency_closure('jawabu_portal', {'portal.invoice.write'})
        self.assertEqual(keys, {'portal.invoice.write', 'portal.invoice.view'})

    def test_catalogue_keys_are_scoped_to_their_workflow(self):
        self.assertTrue(capabilities_for_workflow('tat_tracker'))
        self.assertFalse(any(
            item.key.startswith('portal.')
            for item in capabilities_for_workflow('complaint_cases')
        ))

    def test_it_role_exists_in_every_miniapp_workflow_with_minimum_seeded_access(self):
        expected_capabilities = {
            'jawabu_portal': {
                'portal.dashboard.view', 'portal.case.read', 'portal.workspace.manage',
                'portal.health.read', 'portal.health.maintenance.manage', 'portal.imports.view',
            },
            'complaint_cases': {'complaint.queue.view'},
            'tat_tracker': {'tat.home.view'},
            'spin_credit_analysis': {'spin.request.view'},
        }

        for workflow, expected in expected_capabilities.items():
            self.assertIn('IT', {role for role, _label in WORKFLOW_ROLES[workflow]})
            enabled = set(WorkflowRoleCapability.objects.filter(
                workflow=workflow,
                role='IT',
                effect=WorkflowRoleCapability.EFFECT_ALLOW,
            ).values_list('capability_key', flat=True))
            self.assertTrue(expected.issubset(enabled), workflow)

    def test_only_it_gets_the_portal_maintenance_capability(self):
        jbl_access = user_access(self.user, 'jawabu_portal')
        self.assertNotIn(
            'portal.health.maintenance.manage',
            effective_capability_keys(self.user, 'jawabu_portal', access=jbl_access),
        )
        it_user = get_user_model().objects.create_user(username='portal-it', is_active=True)
        AccessGrant.objects.create(user=it_user, workflow='jawabu_portal', role='IT')
        it_access = user_access(it_user, 'jawabu_portal')
        self.assertIn(
            'portal.health.maintenance.manage',
            effective_capability_keys(it_user, 'jawabu_portal', access=it_access),
        )

    def test_maker_cannot_apply_own_policy_request_but_another_approver_can(self):
        maker = get_user_model().objects.create_superuser(username='maker', email='maker@example.test', password='password')
        approver = get_user_model().objects.create_superuser(username='checker', email='checker@example.test', password='password')
        request = create_capability_request(
            requester=maker, workflow='jawabu_portal', role='JBL_OFFICER',
            capability_keys={'portal.jbl_queue.view'}, reason='Least privilege review',
        )
        with self.assertRaises(PermissionDenied):
            approve_request(request_id=request.pk, approver=maker)
        self.assertEqual(request.status, AccessControlChangeRequest.STATUS_PENDING)
        approve_request(request_id=request.pk, approver=approver)
        request.refresh_from_db()
        self.assertEqual(request.status, AccessControlChangeRequest.STATUS_APPLIED)
        self.assertFalse(WorkflowRoleCapability.objects.get(
            workflow='jawabu_portal', role='JBL_OFFICER', capability_key='portal.jbl_visit.write',
        ).enabled)

    def test_sole_superuser_bootstrap_override_requires_a_reason_then_is_audited(self):
        root = get_user_model().objects.create_superuser(
            username='sole-root', email='sole-root@example.test', password='password',
        )
        request = create_capability_request(
            requester=root,
            workflow='jawabu_portal',
            role='JBL_OFFICER',
            capability_keys={'portal.jbl_queue.view'},
            reason='Establish initial least-privilege baseline.',
        )

        with self.assertRaises(ValidationError):
            approve_request(request_id=request.pk, approver=root)
        request.refresh_from_db()
        self.assertEqual(request.status, AccessControlChangeRequest.STATUS_PENDING)

        approve_request(
            request_id=request.pk,
            approver=root,
            review_comment='Bootstrap override: no independent checker is active.',
        )
        request.refresh_from_db()
        self.assertEqual(request.status, AccessControlChangeRequest.STATUS_APPLIED)
        event = ComplianceAuditEvent.objects.get(source_event_id=f'{request.pk}:applied')
        self.assertEqual(event.action, 'access_control.change.bootstrap_override_applied')
        self.assertEqual(event.metadata['decision_mode'], 'bootstrap_override')

    def test_superuser_can_appoint_and_revoke_an_independent_checker(self):
        root = get_user_model().objects.create_superuser(
            username='root-admin', email='root-admin@example.test', password='password',
        )
        checker = get_user_model().objects.create_user(
            username='independent-checker',
            is_active=True,
            is_staff=True,
        )

        assignment, created = appoint_access_control_checker(
            actor=root,
            user=checker,
            reason='Establish the first independent access-control checker.',
        )

        self.assertTrue(created)
        self.assertEqual(assignment.source, AccessControlCheckerAssignment.SOURCE_BOOTSTRAP)
        self.assertTrue(can_approve_access_change(checker))
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            action='access_control.checker.appointed',
            subject_id=str(assignment.pk),
        ).exists())

        request = create_capability_request(
            requester=root,
            workflow='jawabu_portal',
            role='JBL_OFFICER',
            capability_keys={'portal.jbl_queue.view'},
            reason='Confirm independent approval is now required.',
        )
        with self.assertRaises(PermissionDenied):
            approve_request(
                request_id=request.pk,
                approver=root,
                review_comment='This must be denied because a checker is active.',
            )
        approve_request(request_id=request.pk, approver=checker)

        assignment, changed = revoke_access_control_checker(
            actor=root,
            assignment=assignment,
            reason='Checker role moved to another staff member.',
        )
        self.assertTrue(changed)
        self.assertFalse(assignment.active)
        self.assertFalse(can_approve_access_change(checker))
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            action='access_control.checker.revoked',
            subject_id=str(assignment.pk),
        ).exists())

    def test_checker_appointment_requires_deliberate_django_admin_access(self):
        root = get_user_model().objects.create_superuser(
            username='appointment-root', email='appointment-root@example.test', password='password',
        )
        telegram_only_user = get_user_model().objects.create_user(
            username='telegram-only-checker',
            is_active=True,
            is_staff=False,
        )

        with self.assertRaises(ValidationError):
            appoint_access_control_checker(
                actor=root,
                user=telegram_only_user,
                reason='This should not create an unreachable admin reviewer.',
            )
        self.assertFalse(AccessControlCheckerAssignment.objects.filter(user=telegram_only_user).exists())

    def test_appointed_checker_can_open_the_admin_review_queue_without_extra_model_permissions(self):
        root = get_user_model().objects.create_superuser(
            username='review-root', email='review-root@example.test', password='password',
        )
        checker = get_user_model().objects.create_user(
            username='review-checker', is_active=True, is_staff=True,
        )
        appoint_access_control_checker(
            actor=root,
            user=checker,
            reason='Provide the independent reviewer with the dedicated queue only.',
        )
        request = create_capability_request(
            requester=self.user,
            workflow='jawabu_portal',
            role='JBL_OFFICER',
            capability_keys={'portal.jbl_queue.view'},
            reason='Review queue visibility test.',
        )

        self.client.force_login(checker)
        response = self.client.get(reverse('admin:core_accesscontrolchangerequest_change', args=[request.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Approval decision')

    def test_emergency_grant_is_resolved_without_creating_a_permanent_grant(self):
        actor = get_user_model().objects.create_superuser(username='emergency-admin', email='emergency@example.test', password='password')
        target = get_user_model().objects.create_user(username='emergency-user', is_active=True)
        grant = create_emergency_grant(
            actor=actor, user=target, workflow='tat_tracker', role='BRO', reason='Approved after-hours correction',
        )
        access = user_access(target, 'tat_tracker')
        self.assertTrue(access['authorized'])
        self.assertIn('BRO', access['roles'])
        self.assertEqual(EmergencyAccessGrant.objects.filter(pk=grant.pk).count(), 1)
        self.assertFalse(AccessGrant.objects.filter(user=target, workflow='tat_tracker').exists())


class WorkflowCapabilityMatrixAdminTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username='matrix-admin', email='matrix@example.test', password='password',
        )
        self.client.force_login(self.superuser)

    def test_matrix_submission_requires_an_independent_approval(self):
        approver = get_user_model().objects.create_superuser(
            username='matrix-approver', email='approver@example.test', password='password',
        )
        response = self.client.post('/admin/core/workflowrolecapability/matrix/', {
            'workflow': 'complaint_cases',
            'role': 'OFFICER',
            'propose_matrix': '1',
            'capability:complaint.queue.view': 'on',
            'reason': 'Test controlled change',
        })
        self.assertEqual(response.status_code, 302)
        change = AccessControlChangeRequest.objects.get(workflow='complaint_cases', role='OFFICER')
        self.assertEqual(change.status, AccessControlChangeRequest.STATUS_PENDING)
        self.assertFalse(WorkflowRoleCapability.objects.get(
            workflow='complaint_cases', role='OFFICER', capability_key='complaint.case.create',
        ).effect == 'deny')
        approve_request(request_id=change.pk, approver=approver)
        self.assertTrue(WorkflowRoleCapabilityAuditEvent.objects.filter(
            workflow='complaint_cases', role='OFFICER', actor=approver,
        ).exists())
        self.assertTrue(WorkflowRoleCapability.objects.get(
            workflow='complaint_cases', role='OFFICER', capability_key='complaint.queue.view',
        ).enabled)
        self.assertFalse(WorkflowRoleCapability.objects.get(
            workflow='complaint_cases', role='OFFICER', capability_key='complaint.case.create',
        ).enabled)

    def test_matrix_displays_impact_and_search_controls(self):
        response = self.client.get('/admin/core/workflowrolecapability/matrix/?workflow=jawabu_portal&role=JBL_OFFICER')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Impact:')
        self.assertContains(response, 'Find capability')
        self.assertContains(response, 'Submit for approval')
