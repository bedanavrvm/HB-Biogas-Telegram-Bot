import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.test import RequestFactory
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core.models import (
    MiniAppDiagnosticDailyAggregate,
    MiniAppDiagnosticEvent,
    MiniAppDiagnosticSession,
)
from core.services.miniapp_diagnostics import aggregate_and_prune, abrupt_rate_alert_snapshot


@override_settings(MINIAPP_DIAGNOSTICS_ENABLED=True)
class MiniAppDiagnosticApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='diagnostic-officer')
        self.session_uuid = uuid.uuid4()
        self.start_url = reverse('miniapp_diagnostic_session_start')

    def start(self, *, session_uuid=None, surface='portal'):
        payload = {
            'session_uuid': str(session_uuid or self.session_uuid),
            'surface': surface,
            'release': 'release-1',
            'platform': 'android',
            'network_bucket': 'cellular',
            'device_memory_bucket': 'low',
        }
        with patch(
            'core.api.miniapp_diagnostic_views._authorized_actor',
            return_value=self.user,
        ):
            return self.client.post(
                self.start_url, data=json.dumps(payload), content_type='application/json',
            )

    def signal(self, session_uuid, token, events):
        return self.client.post(
            reverse('miniapp_diagnostic_signals', args=[session_uuid]),
            data=json.dumps({'signal_token': token, 'events': events}),
            content_type='application/json',
        )

    def event(self, event_type, *, visibility='visible', request_id='', action=''):
        return {
            'event_uuid': str(uuid.uuid4()),
            'event_type': event_type,
            'elapsed_ms': 100,
            'visibility': visibility,
            'online': True,
            'network_bucket': 'cellular',
            'status_bucket': '',
            'request_id': request_id,
            'action': action,
            'route': '/customer/should-not-be-stored',
        }

    def test_session_start_is_idempotent_and_returns_scoped_token(self):
        first = self.start()
        second = self.start()

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()['created'])
        self.assertFalse(second.json()['created'])
        self.assertTrue(first.json()['signal_token'])
        self.assertEqual(MiniAppDiagnosticSession.objects.count(), 1)

    def test_start_requires_authorized_telegram_actor(self):
        response = self.client.post(
            self.start_url,
            data=json.dumps({'session_uuid': str(self.session_uuid), 'surface': 'portal'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MiniAppDiagnosticSession.objects.count(), 0)

    def test_signals_are_idempotent_and_never_store_client_route(self):
        started = self.start().json()
        event = self.event(
            'api_request', request_id='request-12345678', action='api_request',
        )

        first = self.signal(self.session_uuid, started['signal_token'], [event])
        second = self.signal(self.session_uuid, started['signal_token'], [event])

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(MiniAppDiagnosticEvent.objects.count(), 1)
        stored = MiniAppDiagnosticEvent.objects.get()
        self.assertEqual(stored.route, '')
        self.assertEqual(stored.request_id, 'request-12345678')

    def test_background_and_resume_cycle_is_never_classified_as_abrupt(self):
        started = self.start().json()
        response = self.signal(self.session_uuid, started['signal_token'], [
            self.event('backgrounded', visibility='hidden', action='visibility_change'),
            self.event('resumed', visibility='visible', action='visibility_change'),
        ])

        self.assertEqual(response.status_code, 200)
        session = MiniAppDiagnosticSession.objects.get()
        self.assertEqual(session.classification, MiniAppDiagnosticSession.CLASSIFICATION_ACTIVE)
        self.assertIsNone(session.ended_at)

    def test_delayed_backward_heartbeat_is_acknowledged_without_becoming_new_evidence(self):
        started = self.start().json()
        later = self.event('resumed', action='visibility_change')
        later['elapsed_ms'] = 5000
        delayed = self.event('heartbeat', action='periodic')
        delayed['elapsed_ms'] = 1000

        response = self.signal(self.session_uuid, started['signal_token'], [later, delayed])

        self.assertEqual(response.status_code, 200)
        self.assertIn(delayed['event_uuid'], response.json()['acknowledged'])
        self.assertEqual(MiniAppDiagnosticEvent.objects.count(), 1)

    def test_later_launch_confirms_visible_gap_as_abrupt_unknown(self):
        started = self.start().json()
        second_uuid = uuid.uuid4()
        self.start(session_uuid=second_uuid)
        session = MiniAppDiagnosticSession.objects.get(client_session_uuid=self.session_uuid)
        self.assertEqual(session.classification, MiniAppDiagnosticSession.CLASSIFICATION_STALE)

        response = self.signal(self.session_uuid, started['signal_token'], [
            self.event('recovery_complete', visibility='visible', action='recovery'),
        ])

        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.classification, MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT)
        self.assertTrue(session.recovered_on_later_launch)

    def test_later_launch_preserves_backgrounding_distinction(self):
        started = self.start().json()
        self.signal(self.session_uuid, started['signal_token'], [
            self.event('backgrounded', visibility='hidden', action='visibility_change'),
            self.event('recovery_complete', visibility='hidden', action='recovery'),
        ])

        session = MiniAppDiagnosticSession.objects.get()
        self.assertEqual(
            session.classification,
            MiniAppDiagnosticSession.CLASSIFICATION_BACKGROUND_NOT_RESUMED,
        )

    def test_intentional_close_remains_terminal_when_recovery_is_retried(self):
        started = self.start().json()
        self.signal(self.session_uuid, started['signal_token'], [
            self.event('intentional_close', action='submit_success'),
            self.event('recovery_complete', action='recovery'),
        ])

        session = MiniAppDiagnosticSession.objects.get()
        self.assertEqual(
            session.classification,
            MiniAppDiagnosticSession.CLASSIFICATION_INTENTIONAL_CLOSE,
        )

    def test_signal_token_cannot_be_reused_for_another_session(self):
        first = self.start().json()
        second_uuid = uuid.uuid4()
        self.start(session_uuid=second_uuid)

        response = self.signal(second_uuid, first['signal_token'], [self.event('heartbeat')])

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            MiniAppDiagnosticEvent.objects.filter(session__client_session_uuid=second_uuid).exists()
        )


