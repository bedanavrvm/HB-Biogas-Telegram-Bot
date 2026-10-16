import copy
import io
import json
import uuid
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image

from . import services
from .catalog import APPS, PATTERNS, current_manifest, digest, inventory, sources
from .models import ReviewDecision, ReviewRevision, StandardRelease


def screenshot():
    content = io.BytesIO()
    Image.new('RGB', (360, 740), 'white').save(content, format='PNG')
    return SimpleUploadedFile('synthetic.png', content.getvalue(), content_type='image/png')


@override_settings(UI_DESIGN_LAB_ENABLED=True)
class DesignReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser('synthetic-designer', '', 'test-only')
        cls.staff = get_user_model().objects.create_user('synthetic-staff', is_staff=True)
        cls.manifests = {key: current_manifest(key) for key in PATTERNS}

    def setUp(self):
        self.client.force_login(self.actor)
        self.enterContext(patch('ui_review.services.current_manifest', side_effect=lambda key: copy.deepcopy(self.manifests[key])))
        self.storage = self.enterContext(patch('core.services.order_approval.GoogleDriveMediaStorage'))
        self.storage.return_value.upload.return_value = ('synthetic-private-file', '')

    def revision(self, key='cards'):
        return services.snapshot(key, digest(self.manifests[key]), self.actor)

    def evidence(self, revision, variant='tat'):
        return services.attach_evidence(revision, self.actor, screenshot(), variant=variant, theme='light', state='one', kind='browser', font_verified=True)

    def decision(self, revision, action='defer', **payload):
        return services.decide(revision, self.actor, decision=action, payload={'reason':'Synthetic reviewer decision', **payload}, request_key=uuid.uuid4())

    def test_default_gate_and_no_anonymous_catalogue_or_evidence(self):
        with override_settings(UI_DESIGN_LAB_ENABLED=False):
            self.assertEqual(self.client.get('/ui-lab/').status_code, 404)
            self.assertEqual(self.client.get('/ui-lab/api/catalogue/').status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get('/ui-lab/').status_code, 200)
        self.assertEqual(self.client.get('/ui-lab/api/catalogue/').status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/ui-lab/api/catalogue/').status_code, 403)
        with self.assertRaises(ValidationError):
            services.snapshot('cards', digest(self.manifests['cards']), self.staff)

    def test_launcher_entry_requires_enabled_lab_and_active_superuser(self):
        from core.services.miniapp_launcher import available_apps
        self.assertIn('design_lab', {item['key'] for item in available_apps(self.actor)})
        self.assertNotIn('design_lab', {item['key'] for item in available_apps(self.staff)})
        with override_settings(UI_DESIGN_LAB_ENABLED=False):
            self.assertNotIn('design_lab', {item['key'] for item in available_apps(self.actor)})
        self.actor.is_active = False
        self.assertEqual(available_apps(self.actor), [])

    def test_browser_session_writes_require_csrf_and_invalid_telegram_never_falls_back(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        body = {'pattern':'cards', 'fingerprint':digest(self.manifests['cards'])}
        self.assertEqual(client.post('/ui-lab/api/revisions/', body, content_type='application/json').status_code, 403)
        client.get('/ui-lab/')
        self.assertEqual(client.post('/ui-lab/api/revisions/', body, content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value).status_code, 200)
        with patch('ui_review.views.authenticate', return_value=None):
            self.assertEqual(client.get('/ui-lab/api/catalogue/', HTTP_X_TELEGRAM_INIT_DATA='invalid').status_code, 403)
        client.logout()
        with patch('ui_review.views.authenticate', return_value=self.actor):
            self.assertEqual(client.get('/ui-lab/api/catalogue/', HTTP_X_TELEGRAM_INIT_DATA='mock-verified').status_code, 200)

    def test_snapshot_is_source_bound_and_idempotent(self):
        first = self.revision()
        self.assertEqual(self.revision().pk, first.pk)
        self.assertEqual(ReviewRevision.objects.count(), 1)
        self.assertFalse(first.manifest['migration_authorized'])
        with self.assertRaises(ValidationError):
            services.snapshot('cards', 'stale-source', self.actor)
        first.pattern = 'forms'
        with self.assertRaises(ValidationError):
            first.save()
        self.assertFalse(admin.site._registry[ReviewRevision].has_delete_permission(type('Request', (), {'user':self.actor})()))

    def test_adopt_with_changes_and_device_result_do_not_approve(self):
        revision = self.revision()
        first = self.decision(revision, 'changes', variant='tat')
        self.decision(revision, 'device', device_result='Native check not yet run')
        self.assertEqual(services.latest_design_decision(revision).pk, first.pk)
        self.assertEqual(revision.decisions.count(), 2)
        self.assertFalse(StandardRelease.objects.exists())

    def test_approval_requires_selected_evidence_review_and_verified_font(self):
        revision = self.revision()
        with self.assertRaisesMessage(ValidationError, 'Attach a screenshot'):
            self.decision(revision, 'adopt', variant='tat', reviewed=True)
        revision = self.evidence(revision)
        with self.assertRaisesMessage(ValidationError, 'Confirm that'):
            self.decision(revision, 'adopt', variant='tat', reviewed='false')
        self.decision(revision, 'adopt', variant='tat', reviewed=True)
        self.assertEqual(services.latest_design_decision(revision).decision, 'adopt')
        self.assertEqual(self.storage.return_value.upload.call_count, 1)

    def test_decision_retry_preserves_one_event_and_rejects_changed_meaning(self):
        revision = self.revision()
        key = uuid.uuid4()
        arguments = {'decision':'defer', 'payload':{'reason':'Not reviewed yet'}, 'request_key':key}
        first = services.decide(revision, self.actor, **arguments)
        self.assertEqual(services.decide(revision, self.actor, **arguments).pk, first.pk)
        arguments['payload'] = {'reason':'Different meaning'}
        with self.assertRaises(ValidationError):
            services.decide(revision, self.actor, **arguments)
        self.assertEqual(ReviewDecision.objects.count(), 1)

    def test_source_changes_leave_history_but_prevent_current_approval(self):
        revision = self.evidence(self.revision())
        self.decision(revision, 'adopt', variant='tat', reviewed=True)
        modified = copy.deepcopy(self.manifests['cards'])
        modified['fixture_version'] = 'changed-source'
        with patch('ui_review.services.current_manifest', return_value=modified):
            with self.assertRaisesMessage(ValidationError, 'source changed'):
                self.decision(revision, 'adopt', variant='tat', reviewed=True)
        self.assertEqual(revision.decisions.count(), 1)

    def test_evidence_is_private_hash_verified_and_duplicates_do_not_upload_again(self):
        original = self.revision()
        revision = self.evidence(original)
        self.assertEqual(self.evidence(revision).pk, revision.pk)
        self.assertEqual(self.evidence(original).pk, revision.pk)
        self.assertEqual(self.storage.return_value.upload.call_count, 1)
        content = self.storage.return_value.upload.call_args.args[0]
        self.storage.return_value.download.return_value = content
        url = f'/ui-lab/api/revisions/{revision.pk}/evidence/0/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)
        self.assertIn('no-store', response['Cache-Control'])
        self.storage.return_value.download.return_value = b'corrupted'
        self.assertEqual(self.client.get(url).status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_review_queue_status_tracks_latest_decision_and_changed_source(self):
        def status():
            data = self.client.get('/ui-lab/api/catalogue/').json()
            return next(item['review_status'] for item in data['patterns'] if item['key'] == 'cards')
        self.assertEqual(status(), 'unreviewed')
        revision = self.revision()
        self.decision(revision, 'changes', variant='tat')
        self.assertEqual(status(), 'changes')
        self.decision(revision, 'device', device_result='Native check pending')
        self.assertEqual(status(), 'changes')
        with patch('ui_review.views.inventory', return_value=[{'key':'cards','fingerprint':'changed'}]):
            self.assertEqual(status(), 'stale')

    def test_wrong_file_and_storage_failure_do_not_create_a_successor(self):
        revision = self.revision()
        with self.assertRaises(ValidationError):
            services.attach_evidence(revision, self.actor, SimpleUploadedFile('bad.png', b'not-an-image'), variant='tat', theme='light', state='one', kind='browser', font_verified=False)
        self.storage.return_value.upload.side_effect = RuntimeError('Synthetic outage')
        response = self.client.post(f'/ui-lab/api/revisions/{revision.pk}/evidence/', {'screenshot':screenshot(), 'variant':'tat', 'theme':'light', 'state':'one', 'kind':'browser', 'synthetic_only':'true'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(ReviewRevision.objects.count(), 1)
        self.assertFalse(ReviewDecision.objects.exists())

    def test_original_app_scenes_have_network_and_native_guards(self):
        for app in APPS:
            response = self.client.get(f'/ui-lab/api/scenes/{app}/queue/')
            self.assertEqual(response.status_code, 200, app)
            self.assertIn("connect-src 'none'", response['Content-Security-Policy'])
            self.assertIn('camera=()', response['Permissions-Policy'])
            self.assertContains(response, 'ui_review/scene_fixture.js')
            self.assertContains(response, 'Content-Security-Policy')
            self.assertNotContains(response, 'synthetic-designer')
        self.assertContains(self.client.get('/ui-lab/api/scenes/portal/detail/'), 'data:text/javascript;base64,')
        self.assertEqual(self.client.get('/ui-lab/api/scenes/unknown/queue/').status_code, 404)

    def test_no_unapproved_standard_can_be_prepared(self):
        self.revision('foundations')
        with self.assertRaises(ValidationError):
            services.prepare_release(self.actor, uuid.uuid4())
        self.assertFalse(StandardRelease.objects.exists())

    def test_reviewed_release_is_immutable_and_does_not_authorize_phase_six(self):
        for key in PATTERNS:
            revision = self.revision(key)
            if key == 'foundations':
                revision = self.evidence(revision, 'compact')
                self.decision(revision, 'approve', variant='compact', reviewed=True)
            else:
                self.decision(revision)
        key = uuid.uuid4()
        release = services.prepare_release(self.actor, key)
        self.assertEqual(services.prepare_release(self.actor, key).pk, release.pk)
        self.assertFalse(release.manifest['migration_authorized'])
        self.assertEqual(release.version, 1)
        response = self.client.get(f'/ui-lab/api/releases/{release.pk}/export/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json.loads(response.content)['manifest']['migration_authorized'])


class DesignInventoryTests(TestCase):
    def test_source_hash_ignores_only_equivalent_text_line_endings(self):
        from .fingerprints import source_digest
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.js'
            path.write_bytes(b'first\r\nsecond\n')
            first = source_digest(path)
            path.write_bytes(b'first\nsecond\n')
            self.assertEqual(source_digest(path), first)
            path.write_bytes(b'changed\nsecond\n')
            self.assertNotEqual(source_digest(path), first)

    def test_four_apps_have_distinct_dependency_sets_and_no_production_candidate_loads(self):
        self.assertEqual(set(APPS), {'portal','tat','complaints','origination'})
        items = inventory()
        self.assertGreaterEqual(len(items), 30)
        sets = {app: {item['path'] for item in sources(app)} for app in APPS}
        self.assertNotEqual(sets['tat'], sets['origination'])
        for app, config in APPS.items():
            from .catalog import ROOT
            self.assertNotIn('ui_review/tokens.css', (ROOT / config['template']).read_text(encoding='utf-8'))
