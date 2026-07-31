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
        self.assertLess(html.index('miniapp/portal_queues.js'), html.index('miniapp/portal_farmer_sheet.js'))
        self.assertLess(html.index('miniapp/portal_farmer_sheet.js'), html.index('miniapp/portal_filters.js'))
        self.assertLess(html.index('miniapp/portal_filters.js'), html.index('miniapp/portal_requisitions.js'))
        self.assertLess(html.index('miniapp/portal_requisitions.js'), html.index('miniapp/portal.js'))
        self.assertLess(html.index('miniapp/portal_requisitions.js'), html.index('miniapp/portal_payments.js'))
        self.assertLess(html.index('miniapp/portal_payments.js'), html.index('miniapp/portal.js'))

        spin_response = self.client.get(reverse('spin_form') + '?group_id=-100spin&token=test-token')
        spin_html = spin_response.content.decode('utf-8')
        self.assertLess(spin_html.index('miniapp/utils.js'), spin_html.index('miniapp/spin_api.js'))
        self.assertLess(spin_html.index('miniapp/spin_api.js'), spin_html.index('miniapp/spin_form.js'))

        tat_response = self.client.get(reverse('tat_tracker_app') + '?group_id=-100tat&token=test-token')
        tat_html = tat_response.content.decode('utf-8')
        self.assertLess(tat_html.index('miniapp/utils.js'), tat_html.index('miniapp/tat_api.js'))
        self.assertLess(tat_html.index('miniapp/tat_api.js'), tat_html.index('miniapp/tat_tracker.js'))

        complaint_response = self.client.get(reverse('complaint_cases_app') + '?group_id=-100complaints')
        complaint_html = complaint_response.content.decode('utf-8')
        self.assertLess(complaint_html.index('miniapp/utils.js'), complaint_html.index('miniapp/complaint_cases_api.js'))
        self.assertLess(complaint_html.index('miniapp/complaint_cases_api.js'), complaint_html.index('miniapp/complaint_cases.js'))

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

    def test_miniapp_navigation_maps_case_detail_route_to_case_history(self):
        source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')
        response = self.client.get(reverse('portal_home'))

        self.assertIn('/\\/portal\\/cases\\/[^/]+\\//', source)
        self.assertIn("return 'case_history'", source)
        self.assertContains(response, 'miniapp/miniapp-nav.js?v=8')

    def test_portal_sheets_use_a_stable_overlay_viewport_after_file_picker_return(self):
        portal_css = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')

        self.assertIn('inset: 0 auto auto 0', portal_css)
        self.assertIn('height: 100vh', portal_css)
        self.assertIn('.sheet-panel {', portal_css)
        self.assertIn('height: 100%;', portal_css)
        self.assertNotIn('--miniapp-viewport-height', portal_css)

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
            'batchClientRows',
            'invoiceResultRows',
            'invoiceResultsSummary',
            'validateInvoiceFile',
        ):
            self.assertIn(expected, source)
        # Branch is an operational routing/access field, not part of the
        # customer location line shown beneath queue-card names.
        self.assertNotIn('farmer && farmer.branch,', source)

    def test_portal_api_exposes_request_primitives(self):
        source = Path('core/static/miniapp/portal_api.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppApi',
            'apiBase',
            'initDataHeader',
            'apiFetch',
            'fetchHtml',
            'postForm',
            'postJson',
        ):
            self.assertIn(expected, source)

    def test_spin_api_exposes_request_primitives(self):
        source = Path('core/static/miniapp/spin_api.js').read_text(encoding='utf-8')

        for expected in (
            'window.SpinMiniAppApi',
            'getJson',
            'postJson',
            'postForm',
        ):
            self.assertIn(expected, source)

    def test_tat_api_exposes_request_primitives(self):
        source = Path('core/static/miniapp/tat_api.js').read_text(encoding='utf-8')

        for expected in (
            'window.TatMiniAppApi',
            'postJson',
            'postFragment',
        ):
            self.assertIn(expected, source)

    def test_complaint_cases_api_exposes_request_primitives(self):
        source = Path('core/static/miniapp/complaint_cases_api.js').read_text(encoding='utf-8')

        for expected in (
            'window.ComplaintCasesMiniAppApi',
            'postJson',
            'postForm',
            'postFragment',
        ):
            self.assertIn(expected, source)

    def test_order_approval_api_exposes_request_primitives(self):
        source = Path('core/static/miniapp/order_approval_api.js').read_text(encoding='utf-8')
        template = Path('core/templates/order_approval/form.html').read_text(encoding='utf-8')

        self.assertIn('window.OrderApprovalMiniAppApi', source)
        self.assertIn('postForm', source)
        self.assertIn('miniapp/order_approval_api.js', template)
        self.assertIn('window.OrderApprovalMiniAppApi', template)
        self.assertIn('orderApprovalApi.postForm', template)

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

    def test_portal_filters_expose_filter_primitives(self):
        source = Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppFilters',
            'init',
            'updateFilterOptions',
            'applyFilters',
            'renderFilteredFarmerList',
            'filter-county',
            'filter-branch',
            'btn-clear-filters',
        ):
            self.assertIn(expected, source)

    def test_portal_farmer_sheet_exposes_detail_primitives(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppFarmerSheet',
            'openFarmerSheet',
            'renderCase360',
            'case360-hero',
            'case360-flow',
            'case360-sections',
            'case360-link',
            'Open map',
            'buildJblForm',
            'submitJblVisit',
            '/complete-visit/',
            'selectedJblFilesAreValid',
            'slowUploadNotice',
            'saveJblVisitDraft',
            'jbl-laf-media',
            'jbl-visit-photo-media',
            'laf_files',
            'jbl_visit_photo_files',
            'buildCreditForm',
            'wireCreditImabFields',
            'submitCreditDecision',
            'buildFinalReviewForm',
            'submitFinalDecision',
            'buildRequisitionForm',
            'submitOrder',
            'initMap',
            'btn-gps',
        ):
            self.assertIn(expected, source)

    def test_portal_requisitions_exposes_batch_primitives(self):
        source = Path('core/static/miniapp/portal_requisitions.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppRequisitions',
            'init',
            'openBatchDetail',
            'openInvoiceOverlay',
            'updateBatchPanel',
            'requestRequisitionPreview',
            'generateRequisitionFromPreview',
            'bindInvoiceUpload',
            'portalApi.postJson',
            'portalApi.postForm',
            'portalHelpers.invoiceResultRows',
            "source.includes('jawabu')",
        ):
            self.assertIn(expected, source)

        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        self.assertIn('id="requisition-preview-confirm" type="button" hidden', template)
        self.assertIn('data-main-action-proxy="true"', template)
        self.assertIn('mainActionProxy', Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8'))

    def test_history_actions_use_shell_link_and_payment_case_review_cards(self):
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        requisitions_source = Path('core/static/miniapp/portal_requisitions.js').read_text(encoding='utf-8')

        self.assertIn("openPortalLink(excelButton.dataset.url || '')", portal_source)
        self.assertNotIn("deps.openPortalLink(excelButton.dataset.url || '')", portal_source)
        self.assertIn('payment-review-case-card', requisitions_source)
        self.assertIn('payment-open-case', requisitions_source)
        self.assertIn('payment-case-comment', requisitions_source)
        self.assertIn('data-payment-case-card', requisitions_source)
        self.assertIn('bindPaymentReviewAccordion', requisitions_source)

    def test_head_of_rural_selector_only_contains_actual_hor_queues(self):
        response = self.client.get(reverse('portal_home'))
        self.assertContains(response, 'Final decision (before requisition)')
        self.assertContains(response, 'Payment batches awaiting HOR review')
        self.assertNotContains(response, 'Ready for requisition / order')

    def test_portal_payments_exposes_selection_primitives(self):
        source = Path('core/static/miniapp/portal_payments.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppPayments',
            'payment-candidate-checkbox',
            '/payments/candidates/',
            '/payments/selection/',
            'farmer_ids',
        ):
            self.assertIn(expected, source)

    def test_order_and_invoice_surfaces_do_not_expose_payment_actions(self):
        requisitions = Path('core/static/miniapp/portal_requisitions.js').read_text(encoding='utf-8')
        invoices = Path('core/static/miniapp/portal_invoices.js').read_text(encoding='utf-8')
        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')

        for forbidden in ('id="batch-payment-readiness"', 'id="batch-payment-preview"', 'id="batch-payment-final"'):
            self.assertNotIn(forbidden, requisitions)
        self.assertNotIn('invoice-payment-preview-action', invoices)
        self.assertNotIn('id="batch-detail-payment-result"', template)

    def test_queue_apps_keep_fragment_fallback_paths(self):
        expectations = {
            'core/static/miniapp/complaint_cases.js': (
                'await renderCasesFragment()',
                "api('cases/'",
                'window.ComplaintCasesMiniAppApi',
                'complaintApi.postJson',
                'complaintApi.postForm',
                'complaintApi.postFragment',
            ),
            'core/static/miniapp/tat_tracker.js': (
                "renderList('queueList'",
                "renderList('recentList'",
                'await renderTatSearchFragment(query)',
                'window.TatMiniAppApi',
                'tatApi.postJson',
                'tatApi.postFragment',
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
                'window.PortalMiniAppFarmerSheet',
                'portalFarmerSheet.init',
                'portalFarmerSheet.openFarmerSheet',
                'window.PortalMiniAppFilters',
                'portalFilters.init',
                'portalFilters.updateFilterOptions',
                'portalFilters.applyFilters',
                'window.PortalMiniAppRequisitions',
                'portalRequisitions.init',
                'portalRequisitions.openBatchDetail',
                'portalRequisitions.updateBatchPanel',
                'portalHelpers.batchClientRows',
            ),
            'core/static/miniapp/spin_form.js': (
                'window.SpinMiniAppApi',
                'spinApi.getJson',
                'spinApi.postJson',
                'spinApi.postForm',
            ),
        }

        for path, markers in expectations.items():
            source = Path(path).read_text(encoding='utf-8')
            with self.subTest(path=path):
                for marker in markers:
                    self.assertIn(marker, source)

    def test_portal_top_nav_is_horizontally_scrollable_on_mobile(self):
        stylesheet = Path('core/static/miniapp/workflow_standard.css').read_text(encoding='utf-8')
        response = self.client.get(reverse('portal_home'))
        html = response.content.decode('utf-8')

        self.assertIn('miniapp/workflow_standard.css?v=16', html)
        self.assertIn('.workflow-standard.portal-app .tab-bar', stylesheet)
        self.assertIn('flex-wrap: nowrap', stylesheet)
        self.assertIn('overflow-x: auto', stylesheet)
        self.assertIn('-webkit-overflow-scrolling: touch', stylesheet)
        self.assertIn('.workflow-standard.portal-app .tab-btn', stylesheet)
        self.assertIn('flex: 0 0 auto', stylesheet)

    def test_requisition_preview_stacks_above_batch_detail(self):
        stylesheet = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')
        response = self.client.get(reverse('portal_home'))

        # The cache-buster changes whenever Portal styles change; assert the
        # stylesheet is present without tying a stacking-regression test to it.
        self.assertContains(response, 'miniapp/portal.css?v=')
        self.assertIn('#requisition-preview-overlay { z-index: 240; }', stylesheet)
