"""Regression tests for the controlled Mini App capability matrix."""

import json
import hashlib
import hmac
import time
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.test.client import RequestFactory
from django.test import TestCase, override_settings

from core.api.portal_views import portal_meta
from core.models import (
    AccessControlChangeRequest,
    AccessControlCheckerAssignment,
    AccessGrant,
    ComplianceAuditEvent,
    EmergencyAccessGrant,
    JawabuFarmerMaster,
    Product,
    WorkflowRoleCapability,
    WorkflowRoleCapabilityAuditEvent,
)
from core.services.access_control import (
    APPROVER_GROUP_NAME,
    apply_superuser_grant_override,
    appoint_access_control_checker,
    approve_request,
    can_approve_access_change,
    create_capability_request,
    create_emergency_grant,
    create_grant_request,
    policy_version,
    revoke_access_control_checker,
    revoke_emergency_grant,
)
from core.services.access_policies import WORKFLOW_ROLES
from core.services.business_admin import legacy_business_admin_cutover_issues
from core.services.portal_permissions import portal_access_decision, scope_portal_case_queryset
from core.services.telegram_identity import (
    TelegramAuthenticationError, user_access, validate_telegram_init_data,
)
from core.services.workflow_capabilities import (
    capabilities_for_workflow,
    dependency_closure,
    effective_capability_keys,
)
from core.services.workflow_access import (
    MINIAPP_DYNAMIC_ENDPOINT_POLICIES,
    MINIAPP_ENDPOINT_CAPABILITIES,
    workflow_access_decision,
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

    def test_django_superuser_is_auditable_technical_break_glass_override(self):
        superuser = get_user_model().objects.create_superuser(
            username='technical-only', email='technical@example.test', password='password',
        )
        no_grant_access = user_access(superuser, 'jawabu_portal')
        self.assertTrue(no_grant_access['authorized'])
        capabilities = effective_capability_keys(superuser, 'jawabu_portal', access=no_grant_access)
        self.assertIn('portal.health.maintenance.manage', capabilities)
        self.assertIn('portal.final_review.write', capabilities)

        AccessGrant.objects.create(
            user=superuser, workflow='jawabu_portal', role='BUSINESS_ADMIN', branch='EMBU',
        )
        business_access = user_access(superuser, 'jawabu_portal')
        self.assertIn('BUSINESS_ADMIN', business_access['roles'])
        self.assertIn(
            'portal.payment.review',
            effective_capability_keys(superuser, 'jawabu_portal', access=business_access),
        )

    def test_portal_role_separation_preserves_jbl_followup_but_denies_generation(self):
        access = user_access(self.user, 'jawabu_portal')
        capabilities = effective_capability_keys(self.user, 'jawabu_portal', access=access)
        self.assertIn('portal.jbl_followup.view', capabilities)
        self.assertIn('portal.requisition.view', capabilities)
        self.assertNotIn('portal.requisition.write', capabilities)
        self.assertNotIn('portal.requisition.preview', capabilities)

        operations = get_user_model().objects.create_user(username='ops-admin', is_active=True)
        AccessGrant.objects.create(
            user=operations, workflow='jawabu_portal', role='OPERATIONS_ADMIN', branch='EMBU',
        )
        operation_caps = effective_capability_keys(
            operations, 'jawabu_portal', access=user_access(operations, 'jawabu_portal'),
        )
        self.assertIn('portal.requisition.write', operation_caps)
        self.assertIn('portal.documents.sign', operation_caps)
        self.assertNotIn('portal.jbl_visit.write', operation_caps)
        self.assertNotIn('portal.final_review.write', operation_caps)

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

    def test_global_resolver_does_not_compose_role_and_scope_across_grants(self):
        grants = [
            SimpleNamespace(
                pk='one', role='BRO', branch='EMBU', product='business',
                group_configuration_id=None, group_configuration=None,
            ),
            SimpleNamespace(
                pk='two', role='IT', branch='NAKURU', product='logbook',
                group_configuration_id=None, group_configuration=None,
            ),
        ]
        access = {'authorized': True, 'roles': ['BRO', 'IT'], 'grants': grants}

        self.assertTrue(workflow_access_decision(
            self.user, 'tat_tracker', 'tat.case.create', access=access,
            branch='EMBU', product='business',
        ).allowed)
        self.assertFalse(workflow_access_decision(
            self.user, 'tat_tracker', 'tat.case.create', access=access,
            branch='EMBU', product='logbook',
        ).allowed)

    def test_global_resolver_enforces_group_scope_and_allows_global_grant(self):
        group_one = SimpleNamespace(pk='group-one', group_id='-1001')
        group_two = SimpleNamespace(pk='group-two', group_id='-1002')
        scoped = SimpleNamespace(
            pk='scoped', role='MANAGER', branch='', product='',
            group_configuration_id='group-one', group_configuration=group_one,
        )
        access = {'authorized': True, 'roles': ['MANAGER'], 'grants': [scoped]}
        self.assertTrue(workflow_access_decision(
            self.user, 'complaint_cases', 'complaint.case.manage', access=access,
            group_configuration=group_one,
        ).allowed)
        self.assertFalse(workflow_access_decision(
            self.user, 'complaint_cases', 'complaint.case.manage', access=access,
            group_configuration=group_two,
        ).allowed)

        global_grant = SimpleNamespace(
            pk='global', role='MANAGER', branch='', product='',
            group_configuration_id=None, group_configuration=None,
        )
        access['grants'].append(global_grant)
        self.assertTrue(workflow_access_decision(
            self.user, 'complaint_cases', 'complaint.case.manage', access=access,
            group_configuration=group_two,
        ).allowed)

    def test_endpoint_manifest_only_references_real_capabilities_and_views(self):
        from core.api import complaint_case_views, views
        from core.services.workflow_capabilities import capability_definition

        for view_name, (workflow, capability) in MINIAPP_ENDPOINT_CAPABILITIES.items():
            self.assertIsNotNone(capability_definition(workflow, capability), view_name)
            module = complaint_case_views if view_name.startswith('complaint_cases_') else views
            self.assertTrue(callable(getattr(module, view_name, None)), view_name)
        for view_name in MINIAPP_DYNAMIC_ENDPOINT_POLICIES:
            self.assertTrue(callable(getattr(views, view_name, None)), view_name)

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

    def test_sole_superuser_cannot_bootstrap_approve_operational_access(self):
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

        with self.assertRaises(PermissionDenied):
            approve_request(request_id=request.pk, approver=root)
        request.refresh_from_db()
        self.assertEqual(request.status, AccessControlChangeRequest.STATUS_PENDING)

        self.assertFalse(ComplianceAuditEvent.objects.filter(source_event_id=f'{request.pk}:applied').exists())

    def test_superuser_direct_grant_override_is_retired(self):
        root = get_user_model().objects.create_superuser(
            username='grant-root', email='grant-root@example.test', password='password',
        )
        other_root = get_user_model().objects.create_superuser(
            username='grant-other-root', email='grant-other-root@example.test', password='password',
        )
        target = get_user_model().objects.create_user(username='grant-target', is_active=True)
        with self.assertRaises(PermissionDenied):
            apply_superuser_grant_override(
                actor=root,
                user=target,
                workflow='jawabu_portal',
                role='JBL_OFFICER',
            )
        self.assertFalse(AccessGrant.objects.filter(user=target).exists())

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
            confirmation_phrase='APPOINT FIRST CHECKER',
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
            confirmation_phrase='APPOINT FIRST CHECKER',
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


class PortalAccessHardeningTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='scoped-user', is_active=True)
        self.embu = JawabuFarmerMaster.objects.create(customer_name='Embu case', branch='EMBU')
        self.nakuru = JawabuFarmerMaster.objects.create(customer_name='Nakuru case', branch='NAKURU')

    def test_role_and_scope_are_resolved_from_the_same_grant(self):
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='CREDIT_ANALYST', branch='NAKURU',
        )
        access = user_access(self.user, 'jawabu_portal')

        self.assertTrue(portal_access_decision(
            self.user, 'portal.jbl_visit.write', access=access, resource=self.embu,
        ).allowed)
        self.assertFalse(portal_access_decision(
            self.user, 'portal.jbl_visit.write', access=access, resource=self.nakuru,
        ).allowed)
        self.assertTrue(portal_access_decision(
            self.user, 'portal.credit.write', access=access, resource=self.nakuru,
        ).allowed)
        self.assertFalse(portal_access_decision(
            self.user, 'portal.credit.write', access=access, resource=self.embu,
        ).allowed)
        self.assertEqual(
            list(scope_portal_case_queryset(
                JawabuFarmerMaster.objects.all(), self.user,
                'portal.jbl_visit.write', access=access,
            ).values_list('pk', flat=True)),
            [self.embu.pk],
        )

    def test_global_grant_for_one_role_does_not_widen_another_role(self):
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='JBL_OFFICER',
        )
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='CREDIT_ANALYST', branch='NAKURU',
        )
        access = user_access(self.user, 'jawabu_portal')

        self.assertTrue(portal_access_decision(
            self.user, 'portal.jbl_visit.write', access=access, resource=self.nakuru,
        ).allowed)
        self.assertFalse(portal_access_decision(
            self.user, 'portal.credit.write', access=access, resource=self.embu,
        ).allowed)

    def test_branch_scoped_grant_fails_closed_for_unclassified_case(self):
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )
        unclassified = JawabuFarmerMaster.objects.create(customer_name='No branch case')

        self.assertFalse(portal_access_decision(
            self.user, 'portal.jbl_visit.write',
            access=user_access(self.user, 'jawabu_portal'), resource=unclassified,
        ).allowed)

    def test_product_scope_is_enforced_for_case_permissions(self):
        product_a = Product.objects.create(name='Scoped Product A', code='scoped_a')
        product_b = Product.objects.create(name='Scoped Product B', code='scoped_b')
        case_a = JawabuFarmerMaster.objects.create(
            customer_name='Product A case', branch='EMBU', product=product_a,
        )
        case_b = JawabuFarmerMaster.objects.create(
            customer_name='Product B case', branch='EMBU', product=product_b,
        )
        AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='JBL_OFFICER',
            branch='EMBU', product=product_a.code,
        )
        access = user_access(self.user, 'jawabu_portal')

        self.assertTrue(portal_access_decision(
            self.user, 'portal.jbl_visit.write', access=access, resource=case_a,
        ).allowed)
        self.assertFalse(portal_access_decision(
            self.user, 'portal.jbl_visit.write', access=access, resource=case_b,
        ).allowed)

    def test_multi_role_policy_change_is_one_atomic_request(self):
        maker = get_user_model().objects.create_superuser(
            username='atomic-maker', email='atomic-maker@example.test', password='password',
        )
        checker = get_user_model().objects.create_superuser(
            username='atomic-checker', email='atomic-checker@example.test', password='password',
        )
        change = create_capability_request(
            requester=maker, workflow='jawabu_portal',
            roles=['JBL_OFFICER', 'CREDIT_ANALYST'],
            capability_keys={'portal.case.read'}, reason='Apply one reviewed baseline.',
            request_key='atomic-policy-1',
        )
        duplicate = create_capability_request(
            requester=maker, workflow='jawabu_portal', roles=['JBL_OFFICER'],
            capability_keys=set(), reason='Repeated network submission.',
            request_key='atomic-policy-1',
        )
        self.assertEqual(duplicate.pk, change.pk)
        self.assertEqual(change.target_roles, ['JBL_OFFICER', 'CREDIT_ANALYST'])

        approve_request(request_id=change.pk, approver=checker)

        for role in change.target_roles:
            self.assertEqual(set(WorkflowRoleCapability.objects.filter(
                workflow='jawabu_portal', role=role,
                effect=WorkflowRoleCapability.EFFECT_ALLOW,
            ).values_list('capability_key', flat=True)), {'portal.case.read'})

    def test_unrelated_requests_do_not_become_stale_after_first_approval(self):
        maker = get_user_model().objects.create_superuser(
            username='parallel-maker', email='parallel-maker@example.test', password='password',
        )
        checker = get_user_model().objects.create_superuser(
            username='parallel-checker', email='parallel-checker@example.test', password='password',
        )
        first = create_capability_request(
            requester=maker, workflow='complaint_cases', role='OFFICER',
            capability_keys={'complaint.queue.view'}, reason='Officer review.',
        )
        second = create_capability_request(
            requester=maker, workflow='complaint_cases', role='MANAGER',
            capability_keys={'complaint.queue.view'}, reason='Manager review.',
        )

        approve_request(request_id=first.pk, approver=checker)
        approve_request(request_id=second.pk, approver=checker)
        second.refresh_from_db()

        self.assertEqual(second.status, AccessControlChangeRequest.STATUS_APPLIED)

    def test_checker_cannot_approve_a_grant_for_their_own_account(self):
        root = get_user_model().objects.create_superuser(
            username='conflict-root', email='conflict-root@example.test', password='password',
        )
        checker = get_user_model().objects.create_user(
            username='conflicted-checker', is_active=True, is_staff=True,
        )
        appoint_access_control_checker(
            actor=root, user=checker, reason='Independent reviewer.',
            confirmation_phrase='APPOINT FIRST CHECKER',
        )
        change = create_grant_request(
            requester=root, user=checker, workflow='jawabu_portal', role='IT',
            reason='Requested support access.',
        )

        with self.assertRaises(PermissionDenied):
            approve_request(request_id=change.pk, approver=checker)

    def test_emergency_access_is_idempotent_and_revocable(self):
        root = get_user_model().objects.create_superuser(
            username='emergency-root', email='emergency-root@example.test', password='password',
        )
        first = create_emergency_grant(
            actor=root, user=self.user, workflow='jawabu_portal', role='IT',
            reason='Restore urgent support.', request_id='emergency-1',
        )
        repeated = create_emergency_grant(
            actor=root, user=self.user, workflow='jawabu_portal', role='IT',
            reason='Repeated tap.', request_id='emergency-1',
        )
        self.assertEqual(first.pk, repeated.pk)
        revoked, changed = revoke_emergency_grant(
            actor=root, grant=first, reason='Incident resolved.',
        )
        self.assertTrue(changed)
        self.assertIsNotNone(revoked.revoked_at)
        self.assertFalse(user_access(self.user, 'jawabu_portal')['authorized'])

    def test_deactivation_retires_access_and_reactivation_does_not_restore_it(self):
        grant = AccessGrant.objects.create(
            user=self.user, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )
        pending = create_grant_request(
            requester=self.user, user=self.user, workflow='jawabu_portal',
            role='CREDIT_ANALYST', branch='Embu', reason='Pending role change.',
        )
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        grant.refresh_from_db()
        pending.refresh_from_db()
        self.assertFalse(grant.active)
        self.assertEqual(pending.status, AccessControlChangeRequest.STATUS_CANCELLED)

        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        grant.refresh_from_db()
        self.assertFalse(grant.active)
        self.assertFalse(user_access(self.user, 'jawabu_portal')['authorized'])

    def test_future_telegram_auth_date_is_rejected(self):
        token = 'test-bot-token'
        values = {
            'auth_date': str(int(time.time()) + 300),
            'query_id': 'future-query',
            'user': json.dumps({'id': 12345, 'username': 'future-user'}, separators=(',', ':')),
        }
        data_check = '\n'.join(f'{key}={value}' for key, value in sorted(values.items()))
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        values['hash'] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

        with self.assertRaises(TelegramAuthenticationError):
            validate_telegram_init_data(urlencode(values), bot_token=token)

    @override_settings(DEBUG=False, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    def test_deployment_check_rejects_disabled_portal_authentication(self):
        from core.checks import portal_authentication_check

        self.assertEqual(
            [issue.id for issue in portal_authentication_check(None)],
            ['core.E001'],
        )


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
