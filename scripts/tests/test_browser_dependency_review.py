"""Offline safety/evidence contracts; never download or install npm packages."""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2] / 'codebase-analysis-docs/assets/review_browser_dependencies.py'
SPEC = importlib.util.spec_from_file_location('browser_dependency_review', SOURCE)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def archive(extra=None, license_value='MIT', license_text='Synthetic MIT licence fixture', root='package'):
    files = [(f'{root}/package.json', json.dumps({'name': 'synthetic-package', 'version': '1.2.3',
              'license': license_value, 'scripts': {'postinstall': 'DO_NOT_EXECUTE'}}).encode())]
    if license_text is not None:
        files.append((f'{root}/LICENSE', license_text.encode()))
    files.extend(extra or [])
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz') as target:
        for name, content in files:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            target.addfile(info, io.BytesIO(content))
    return result.getvalue()


def integrity(raw):
    return 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode()


class BrowserDependencyReviewTests(unittest.TestCase):
    def test_checked_in_snapshot_binds_exact_graph_and_generated_markdown_offline(self):
        assets = SOURCE.parent
        candidate = json.loads((assets / 'BROWSER_DEPENDENCY_CANDIDATE.json').read_bytes())
        lock = json.loads((assets / 'BROWSER_DEPENDENCY_REVIEW_LOCK.json').read_bytes())
        report = json.loads((assets / 'BROWSER_DEPENDENCY_REVIEW.json').read_bytes())
        with patch.object(review, 'build_opener', side_effect=AssertionError('Network forbidden')):
            review.verify_report(candidate, lock, report)
        self.assertEqual((assets / 'BROWSER_DEPENDENCY_REVIEW.md').read_text(encoding='utf-8'), review.render(report))

    def test_only_public_registry_https_without_credentials_query_or_port(self):
        valid = 'https://registry.npmjs.org/synthetic-package/-/synthetic-package-1.2.3.tgz'
        self.assertEqual(review.registry_url(valid), valid)
        for value in ('http://registry.npmjs.org/a', 'https://registry.npmjs.org.evil.invalid/a',
                      'https://user:password@registry.npmjs.org/a', 'https://registry.npmjs.org/a?token=bad',
                      'file:///tmp/a', 'https://registry.npmjs.org:8443/a', 'https://registry.npmjs.org/a#bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                review.registry_url(value)

    def test_redirects_never_follow_a_new_location(self):
        with self.assertRaises(ValueError):
            review.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid/')

    def test_integrity_requires_strong_hash_and_rejects_tampered_bytes(self):
        raw = archive()
        review.verify_integrity(raw, integrity(raw))
        for value in ('', 'sha1-AAAA', 'sha512-!!', integrity(b'different')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                review.verify_integrity(raw, value)
        weaker = 'sha256-' + base64.b64encode(hashlib.sha256(raw).digest()).decode()
        with self.assertRaises(ValueError):
            review.verify_integrity(raw, integrity(b'different') + ' ' + weaker)

    def test_archive_metadata_licence_hash_assets_and_scripts_are_data(self):
        raw = archive([('package/font.woff2', b'synthetic'), ('package/nested/package.json', b'{}')])
        result = review.inspect_archive(raw, 'synthetic-package', '1.2.3')
        self.assertEqual(result['archive_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['declared_license'], 'MIT')
        self.assertEqual(result['lifecycle_scripts'], {'postinstall': 'DO_NOT_EXECUTE'})
        self.assertEqual(result['license_files'][0]['sha256'], hashlib.sha256(b'Synthetic MIT licence fixture').hexdigest())
        self.assertIn('shipped_assets_require_review', result['flags'])
        self.assertIn('nested_package_metadata_requires_review', result['flags'])
        self.assertNotIn('DO_NOT_EXECUTE', review.render({'candidate_sha256': 'a', 'lock_sha256': 'b',
            'summary': {'lock_entries': 0, 'unique_artifacts': 0, 'inspected_artifacts': 0, 'errors': 0}, 'artifacts': []}))

    def test_identity_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):
            review.inspect_archive(archive(), 'other-package', '1.2.3')

    def test_third_party_notices_and_named_licence_directory_files_are_inventoried(self):
        result = review.inspect_archive(archive([('package/THIRD-PARTY-NOTICES.txt', b'Synthetic third-party notice'),
            ('package/licenses/MIT.txt', b'Synthetic nested licence')]), 'synthetic-package', '1.2.3')
        paths = {row['path'] for row in result['license_files']}
        self.assertIn('package/THIRD-PARTY-NOTICES.txt', paths)
        self.assertIn('package/licenses/MIT.txt', paths)

    def test_traversal_absolute_backslash_and_duplicate_members_rejected(self):
        for name in ('../LICENSE', '/package/LICENSE', 'package/../LICENSE', 'package\\LICENSE',
                     'package/LICENSE', 'package/./LICENSE', 'different-root/LICENSE'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                review.inspect_archive(archive([(name, b'bad')]), 'synthetic-package', '1.2.3')

    def test_single_definitelytyped_style_root_with_spaces_is_not_an_extraction_path(self):
        result = review.inspect_archive(archive(root='synthetic v18.3'), 'synthetic-package', '1.2.3')
        self.assertEqual(result['license_files'][0]['path'], 'synthetic v18.3/LICENSE')

    def test_size_and_member_limits_fail_closed(self):
        raw = archive()
        for setting in ('MAX_ARCHIVE', 'MAX_UNPACKED', 'MAX_TEXT', 'MAX_MEMBERS'):
            with self.subTest(setting=setting), patch.object(review, setting, 1), self.assertRaises(ValueError):
                review.inspect_archive(raw, 'synthetic-package', '1.2.3')

    def test_missing_licence_and_restricted_terms_are_not_cleared(self):
        result = review.inspect_archive(archive(license_text=None), 'synthetic-package', '1.2.3')
        self.assertIn('no_shipped_licence_file_found', result['flags'])
        result = review.inspect_archive(archive(license_value='SEE LICENSE IN terms',
            license_text='Atlassian Design System License'), 'synthetic-package', '1.2.3')
        self.assertIn('declared_licence_requires_review', result['flags'])
        self.assertIn('licence_text_requires_review', result['flags'])

    def test_expression_and_legacy_object_handling_is_not_legal_approval(self):
        self.assertEqual(review.license_expression({'type': 'MIT'}), 'MIT')
        self.assertFalse(review.needs_license_review('(MIT OR Apache-2.0)'))
        for value in ('', 'LicenseRef-Proprietary', 'Apache-2.0 WITH LLVM-exception', 'UNLICENSED'):
            self.assertTrue(review.needs_license_review(value))

    def test_offline_cache_reverified_and_missing_cache_never_downloads(self):
        raw = archive()
        row = {'name': 'synthetic-package', 'version': '1.2.3', 'resolved':
               'https://registry.npmjs.org/synthetic-package/-/synthetic-package-1.2.3.tgz', 'integrity': integrity(raw)}
        with TemporaryDirectory() as directory, patch.object(review, 'build_opener', side_effect=AssertionError('Network forbidden')):
            cache = Path(directory)
            with self.assertRaises(ValueError):
                review.fetch_archive(row, cache)
            target = cache / (review.digest(row['resolved'].encode()) + '.tgz')
            target.write_bytes(raw)
            self.assertEqual(review.fetch_archive(row, cache)['declared_license'], 'MIT')
            target.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                review.fetch_archive(row, cache)

    def test_lock_candidate_requires_exact_direct_versions_registry_and_integrity(self):
        candidate = {'dependencies': {'synthetic-package': '1.2.3'}}
        entry = {'version': '1.2.3', 'resolved': 'https://registry.npmjs.org/a.tgz', 'integrity': integrity(b'')}
        lock = {'lockfileVersion': 3, 'packages': {'': candidate, 'node_modules/synthetic-package': entry}}
        self.assertEqual(review.lock_records(lock, candidate)[0]['name'], 'synthetic-package')
        for mutation in ({'link': True}, {'resolved': 'https://other.invalid/a.tgz'}, {'integrity': ''}, {'version': '1.2.4'}):
            invalid = {**lock, 'packages': {'': candidate, 'node_modules/synthetic-package': {**entry, **mutation}}}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                review.lock_records(invalid, candidate)
        with self.assertRaises(ValueError):
            review.lock_records(lock, {'dependencies': {'synthetic-package': '^1.2.3'}})

    def test_scoped_nested_package_names_are_preserved(self):
        lock = {'lockfileVersion': 3, 'packages': {'': {},
            'node_modules/parent/node_modules/@scope/child': {'version': '1.0.0',
                'resolved': 'https://registry.npmjs.org/a.tgz', 'integrity': integrity(b'')}}}
        self.assertEqual(review.lock_records(lock, {})[0]['name'], '@scope/child')

    def test_snapshot_binding_is_checkout_independent_but_rejects_changes(self):
        candidate = {'dependencies': {'synthetic-package': '1.2.3'}}
        entry = {'version': '1.2.3', 'resolved': 'https://registry.npmjs.org/a.tgz', 'integrity': integrity(b'')}
        lock = {'lockfileVersion': 3, 'packages': {'': candidate, 'node_modules/synthetic-package': entry}}
        report = {'schema_version': 1, 'review_status': 'human_review_required_not_installation_approval',
            'candidate_sha256': review.json_digest(candidate), 'lock_sha256': review.json_digest(lock),
            'summary': {'errors': 0, 'lock_entries': 1, 'unique_artifacts': 1, 'inspected_artifacts': 1},
            'artifacts': [{'name': 'synthetic-package', **entry, 'paths': ['node_modules/synthetic-package'],
                           'inspection': {'archive_sha256': 'a' * 64}}]}
        review.verify_report(json.loads(json.dumps(candidate, indent=4)), lock, report)
        for change in ({'review_status': 'approved'}, {'candidate_sha256': 'bad'}, {'artifacts': []},
                       {'summary': {**report['summary'], 'errors': 1}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                review.verify_report(candidate, lock, {**report, **change})


if __name__ == '__main__':
    unittest.main()
