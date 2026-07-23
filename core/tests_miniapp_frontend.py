from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(SECURE_SSL_REDIRECT=False)
class MiniAppFrontendSmokeTests(TestCase):
    """Static smoke checks for the no-build Mini App frontend contract."""

    def assert_script_order(self, response, utility_marker, app_marker):
        html = response.content.decode('utf-8')
        self.assertIn(utility_marker, html)
        self.assertIn(app_marker, html)
        self.assertLess(html.index(utility_marker), html.index(app_marker))

    def test_active_mini_app_shells_load_shared_utils_before_app_scripts(self):
        shells = [
            (reverse('portal_home'), 'miniapp/utils.js', 'miniapp/portal.js'),
            (reverse('complaint_cases_app') + '?group_id=-100complaints', 'miniapp/utils.js', 'miniapp/complaint_cases.js'),
            (reverse('tat_tracker_app') + '?group_id=-100tat&token=test-token', 'miniapp/utils.js', 'miniapp/tat_tracker.js'),
            (reverse('spin_form') + '?group_id=-100spin&token=test-token', 'miniapp/utils.js', 'miniapp/spin_form.js'),
        ]

        for url, utility_marker, app_marker in shells:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assert_script_order(response, utility_marker, app_marker)

    def test_portal_loads_helper_module_between_utils_and_app(self):
        response = self.client.get(reverse('portal_home'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        self.assertLess(html.index('miniapp/utils.js'), html.index('miniapp/portal_helpers.js'))
        self.assertLess(html.index('miniapp/portal_helpers.js'), html.index('miniapp/portal.js'))
        self.assertLess(html.index('miniapp/portal_helpers.js'), html.index('miniapp/portal_api.js'))
        self.assertLess(html.index('miniapp/portal_api.js'), html.index('miniapp/portal.js'))
        self.assertLess(html.index('miniapp/portal_api.js'), html.index('miniapp/portal_queues.js'))
        self.assertLess(html.index('miniapp/portal_queues.js'), html.index('miniapp/portal.js'))

    def test_shared_utils_expose_frontend_primitives(self):
        source = Path('core/static/miniapp/utils.js').read_text(encoding='utf-8')

        for expected in (
            'window.MiniAppUtils',
            'initTelegram',
            'escapeHtml',
            'initDataHeader',
            'fetchJson',
            'fetchHtml',
            'setButtonLoading',
            'showToast',
        ):
            self.assertIn(expected, source)

    def test_portal_helpers_expose_pure_ui_primitives(self):
        source = Path('core/static/miniapp/portal_helpers.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppHelpers',
            'fmtDate',
            'stageBadge',
            'creditBadge',
            'finalDecisionBadge',
            'jblBadge',
            'summaryGrid',
            'renderWarnings',
            'validateInvoiceFile',
        ):
            self.assertIn(expected, source)

    def test_portal_api_exposes_request_primitives(self):
        source = Path('core/static/miniapp/portal_api.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppApi',
            'apiBase',
            'initDataHeader',
            'apiFetch',
            'fetchHtml',
        ):
            self.assertIn(expected, source)

    def test_portal_queues_expose_queue_primitives(self):
        source = Path('core/static/miniapp/portal_queues.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppQueues',
            'QUEUE_CONFIG',
            'queueKeyForList',
            'queueUrl',
            'fragmentPath',
            'renderFragment',
        ):
            self.assertIn(expected, source)

    def test_queue_apps_keep_fragment_fallback_paths(self):
        expectations = {
            'core/static/miniapp/complaint_cases.js': (
                'await renderCasesFragment()',
                "api('cases/'",
            ),
            'core/static/miniapp/tat_tracker.js': (
                "renderTatHomeFragment('action_required').then",
                "renderList('queueList'",
                'await renderTatSearchFragment(query)',
            ),
            'core/static/miniapp/portal.js': (
                'const rendered = await renderQueueFragment(qKey, page)',
                'renderFarmerList(listEl, farmers, cfg, qKey)',
                'renderBatchesList(listEl, batches, cfg)',
                'function setButtonLoading(button, loading, label)',
                'utils.setButtonLoading',
                'window.PortalMiniAppHelpers',
                'window.PortalMiniAppApi',
                'portalApi.fetchHtml',
                'window.PortalMiniAppQueues',
                'portalQueues.renderFragment',
            ),
        }

        for path, markers in expectations.items():
            source = Path(path).read_text(encoding='utf-8')
            with self.subTest(path=path):
                for marker in markers:
                    self.assertIn(marker, source)
