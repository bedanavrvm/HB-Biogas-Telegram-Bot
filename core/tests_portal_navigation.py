from unittest.mock import patch

from django.test import SimpleTestCase

from core.services.portal_navigation import (
    get_portal_nav_groups,
    get_portal_nav_hubs,
    get_portal_nav_items,
    get_portal_pipeline_stages,
)


class PortalNavigationTests(SimpleTestCase):
    def _items_for(self, roles, capabilities):
        with patch(
            'core.services.workflow_capabilities.effective_capability_keys',
            return_value=set(capabilities),
        ):
            return get_portal_nav_items(
                user={'user_id': 'test-user'},
                access={'roles': roles},
            )

    def test_jbl_officer_bottom_navigation_uses_stable_authorized_hubs(self):
        capabilities = {
            'portal.dashboard.view',
            'portal.jbl_queue.view',
            'portal.jbl_followup.view',
            'portal.requisition.view',
            'portal.case.read',
        }
        with patch(
            'core.services.workflow_capabilities.effective_capability_keys',
            return_value=capabilities,
        ):
            hubs = get_portal_nav_hubs(
                user={'user_id': 'test-user'}, access={'roles': ['JBL_OFFICER']},
                active_screen='my_visits',
            )

        self.assertEqual([hub['key'] for hub in hubs], ['home', 'pipeline', 'cases', 'more'])
        self.assertEqual(next(hub for hub in hubs if hub['key'] == 'pipeline')['screen'], 'jbl')
        self.assertTrue(next(hub for hub in hubs if hub['key'] == 'pipeline')['active'])
        self.assertLessEqual(len(hubs), 4)

    def test_pipeline_stages_keep_loan_cycle_order_after_capability_filtering(self):
        capabilities = {
            'portal.jbl_queue.view', 'portal.credit_queue.view',
            'portal.requisition.view', 'portal.invoice.view',
        }
        with patch(
            'core.services.workflow_capabilities.effective_capability_keys',
            return_value=capabilities,
        ):
            stages = get_portal_pipeline_stages(
                user={'user_id': 'test-user'}, access={'roles': ['IT']}, active_screen='credit',
            )

        self.assertEqual([stage['key'] for stage in stages], ['visit', 'credit', 'fulfilment', 'finance'])
        self.assertTrue(next(stage for stage in stages if stage['key'] == 'credit')['active'])

        unfiltered_hubs = get_portal_nav_hubs(None, access=None, active_screen='dashboard')
        self.assertEqual(next(hub for hub in unfiltered_hubs if hub['key'] == 'pipeline')['screen'], 'farmup')

    def test_navigation_items_retain_stable_route_keys(self):
        items = self._items_for(
            ['JBL_OFFICER'],
            {
                'portal.dashboard.view',
                'portal.jbl_queue.view',
                'portal.jbl_followup.view',
                'portal.requisition.view',
                'portal.case.read',
            },
        )

        self.assertEqual([item['key'] for item in items], ['dashboard', 'jbl', 'my_visits', 'requisition', 'all', 'case_history', 'settings'])
        self.assertEqual(next(item for item in items if item['key'] == 'jbl')['stage'], 'visit')

    def test_sidebar_groups_only_already_authorized_destinations(self):
        capabilities = {
            'portal.dashboard.view',
            'portal.case.read',
            'portal.farmup.view',
            'portal.imports.view',
            'portal.reports.view',
        }
        with patch(
            'core.services.workflow_capabilities.effective_capability_keys',
            return_value=capabilities,
        ):
            groups = get_portal_nav_groups(
                user={'user_id': 'it-user'},
                access={'roles': ['IT']},
            )

        grouped_keys = {
            group['label']: [item['key'] for item in group['items']]
            for group in groups
        }

        self.assertEqual(grouped_keys['Home'], ['dashboard'])
        self.assertEqual(grouped_keys['Cases'], ['all', 'case_history'])
        self.assertEqual(grouped_keys['Pipeline · Intake'], ['farmup', 'imports'])
        self.assertEqual(grouped_keys['More'], ['reports', 'settings'])
        self.assertNotIn('Credit', str(grouped_keys))

    def test_farmup_is_sidebar_only_for_it_and_operations_admin(self):
        for role in ('IT', 'OPERATIONS_ADMIN'):
            items = self._items_for([role], {'portal.dashboard.view', 'portal.farmup.view'})
            farmup = next(item for item in items if item['key'] == 'farmup')
            self.assertFalse(farmup['bottom_primary'])
            self.assertEqual(farmup['category'], 'Pipeline · Intake')

        denied = self._items_for(['JBL_OFFICER'], {'portal.dashboard.view'})
        self.assertNotIn('farmup', [item['key'] for item in denied])
