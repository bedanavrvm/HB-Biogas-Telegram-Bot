from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import ComplaintCategory, GroupSheetConfiguration, OperationalLocation, Product
from core.services.fresh_database_baseline import apply_baseline, audit_baseline


class FreshDatabaseBaselineTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(
            username='baseline-root', email='baseline@example.test', password='password',
        )

    def test_migrated_database_has_the_reviewed_location_baseline(self):
        apply_baseline(actor=self.actor)
        report = audit_baseline()

        self.assertTrue(report['ok'], report)
        self.assertEqual(report['location_counts']['counties'], 47)
        self.assertEqual(report['location_counts']['sub_counties'], 349)
        self.assertGreaterEqual(report['location_counts']['branches'], 9)
        self.assertEqual(
            list(Product.objects.order_by('sort_order').values_list('code', 'name')),
            [
                ('business', 'Business'),
                ('logbook', 'Logbook'),
                ('mjengo', 'Mjengo'),
                ('micro_asset', 'Micro-Asset'),
            ],
        )

    def test_apply_restores_missing_reference_data_and_is_idempotent(self):
        ComplaintCategory.objects.filter(key='technical-support').delete()
        OperationalLocation.objects.filter(
            location_type='branch', name='Eco Conserve',
        ).delete()

        first = apply_baseline(actor=self.actor)
        second = apply_baseline(actor=self.actor)

        self.assertTrue(first['ok'], first)
        self.assertTrue(second['ok'], second)
        self.assertEqual(first['summary'], second['summary'])
        self.assertEqual(Product.objects.count(), 4)

    def test_audit_rejects_an_unapproved_default_product(self):
        apply_baseline(actor=self.actor)
        Product.objects.create(name='Unexpected', code='unexpected', active=True)

        report = audit_baseline()

        self.assertFalse(report['ok'])
        self.assertTrue(any(
            item['area'] == 'products'
            and item['key'] == 'unexpected'
            and item['state'] == 'conflicting'
            for item in report['items']
        ))

    def test_apply_refuses_a_database_with_operational_configuration(self):
        GroupSheetConfiguration.objects.create(
            group_id='-100-live', display_name='Live', workflow={'type': 'case'},
        )

        with self.assertRaisesMessage(ValueError, 'restricted to a fresh database'):
            apply_baseline()

    def test_management_command_is_read_only_by_default(self):
        output = StringIO()
        apply_baseline(actor=self.actor)

        call_command('seed_fresh_database_baseline', stdout=output)

        self.assertIn('Baseline:', output.getvalue())

    def test_management_command_requires_superuser_for_apply(self):
        with self.assertRaises(CommandError):
            call_command('seed_fresh_database_baseline', '--apply', '--actor', 'missing')
