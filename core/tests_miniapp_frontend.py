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
        self.assertIn('miniapp/components.js?v=3', html)
        self.assertIn('miniapp/asset_loader.js?v=1', html)
        self.assertIn('miniapp/portal_queues.js?v=13', html)
        self.assertIn('miniapp/portal_farmer_sheet.js?v=76', html)
        self.assertIn('miniapp/utils.js?v=18', html)
        self.assertIn('miniapp/portal_helpers.js?v=9', html)
        self.assertIn('miniapp/components.css?v=2', html)
        self.assertIn('miniapp/portal.css?v=121', html)
        self.assertIn('miniapp/portal_filters.js?v=16', html)
        self.assertIn('miniapp/portal_imports.js?v=10', html)
        self.assertNotIn('portal-import-group', html)
        self.assertIn('miniapp/portal_requisitions.js?v=40', html)
        self.assertIn('miniapp/portal_api.js?v=9', html)
        self.assertIn('miniapp/portal_invoices.js?v=24', html)
        self.assertIn('miniapp/portal_payments.js?v=18', html)
        self.assertIn('miniapp/portal_curated_reports.js?v=4', html)
        self.assertIn('miniapp/portal.js?v=95', html)
        self.assertNotIn('vendor-chartjs-4.5.1.umd.min.js', html)
        self.assertNotIn('<script src="/static/miniapp/vendor-leaflet-1.9.4.js', html)
        self.assertIn('miniapp/portal_case_history.js?v=1', html)
        self.assertLess(html.index('miniapp/portal_case_history.js'), html.index('miniapp/portal.js'))

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
            'disableVerticalSwipes',
            'setCloseProtection',
            'clearCloseProtection',
            'protectWhile',
            'escapeHtml',
            'initDataHeader',
            'fetchJson',
            'fetchHtml',
            'setButtonLoading',
            'showToast',
        ):
            self.assertIn(expected, source)

        self.assertIn("closeProtectionReasons = new Set()", source)
        self.assertIn("method === 'GET' || method === 'HEAD'", source)
        self.assertIn("url.indexOf('/miniapp-diagnostics/')", source)

    def test_shared_runtime_provides_compact_toasts_and_delayed_top_progress(self):
        runtime = Path('core/static/miniapp/runtime.js').read_text(encoding='utf-8')
        styles = Path('core/static/miniapp/base.css').read_text(encoding='utf-8')

        self.assertIn('miniapp-top-progress', runtime)
        self.assertIn('miniapp-shared-toast', runtime)
        self.assertIn('window.fetch = progressFetch', runtime)
        self.assertIn('}, 120);', runtime)
        self.assertIn("progressPhase === 'completing'", runtime)
        self.assertIn("document.addEventListener('htmx:beforeRequest', beginProgress)", runtime)
        self.assertNotIn('id="shell-progress"', Path('core/templates/base_shell.html').read_text(encoding='utf-8'))
        self.assertIn('.miniapp-top-progress.is-active', styles)
        self.assertIn('.miniapp-shared-toast.is-visible', styles)
        self.assertIn('env(safe-area-inset-top)', styles)

    def test_portal_uses_one_shell_header_for_actor_role_and_freshness(self):
        shell = Path('core/templates/base_shell.html').read_text(encoding='utf-8')
        portal = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')

        self.assertIn('class="shell-actor"', shell)
        self.assertIn('id="portal-actor-role"', shell)
        self.assertIn('id="portal-freshness"', shell)
        self.assertNotIn('portal-context-bar', portal)

    def test_high_risk_miniapps_use_state_aware_close_protection(self):
        origination = Path('core/static/miniapp/loan_origination.js').read_text(encoding='utf-8')
        signing = Path('core/static/miniapp/origination_signing.js').read_text(encoding='utf-8')
        complaints = Path('core/static/miniapp/complaint_cases.js').read_text(encoding='utf-8')

        self.assertIn("'origination-unsaved'", origination)
        self.assertIn("'origination-operation'", origination)
        self.assertIn("'origination-evidence-upload'", origination)
        self.assertIn("'signing-capture'", signing)
        self.assertIn("'complaint-create-draft'", complaints)
        self.assertIn("'complaint-transition-draft'", complaints)

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
        self.assertIn('Object.assign(result, idempotencyHeaders(key));', utilities)
        self.assertIn('state().jblVisitDraftFields', source)
        self.assertNotIn("'jbl-location-override-reason'", source)
        self.assertIn("deps.tg?.onEvent?.('deactivated'", source)

    def test_portal_case360_reuses_shared_server_clock_and_secure_media_viewer(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        runtime = Path('core/static/miniapp/runtime.js').read_text(encoding='utf-8')
        tat = Path('core/static/miniapp/tat_tracker.js').read_text(encoding='utf-8')

        self.assertIn('bindServerCounters', runtime)
        self.assertIn('tickServerCounters', tat)
        self.assertIn("selector: '[data-server-counter]'", source)
        self.assertIn('openClientMediaPreview(item)', source)
        self.assertIn('Open externally', source)
        self.assertNotIn('Show business-hours time', source)
        self.assertIn("'Pending Visit'", source)

    def test_origination_draft_saves_are_serialized_and_conflicts_are_recoverable(self):
        source = Path('core/static/miniapp/loan_origination.js').read_text(encoding='utf-8')
        template = Path('core/templates/loan_origination/app.html').read_text(encoding='utf-8')

        self.assertIn('if (saveInFlight)', source)
        self.assertIn('const waitingForRequestId = saveInFlightRequestId;', source)
        self.assertIn('lastFailedSaveRequestId === waitingForRequestId', source)
        self.assertIn('lastFailedSaveRequestId = key;', source)
        self.assertIn("pendingSaveRequestId = requestKey('save');", source)
        self.assertIn('visibleDraftNumericErrors()', source)
        self.assertIn("showErrors({});", source)
        self.assertIn("if (saveInFlight) pendingSaveRequestId = requestKey('save');", source)
        self.assertIn('reconcileSavedDraftConflict(phoneDraft, showError)', source)
        self.assertIn('attemptedSnapshot: attemptedDraft', source)
        self.assertIn('draftMatchesApplication(local, application)', source)
        self.assertIn('renderFreshEditor(current, step)', source)
        self.assertIn('id="recovery-retry-refresh"', source)
        self.assertIn("window.addEventListener('pageshow'", source)
        self.assertIn('void resumeDraftSynchronization();', source)
        self.assertIn("window.addEventListener('online'", source)
        self.assertNotIn('keepalive: true', source)
        self.assertNotIn('fetch(`/api/origination/api/applications/${current.id}/`', source)
        self.assertIn('data-ui-version="20260909-1"', template)
        self.assertIn('loan_origination.js\' %}?v=20260909-1', template)

    def test_origination_repeatable_security_normalizes_numeric_entry_and_marks_required_columns(self):
        source = Path('core/static/miniapp/loan_origination.js').read_text(encoding='utf-8')

        self.assertIn('function normalizeNumericText(value)', source)
        self.assertIn('value = normalizeNumericText(value);', source)
        self.assertIn('const normalized = normalizeNumericText(input.value);', source)
        self.assertIn("column.required ? '<span class=\"required-mark\"", source)

    def test_portal_import_review_uses_only_the_retained_source_table_columns(self):
        source = Path('core/static/miniapp/portal_imports.js').read_text(encoding='utf-8')

        self.assertIn('const sourceTable = batch.source_table || {};', source)
        self.assertIn('const columns = Array.isArray(sourceTable.headers)', source)
        self.assertIn('const rows = Array.isArray(sourceTable.rows)', source)
        self.assertNotIn('<th class="table-number">No.</th>', source)
        self.assertIn('Archive from Imports', source)
        self.assertIn('archiveFromWorkingList', source)
        self.assertIn("/imports/${encodeURIComponent(batch.id)}/archive/", source)

    def test_miniapp_navigation_maps_case_detail_route_to_case_history(self):
        source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')
        response = self.client.get(reverse('portal_home'))

        self.assertIn('/\\/portal\\/cases\\/[^/]+\\//', source)
        self.assertIn("return 'case_history'", source)
        self.assertIn("document.getElementById('portal-screen')?.dataset.screen", source)
        self.assertIn("document.addEventListener('DOMContentLoaded', activateScreen)", source)
        self.assertContains(response, 'miniapp/miniapp-nav.js?v=25')

    def test_telegram_back_never_uses_host_history_for_a_cold_portal_screen(self):
        source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')

        self.assertIn('navigateBackWithinPortal', source)
        self.assertIn('portalBackFallbackUrl', source)
        self.assertIn('window.location.assign(fallbackUrl)', source)
        self.assertIn("? 'reports'", source)
        self.assertIn("? 'invoices'", source)
        self.assertIn("backHandler = navigateBackWithinPortal", source)
        self.assertNotIn('backHandler = () => window.history.back()', source)

    def test_portal_routes_use_full_pages_and_keep_fragment_refreshes(self):
        shell_template = Path('core/templates/base_shell.html').read_text(encoding='utf-8')
        portal_template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        navigation = Path('core/templates/portal/partials/navigation.html').read_text(encoding='utf-8')
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        navigation_source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')

        self.assertIn('portal_fragment_only', portal_template)
        self.assertIn('id="portal-shell"', portal_template)
        self.assertIn('<main id="content">', shell_template)
        self.assertNotIn('class="portal-pipeline-navigation"\n       hx-get=', portal_template)
        self.assertNotIn('id="bottom-tabs"', shell_template)
        self.assertIn('surface=sidebar', shell_template)
        self.assertIn('href="{{ item.url }}"', navigation)
        self.assertNotIn('hx-get=', navigation)
        self.assertNotIn('hx-target="#portal-screen"', portal_template)
        self.assertIn('window.location.assign(destination.href)', portal_source)
        self.assertIn('window.location.assign(fallbackUrl)', navigation_source)
        self.assertNotIn("target: '#portal-screen'", navigation_source)
        self.assertIn('portalReports.unmount?.()', portal_source)
        self.assertIn("state.activePage === 'reports' && nextPage !== 'reports'", portal_source)
        self.assertIn('window.htmx.config.timeout = 20000', portal_source)
        self.assertIn("root?.dataset.reportStep || ''", portal_source)
        self.assertIn("document.body.addEventListener('htmx:timeout'", navigation_source)
        self.assertIn("document.body.addEventListener('htmx:afterSwap'", navigation_source)
        self.assertNotIn("document.body.addEventListener('htmx:historyRestore'", navigation_source)
        self.assertIn('runScreenLoader(page)', portal_source)
        self.assertIn('renderScreenLoadFailure', portal_source)

    def test_portal_navigation_and_camera_have_one_surface_each(self):
        shell = Path('core/templates/base_shell.html').read_text(encoding='utf-8')
        portal = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        camera = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        dialogs = Path('core/static/miniapp/portal_dialogs.js').read_text(encoding='utf-8')

        self.assertIn('surface=sidebar', shell)
        self.assertNotIn('id="bottom-tabs"', shell)
        self.assertNotIn('portal-pipeline-navigation', portal)
        self.assertEqual(portal.count('id="jbl-camera-overlay"'), 1)
        self.assertIn('id="jbl-camera-done"', portal)
        self.assertNotIn('jblLiveCameraMarkup()', camera)
        self.assertIn('replaceJblMediaFile', camera)
        self.assertIn('portal-jbl-media-selected', camera)
        self.assertIn("'jbl-camera-overlay': '#jbl-camera-close, #jbl-camera-done'", dialogs)

    def test_dashboard_links_and_sections_are_route_backed_and_terminal(self):
        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')

        self.assertIn('id="dashboard-attention"', template)
        self.assertIn('id="dashboard-activity"', template)
        self.assertIn('id="dashboard-recent"', template)
        self.assertIn('id="dashboard-pipeline-distribution"', template)
        self.assertIn('href="{% url \'portal_screen\' screen=\'jbl\' %}"', template)
        self.assertIn('dashboard-route-link', source)
        self.assertIn('portal-screen-retry', source)

    def test_portal_reports_use_route_backed_drill_down_screens(self):
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        reports_source = Path('core/static/miniapp/portal_reports.js').read_text(encoding='utf-8')
        portal_css = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')
        navigation_source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')
        portal_template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')

        self.assertIn('data-report-view', portal_template)
        self.assertIn('data-report-id', portal_template)
        self.assertIn('data-report-step', portal_template)
        self.assertIn('routeUrl(view', reports_source)
        self.assertIn("'/portal/s/reports/'", reports_source)
        self.assertIn('EDITOR_STEPS', reports_source)
        self.assertIn("DRAFT_STORAGE_PREFIX", reports_source)
        self.assertIn('sessionStorage', reports_source)
        self.assertIn("view === 'detail'", reports_source)
        self.assertIn("view === 'edit'", reports_source)
        self.assertIn("view === 'run'", reports_source)
        self.assertIn("data-report-action=\"step\"", reports_source)
        self.assertIn('data-report-catalogue-search', reports_source)
        self.assertIn('data-report-action=\"discard\"', reports_source)
        self.assertIn('No.</th>', reports_source)
        self.assertIn('function showLoadFailure', reports_source)
        self.assertIn('shouldRender = true', reports_source)
        self.assertNotIn('{ render = true', reports_source)
        self.assertIn('data-report-action="archive-card"', reports_source)
        self.assertIn('function isCurrentLoad', reports_source)
        self.assertIn('Preparing the live report...', reports_source)
        self.assertIn("action = 'retry-load'", reports_source)
        self.assertIn('chartFallbackMarkup', reports_source)
        self.assertIn("'[data-report-filter-field], [data-report-filter-operator]'", reports_source)
        self.assertIn('IntersectionObserver', reports_source)
        self.assertIn('interaction: { mode: \'nearest\', intersect: false }', reports_source)
        self.assertIn('themePalette(primary)', reports_source)
        self.assertIn('portal-report-table-wrap', reports_source)
        self.assertIn('@media (max-width: 600px)', portal_css)
        self.assertIn('overflow-x: auto', portal_css)
        self.assertIn('portal-report-wizard-actions', reports_source)
        self.assertIn('portal-report-field-category', reports_source)
        self.assertIn('data-report-field-search-empty', reports_source)
        self.assertIn('function applyFieldSearch', reports_source)
        self.assertIn('data-report-action="remove-field"', reports_source)
        self.assertIn('chartDimensions()', reports_source)
        self.assertIn('chartMetricsForAggregation', reports_source)
        self.assertIn('chartTypesForDimension', reports_source)
        self.assertIn('data-report-chart-type-choice', reports_source)
        self.assertIn('Choose whether this date trend is grouped by day or by month.', reports_source)
        self.assertIn("postJson('/reports/preview/'", reports_source)
        self.assertIn('editorPreviewController?.abort?.()', reports_source)
        self.assertIn('data-report-editor-preview', reports_source)
        self.assertIn('portal-report-chart-card', portal_css)
        self.assertIn('portal-report-chart-preview', portal_css)
        self.assertIn('portal-report-review-summary', reports_source)
        self.assertIn('portal-report-more-menu', reports_source)
        self.assertIn('portal-report-editor-active', reports_source)
        self.assertIn('body.portal-report-editor-active', portal_css)
        self.assertIn('canHandleBack', reports_source)
        self.assertIn('function canReuseEditorDraft', reports_source)
        self.assertIn('canReuseEditorDraft(nextRoute)', reports_source)
        self.assertIn('portal:reports-route-change', navigation_source)
        self.assertIn('reports?.canHandleBack?.()', navigation_source)
        self.assertIn('navigateUrl(url, options)', portal_source)

    def test_portal_invoices_use_route_backed_workspace_screens(self):
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        invoices_source = Path('core/static/miniapp/portal_invoices.js').read_text(encoding='utf-8')
        portal_template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')

        self.assertIn('data-invoice-view', portal_template)
        self.assertIn('data-invoice-id', portal_template)
        self.assertIn('routeUrl(view', invoices_source)
        self.assertIn("'/portal/s/invoices/'", invoices_source)
        self.assertIn("view === 'detail'", invoices_source)
        self.assertIn("workspace', route.view", invoices_source)
        self.assertIn('navigateUrl(url, options)', portal_source)

    def test_portal_invoice_handlers_are_delegated_for_screen_fragment_swaps(self):
        source = Path('core/static/miniapp/portal_invoices.js').read_text(encoding='utf-8')

        self.assertIn('invoicePoolUploadBound', source)
        self.assertIn("event.target.closest('#invoice-pool-upload-form')", source)
        self.assertIn('invoiceBulkActionsBound', source)

    def test_invoice_name_change_is_inline_with_local_letter_and_identity_safeguards(self):
        source = Path('core/static/miniapp/portal_invoices.js').read_text(encoding='utf-8')
        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        stylesheet = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')

        self.assertIn('openInvoiceWorkflowSheet', source)
        self.assertIn('Request corrected invoice', source)
        self.assertIn('FarmUp lead', source)
        self.assertIn('SysUp applicant', source)
        self.assertIn('Invoice holder', source)
        self.assertIn('invoice_revision: invoice.revision', source)
        self.assertIn('application_revision: invoice.application_revision', source)
        self.assertIn('confirmed: values.confirmed ===', source)
        self.assertIn('Correct sent request', source)
        self.assertIn('openLetterPreview', source)
        self.assertIn('Generated letter', source)
        self.assertIn('openReplacementSelector', source)
        self.assertIn("'/generate/'", source)
        self.assertIn('artifact_id: letter.id', source)
        self.assertIn('latest_letter.download_url', source)
        self.assertNotIn('window.prompt', source)
        self.assertNotIn('window.confirm', source)
        self.assertNotIn('Invoice name changes', template)
        self.assertIn('invoice-record-source-meta', source)
        self.assertIn('invoice-parsed-edit-toggle', source)
        self.assertIn('invoice-parsed-edit-form', source)
        self.assertIn('name="correction_reason"', source)
        self.assertIn("kv('National ID', invoice.customer_id)", source)
        self.assertIn('invoice-identity-comparison', source)
        self.assertIn('.invoice-detail-field-wide { grid-column: 1 / -1; }', stylesheet)
        self.assertNotIn('@media (max-width: 480px) { .invoice-detail-grid { grid-template-columns: 1fr; } }', stylesheet)

    def test_portal_sheets_do_not_reexpand_during_external_media_activity_return(self):
        navigation_source = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')
        portal_css = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')

        self.assertNotIn('restoreTelegramViewport', navigation_source)
        self.assertNotIn('visibilitychange', navigation_source)
        self.assertNotIn("tg.onEvent?.('activated'", navigation_source)
        self.assertIn('viewportChanged', navigation_source)
        self.assertIn('viewportStableHeight', navigation_source)
        self.assertIn('event.isStateStable !== false', navigation_source)
        self.assertIn('--miniapp-viewport-height', navigation_source)
        self.assertEqual(navigation_source.count('tg.expand?.();'), 0)
        self.assertIn('MiniAppUtils?.initTelegram?.()', navigation_source)
        self.assertNotIn("input[type=\"file\"]", navigation_source)
        self.assertIn('inset: 0;', portal_css)
        self.assertIn('height: var(--miniapp-viewport-height, 100dvh);', portal_css)
        self.assertIn('.sheet-panel {', portal_css)
        self.assertIn('max-height: var(--miniapp-viewport-height, 100dvh);', portal_css)
        self.assertIn('--miniapp-viewport-height', portal_css)

    def test_portal_nested_media_and_case_history_have_terminal_navigation_states(self):
        navigation = Path('core/static/miniapp/miniapp-nav.js').read_text(encoding='utf-8')
        portal = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')

        self.assertIn('window.getComputedStyle(overlay).zIndex', navigation)
        self.assertIn('caseHistoryLoadVersion', portal)
        self.assertIn('case-history-retry', portal)
        self.assertIn("typeof portalFarmerSheet.renderCase360 !== 'function'", portal)
        self.assertIn('CASE_HISTORY_WATCHDOG_MS = 22000', portal)
        self.assertIn('content.dataset.caseHistoryLoadToken === loadToken', portal)
        self.assertIn('window.PortalCaseHistoryLoader.load(farmerId)', portal)

        case_history = Path('core/static/miniapp/portal_case_history.js').read_text(encoding='utf-8')
        self.assertIn('TIMEOUT_MS = 22000', case_history)
        self.assertIn("document.addEventListener('htmx:afterSwap', loadCurrent)", case_history)
        self.assertIn('case-history-independent-retry', case_history)
        self.assertIn('window.Telegram?.WebApp', case_history)

        farmer_sheet = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        self.assertIn("hasCapability('portal.jbl_media.view') && mediaCount >= 1", farmer_sheet)
        self.assertIn('data-collapsed-label="${collapsedMediaLabel}"', farmer_sheet)
        self.assertIn('function toggleClientMedia(farmerId)', farmer_sheet)
        self.assertIn("button.setAttribute('aria-expanded', 'false')", farmer_sheet)
        self.assertIn('Portal pipeline TAT (wall clock)', farmer_sheet)
        self.assertNotIn('Show business-hours time', farmer_sheet)

    def test_portal_cards_filters_imab_and_workflow_drafts_are_consistent(self):
        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        card = Path('core/templates/portal/partials/farmer_card.html').read_text(encoding='utf-8')
        portal = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        filters = Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8')
        sheet = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        queues = Path('core/static/miniapp/portal_queues.js').read_text(encoding='utf-8')

        self.assertNotIn('id="portal-filter-bar"', template)
        self.assertNotIn('portal-preference-default-branch', template)
        self.assertIn('farmer.location_label', card)
        self.assertIn('JBL visit:', card)
        self.assertIn('queue_key == "jbl" or queue_key == "my_visits"', card)
        self.assertIn('jbl-queue-card-bottom', card)
        self.assertLess(card.index('Unit {{ farmer.unit_number'), card.index('HB visit: {{ farmer.hbg_visit_date_label'))
        self.assertIn('JBL visit: {{ farmer.jbl_visit_date_label', card)
        self.assertIn('function renderVisitQueueCard(f, qKey)', portal)
        self.assertIn('setupQueueTools', filters)
        self.assertIn('bindFilterSheet', filters)
        self.assertIn('class="operational-queue-card-content"', card)
        self.assertIn('farmer.current_pipeline_state|default:"In Progress"', card)
        self.assertIn('function renderOperationalQueueCard(f, qKey)', portal)
        self.assertIn("['county', 'branch', 'status', 'ordering']", queues)
        self.assertIn("params.append(key, value)", queues)
        self.assertIn("farmer.imab_created || 'Pending'", sheet)
        self.assertIn('WORKFLOW_DRAFT_CONFIG', sheet)
        self.assertIn('clearWorkflowDraft', sheet)

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
            'getJson',
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

    def test_portal_list_loaders_resolve_transport_failures_to_recoverable_ui(self):
        api_source = Path('core/static/miniapp/portal_api.js').read_text(encoding='utf-8')
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        invoice_source = Path('core/static/miniapp/portal_invoices.js').read_text(encoding='utf-8')
        payment_source = Path('core/static/miniapp/portal_payments.js').read_text(encoding='utf-8')

        self.assertIn('REQUEST_TIMEOUT_MS = 20000', api_source)
        self.assertIn('fetchWithTimeout', api_source)
        self.assertIn('requestFailureMessage', api_source)
        self.assertIn("data: { ok: false, error: requestFailureMessage(error) }", api_source)
        self.assertIn('queueFailureMarkup', portal_source)
        self.assertIn('renderQueueFailure(listEl, qKey, page, data?.error, requestId)', portal_source)
        self.assertIn('renderQueueFailure(listEl, qKey, page, \'The queue could not be loaded. Please try again.\')', portal_source)
        self.assertIn("qKey === 'jbl' && cfg.fragmentEndpoint && window.htmx", portal_source)
        self.assertIn('queueLoadVersions', portal_source)
        self.assertIn('isCurrentQueueLoad', portal_source)
        self.assertIn('isCurrent: () => loadVersion === null || isCurrentQueueLoad(qKey, loadVersion)', portal_source)
        self.assertIn('try {', invoice_source)
        self.assertIn('finally {\n      state.loading = false;', invoice_source)
        self.assertIn('Could not load invoices', invoice_source)
        self.assertIn('Could not load payment cases', payment_source)

    def test_portal_queue_filters_use_shared_server_backed_controls(self):
        source = Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8')
        template = Path('core/templates/portal/partials/queue_tools.html').read_text(encoding='utf-8')
        portal = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppFilters',
            'init',
            'setupQueueTools',
            'bindSearch',
            'bindFilterSheet',
            'filtersByQueue',
        ):
            self.assertIn(expected, source)
        self.assertIn('data-portal-queue-search', template)
        self.assertIn('data-portal-filter-trigger', template)
        self.assertIn('data-portal-filter-chips', template)
        self.assertEqual(template.count('data-portal-filter-options="county"'), 1)
        self.assertEqual(template.count('data-portal-filter-options="branch"'), 1)
        self.assertNotIn('<select name="county">', template)
        self.assertNotIn('<select name="branch">', template)
        self.assertIn("filters[key] = data.getAll(key)", source)
        self.assertNotIn('restoredPortalUi.search', portal)
        self.assertNotIn('restoredPortalUi.jblSearch', portal)

    def test_portal_queue_tools_and_report_zoom_are_shared_and_mobile_safe(self):
        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        tools = Path('core/templates/portal/partials/queue_tools.html').read_text(encoding='utf-8')
        components = Path('core/static/miniapp/components.js').read_text(encoding='utf-8')
        curated = Path('core/static/miniapp/portal_curated_reports.js').read_text(encoding='utf-8')
        asset_loader = Path('core/static/miniapp/asset_loader.js').read_text(encoding='utf-8')

        for queue_key in ('jbl', 'my_visits', 'credit', 'final', 'requisition', 'deferred', 'all'):
            self.assertIn(f'queue_key="{queue_key}"', template)
        self.assertIn('Choose filters to narrow this queue.', tools)
        self.assertIn('delay: 250', Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8'))
        self.assertIn('[20, 40, 60, 80, 90, 100, 110, 125, 140, 160, 180, 200]', components)
        self.assertNotIn("focusId: String(source.focusId", components)
        self.assertIn('bindTableZoom', curated)
        self.assertIn('loadLeaflet', asset_loader)

    def test_portal_queue_empty_states_use_the_compact_completion_treatment(self):
        queue_source = Path('core/static/miniapp/portal_queues.js').read_text(encoding='utf-8')
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        filter_source = Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8')
        list_template = Path('core/templates/portal/partials/farmer_list.html').read_text(encoding='utf-8')
        stylesheet = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')

        self.assertIn('Credit queue is clear', queue_source)
        self.assertNotIn('No BRO analysis cases', queue_source)
        for source in (portal_source, list_template):
            self.assertIn('queue-empty-state', source)
            self.assertIn('<svg viewBox', source)
            self.assertNotIn('es-icon">OK', source)
        self.assertIn('.farmer-list > .queue-empty-state', stylesheet)
        self.assertIn('min-height: 148px', stylesheet)

    def test_final_review_queue_is_the_single_canonical_decision_queue(self):
        queue_source = Path('core/static/miniapp/portal_queues.js').read_text(encoding='utf-8')
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        filter_source = Path('core/static/miniapp/portal_filters.js').read_text(encoding='utf-8')
        portal_template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        list_template = Path('core/templates/portal/partials/farmer_list.html').read_text(encoding='utf-8')

        self.assertIn("final: { endpoint: '/final-review-queue/'", queue_source)
        self.assertNotIn("state.activePage === 'final'", queue_source)
        self.assertNotIn("params.set('stage', state.filters.reviewStage)", queue_source)
        self.assertNotIn('reviewStage', portal_source)
        self.assertNotIn('data-final-review-stage', portal_template)
        self.assertNotIn('Payment files', portal_template)
        self.assertNotIn('id="final-review-stage"', portal_template)
        self.assertNotIn("el('final-review-stage')", filter_source)
        self.assertIn('data-queue-key="{{ queue_key }}"', list_template)

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

    def test_portal_maps_use_authenticated_runtime_carto_configuration(self):
        portal_source = Path('core/static/miniapp/portal.js').read_text(encoding='utf-8')
        sheet_source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')

        self.assertIn('state.cartoBasemaps = data.carto_basemaps', portal_source)
        self.assertIn('const basemaps = state().cartoBasemaps || {};', sheet_source)
        self.assertIn('if (!window.L || !basemaps.enabled || !tileUrl)', sheet_source)
        self.assertIn("if (!state().cartoBasemaps?.enabled)", sheet_source)
        self.assertNotIn("'https://{s}.basemaps.cartocdn.com", sheet_source)

    def test_credit_form_exposes_only_reasons_required_by_the_approval_contract(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        stylesheet = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')
        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        form = source[source.index('function buildCreditForm'):source.index('function wireCreditImabFields')]
        submit = source[source.index('async function submitCreditDecision'):source.index('async function submitFinalDecision')]

        self.assertNotIn('Status guide:', form)
        self.assertNotIn("buildApprovalReasonFields('credit')", form)
        self.assertNotIn("renderApprovalConditions(farmer, 'credit')", form)
        self.assertIn("decision !== 'Pending'", form)
        self.assertIn("decisionReasonMarkup('credit', true)", form)
        self.assertIn('credit-reason-code', source)
        self.assertNotIn('credit-conditions', submit)
        self.assertIn('reason_code: reasonCode', submit)
        self.assertIn('decision_comment: decisionComment', submit)
        self.assertIn('.decision-other-note[hidden]', stylesheet)
        self.assertNotIn('conditions }', submit)
        self.assertNotIn('Approved with Conditions', source)
        self.assertIn('form-section form-grid credit-analysis-form', form)
        self.assertIn('Credit Decision <span class="required-marker" aria-hidden="true">*</span>', form)
        self.assertIn('Created on iMAB? <span class="required-marker"', form)
        self.assertIn('class="credit-jbl-comment"', form)
        self.assertIn('class="credit-comment-type"', form)
        self.assertIn('class="credit-customer-number-heading"', form)
        self.assertIn("sheetOverlay?.classList.toggle('credit-analysis-sheet', mode === 'credit')", source)
        self.assertIn('.credit-analysis-sheet .credit-analysis-form', stylesheet)
        self.assertIn('.credit-analysis-sheet #sheet-map { height: 112px; }', stylesheet)
        self.assertIn('.credit-analysis-sheet .credit-gps-summary #sheet-map', stylesheet)
        self.assertIn('data-lucide="external-link"', template)

    def test_final_review_form_uses_client_media_and_conditional_decision_reasons(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        form = source[source.index('function buildFinalReviewForm'):source.index('async function loadClientMedia')]
        submit = source[source.index('async function submitFinalDecision'):source.index('function bindEvents')]

        self.assertIn("decisionReasonMarkup('final', false)", form)
        self.assertNotIn('approval-condition', form)
        self.assertNotIn("decision !== 'Under Review'", form)
        self.assertIn('btn-view-client-media', form)
        self.assertIn('final-client-media', form)
        self.assertIn('loadClientMedia', source)
        self.assertIn('renderClientMediaLinks', source)
        self.assertIn('openClientMediaPreview', source)
        self.assertIn('openClientMediaExternally', source)
        self.assertIn('viewer.fetchAuthorizedBlob(item.preview_url', source)
        self.assertIn('window.SecureMediaViewer', source)
        self.assertIn('Open externally', source)
        self.assertIn('class="client-media-summary"', source)
        self.assertIn('class="client-media-type-icon"', source)
        self.assertIn("classList.add('client-media-open')", source)
        self.assertIn('data-lucide="eye"', source)
        self.assertIn('deps.openPortalLink(latest.open_url)', source)
        self.assertIn('sandbox=""', source)
        self.assertNotIn('docs.google.com/gview', source)
        self.assertNotIn('item.viewer_url', source)
        self.assertNotIn('item.open_url || item.view_url', source)
        self.assertIn('Supporting Photo', source)
        self.assertIn('Signed LAF', source)
        self.assertIn('form-grid final-review-grid', form)
        self.assertIn('form-row form-row-wide', form)
        stylesheet = Path('core/static/miniapp/portal.css').read_text(encoding='utf-8')
        self.assertIn('phone-action-field', form)
        self.assertIn('<span class="sr-only">Call customer</span>', form)
        self.assertIn("phoneDigits.startsWith('0')", form)
        self.assertIn('.workflow-standard.portal-app .phone-call-button span', stylesheet)
        self.assertIn('-webkit-text-fill-color: #fff', stylesheet)
        self.assertIn('--portal-z-media: 260;', stylesheet)
        self.assertIn('#media-viewer-overlay { z-index: var(--portal-z-media); }', stylesheet)
        self.assertIn('final-reason-code', source)
        self.assertIn('reason_code: reasonCode', submit)
        self.assertIn('id="final-comment-required"', form)
        self.assertNotIn('final-conditions', submit)
        self.assertNotIn('Approved with Conditions', source)
        self.assertIn("wireVoiceWidget('final_decision_comment')", source)

    def test_portal_map_uses_an_offline_inline_marker(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')
        shell = Path('core/templates/base_shell.html').read_text(encoding='utf-8')

        self.assertNotIn('marker-icon.png', shell)
        self.assertIn("L.divIcon({", source)
        self.assertIn("className: 'portal-map-marker'", source)
        self.assertIn('{ icon: portalMarkerIcon() }', source)

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

    def test_jbl_visit_retry_reconciles_an_interrupted_response(self):
        source = Path('core/static/miniapp/portal_farmer_sheet.js').read_text(encoding='utf-8')

        self.assertIn('portal:jbl:submission:', source)
        self.assertIn('/completion-status/?request_id=', source)
        self.assertIn('already_completed: true', source)
        self.assertIn('Your form is still here; retry to safely continue the same request.', source)

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
        self.assertIn('id="requisition-preview-confirm" type="button"', template)
        self.assertNotIn('id="requisition-preview-confirm" type="button" hidden', template)

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

    def test_head_of_rural_screen_exposes_only_final_decisions(self):
        response = self.client.get(reverse('portal_screen', kwargs={'screen': 'final'}))
        self.assertContains(response, 'Make final case decisions before order preparation.')
        self.assertContains(response, 'Order Approval')
        self.assertNotContains(response, 'data-final-review-stage')
        self.assertNotContains(response, 'Payment files')
        self.assertNotContains(response, 'id="final-review-stage"')
        self.assertNotContains(response, 'Ready for requisition / order')

    def test_portal_payments_exposes_selection_primitives(self):
        source = Path('core/static/miniapp/portal_payments.js').read_text(encoding='utf-8')

        for expected in (
            'window.PortalMiniAppPayments',
            'payment-candidate-checkbox',
            '/payments/candidates/',
            '/payments/batches/',
            'data-payment-batch-filter',
            'activeBatch.revision',
            '/cancel/',
            'farmer_ids',
            'payment_modes',
            'data-payment-candidate-mode',
            'data-payment-case-mode',
            'confirmFirstSubmission',
            'payment-submit-confirm',
        ):
            self.assertIn(expected, source)
        template = Path('core/templates/portal/portal.html').read_text(encoding='utf-8')
        self.assertIn('id="payment-submit-confirm"', template)
        self.assertIn('permanently allocates the next official payment number', source)
        self.assertNotIn('payments-detail-mode', source)
        self.assertNotIn('id="payments-mode"', Path('core/templates/portal/portal.html').read_text(encoding='utf-8'))

    def test_payment_preparation_and_approval_have_distinct_route_backed_screens(self):
        batch_id = '00000000-0000-0000-0000-000000000001'

        self.assertEqual(reverse('portal_payments_screen'), '/portal/s/payments/')
        self.assertEqual(
            reverse('portal_payment_batch_screen_detail', kwargs={'batch_id': batch_id}),
            f'/portal/s/payments/{batch_id}/',
        )
        self.assertEqual(reverse('portal_payment_approvals_screen'), '/portal/s/approvals/payments/')
        self.assertEqual(
            reverse('portal_payment_approval_detail', kwargs={'batch_id': batch_id}),
            f'/portal/s/approvals/payments/{batch_id}/',
        )
        self.assertEqual(
            reverse('portal_payment_batch_detail', kwargs={'batch_id': batch_id}),
            f'/api/portal/payments/batches/{batch_id}/',
        )

        source = Path('core/static/miniapp/portal_payments.js').read_text(encoding='utf-8')
        self.assertIn("screen() === 'payment_approvals'", source)
        self.assertIn("function detailUrl(id)", source)
        self.assertIn('href="${escape(detailUrl(batch.id))}"', source)
        self.assertIn('window.PortalAppShell?.navigateUrl', source)
        self.assertIn("if (routeBatchId)", source)

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
                "await json('cases/'",
                'renderCases(response.cases || [], response.start_index || 0)',
                'window.ComplaintCasesMiniAppApi',
                'apiClient.postJson',
                'apiClient.postForm',
            ),
            'core/static/miniapp/tat_tracker.js': (
                "renderList('queueList'",
                'state.lastSuccessfulHome = snapshotHome()',
                'renderHome(state.lastSuccessfulHome)',
                'await renderTatSearchFragment(query)',
                'window.TatMiniAppApi',
                'tatApi.postJson',
                'tatApi.postFragment',
            ),
            'core/static/miniapp/portal.js': (
                'const rendered = await renderQueueFragment(qKey, page, loadVersion)',
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

        self.assertIn('miniapp/workflow_standard.css?v=17', html)
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
        self.assertIn('...payloadAtPreviewRevision(payload, data)', source)
        self.assertIn('preview_token: data.preview_token', source)
        self.assertIn('finalize_request_id: requisitionRequestId()', source)
