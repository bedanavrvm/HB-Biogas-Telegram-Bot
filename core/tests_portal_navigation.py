from unittest.mock import patch

from django.test import SimpleTestCase

from core.services.portal_navigation import get_portal_nav_groups, get_portal_nav_items


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

    def test_jbl_officer_bottom_navigation_is_compact_and_permitted(self):
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

        bottom_keys = [item['key'] for item in items if item['bottom_primary']]

        self.assertEqual(bottom_keys, ['dashboard', 'jbl', 'my_visits', 'requisition'])
        self.assertLessEqual(len(bottom_keys), 4)

    def test_sidebar_groups_only_already_authorized_destinations(self):
        capabilities = {
            'portal.dashboard.view',
            'portal.case.read',
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

        self.assertEqual(grouped_keys['Overview'], ['dashboard'])
        self.assertEqual(grouped_keys['Cases'], ['all', 'case_history'])
        self.assertEqual(grouped_keys['IT tools'], ['imports', 'reports'])
        self.assertEqual(grouped_keys['Account'], ['settings'])
        self.assertNotIn('Credit', str(grouped_keys))
