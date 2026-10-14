from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AccessGrant, GroupSheetConfiguration, WorkflowRoleCapability
from core.services.miniapp_launcher import available_apps


@override_settings(APP_BASE_URL='https://example.invalid')
class MiniAppLauncherTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('synthetic-app-launcher')
        self.group = GroupSheetConfiguration.objects.create(group_id='synthetic-tat', display_name='Training TAT', workflow={'type':'tat_tracker'})
        self.other = GroupSheetConfiguration.objects.create(group_id='synthetic-other-tat', workflow={'type':'tat_tracker'})
        GroupSheetConfiguration.objects.create(group_id='synthetic-origination', workflow={'type':'loan_origination'})

    def test_scoped_it_only_sees_its_own_workflow_and_group(self):
        grant = AccessGrant.objects.create(user=self.user, workflow='tat_tracker', role='IT', group_configuration=self.group)
        apps = available_apps(self.user)
        self.assertEqual([app['key'] for app in apps], ['tat_tracker'])
        self.assertEqual(len(apps[0]['destinations']), 1)
        self.assertEqual(apps[0]['destinations'][0]['label'], 'Training TAT')
        grant.active = False; grant.save(update_fields=['active'])
        self.assertEqual(available_apps(self.user), [])

    def test_role_needs_its_own_capability(self):
        AccessGrant.objects.create(user=self.user, workflow='loan_origination', role='BM')
        self.assertFalse(any(row['key']=='pipeline_portal' for row in available_apps(self.user)))
        WorkflowRoleCapability.objects.update_or_create(workflow='loan_origination', role='BM', capability_key='origination.view', defaults={'effect':'allow'})
        self.assertEqual([row['key'] for row in available_apps(self.user)], ['loan_origination'])

    def test_endpoint_requires_fresh_telegram_identity_not_cookie(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse('miniapp_available')).status_code, 403)
        with patch('core.api.miniapp_launcher_views.authenticate', return_value=self.user):
            response = self.client.post(reverse('miniapp_available'), HTTP_X_TELEGRAM_INIT_DATA='synthetic-only')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok':True, 'apps':[]})
        self.assertEqual(response['Cache-Control'], 'no-store, private')

    def test_retired_order_approval_is_not_a_destination(self):
        self.user.is_superuser = True; self.user.save(update_fields=['is_superuser'])
        self.assertNotIn('order_approval', [row['key'] for row in available_apps(self.user)])
        with override_settings(ORDER_APPROVAL_WEBAPP_ENABLED=False):
            response = self.client.get('/order-approval/')
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, '/apps/', status_code=410)

    @override_settings(TELEGRAM_BOT_USERNAME='example', ORIGINATION_MINI_APP_SHORT_NAME='origination')
    def test_named_apps_with_their_own_group_selector_are_not_duplicated(self):
        self.user.is_superuser = True; self.user.save(update_fields=['is_superuser'])
        GroupSheetConfiguration.objects.create(group_id='synthetic-origination-two', workflow={'type':'loan_origination'})
        app = next(row for row in available_apps(self.user) if row['key']=='loan_origination')
        self.assertEqual(len(app['destinations']), 1)
