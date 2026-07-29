from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from core.models import MiniAppDraft
from core.services.miniapp_drafts import MiniAppDraftConflict, MiniAppDraftError, get_draft, save_draft


class MiniAppDraftServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('draft-owner', password='test-password')

    def test_save_updates_revision_and_isolated_per_user(self):
        first = save_draft(
            user=self.user,
            workflow='spin_request',
            context_key='group-1',
            payload={'customer_name': 'Example Customer'},
            expected_revision=None,
        )
        updated = save_draft(
            user=self.user,
            workflow='spin_request',
            context_key='group-1',
            payload={'customer_name': 'Updated Customer'},
            expected_revision=first.revision,
        )

        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.payload['customer_name'], 'Updated Customer')
        other_user = get_user_model().objects.create_user('second-draft-owner', password='test-password')
        save_draft(
            user=other_user,
            workflow='spin_request',
            context_key='group-1',
            payload={'customer_name': 'Separate Customer'},
            expected_revision=None,
        )
        self.assertEqual(MiniAppDraft.objects.count(), 2)

    def test_draft_rejects_attachment_payloads(self):
        with self.assertRaises(MiniAppDraftError):
            save_draft(
                user=self.user,
                workflow='spin_request',
                context_key='group-1',
                payload={'customer_name': 'Example Customer', 'spin_report': 'data:application/pdf;base64,abc'},
                expected_revision=None,
            )

    def test_stale_revision_never_overwrites_another_device(self):
        saved = save_draft(
            user=self.user,
            workflow='fca_review',
            context_key='batch-1',
            payload={'rows': [{'Customer Name': 'One'}]},
            expected_revision=None,
        )
        save_draft(
            user=self.user,
            workflow='fca_review',
            context_key='batch-1',
            payload={'rows': [{'Customer Name': 'Two'}]},
            expected_revision=saved.revision,
        )

        with self.assertRaises(MiniAppDraftConflict):
            save_draft(
                user=self.user,
                workflow='fca_review',
                context_key='batch-1',
                payload={'rows': [{'Customer Name': 'Stale'}]},
                expected_revision=saved.revision,
            )

    def test_expired_draft_is_not_restored(self):
        MiniAppDraft.objects.create(
            user=self.user,
            workflow='farmup_review',
            context_key='batch-1',
            payload={'rows': []},
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        self.assertIsNone(get_draft(user=self.user, workflow='farmup_review', context_key='batch-1'))
        self.assertFalse(MiniAppDraft.objects.exists())


class MiniAppDraftApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('draft-api-owner', password='test-password')
        self.url = reverse('miniapp_draft', args=['fca_review', 'batch-1'])

    @patch('core.api.views._miniapp_draft_context')
    def test_api_load_save_and_clear(self, context):
        context.return_value = self.user, ''
        saved = self.client.post(
            self.url,
            data={'payload': {'rows': [{'Customer Name': 'Example'}]}},
            content_type='application/json',
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['draft']['revision'], 1)

        loaded = self.client.get(self.url)
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()['draft']['payload']['rows'][0]['Customer Name'], 'Example')

        cleared = self.client.delete(self.url)
        self.assertEqual(cleared.status_code, 200)
        self.assertFalse(MiniAppDraft.objects.exists())

    @patch('core.api.views._miniapp_draft_context')
    def test_api_reports_revision_conflicts(self, context):
        context.return_value = self.user, ''
        first = self.client.post(self.url, data={'payload': {'rows': []}}, content_type='application/json').json()
        stale = self.client.post(
            self.url,
            data={'payload': {'rows': []}, 'revision': first['draft']['revision'] + 1},
            content_type='application/json',
        )
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(stale.json()['conflict'])

    def test_api_never_accepts_a_draft_without_verified_context(self):
        response = self.client.post(
            self.url,
            data={'payload': {'rows': []}},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(MiniAppDraft.objects.exists())
