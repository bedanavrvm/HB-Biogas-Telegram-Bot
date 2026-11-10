"""Synthetic examples for the reviewed initial-load amendment boundary."""
from django.test import SimpleTestCase

from .cleaning import clean_review_values, merge_source_notes, money_value, outcome_value, reference_value
from .updates import equivalent


class ReviewedCleaningTests(SimpleTestCase):
    def test_equivalent_hb_statuses_do_not_create_milestones(self):
        for key, left, right in (
            ('commissioning_status', 'Done', 'commissioned'),
            ('commissioning_status', 'Pending', 'not_commissioned'),
            ('installation_status', 'Pending Installation', 'open'),
            ('readiness_status', 'Not ready', 'not_ready'),
        ):
            self.assertEqual(equivalent(key, left), equivalent(key, right))
        self.assertNotEqual(equivalent('commissioning_status', 'Done'), equivalent('commissioning_status', 'Pending'))
        self.assertEqual(equivalent('hb_sales_person', 'HB - EXAMPLE OFFICER'), equivalent('hb_sales_person', 'HB-EXAMPLE OFFICER'))

    def test_reference_formatting_is_partner_bound(self):
        self.assertEqual(reference_value('order_number', 'ORDER NO. 0012', 'Master Data'), 'HB-12')
        self.assertEqual(reference_value('order_number', '12', 'Eco-conserve'), 'ECO-12')
        self.assertEqual(reference_value('payment_number', '#0012'), '12')
        for key, raw, register in (
            ('order_number', 'ECO-12', 'Master Data'), ('payment_number', 'HB-12', 'Master Data'),
            ('order_number', '0', 'Master Data'), ('order_number', '12 / 13', 'Master Data'),
        ):
            with self.assertRaises(ValueError):
                reference_value(key, raw, register)

    def test_amounts_use_decimal_and_never_infer_a_receipt(self):
        self.assertEqual(money_value('KES 6,250.50/-'), '6250.50')
        self.assertEqual(money_value('-'), '0')
        for raw in ('31-10-2026', 'balance 6250', '6,25', '-500', 'NaN', '1.001'):
            with self.assertRaises(ValueError):
                money_value(raw)
        review = clean_review_values({'invoice_amount': '31-10-2026', 'deposit_paid_hbg': ''},
            source_sheet='Master Data', baseline={'invoice_amount': '125000', 'deposit_paid_hbg': '5000'})
        self.assertEqual(review.values['invoice_amount'], '125000')
        self.assertEqual(review.values['deposit_paid_hbg'], '5000')
        self.assertIn('invoice_amount', review.issues)

    def test_partial_dates_retain_only_the_matching_reviewed_full_date(self):
        review = clean_review_values({'installation_date': '10-Oct', 'commissioning_date': '11-Oct'},
            source_sheet='Master Data', baseline={'installation_date': '2025-10-10'})
        self.assertEqual(review.values['installation_date'], '2025-10-10')
        self.assertEqual(review.values['commissioning_date'], '')
        self.assertIn('commissioning_date', review.issues)

    def test_original_identity_correction_and_confirmed_geography_are_retained(self):
        review = clean_review_values({'national_id': '12345678 / OTHER', 'county': 'NYANDURUAH'},
            source_sheet='Master Data', baseline={'national_id': '12345678', 'county': 'NYANDARUA'},
            originals={'national_id': '12345678 / OTHER'}, county_aliases={'nyanduruah': 'NYANDARUA'})
        self.assertEqual(review.values['national_id'], '12345678')
        self.assertEqual(review.values['county'], 'NYANDARUA')
        unknown = clean_review_values({'county': 'AN UNKNOWN AREA'}, source_sheet='Master Data', baseline={'county': 'NYANDARUA'})
        self.assertEqual(unknown.values['county'], 'NYANDARUA')
        self.assertIn('county', unknown.issues)

    def test_notes_append_once_and_do_not_swallow_short_new_information(self):
        merged = merge_source_notes('Not installed', 'Installed', 'New source note')
        self.assertIn('Updated source comments:\nInstalled', merged)
        self.assertIn('November source note:\nNew source note', merged)
        self.assertEqual(merge_source_notes(merged, 'Installed', 'New source note'), merged)
        error = clean_review_values({'legacy:NOV COMMMENTS': '#REF!'}, source_sheet='Master Data')
        self.assertEqual(error.values['case_comment_history'], '')

    def test_reviewed_staff_label_and_receipt_totals_keep_their_meaning(self):
        review = clean_review_values({'hb_sales_person':'HB-EXAMPLE OFFICER [REGION]',
            'deposit_paid_hbg':'5000', 'legacy_deposit_paid_jbl':'2500', 'legacy:Total':'999999'},
            source_sheet='Master Data', baseline={'hb_sales_person':'HB - EXAMPLE OFFICER'})
        self.assertEqual(review.values['hb_sales_person'],'HB - EXAMPLE OFFICER')
        self.assertEqual(review.values['legacy:Total'],'7500')
        shortened = clean_review_values({'hb_sales_person':'HB-EXAMPLE OFFICER'},source_sheet='Master Data',baseline={'hb_sales_person':'HB - EXAMPLE FULL OFFICER'})
        self.assertEqual(shortened.values['hb_sales_person'],'HB - EXAMPLE FULL OFFICER')
        self.assertIn('hb_sales_person',shortened.issues)
        marker = clean_review_values({'deposit_paid_hbg':'Not on SF', 'legacy_deposit_paid_jbl':'2500', 'legacy:Total':'999999'},source_sheet='Master Data')
        self.assertEqual(marker.values['legacy:Total'],'')

    def test_conflicting_outcome_text_is_not_simplified(self):
        self.assertEqual(outcome_value('APPROVED - 12 October'), 'Approved')
        self.assertEqual(outcome_value('Rejected then APPROVED'), 'Rejected then APPROVED')
        self.assertEqual(outcome_value('NOT REJECTED'), 'NOT REJECTED')
