import hashlib
import json
import unittest

from scripts.check_ui_standard import REGISTRY, ROOT, check_registry, check_release, source_hash


class UiStandardGateTests(unittest.TestCase):
    def test_current_source_and_changed_source_have_distinct_verdicts(self):
        path = 'core/static/miniapp/components.css'
        digest = source_hash(path)
        registry = {'migration_authorized':False, 'legacy_sources':[{'path':path, 'sha256':digest}], 'operational_templates':[]}
        self.assertEqual(check_registry(registry), [])
        registry['legacy_sources'][0]['sha256'] = 'stale'
        self.assertTrue(check_registry(registry))
        registry['changes'] = [{'path':path,'sha256':digest,'review_reference':'synthetic-review-id','reason':'Synthetic nonvisual exception probe'}]
        self.assertEqual(check_registry(registry), [])

    def test_manifest_tampering_and_unreviewed_actions_fail(self):
        manifest = {'selections':[{'pattern':'cards','action':'changes','sources':[]}]}
        value = {'manifest':manifest,'fingerprint':hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()}
        self.assertTrue(check_release(value))
        manifest['selections'][0].update(action='defer',decision='synthetic-event')
        self.assertTrue(check_release(value))

    def test_new_ui_files_cannot_escape_the_source_ratchet(self):
        registry = {'migration_authorized':False, 'legacy_sources':[], 'source_roots':['origination/templates/loan_origination'], 'operational_templates':[]}
        self.assertTrue(any('new UI source' in error for error in check_registry(registry)))

    def test_empty_release_is_not_an_approved_standard(self):
        manifest = {'selections':[], 'governed_modules':[], 'migration_authorized':False}
        value = {'manifest':manifest,'fingerprint':hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()}
        self.assertTrue(check_release(value))

    def test_reviewed_release_checks_sources_without_live_database(self):
        source = 'ui_review/static/ui_review/tokens.css'
        keys = json.loads(REGISTRY.read_text(encoding='utf-8'))['pattern_keys']
        selections = [{'pattern':key, 'action':'approve' if key=='foundations' else 'defer', 'decision':'synthetic-review-id',
                       'sources':[{'path':source,'sha256':source_hash(source)}] if key=='foundations' else []} for key in keys]
        manifest = {'selections':selections, 'governed_modules':[], 'migration_authorized':False}
        value = {'manifest':manifest,'fingerprint':hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()}
        self.assertEqual(check_release(value), [])
