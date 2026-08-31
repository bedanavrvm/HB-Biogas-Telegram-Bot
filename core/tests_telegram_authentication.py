"""Cross-workflow tests for canonical Telegram Mini App authentication."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.api.portal_views import validate_portal_telegram_init_data
from core.models import AccessGrant, GroupSheetConfiguration, UserProfile
from core.production import MINIAPP_AUTH_SETTINGS, TELEGRAM_AUTH_AGE_SETTINGS
from core.services.group_config import GroupRegistry
from core.services.order_approval import validate_telegram_webapp_init_data
from core.services.spin_credit import validate_spin_telegram_webapp_init_data
from core.services.tat_tracker import validate_tat_telegram_webapp_init_data
from core.services.telegram_auth import validate_telegram_init_data as validate_legacy_init_data
from core.services.telegram_identity import (
    TELEGRAM_AUTH_MAX_AGE_LIMIT_SECONDS,
    TelegramAuthenticationError,
    validate_telegram_init_data,
)


BOT_TOKEN = 'phase-three-test-token'
_MISSING_USER = object()


def signed_init_data(*, auth_date=None, user=_MISSING_USER, include_hash=True) -> str:
    pairs = {'auth_date': str(auth_date if auth_date is not None else int(time.time()))}
    if user is not _MISSING_USER:
        pairs['user'] = user if isinstance(user, str) else json.dumps(user, separators=(',', ':'))
    if include_hash:
        check = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
        secret = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


@override_settings(
    TELEGRAM_BOT_TOKEN=BOT_TOKEN,
    TELEGRAM_AUTH_MAX_AGE_SECONDS=86400,
    PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    COMPLAINT_CASES_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    SECURE_SSL_REDIRECT=False,
)
class CanonicalTelegramAuthenticationTests(TestCase):
    def setUp(self):
        GroupRegistry._instance = None

    def tearDown(self):
        GroupRegistry._instance = None

    def test_valid_canonical_payload_succeeds_in_every_workflow_adapter(self):
        init_data = signed_init_data(user={
            'id': 731001, 'username': 'canonical_user', 'first_name': 'Canonical',
        })
        payload, identity = validate_telegram_init_data(init_data)
        self.assertEqual(identity.telegram_id, '731001')
        self.assertIn('user', payload)

        legacy_results = {
            'complaint_cases': validate_legacy_init_data(init_data),
            'portal': validate_portal_telegram_init_data(init_data),
            'spin': validate_spin_telegram_webapp_init_data(init_data),
            'order_approval': validate_telegram_webapp_init_data(init_data),
        }
        for workflow, (valid, error, workflow_payload) in legacy_results.items():
            with self.subTest(workflow=workflow):
                self.assertTrue(valid, error)
                self.assertIn('user', workflow_payload)
        valid, error, tat_user = validate_tat_telegram_webapp_init_data(init_data)
        self.assertTrue(valid, error)
        self.assertEqual(str(tat_user['id']), '731001')

    def test_unsigned_expired_malformed_missing_and_future_payloads_fail(self):
        invalid_payloads = {
            'unsigned': signed_init_data(user={'id': 1}, include_hash=False),
            'expired': signed_init_data(auth_date=1, user={'id': 1}),
            'malformed-user': signed_init_data(user='{not-json'),
            'missing-user': signed_init_data(),
            'missing-user-id': signed_init_data(user={'username': 'no_id'}),
            'future-dated': signed_init_data(
                auth_date=int(time.time()) + 300, user={'id': 1},
            ),
        }
        for case, init_data in invalid_payloads.items():
            with self.subTest(case=case), self.assertRaises(TelegramAuthenticationError):
                validate_telegram_init_data(init_data)
            workflow_results = {
                'complaint_cases': validate_legacy_init_data(init_data),
                'portal': validate_portal_telegram_init_data(init_data),
                'tat_tracker': validate_tat_telegram_webapp_init_data(init_data),
                'spin': validate_spin_telegram_webapp_init_data(init_data),
                'order_approval': validate_telegram_webapp_init_data(init_data),
            }
            for workflow, (valid, _error, _payload) in workflow_results.items():
                with self.subTest(case=case, workflow=workflow):
                    self.assertFalse(valid)

    def test_authentication_age_must_be_positive_and_bounded(self):
        init_data = signed_init_data(user={'id': 1})
        for max_age in (0, -1, TELEGRAM_AUTH_MAX_AGE_LIMIT_SECONDS + 1):
            with self.subTest(max_age=max_age), self.assertRaises(TelegramAuthenticationError):
                validate_telegram_init_data(init_data, max_age_seconds=max_age)

    def test_valid_identity_without_access_grant_remains_unauthorized(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-100-phase-three-complaints',
            sheet_id='test-sheet', sheet_name='Complaints', workflow={'type': 'case'},
        )
        user = get_user_model().objects.create_user(username='valid-without-access')
        UserProfile.objects.create(
            user=user, telegram_id='731002', telegram_username='valid_without_access',
        )

        response = self.client.post(
            reverse('complaint_cases_bootstrap'),
            data=json.dumps({'group_id': group.group_id}),
            content_type='application/json',
            HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(user={
                'id': 731002, 'username': 'valid_without_access',
            }),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'permission_denied')

    @override_settings(
        DEBUG=False,
        RUNNING_TESTS=True,
        COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=False,
    )
    def test_explicit_test_mode_can_use_logged_in_user_without_unsigned_identity(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-100-phase-three-local',
            sheet_id='test-sheet', sheet_name='Complaints', workflow={'type': 'case'},
        )
        user = get_user_model().objects.create_user(username='local-complaint-user')
        UserProfile.objects.create(user=user, telegram_username='local_user')
        AccessGrant.objects.create(
            user=user, workflow='complaint_cases', role='OFFICER',
            group_configuration=group,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse('complaint_cases_bootstrap'),
            data=json.dumps({'group_id': group.group_id}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)

    @override_settings(
        DEBUG=False,
        RUNNING_TESTS=False,
        ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False,
    )
    def test_disabled_flag_does_not_create_a_production_runtime_bypass(self):
        valid, error, payload = validate_telegram_webapp_init_data('')
        self.assertFalse(valid)
        self.assertIn('local or test runtime', error)
        self.assertEqual(payload, {})

    @override_settings(
        DEBUG=False,
        RUNNING_TESTS=False,
        SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=False,
    )
    def test_disabled_spin_flag_does_not_grant_production_capabilities(self):
        from core.api.views import _spin_user_capabilities

        self.assertEqual(_spin_user_capabilities({}), set())

    def test_every_authentication_flag_and_age_has_a_deployment_check(self):
        from core.checks import portal_authentication_check

        baseline = {name: True for _surface, name in MINIAPP_AUTH_SETTINGS}
        baseline.update({name: 86400 for _surface, name in TELEGRAM_AUTH_AGE_SETTINGS})
        for expected_index, (_surface, setting_name) in enumerate(
            MINIAPP_AUTH_SETTINGS, start=1,
        ):
            configured = {**baseline, 'DEBUG': False, setting_name: False}
            with self.subTest(setting=setting_name), self.settings(**configured):
                self.assertIn(
                    f'core.E{expected_index:03d}',
                    {issue.id for issue in portal_authentication_check(None)},
                )
        for expected_index, (_surface, setting_name) in enumerate(
            TELEGRAM_AUTH_AGE_SETTINGS, start=6,
        ):
            configured = {**baseline, 'DEBUG': False, setting_name: 0}
            with self.subTest(setting=setting_name), self.settings(**configured):
                self.assertIn(
                    f'core.E{expected_index:03d}',
                    {issue.id for issue in portal_authentication_check(None)},
                )
