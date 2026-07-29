from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from unfold.admin import ModelAdmin

from core.admin_dashboard import dashboard_callback
from core.admin import GroupSheetConfigurationAdmin
from core.admin_navigation import get_admin_navigation
from core.models import (
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    ParsedMessage,
    SpinCreditRequest,
    TatTrackerCase,
    TatTrackerEvent,
)


@override_settings(ROOT_URLCONF='config.urls')
class AdminMonitoringTests(TestCase):
    def test_dashboard_callback_exposes_aggregate_operational_state(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-1001',
            display_name='TAT Test',
            sheet_id='sheet',
            workflow={'type': 'tat_tracker'},
        )
        ParsedMessage.objects.create(
            processed_message_id=self._processed_message_id(),
            message_id='msg-1',
            raw_message='private complaint body',
            complaint_status='Open',
            group_id=group.group_id,
            synced_to_sheets=False,
            last_sync_error='quota',
        )
        SpinCreditRequest.objects.create(
            group_id=group.group_id,
            request_type='spin',
            import_status='completed',
            sync_error='quota',
        )
        case = TatTrackerCase.objects.create(
            group_id=group.group_id,
            case_id='JBL-BS-2026-001',
            product_key='business',
            client_name='Private Name',
            status='Active',
            sync_error='quota',
        )
        TatTrackerEvent.objects.create(
            case=case,
            group_id=group.group_id,
            source='mini_app',
            synced_to_sheet=False,
        )

        request = RequestFactory().get('/admin/')
        request.current_app = AdminSite().name
        context = dashboard_callback(request, {})

        dashboard = context['ops_dashboard']
        card_titles = {card['title'] for card in dashboard['cards']}
        alert_counts = {alert['label']: alert['count'] for alert in dashboard['alerts']}

        self.assertIn('Complaint Cases', card_titles)
        self.assertIn('SPIN Requests', card_titles)
        self.assertIn('Active TAT Cases', card_titles)
        self.assertEqual(alert_counts['Complaint sheet sync failures'], 1)
        self.assertEqual(alert_counts['SPIN sheet sync failures'], 1)
        self.assertEqual(alert_counts['TAT sheet sync failures'], 1)
        self.assertEqual(alert_counts['Unsynced TAT events'], 1)
        self.assertNotIn('Private Name', str(dashboard))
        self.assertNotIn('private complaint body', str(dashboard))

    def test_health_check_url_is_available(self):
        match = resolve('/ops/health/')

        self.assertEqual(match.url_name, 'health_check_home')

    def test_admin_index_renders_operational_dashboard(self):
        user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)

        response = client.get('/admin/', follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operations dashboard')
        self.assertContains(response, '/static/admin/css/compact_unfold.css')
        self.assertContains(response, 'compact_unfold.css?v=3')

    def test_admin_index_uses_curated_sidebar_and_global_search(self):
        user = get_user_model().objects.create_superuser(
            username='navigation-admin',
            email='navigation@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)

        response = client.get('/admin/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operations')
        self.assertContains(response, 'All workflows')
        self.assertContains(response, 'Configuration')
        self.assertContains(response, 'Technical records')
        self.assertContains(response, 'Branches and counties')
        self.assertContains(response, 'search-input-command')
        self.assertContains(response, 'admin-operations-dashboard')
        # The raw 32-model app list must not be dumped into the dashboard.
        self.assertNotContains(response, 'Complaint case sequences')

    def test_admin_dashboard_preserves_private_data_boundary(self):
        user = get_user_model().objects.create_superuser(
            username='dashboard-admin',
            email='dashboard@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)

        response = client.get('/admin/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Needs attention')
        self.assertContains(response, 'Workflow overview')
        self.assertContains(response, 'Status distribution')
        self.assertNotContains(response, 'private complaint body')
        self.assertNotContains(response, 'Private Name')

    def test_builtin_auth_models_use_unfold_admin(self):
        self.assertIsInstance(admin.site._registry[get_user_model()], ModelAdmin)
        self.assertIsInstance(admin.site._registry[Group], ModelAdmin)

    def test_group_configuration_change_form_uses_unfold_tabs(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-1002',
            display_name='Config Test',
            sheet_id='sheet',
            workflow={'type': 'tat_tracker'},
        )
        user = get_user_model().objects.create_superuser(
            username='admin2',
            email='admin2@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)

        response = client.get(f'/admin/core/groupsheetconfiguration/{group.pk}/change/', follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'tab-wrapper')
        self.assertContains(response, 'TAT Tracker Targets')
        self.assertTrue(GroupSheetConfigurationAdmin.compressed_fields)
        self.assertTrue(GroupSheetConfigurationAdmin.list_filter_submit)
        self.assertTrue(GroupSheetConfigurationAdmin.list_fullwidth)

    def test_jawabu_master_change_form_groups_operational_fields_compactly(self):
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Test Customer',
            national_id='12345678',
        )
        user = get_user_model().objects.create_superuser(
            username='jawabu-admin',
            email='jawabu-admin@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)

        response = client.get(f'/admin/core/jawabufarmermaster/{farmer.pk}/change/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Export / Payment')
        self.assertContains(response, 'Final Review / Decision')
        self.assertContains(response, 'field-imab_customer_name')
        self.assertContains(response, 'field-jbl_media_urls')
        self.assertContains(response, 'lg:grid-cols-2')

    def test_registered_admin_model_lists_and_available_add_forms_render(self):
        """Guard the shared Unfold shell against one model page breaking it all."""
        user = get_user_model().objects.create_superuser(
            username='render-audit-admin',
            email='render-audit@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)

        permission_request = RequestFactory().get('/admin/')
        permission_request.user = user
        for model, model_admin in admin.site._registry.items():
            changelist_url = reverse(
                f'admin:{model._meta.app_label}_{model._meta.model_name}_changelist'
            )
            with self.subTest(page=changelist_url):
                self.assertEqual(client.get(changelist_url).status_code, 200)

            if not model_admin.has_add_permission(permission_request):
                continue
            add_url = reverse(
                f'admin:{model._meta.app_label}_{model._meta.model_name}_add'
            )
            with self.subTest(page=add_url):
                response = client.get(add_url)
                # The User admin deliberately redirects to its guided staff
                # creation screen; every other permitted add form is rendered.
                self.assertIn(response.status_code, {200, 302})

    def test_sidebar_keeps_each_configured_workflow_group_together(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-1010',
            display_name='North TAT Desk',
            sheet_id='sheet',
            workflow={'type': 'tat_tracker'},
        )
        user = get_user_model().objects.create_superuser(
            username='workflow-navigation-admin',
            email='workflow-navigation@example.test',
            password='password',
        )
        request = RequestFactory().get('/admin/')
        request.user = user

        navigation = get_admin_navigation(request)
        group = next(item for item in navigation if item['title'] == 'TAT Tracker: North TAT Desk')
        item_titles = {item['title'] for item in group['items']}
        item_links = {item['title']: item['link'] for item in group['items']}

        self.assertTrue(group['collapsible'])
        self.assertSetEqual(
            item_titles,
            {
                'Configuration',
                'Live Sheet (view only)',
                'Cases',
                'Event history',
                'Reconcile TAT Sheet',
                'Find duplicate rows',
            },
        )
        self.assertIn(str(config.pk), item_links['Configuration'])
        self.assertIn('group_id__exact=-1010', item_links['Cases'])

    def test_live_sheet_sticky_cells_have_opaque_theme_backgrounds(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-1011',
            display_name='Sheet style test',
            sheet_id='sheet',
            sheet_name='Tracker',
            workflow={'type': 'case'},
        )
        user = get_user_model().objects.create_superuser(
            username='live-sheet-style-admin',
            email='live-sheet-style@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)
        table = {
            'sheet_tab': 'Tracker',
            'header_row': 2,
            'row_count': 1,
            'headers': ['Case ID', 'Customer'],
            'rows': [{
                'row_number': 3,
                'cells': [{'value': 'JBL-1'}, {'value': 'Customer'}],
            }],
        }

        with patch('core.services.live_sheet_records.load_live_sheet_table', return_value=table):
            response = client.get(
                reverse('admin:core_groupsheetconfiguration_live_records', args=[group.pk])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'isolation:isolate')
        self.assertContains(response, 'background:rgb(var(--color-base-100))')
        self.assertContains(response, 'th.row-number')
        self.assertContains(response, 'z-index:4')

    def test_sheet_audit_pages_use_unfold_theme_colours_and_mobile_safe_tables(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-1012',
            display_name='Sheet audit style test',
            sheet_id='sheet',
            sheet_name='Tracker',
            workflow={'type': 'tat_tracker'},
        )
        user = get_user_model().objects.create_superuser(
            username='sheet-audit-style-admin',
            email='sheet-audit-style@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)
        service = Mock()
        service.is_available.return_value = True
        service._sheet.row_values.return_value = ['Case ID', 'Customer name']

        with patch('core.services.sheets.get_sheets_service', return_value=service):
            coverage_response = client.get(
                reverse('admin:core_groupsheetconfiguration_coverage', args=[group.pk])
            )
        with patch(
            'core.services.sheet_analyzer.analyze_google_sheet',
            return_value={
                'status': 'success',
                'data_row_count': 1,
                'header_row': 1,
                'headers': ['Case ID'],
                'sample_size': 1,
                'warnings': [],
                'columns': [],
            },
        ):
            analysis_response = client.get(
                reverse('admin:core_groupsheetconfiguration_analyze', args=[group.pk])
            )

        for response in (coverage_response, analysis_response):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'rgb(var(--color-base-50))')
            self.assertNotContains(response, 'var(--body-bg)')
            self.assertNotContains(response, 'var(--darkened-bg)')
            self.assertNotContains(response, 'var(--hairline-color)')
        self.assertContains(coverage_response, 'overflow:auto')
        self.assertContains(analysis_response, 'overflow-x: auto')
        self.assertContains(analysis_response, 'min-width: 58rem')

    def test_custom_group_configuration_pages_use_shared_admin_shell(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-1003',
            display_name='Maintenance Test',
            sheet_id='sheet',
            workflow={'type': 'tat_tracker'},
        )
        user = get_user_model().objects.create_superuser(
            username='maintenance-admin',
            email='maintenance@example.test',
            password='password',
        )
        client = Client()
        client.force_login(user)

        response = client.get(
            reverse(
                'admin:core_groupsheetconfiguration_reset_data',
                args=[group.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="admin-custom-page"')
        self.assertContains(response, 'Reset local DB data')
        self.assertContains(response, 'class="submit-row"')
        self.assertContains(response, '/static/admin/css/compact_unfold.css')

    def _processed_message_id(self):
        from core.models import ProcessedMessage, RawMessage
        raw = RawMessage.objects.create(
            telegram_message_id='msg-1',
            sender='tester',
            content='private complaint body',
        )
        processed = ProcessedMessage.objects.create(raw_message=raw, message_hash='test-hash-1', status='success')
        return processed.pk
