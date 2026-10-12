"""Workflow-specific role presentation and signing isolation."""
import json
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from core.admin import WorkflowScopedSelect
from core.models import AccessGrant, WorkflowRoleCapability
from core.services.access_policies import role_choices, role_workflow_map
from core.services.telegram_identity import user_access
from origination.services.loan_origination import OriginationError
from origination.services.origination_esign import authorize_staff_signer


class RoleLabelTests(SimpleTestCase):
    def test_choices_use_selected_workflow_without_combined_labels(self):
        self.assertEqual(dict(role_choices('jawabu_portal'))['BUSINESS_ADMIN'], 'Head of Rural')
        self.assertEqual(dict(role_choices('loan_origination'))['BUSINESS_ADMIN'], 'Business Administrator')
        self.assertTrue(all(' — ' not in label for _, label in role_choices()))
        widget = WorkflowScopedSelect(workflow_map=role_workflow_map())
        option = widget.create_option('grants-0-role', 'BUSINESS_ADMIN', 'Business Administrator', True, 0)
        labels = json.loads(option['attrs']['data-role-labels'])
        self.assertEqual(labels['jawabu_portal'], 'Head of Rural')
        self.assertEqual(labels['loan_origination'], 'Business Administrator')


class OriginationRoleIsolationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='synthetic-signer-scope')
        self.application = SimpleNamespace(branch='Training', product='BIOGAS', group_configuration_id=None)
        WorkflowRoleCapability.objects.update_or_create(workflow='loan_origination', role='BM',
            capability_key='origination.signing.staff', defaults={'effect':'allow'})

    def test_other_miniapp_manager_roles_do_not_authorize_origination(self):
        for workflow in ('tat_tracker', 'jawabu_portal'):
            AccessGrant.objects.create(user=self.user, workflow=workflow, role='BM')
        self.assertEqual(user_access(self.user, 'loan_origination')['roles'], [])
        with self.assertRaises(OriginationError):
            authorize_staff_signer(actor=self.user, application=self.application, signer_role='branch_manager')

    def test_one_complete_origination_grant_authorizes_only_its_scope(self):
        AccessGrant.objects.create(user=self.user, workflow='loan_origination', role='BM', branch='Training', product='BIOGAS')
        authorize_staff_signer(actor=self.user, application=self.application, signer_role='branch_manager')
        self.application.branch = 'Other branch'
        with self.assertRaises(OriginationError):
            authorize_staff_signer(actor=self.user, application=self.application, signer_role='branch_manager')

    def test_scopes_from_other_apps_and_roles_cannot_fill_missing_permission(self):
        AccessGrant.objects.create(user=self.user, workflow='loan_origination', role='BM', branch='Other branch', product='BIOGAS')
        AccessGrant.objects.create(user=self.user, workflow='jawabu_portal', role='BM', branch='Training', product='BIOGAS')
        AccessGrant.objects.create(user=self.user, workflow='loan_origination', role='CA', branch='Training', product='BIOGAS')
        with self.assertRaises(OriginationError):
            authorize_staff_signer(actor=self.user, application=self.application, signer_role='branch_manager')
