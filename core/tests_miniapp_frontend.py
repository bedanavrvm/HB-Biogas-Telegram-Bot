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
        self.assertLess(html.index('miniapp/portal_imports.js'), html.index('miniapp/portal.js'))
        self.assertIn('miniapp/portal_queues.js?v=6', html)
        self.assertIn('miniapp/portal_farmer_sheet.js?v=29', html)
        self.assertIn('miniapp/utils.js?v=4', html)
        self.assertIn('miniapp/portal.css?v=57', html)
        self.assertIn('miniapp/portal_filters.js?v=7', html)
        self.assertIn('miniapp/portal_imports.js?v=4', html)
        self.assertNotIn('portal-import-group', html)
        self.assertIn('miniapp/portal_requisitions.js?v=33', html)
        self.assertIn('miniapp/portal.js?v=54', html)

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

    def test_portal_jbl_visit_keeps_a_server_backed_field_draft_through_sheet_closure(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        utilities = Path('core/static/miniapp/utils.js').read_text(encoding='utf-8')

        self.assertIn('/jbl-queue/${encodeURIComponent(farmer.id)}/draft/', source)
        self.assertIn('restoreJblVisitServerDraft', source)
        self.assertIn('window.addEventListener(\'pagehide\'', source)
        self.assertIn('await clearJblVisitDraft(farmer);', source)
        self.assertIn('closeSheet({ saveDraft: false });', source)
        self.assertIn('Closing a sheet, opening case history, or Telegram temporarily replacing', source)
        self.assertIn("const baseUrl = settings.baseUrl ||", utilities)
        self.assertIn("result['X-Request-ID'] = settings.requestId();", utilities)

    def test_miniapp_navigation_maps_case_detail_route_to_case_history(self):
        source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')
        response = self.client.get(reverse('portal_home'))

        self.assertIn('/\\/portal\\/cases\\/[^/]+\\//', source)
        self.assertIn("return 'case_history'", source)
        self.assertContains(response, 'miniapp/miniapp-nav.js?v=13')

    def test_telegram_back_never_uses_host_history_for_a_cold_portal_screen(self):
        source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')

        self.assertIn('navigateBackWithinPortal', source)
        self.assertIn('portalBackFallbackUrl', source)
        self.assertIn('portalMiniAppHistory', source)
        self.assertIn("? 'reports'", source)
        self.assertIn("backHandler = navigateBackWithinPortal", source)
        self.assertNotIn('backHandler = () => window.history.back()', source)

    def test_portal_navigation_swaps_only_the_active_screen_root(self):
        portal_template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        navigation = Path('core/templates/portal/partials/navigation.html').read_text(encoding='utf-8')
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        navigation_source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')

        self.assertIn('portal_fragment_only', portal_template)
        self.assertIn('id="portal-shell"', portal_template)
        self.assertIn('hx-target="#portal-screen"', navigation)
        self.assertIn('hx-swap="outerHTML transition:true"', navigation)
        self.assertIn("target: '#portal-screen'", portal_source)
        self.assertIn("swap: 'outerHTML transition:true'", portal_source)
        self.assertIn("target: '#portal-screen'", navigation_source)
        self.assertIn('portalReports.unmount?.()', portal_source)

    def test_portal_reports_use_route_backed_drill_down_screens(self):
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        reports_source = Path('core/static/miniapp/portal_reports.js').read_text(encoding='utf-8')
        portal_template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')

        self.assertIn('data-report-view', portal_template)
        self.assertIn('data-report-id', portal_template)
        self.assertIn('routeUrl(view', reports_source)
        self.assertIn("'/portal/s/reports/'", reports_source)
        self.assertIn("view === 'detail'", reports_source)
        self.assertIn("view === 'edit'", reports_source)
        self.assertIn("view === 'run'", reports_source)
        self.assertIn('navigateUrl(url, options)', portal_source)

    def test_portal_invoice_handlers_are_delegated_for_screen_fragment_swaps(self):
        source = Path('core/static/miniapp/portal_invoices.js').read_text(encoding='utf-8')

        self.assertIn('invoicePoolUploadBound', source)
        self.assertIn("event.target.closest('#invoice-pool-upload-form')", source)
        self.assertIn('invoiceBulkActionsBound', source)

    def test_portal_sheets_restore_the_telegram_viewport_after_file_picker_return(self):
        navigation_source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')
        portal_css = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')

        self.assertIn('restoreTelegramViewport', navigation_source)
        self.assertIn('visibilitychange', navigation_source)
        self.assertIn('input[type="file"]', navigation_source)
        self.assertIn('viewportChanged', navigation_source)
        self.assertIn('viewportStableHeight', navigation_source)
        self.assertIn('--miniapp-viewport-height', navigation_source)
        self.assertIn('tg?.expand?.()', navigation_source)
        self.assertIn('inset: 0;', portal_css)
        self.assertIn('height: var(--miniapp-viewport-height, 100dvh);', portal_css)
        self.assertIn('.sheet-panel {', portal_css)
        self.assertIn('max-height: var(--miniapp-viewport-height, 100dvh);', portal_css)
        self.assertIn('--miniapp-viewport-height', portal_css)

    def test_requisition_generation_waits_for_the_current_drive_workbook(self):
        requisitions = Path('core/static/miniapp/portal_requisitions.js').read_text(encoding='utf-8')
        portal = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        batch_card = Path('core/templates/portal/partials/batch_card.html').read_text(encoding='utf-8')

        self.assertIn('scheduleRequisitionDriveSync(result.batch, { openWhenReady: true })', requisitions)
        self.assertIn("if (openWhenReady && updated.drive_url) deps.openPortalLink(updated.drive_url);", requisitions)
        self.assertNotIn('result.drive_url || result.download_url', requisitions)
        self.assertNotIn('activeBatch.drive_url || activeBatch.download_url', requisitions)
        self.assertIn('Open in Drive', requisitions)
        self.assertIn('data-url="${escapeHtml(b.drive_url || \'\')}"', portal)
        self.assertNotIn('b.drive_url || b.download_url', portal)
        self.assertIn('data-url="{{ batch.drive_url }}"', batch_card)
        self.assertNotIn('batch.download_url', batch_card)

    def test_jbl_gps_explanation_is_only_revealed_after_capture_failure(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')

        self.assertIn('jbl-location-unavailable-wrap" hidden', source)
        self.assertIn('setGpsUnavailableReasonVisible(true)', source)
        self.assertIn('setGpsUnavailableReasonVisible(false)', source)

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

    def test_portal_queue_empty_states_use_the_compact_completion_treatment(self):
        queue_source = Path('core/static/miniapp/portal_queues.js').read_text(encoding='utf-8')
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        filter_source = Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8')
        list_template = Path('core/templates/portal/partials/farmer_list.html').read_text(encoding='utf-8')
        stylesheet = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')

        self.assertIn('Credit queue is clear', queue_source)
        self.assertNotIn('No BRO analysis cases', queue_source)
        for source in (portal_source, filter_source, list_template):
            self.assertIn('queue-empty-state', source)
            self.assertIn('<svg viewBox', source)
            self.assertNotIn('es-icon">OK', source)
        self.assertIn('.farmer-list > .queue-empty-state', stylesheet)
        self.assertIn('min-height: 148px', stylesheet)

    def test_final_review_queue_keeps_its_selected_lens_in_every_request_path(self):
        queue_source = Path('core/static/miniapp/portal_queues.js').read_text(encoding='utf-8')
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        filter_source = Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8')
        portal_template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        list_template = Path('core/templates/portal/partials/farmer_list.html').read_text(encoding='utf-8')

        self.assertIn("queueKey === 'final'", queue_source)
        self.assertNotIn("state.activePage === 'final'", queue_source)
        self.assertIn("params.set('stage', state.filters.reviewStage)", queue_source)
        self.assertIn("qKey === 'final' && state.filters.reviewStage", portal_source)
        self.assertIn("selectFinalReviewStage", portal_source)
        self.assertIn("closest('[data-final-review-stage]')", portal_source)
        self.assertIn('data-final-review-stage="decision"', portal_template)
        self.assertIn('data-final-review-stage="payment"', portal_template)
        self.assertNotIn('id="final-review-stage"', portal_template)
        self.assertNotIn("el('final-review-stage')", filter_source)
        self.assertIn("&stage={{ review_stage|urlencode }}", list_template)

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
            'buildRequisitionBatchNotice',
            'initMap',
            'btn-gps',
        ):
            self.assertIn(expected, source)

    def test_credit_form_excludes_unrequested_approval_controls(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        form = source[source.index('function buildCreditForm'):source.index('function wireCreditImabFields')]
        submit = source[source.index('async function submitCreditDecision'):source.index('async function submitFinalDecision')]

        self.assertNotIn('Status guide:', form)
        self.assertNotIn("buildApprovalReasonFields('credit')", form)
        self.assertNotIn("renderApprovalConditions(farmer, 'credit')", form)
        self.assertIn("decision !== 'Pending'", form)
        self.assertNotIn('credit-reason-code', submit)
        self.assertNotIn('credit-conditions', submit)
        self.assertNotIn('reason_code:', submit)
        self.assertNotIn('conditions }', submit)
        self.assertNotIn('Approved with Conditions', source)

    def test_final_review_form_uses_client_media_without_reason_or_condition_controls(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        form = source[source.index('function buildFinalReviewForm'):source.index('async function loadClientMedia')]
        submit = source[source.index('async function submitFinalDecision'):source.index('function buildRequisitionBatchNotice')]

        self.assertNotIn('Decision reason', form)
        self.assertNotIn('approval-condition', form)
        self.assertIn("decision !== 'Under Review'", form)
        self.assertIn('btn-view-client-media', form)
        self.assertIn('final-client-media', form)
        self.assertIn('loadClientMedia', source)
        self.assertIn('renderClientMediaLinks', source)
        self.assertIn('openClientMediaPreview', source)
        self.assertIn('openClientMediaExternally', source)
        self.assertIn('fetch(item.preview_url', source)
        self.assertIn('Open externally', source)
        self.assertIn('deps.openPortalLink(latest.open_url)', source)
        self.assertIn('sandbox=""', source)
        self.assertNotIn('docs.google.com/gview', source)
        self.assertNotIn('item.viewer_url', source)
        self.assertNotIn('item.open_url || item.view_url', source)
        self.assertIn('JBL visit photo', source)
        self.assertIn('Signed LAF document', source)
        self.assertIn('form-grid final-review-grid', form)
        self.assertIn('form-row form-row-wide', form)
        stylesheet = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')
        self.assertIn('phone-action-field', form)
        self.assertIn('<span>Call</span>', form)
        self.assertIn("phoneDigits.startsWith('0')", form)
        self.assertIn('.workflow-standard.portal-app .phone-call-button span', stylesheet)
        self.assertIn('-webkit-text-fill-color: #fff', stylesheet)
        self.assertIn('--portal-z-media: 260;', stylesheet)
        self.assertIn('#media-viewer-overlay { z-index: var(--portal-z-media); }', stylesheet)
        self.assertNotIn('final-reason-code', submit)
        self.assertNotIn('final-conditions', submit)
        self.assertNotIn('Approved with Conditions', source)

    def test_requisition_case_sheet_defers_assignment_to_selected_batch_panel(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        form = source[source.index('function buildRequisitionBatchNotice'):source.index('function closeSheet')]

        self.assertIn('Select this case using its checkbox', form)
        self.assertIn('controlled system export', form)
        self.assertNotIn('req-order', source)
        self.assertNotIn('req-date', source)
        self.assertNotIn('req-product', source)
        self.assertNotIn('submitOrder', source)
        self.assertNotIn("requisition: 'portal.requisition.write'", source)

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

    def test_head_of_rural_tabs_only_expose_order_and_payment_reviews(self):
        response = self.client.get(reverse('portal_screen', kwargs={'screen': 'final'}))
        self.assertContains(response, 'data-final-review-stage="decision"')
        self.assertContains(response, 'data-final-review-stage="payment"')
        self.assertContains(response, '>Orders<')
        self.assertContains(response, '>Payments<')
        self.assertNotContains(response, 'id="final-review-stage"')
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
        self.assertIn('--portal-z-overlay-nested: 240;', stylesheet)
        self.assertIn('#requisition-preview-overlay { z-index: var(--portal-z-overlay-nested); }', stylesheet)

    def test_requisition_preview_refreshes_selected_case_revisions_before_generation(self):
        source = Path('core/static/miniapp/portal_requisitions.js').read_text(encoding='utf-8')

        self.assertIn('payloadAtPreviewRevision', source)
        self.assertIn('workflow_revisions', source)
        self.assertIn('state().pendingRequisitionPayload = payloadAtPreviewRevision(payload, data)', source)
