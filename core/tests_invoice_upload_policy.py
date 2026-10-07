"""One uploaded file is one invoice, not a monthly collated register."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.services.invoice_parser import _parse_invoice_pdf_bytes


class InvoiceFilePolicyTests(SimpleTestCase):
    def parse(self, texts):
        pages = [SimpleNamespace(extract_text=lambda text=text: text) for text in texts]
        with patch('core.services.invoice_parser.PdfReader', return_value=SimpleNamespace(pages=pages)):
            return _parse_invoice_pdf_bytes(b'synthetic-pdf')

    def text(self, number='100', page='1 of 1'):
        return f'Page {page}\nHOMEBIOGAS VENTURES LIMITED\nBILL TO\nSynthetic Applicant\n12345678\nINVOICE {number}\nDATE 01/10/2026\nTOTAL 100.00\nBALANCE DUE\n100.00'

    def test_single_invoice_is_accepted(self):
        rows, count = self.parse([self.text()])
        self.assertEqual((len(rows), count), (1, 1))

    def test_collated_different_invoices_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'one invoice'):
            self.parse([self.text(), self.text('101')])

    def test_repeated_complete_copy_is_not_a_continuation(self):
        with self.assertRaisesRegex(ValueError, 'one invoice'):
            self.parse([self.text(), self.text()])

    def test_two_invoices_on_one_page_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'one invoice'):
            self.parse([self.text() + '\n' + self.text('101')])

    def test_numbered_continuation_remains_one_record(self):
        rows, count = self.parse([self.text(page='1 of 2'), 'Page 2 of 2\nINVOICE 100\nContinued item description'])
        self.assertEqual((len(rows), count), (1, 2))
        self.assertEqual(rows[0]['page_numbers'], [1, 2])

    def test_unidentified_extra_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'one invoice'):
            self.parse([self.text(), 'Unidentified attachment'])
