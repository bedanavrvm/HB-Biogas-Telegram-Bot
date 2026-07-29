"""Regression tests for the controlled Mini App capability matrix."""

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test.client import RequestFactory
from django.test import TestCase

from core.api.portal_views import portal_meta
from core.models import AccessControlChangeRequest, AccessGrant, EmergencyAccessGrant, WorkflowRoleCapability, WorkflowRoleCapabilityAuditEvent
from core.services.access_control import APPROVER_GROUP_NAME, approve_request, create_capability_request, create_emergency_grant
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

    def test_maker_cannot_apply_own_policy_request_but_another_approver_can(self):
        maker = get_user_model().objects.create_superuser(username='maker', email='maker@example.test', password='password')
        approver = get_user_model().objects.create_superuser(username='checker', email='checker@example.test', password='password')
        approver.groups.add(Group.objects.get_or_create(name=APPROVER_GROUP_NAME)[0])
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
        approver.groups.add(Group.objects.get_or_create(name=APPROVER_GROUP_NAME)[0])
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
