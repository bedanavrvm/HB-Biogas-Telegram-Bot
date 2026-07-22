from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve

from core.admin_dashboard import dashboard_callback
from core.models import GroupSheetConfiguration, ParsedMessage, SpinCreditRequest, TatTrackerCase, TatTrackerEvent


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
        self.assertContains(response, 'Operations Overview')

    def _processed_message_id(self):
        from core.models import ProcessedMessage, RawMessage
        raw = RawMessage.objects.create(
            telegram_message_id='msg-1',
            sender='tester',
            content='private complaint body',
        )
        processed = ProcessedMessage.objects.create(raw_message=raw, message_hash='test-hash-1', status='success')
        return processed.pk
