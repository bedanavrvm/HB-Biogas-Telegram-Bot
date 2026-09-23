from django.test import SimpleTestCase

from core.services.identifiers import normalize_kenyan_phone, validate_kenyan_national_id
from core.services.loan_origination import normalize_form_payload, validate_form_payload


class KenyanIdentifierValidationTests(SimpleTestCase):
    def test_mobile_variants_normalize_to_canonical_storage_format(self):
        variants = (
            '0712 345 678',
            '0712-345-678',
            '+254 (712) 345 678',
            '254712345678',
            '00254 712 345 678',
            '005 712 345 678',
            '+254 0712 345 678',
            '712345678',
            '0120345678',
        )
        expected = ('254712345678',) * 8 + ('254120345678',)

        self.assertEqual(tuple(normalize_kenyan_phone(value) for value in variants), expected)

    def test_mobile_rejects_non_mobile_and_internal_testing_ranges(self):
        for value in ('0300123456', '0800123456', '0900123456', '0199123456', 'abc'):
            with self.subTest(value=value):
                self.assertEqual(normalize_kenyan_phone(value), '')

    def test_ids_retain_leading_zeroes_and_accept_legacy_and_maisha_lengths(self):
        self.assertEqual(validate_kenyan_national_id('000123'), '000123')
        self.assertEqual(validate_kenyan_national_id('12345678'), '12345678')
        self.assertEqual(validate_kenyan_national_id('123456789'), '123456789')

    def test_ids_reject_serial_like_or_malformed_values(self):
        for value in ('', '1234567890', '12 345', 'ABC123', '12-345'):
            with self.subTest(value=value):
                self.assertEqual(validate_kenyan_national_id(value), '')

    def test_origination_uses_the_same_identifier_contract(self):
        schema = {'fields': [
            {'key': 'applicant_id', 'type': 'national_id', 'required': True},
            {'key': 'applicant_phone', 'type': 'phone', 'required': True},
        ]}
        payload = normalize_form_payload(schema, {
            'applicant_id': '123456789',
            'applicant_phone': '+254 (712) 345 678',
        })
        self.assertEqual(payload['applicant_phone'], '254712345678')
        self.assertTrue(validate_form_payload(schema, payload, require_complete=True).valid)
        invalid = validate_form_payload(schema, {
            'applicant_id': '1234567890', 'applicant_phone': '0800123456',
        }, require_complete=True)
        self.assertFalse(invalid.valid)
        self.assertIn('applicant_id', invalid.errors)
        self.assertIn('applicant_phone', invalid.errors)
