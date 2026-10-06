"""Explicit Operations policy repair, without grants or external notifications."""
from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase
from core.models import AccessControlChangeRequest, AccessControlPolicyState, WorkflowRoleCapability


class OperationsPolicyRepairTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='training-superuser', is_superuser=True)
        self.rows = WorkflowRoleCapability.objects.filter(workflow='jawabu_portal', role='OPERATIONS_ADMIN')
        self.rows.delete()  # Replace seeded policy only inside this test transaction.
        WorkflowRoleCapability.objects.create(workflow='jawabu_portal', role='OPERATIONS_ADMIN',
            capability_key='portal.case.read')
        WorkflowRoleCapability.objects.create(workflow='jawabu_portal', role='OPERATIONS_ADMIN',
            capability_key='portal.final.write', effect='deny', enabled=False)

    def test_preview_is_read_only(self):
        output = StringIO()
        call_command('repair_portal_operations_policy', stdout=output)
        self.assertIn('portal.imports.commit', output.getvalue())
        self.assertEqual(self.rows.count(), 2)
        self.assertFalse(AccessControlChangeRequest.objects.exists())

    def test_apply_requires_active_superuser(self):
        self.actor.is_superuser = False
        self.actor.save(update_fields=['is_superuser'])
        with self.assertRaises(CommandError):
            call_command('repair_portal_operations_policy', apply=True, actor=self.actor.pk, stdout=StringIO())
        self.assertEqual(self.rows.count(), 2)

    @patch('core.services.access_control.notify_approvers')
    def test_apply_is_audited_replay_safe_and_preserves_denied_approvals(self, notify):
        with self.captureOnCommitCallbacks(execute=True):
            call_command('repair_portal_operations_policy', apply=True, actor=self.actor.pk, stdout=StringIO())
        allowed = set(WorkflowRoleCapability.objects.filter(workflow='jawabu_portal',
            role='OPERATIONS_ADMIN', effect='allow').values_list('capability_key', flat=True))
        self.assertTrue({'portal.imports.view', 'portal.imports.commit', 'portal.invoice.write'}.issubset(allowed))
        self.assertNotIn('portal.final.write', allowed)
        self.assertEqual(AccessControlChangeRequest.objects.filter(status='applied').count(), 1)
        version = AccessControlPolicyState.objects.get(singleton=1).version
        call_command('repair_portal_operations_policy', apply=True, actor=self.actor.pk, stdout=StringIO())
        self.assertEqual(AccessControlPolicyState.objects.get(singleton=1).version, version)
        self.assertEqual(AccessControlChangeRequest.objects.count(), 1)
