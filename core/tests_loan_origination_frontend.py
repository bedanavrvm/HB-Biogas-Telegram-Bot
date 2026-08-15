from pathlib import Path

from django.test import SimpleTestCase


class LoanOriginationFrontendTests(SimpleTestCase):
    def test_miniapp_shell_is_not_cached_by_telegram_webview(self):
        response = self.client.get('/origination/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Pragma'], 'no-cache')

    def test_wizard_and_preview_contract_are_present(self):
        source = Path('core/static/miniapp/loan_origination.js').read_text(encoding='utf-8')
        template = Path('core/templates/loan_origination/app.html').read_text(encoding='utf-8')
        css = Path('core/static/miniapp/loan_origination.css').read_text(encoding='utf-8')

        for section in ('Applicant', 'Business', 'Loan', 'Security', 'Guarantors', 'Review'):
            self.assertIn(f"label: '{section}'", source)
        self.assertIn('grid-template-columns:repeat(2', css)
        self.assertIn('laf-field-wide', css)
        self.assertIn('/preview/', source)
        self.assertIn('previewedRevision !== current.revision', source)
        self.assertIn('URL.revokeObjectURL', source)
        self.assertIn('document-preview-overlay', template)
        self.assertIn('preview-regenerate', template)
        self.assertIn('@media (max-width: 390px)', css)
        self.assertIn('font-size: 16px !important', css)
        self.assertIn('position: sticky', css)
        self.assertIn('class="header-icon"', template)
        self.assertIn('data-ui-version="20260815-1"', template)
        self.assertIn('wizardSections()', source)
        self.assertIn('field.section_key', source)
        self.assertIn("field.type === 'textarea'", source)
        self.assertIn("stage.addEventListener('pointermove'", source)
        self.assertIn('setPointerCapture', source)
        self.assertIn('touch-action: none', css)
        self.assertIn('Math.min(300', source)
        self.assertIn('deliberateHorizontalSwipe', source)
        self.assertIn('navigatePreviewPage(deltaX < 0 ? 1 : -1)', source)
        self.assertIn('previewPageUrls.size > 3', source)
        self.assertIn('void fetchPreviewPage(pageNumber)', source)
        self.assertIn('indexedDB.open(RECOVERY_DB', source)
        self.assertIn("name: 'AES-GCM'", source)
        self.assertIn('pendingSaveRequestId', source)
        self.assertIn('saveInFlight', source)
        self.assertIn('data-evidence-upload', source)
        self.assertIn('data-correction-target', source)
        self.assertIn('origination-review-overlay', template)
        self.assertIn('queue-tabs', css)
        self.assertIn('origination-sheet-overlay', template)
        self.assertIn('wizard-progress-compact', source)
        self.assertIn('data-primary-action', source)
        self.assertIn('syncTelegramControls', source)
        self.assertIn("tg?.onEvent?.('viewportChanged'", source)
        self.assertIn("tg?.onEvent?.('themeChanged'", source)
        self.assertIn('listScrollY', source)
        self.assertIn('applyListFilters', source)
        self.assertIn('trapModalFocus', source)
        self.assertIn('iconSvg', source)
        self.assertNotIn('class="app-hero"', source)
        self.assertNotIn('window.prompt', source)

    def test_superuser_template_calibration_workspace_is_present(self):
        template = Path('core/templates/admin/core/originationdocumenttemplate/calibrate.html').read_text(encoding='utf-8')
        source = Path('core/static/admin/origination_calibration.js').read_text(encoding='utf-8')
        for control in ('calibration-canvas', 'calibration-save', 'calibration-publish', 'cal-filled', 'calibration-add-signature'):
            self.assertIn(control, template)
        self.assertIn('global-apply', template)
        self.assertIn('global-font', template)
        self.assertIn('preview_format', Path('core/static/miniapp/loan_origination.js').read_text(encoding='utf-8'))
        self.assertIn('beforeunload', source)

    def test_superuser_visual_product_builder_is_present(self):
        template = Path('core/templates/admin/core/originationproductdefinition/change_form.html').read_text(encoding='utf-8')
        source = Path('core/static/admin/origination_product_builder.js').read_text(encoding='utf-8')

        for control in ('origination-product-builder', 'opb-sections', 'opb-signers', 'add-section', 'add-signer'):
            self.assertIn(control, template)
        for field_type in ('textarea', 'money', 'national_id', 'choice', 'boolean'):
            self.assertIn(field_type, source)
        self.assertIn('Add field', source)
        self.assertIn('Add slot', source)
        self.assertIn('data-validation-prop="min"', source)
        self.assertIn('data-validation-prop="pattern"', source)
