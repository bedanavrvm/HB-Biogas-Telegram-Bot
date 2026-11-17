from django.test import SimpleTestCase, TestCase

from core.services.identifiers import normalize_person_name_case
from core.services.jawabu_pipeline import (
    create_portal_visit_lead, farmer_to_card, internal_order_projection_fields, master_projection_fields,
)


class PortalInputNameTests(TestCase):
    def test_intake_saves_name_case_used_by_both_portal_and_sheet_projection(self):
        farmer = create_portal_visit_lead(
            national_id='90000123', primary_phone='254700000123',
            customer_name="  JANE   O'NEILL-SMITH ", lead_name='jane smith', hb_sales_person='mARY smith',
        )
        farmer.refresh_from_db()
        self.assertEqual(farmer.customer_name, "Jane O'Neill-Smith")
        self.assertEqual(farmer.lead_name, 'Jane Smith')
        self.assertEqual(farmer.hb_sales_person, 'Mary Smith')
        self.assertEqual(farmer_to_card(farmer)['customer_name'], farmer.customer_name)
        farmer.jbl_officer = 'Officer McDonald'
        master = master_projection_fields(farmer)
        internal = internal_order_projection_fields(farmer)
        for field, header in (
            ('customer_name', 'CUSTOMER NAME'), ('hb_sales_person', 'HB STAFF'), ('jbl_officer', 'VISITED BY'),
        ):
            with self.subTest(field=field):
                self.assertEqual(master[field][1], getattr(farmer, field))
                self.assertEqual(internal[header][1], getattr(farmer, field))


class PersonNameCasingTests(SimpleTestCase):
    def test_whitespace_punctuation_and_existing_mixed_case(self):
        for entered, expected in (
            (None, ''), ('  JOHN   smith ', 'John Smith'), ("mARY o'NEILL", "Mary O'Neill"),
            ('jean-luc McDonald', 'Jean-Luc McDonald'), ('HB-JAMES', 'HB-James'), ('élodie MWANGI', 'Élodie Mwangi'),
        ):
            with self.subTest(entered=entered):
                self.assertEqual(normalize_person_name_case(entered), expected)
                self.assertEqual(normalize_person_name_case(expected), expected)