class MiniAppDiagnosticRetentionTests(TestCase):
    def test_retention_rolls_up_before_deleting_raw_rows_and_is_idempotent(self):
        user = get_user_model().objects.create_user(username='retention-officer')
        session = MiniAppDiagnosticSession.objects.create(
            client_session_uuid=uuid.uuid4(), actor=user, workflow='jawabu_portal',
            surface='portal', platform='android', release='release-1',
            classification=MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT,
        )
        MiniAppDiagnosticSession.objects.filter(pk=session.pk).update(
            started_at=timezone.now() - timedelta(days=15),
        )
        MiniAppDiagnosticEvent.objects.create(
            session=session, client_event_uuid=uuid.uuid4(), event_type='heartbeat',
        )

        preview = aggregate_and_prune(apply=False, raw_days=14, aggregate_days=180)
        applied = aggregate_and_prune(apply=True, raw_days=14, aggregate_days=180)
        repeated = aggregate_and_prune(apply=True, raw_days=14, aggregate_days=180)

        self.assertEqual(preview['raw_sessions'], 1)
        self.assertEqual(applied['raw_sessions'], 1)
        self.assertEqual(repeated['raw_sessions'], 0)
        self.assertFalse(MiniAppDiagnosticSession.objects.exists())
        aggregate = MiniAppDiagnosticDailyAggregate.objects.get()
        self.assertEqual(aggregate.session_count, 1)
        self.assertEqual(aggregate.classification, MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT)

    @override_settings(SENTRY_ENVIRONMENT='production')
    def test_alert_threshold_uses_seven_day_segmented_baseline(self):
        user = get_user_model().objects.create_user(username='alert-officer')
        now = timezone.now()

        def make_session(classification, age):
            item = MiniAppDiagnosticSession.objects.create(
                client_session_uuid=uuid.uuid4(), actor=user, workflow='jawabu_portal',
                surface='portal', platform='android', release='release-alert',
                classification=classification,
            )
            MiniAppDiagnosticSession.objects.filter(pk=item.pk).update(started_at=now - age)
            item.refresh_from_db()
            return item

        make_session(MiniAppDiagnosticSession.CLASSIFICATION_ACTIVE, timedelta(days=8))
        for index in range(20):
            make_session(
                MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT if index == 0 else MiniAppDiagnosticSession.CLASSIFICATION_ACTIVE,
                timedelta(days=2, minutes=index),
            )
        current = None
        for index in range(20):
            current = make_session(
                MiniAppDiagnosticSession.CLASSIFICATION_ABRUPT if index < 5 else MiniAppDiagnosticSession.CLASSIFICATION_ACTIVE,
                timedelta(minutes=10, seconds=index),
            )

        snapshot = abrupt_rate_alert_snapshot(current, now=now)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot['platform'], 'android')
        self.assertEqual(snapshot['window_abrupt'], 5)
        self.assertEqual(snapshot['window_sessions'], 20)


@override_settings(
    MINIAPP_DIAGNOSTICS_ENABLED=True,
    SENTRY_BROWSER_DSN='https://public@example.invalid/1',
)
class MiniAppDiagnosticTemplateTests(TestCase):
    def test_all_staff_miniapps_load_shared_diagnostics_but_public_signing_does_not(self):
        request = RequestFactory().get('/')
        batch = SimpleNamespace(import_kind='farmup')
        templates = {
            'base_shell.html': {'active_screen': 'dashboard'},
            'complaint_cases/app.html': {'group_id': ''},
            'loan_origination/app.html': {},
            'order_approval/form.html': {'location_catalog': {}},
            'fca_review/review.html': {'batch': batch, 'batch_json': '{}'},
            'jawabu_farmers/review.html': {'batch': batch, 'batch_json': '{}'},
            'spin/form.html': {'form_json': '{}'},
            'tat_tracker/app.html': {'group_id': '', 'token': '', 'task_token': ''},
        }
        for template_name, context in templates.items():
            with self.subTest(template_name=template_name):
                html = render_to_string(template_name, context, request=request)
                self.assertIn('miniapp/diagnostics.js', html)
                self.assertIn('vendor-sentry-browser-10.55.0.bundle.tracing.min.js', html)

        signing_html = render_to_string('loan_origination/sign.html', {}, request=request)
        self.assertNotIn('miniapp/diagnostics.js', signing_html)
