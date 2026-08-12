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
        self.assertIn('data-ui-version="20260812-2"', template)
        self.assertIn("stage.addEventListener('touchmove'", source)
        self.assertIn('touch-action: pan-x pan-y', css)
        self.assertIn('Math.min(300', source)

    def test_superuser_template_calibration_workspace_is_present(self):
        template = Path('core/templates/admin/core/originationdocumenttemplate/calibrate.html').read_text(encoding='utf-8')
        source = Path('core/static/admin/origination_calibration.js').read_text(encoding='utf-8')
        for control in ('calibration-canvas', 'calibration-save', 'calibration-publish', 'calibration-filled'):
            self.assertIn(control, template)
        self.assertIn('global-apply', template)
        self.assertIn('global-font', template)
        self.assertIn('preview_format', Path('core/static/miniapp/loan_origination.js').read_text(encoding='utf-8'))
        self.assertIn('beforeunload', source)
