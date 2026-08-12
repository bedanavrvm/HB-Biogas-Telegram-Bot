from pathlib import Path

from django.test import SimpleTestCase


class LoanOriginationFrontendTests(SimpleTestCase):
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
