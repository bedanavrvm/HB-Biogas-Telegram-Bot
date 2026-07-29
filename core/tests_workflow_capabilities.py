"""Regression tests for the controlled Mini App capability matrix."""

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test.client import RequestFactory
from django.test import TestCase

from core.api.portal_views import portal_meta
from core.models import AccessGrant, WorkflowRoleCapability, WorkflowRoleCapabilityAuditEvent
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
        ).update(enabled=False)
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


class WorkflowCapabilityMatrixAdminTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username='matrix-admin', email='matrix@example.test', password='password',
        )
        self.client.force_login(self.superuser)

    def test_matrix_save_records_an_audit_event(self):
        response = self.client.post('/admin/core/workflowrolecapability/matrix/', {
            'workflow': 'complaint_cases',
            'role': 'OFFICER',
            'apply_matrix': '1',
            'capability:complaint.queue.view': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(WorkflowRoleCapabilityAuditEvent.objects.filter(
            workflow='complaint_cases', role='OFFICER', actor=self.superuser,
        ).exists())
        self.assertTrue(WorkflowRoleCapability.objects.get(
            workflow='complaint_cases', role='OFFICER', capability_key='complaint.queue.view',
        ).enabled)
        self.assertFalse(WorkflowRoleCapability.objects.get(
            workflow='complaint_cases', role='OFFICER', capability_key='complaint.case.create',
        ).enabled)
