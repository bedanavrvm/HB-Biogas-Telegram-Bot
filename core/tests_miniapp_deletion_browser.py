"""Real local Admin journey; synthetic records and no remote browser requests."""
import os
from pathlib import Path
import shutil
import subprocess
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from core.models import ComplianceAuditChainState, Product


@skipUnless(shutil.which('node'), 'Node required for local browser verification.')
@override_settings(MINIAPP_TEST_DELETION_ENABLED=True, ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'])
class MiniAppDeletionBrowserTests(StaticLiveServerTestCase):
    def test_selection_impact_and_confirmation(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        root = get_user_model().objects.create_superuser('browser-delete-root', 'browser-delete@example.test', 'password')
        product = Product.objects.create(code='browser-delete-synthetic', name='Synthetic deletion product')
        self.client.force_login(root)
        env = {**os.environ, 'QA_SESSION_ID': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
               'QA_DELETE_PRODUCT_ID': str(product.pk)}
        result = subprocess.run(['node', str(Path(settings.BASE_DIR) / 'scripts/test_miniapp_deletion_browser.js'),
            self.live_server_url + reverse('admin:core_product_changelist') + '?q=Synthetic+deletion+product',
            str(Path(settings.BASE_DIR) / 'test-results/miniapp-deletion-live')],
            cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())
