"""Inspect a review-only npm lock without installing or executing package code.

Standard library only. Network is opt-in, registry-only, integrity-checked and
bounded. Archives are never extracted. Output is evidence, NOT legal clearance.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener


ASSETS = Path(__file__).resolve().parent
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_UNPACKED = 256 * 1024 * 1024
MAX_TEXT = 4 * 1024 * 1024
MAX_MEMBERS = 50000
VERSION = re.compile(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\Z')
LICENSE_FILE = re.compile(r'^(?:.*[._-])?(?:licen[cs]es?|copying|copyright|notices?)(?:[._-].*)?$', re.I)
COMMON = {'MIT', 'Apache-2.0', 'ISC', 'BSD-2-Clause', 'BSD-3-Clause', '0BSD',
          'CC0-1.0', 'Unlicense', 'BlueOak-1.0.0', 'Python-2.0', 'CC-BY-4.0'}
RESTRICTED = re.compile(r'atlassian design (?:guidelines|system) license|all rights reserved.*proprietary|'
                        r'not (?:permitted|licensed) for|non[- ]commercial|business source license|'
                        r'server side public license|licenseref-', re.I | re.S)
ASSET_SUFFIXES = {'.woff', '.woff2', '.ttf', '.otf', '.eot', '.png', '.jpg',
                  '.jpeg', '.gif', '.webp', '.ico', '.svg'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_digest(value):
    # Bind meaning, not Windows/Linux checkout line endings or JSON indentation.
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode())


def verify_report(candidate, lock, report):
    if (report.get('review_status') != 'human_review_required_not_installation_approval'
            or report.get('schema_version') != 1
            or report.get('candidate_sha256') != json_digest(candidate)
            or report.get('lock_sha256') != json_digest(lock)):
        raise ValueError('Review snapshot no longer matches its candidate/lock or held status.')
    expected = {}
    for row in lock_records(lock, candidate):
        key = (row['name'], row['version'], row['resolved'], row['integrity'])
        expected.setdefault(key, []).append(row['path'])
    observed = {}
    for row in report.get('artifacts', []):
        key = (row['name'], row['version'], row['resolved'], row['integrity'])
        if key in observed or 'error' in row or not row.get('inspection'):
            raise ValueError('Duplicate, failed or uninspected review artifact.')
        inspection = row['inspection']
        if not re.fullmatch('[0-9a-f]{64}', inspection.get('archive_sha256', '')):
            raise ValueError('Review artifact has no archive evidence hash.')
        observed[key] = row['paths']
    if expected != observed:
        raise ValueError('Review artifacts do not cover the exact locked graph.')
    summary = report.get('summary', {})
    if (summary.get('errors') != 0 or summary.get('unique_artifacts') != len(expected)
            or summary.get('inspected_artifacts') != len(expected)
            or summary.get('lock_entries') != sum(len(paths) for paths in expected.values())):
        raise ValueError('Review summary is inconsistent.')


def registry_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'registry.npmjs.org'
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.startswith('/')):
        raise ValueError('Only credential-free HTTPS npm registry artifact URLs are allowed.')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Registry artifact redirects are not accepted.')


def verify_integrity(raw, integrity):
    # Verify the strongest supported digest; never accept a weaker matching hash
    # alongside a mismatching stronger one. SHA-1-only locks require review.
    tokens = {}
    for token in integrity.split():
        algorithm, separator, encoded = token.partition('-')
        if separator and algorithm in ('sha512', 'sha384', 'sha256'):
            try:
                tokens.setdefault(algorithm, []).append(base64.b64decode(encoded, validate=True))
            except ValueError:
                raise ValueError('Malformed integrity digest.') from None
    for algorithm in ('sha512', 'sha384', 'sha256'):
        if algorithm in tokens:
            actual = hashlib.new(algorithm, raw).digest()
            if actual not in tokens[algorithm]:
                raise ValueError('Archive integrity mismatch.')
            return
    raise ValueError('A SHA-256-or-stronger integrity digest is required.')


def license_expression(value):
    if isinstance(value, dict):
        return str(value.get('type', ''))
    return value if isinstance(value, str) else ''


def needs_license_review(expression):
    terms = re.findall(r'[A-Za-z0-9.+-]+', expression)
    return not terms or any(term not in COMMON | {'AND', 'OR'} for term in terms)


def lock_records(lock, candidate):
    if lock.get('lockfileVersion') != 3 or not isinstance(lock.get('packages'), dict):
        raise ValueError('A version-3 npm lock with packages is required.')
    direct = {**candidate.get('dependencies', {}), **candidate.get('devDependencies', {})}
    if any(not VERSION.fullmatch(version) for version in direct.values()):
        raise ValueError('Review candidate dependencies must use exact versions.')
    root = lock['packages'].get('', {})
    if (root.get('dependencies', {}) != candidate.get('dependencies', {})
            or root.get('devDependencies', {}) != candidate.get('devDependencies', {})):
        raise ValueError('Lock root does not match the reviewed candidate.')
    records = []
    for path, entry in sorted(lock['packages'].items()):
        if not path:
            continue
        if entry.get('link') or 'node_modules/' not in path:
            raise ValueError('Linked/local dependencies are not supported by this review.')
        name = entry.get('name') or path.rsplit('node_modules/', 1)[1]
        if not isinstance(name, str) or not re.fullmatch(r'(?:@[\w.-]+/)?[\w.-]+', name):
            raise ValueError('Invalid locked package identity.')
        version = entry.get('version', '')
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise ValueError('A locked package has no exact version.')
        registry_url(entry.get('resolved', ''))
        if not entry.get('integrity'):
            raise ValueError('A locked package has no integrity.')
        if path == f'node_modules/{name}' and name in direct and version != direct[name]:
            raise ValueError('Direct dependency version does not match candidate.')
        records.append({
            'path': path, 'name': name, 'version': version,
            'resolved': entry['resolved'], 'integrity': entry['integrity'],
            'lock_license': license_expression(entry.get('license')),
            'dev_only': bool(entry.get('dev')), 'optional': bool(entry.get('optional')),
            'os': entry.get('os', []), 'cpu': entry.get('cpu', []),
            'lock_install_script': bool(entry.get('hasInstallScript')),
        })
    for name in direct:
        if not any(row['path'] == f'node_modules/{name}' for row in records):
            raise ValueError('A direct dependency is absent from the lock.')
    return records


def inspect_archive(raw, expected_name, expected_version):
    """Inspect safe members in memory; package paths never become local paths."""
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('Compressed archive limit exceeded.')
    licenses, assets, nested_packages, native_files, flags = [], [], [], [], []
    package = None
    package_root = None
    total = 0
    names = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for index, member in enumerate(archive, 1):
            parts = PurePosixPath(member.name).parts
            normalized = '/'.join(parts)
            if (index > MAX_MEMBERS or not parts or member.name.startswith('/')
                    or '..' in parts or '\\' in member.name or normalized in names):
                raise ValueError('Unsafe, duplicate or excessive archive members.')
            if package_root is None:
                # DefinitelyTyped legitimately uses roots such as "react v18.3".
                # One safe root plus shipped name/version validation is required;
                # it is never interpreted as a filesystem destination.
                package_root = parts[0]
            if parts[0] != package_root:
                raise ValueError('Multiple archive roots are not supported.')
            names.add(normalized)
            if not member.isfile():
                # No extraction or link dereferencing, even for bundled executables.
                continue
            total += member.size
            if total > MAX_UNPACKED:
                raise ValueError('Uncompressed archive limit exceeded.')
            path = PurePosixPath(member.name)
            if path.suffix.lower() in ASSET_SUFFIXES:
                assets.append({'path': member.name, 'bytes': member.size})
            if path.suffix.lower() in {'.node', '.wasm', '.dll', '.exe', '.so', '.dylib'}:
                native_files.append({'path': member.name, 'bytes': member.size})
            package_manifest = f'{package_root}/package.json'
            if path.name == 'package.json' and normalized != package_manifest:
                nested_packages.append(member.name)
            is_license = (LICENSE_FILE.fullmatch(path.name) is not None
                          or any(part.lower() in ('licenses', 'licences') for part in path.parts[:-1]))
            if normalized != package_manifest and not is_license:
                continue
            if member.size > MAX_TEXT:
                raise ValueError('Metadata/licence text limit exceeded.')
            stream = archive.extractfile(member)
            content = stream.read(MAX_TEXT + 1)
            if len(content) != member.size:
                raise ValueError('Truncated archive metadata.')
            if normalized == package_manifest:
                package = json.loads(content)
            else:
                text = content.decode('utf-8', errors='replace')
                item = {'path': member.name, 'bytes': len(content), 'sha256': digest(content)}
                if RESTRICTED.search(text):
                    item['review_marker'] = True
                    flags.append('licence_text_requires_review')
                licenses.append(item)
    if (not isinstance(package, dict) or package.get('name') != expected_name
            or package.get('version') != expected_version):
        raise ValueError('Shipped package identity does not match lock.')
    scripts = package.get('scripts') or {}
    lifecycle = {key: scripts[key] for key in ('preinstall', 'install', 'postinstall') if key in scripts}
    declared = license_expression(package.get('license'))
    if needs_license_review(declared):
        flags.append('declared_licence_requires_review')
    if not licenses:
        flags.append('no_shipped_licence_file_found')
    if assets:
        flags.append('shipped_assets_require_review')
    if nested_packages:
        flags.append('nested_package_metadata_requires_review')
    bundled = package.get('bundledDependencies', package.get('bundleDependencies', []))
    if bundled:
        flags.append('bundled_dependencies_require_review')
    return {
        'archive_sha256': digest(raw), 'archive_bytes': len(raw),
        'declared_license': declared, 'legacy_licenses': package.get('licenses'),
        'license_files': sorted(licenses, key=lambda row: row['path']),
        'assets': sorted(assets, key=lambda row: row['path']),
        'nested_package_metadata': sorted(nested_packages),
        'native_files': sorted(native_files, key=lambda row: row['path']),
        'bundled_dependencies': bundled,
        'lifecycle_scripts': lifecycle, 'flags': sorted(set(flags)),
        'peer_dependencies': package.get('peerDependencies', {}),
        'engines': package.get('engines', {}),
    }


def fetch_archive(row, cache, fetch=False):
    url = registry_url(row['resolved'])
    path = cache / (digest(url.encode()) + '.tgz')
    if path.is_symlink():
        raise ValueError('Archive cache entries must not be symbolic links.')
    if path.exists():
        if path.stat().st_size > MAX_ARCHIVE:
            raise ValueError('Cached archive limit exceeded.')
        raw = path.read_bytes()
    elif fetch:
        with build_opener(NoRedirect()).open(url, timeout=45) as response:
            raw = response.read(MAX_ARCHIVE + 1)
        if len(raw) > MAX_ARCHIVE:
            raise ValueError('Downloaded archive limit exceeded.')
        verify_integrity(raw, row['integrity'])
        path.write_bytes(raw)
    else:
        raise ValueError('Archive is not cached; network requires --fetch.')
    verify_integrity(raw, row['integrity'])
    return inspect_archive(raw, row['name'], row['version'])


def render(report):
    summary = report['summary']
    lines = ['# Browser dependency review: generated evidence', '',
             '**REVIEW ONLY / NOT APPROVED FOR INSTALLATION.** No package code was executed.', '',
             f"Candidate canonical-JSON SHA-256: `{report['candidate_sha256']}`.",
             f"Lock canonical-JSON SHA-256: `{report['lock_sha256']}`.", '',
             f"{summary['lock_entries']} lock entries; {summary['unique_artifacts']} unique archives; "
             f"{summary['inspected_artifacts']} inspected; {summary['errors']} errors.", '',
             'Runtime/development and optional/platform labels come from the npm lock, '
             'not a measured production bundle. An archive may contain nested/vendor code '
             'or inline assets not fully described by its package metadata.', '',
             'This snapshot is forensic inventory, not an installable compatibility-approved '
             'proposal. Original peer declarations and any resolution overrides require review. '
             'See BROWSER_REACT_ADS_DECISION.md section 5.', '',
             '| Exact package | Scope | Shipped declaration | Licence files | Assets | Review flags |',
             '|---|---|---|---|---|---|']
    for row in report['artifacts']:
        scope = 'development only' if row['dev_only'] else 'runtime dependency graph'
        if row['optional']:
            scope += '; optional/platform'
        inspection = row.get('inspection', {})
        cells = [f"`{row['name']}@{row['version']}`", scope,
                 inspection.get('declared_license', 'NOT INSPECTED'),
                 str(len(inspection.get('license_files', []))), str(len(inspection.get('assets', []))),
                 ', '.join(inspection.get('flags', [])) or row.get('error', 'none detected by this limited scanner')]
        lines.append('| ' + ' | '.join(cell.replace('|', '\\|').replace('\n', ' ') for cell in cells) + ' |')
    lines += ['', '## Interpretation and acceptance', '',
              'Findings: exact archive hashes, licence-file hashes, declared terms, assets, '
              'nested metadata and lifecycle-script commands are in BROWSER_DEPENDENCY_REVIEW.json. '
              'Lifecycle commands were read as data, never executed.', '',
              'Open questions: resolve every flagged/missing/ambiguous licence and asset, '
              'review notice obligations, security and actual build compatibility. A clean '
              'scanner row is not legal or security approval.', '',
              'Next steps: read BROWSER_REACT_ADS_DECISION.md for the human decision, '
              'installation gate and Telegram-safe checklist. No runtime/build/deployment '
              'change is authorized by this report.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock-file', type=Path)
    parser.add_argument('--candidate', type=Path, default=ASSETS / 'BROWSER_DEPENDENCY_CANDIDATE.json')
    parser.add_argument('--cache-dir', type=Path, help='Use an OS temporary directory, not repository storage.')
    parser.add_argument('--check', action='store_true', help='Verify the committed snapshot binding without network/cache.')
    parser.add_argument('--fetch', action='store_true', help='Explicitly allow public npm archive downloads.')
    parser.add_argument('--workers', type=int, default=6, choices=range(1, 9))
    args = parser.parse_args()
    if args.check:
        candidate = json.loads(args.candidate.read_bytes())
        lock = json.loads((ASSETS / 'BROWSER_DEPENDENCY_REVIEW_LOCK.json').read_bytes())
        report = json.loads((ASSETS / 'BROWSER_DEPENDENCY_REVIEW.json').read_bytes())
        verify_report(candidate, lock, report)
        if (ASSETS / 'BROWSER_DEPENDENCY_REVIEW.md').read_text(encoding='utf-8') != render(report):
            raise ValueError('Generated Markdown no longer matches review evidence.')
        print('Review snapshot binding verified offline. Installation is still held.')
        return 0
    if args.lock_file is None or args.cache_dir is None:
        parser.error('--lock-file and --cache-dir are required for archive inspection.')
    cache = args.cache_dir.resolve()
    if cache == ASSETS.parents[1] or cache.is_relative_to(ASSETS.parents[1]):
        parser.error('Archive cache must be outside the repository.')
    cache.mkdir(parents=True, exist_ok=True)
    candidate_raw, lock_raw = args.candidate.read_bytes(), args.lock_file.read_bytes()
    candidate, lock = json.loads(candidate_raw), json.loads(lock_raw)
    records = lock_records(lock, candidate)
    grouped = {}
    for row in records:
        key = (row['name'], row['version'], row['resolved'], row['integrity'])
        if key not in grouped:
            grouped[key] = {**row, 'paths': []}
        grouped[key]['paths'].append(row['path'])
        grouped[key]['dev_only'] &= row['dev_only']
        grouped[key]['optional'] &= row['optional']
    artifacts = sorted(grouped.values(), key=lambda row: (row['name'], row['version']))
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = {executor.submit(fetch_archive, row, cache, args.fetch): row for row in artifacts}
        for index, future in enumerate(as_completed(pending), 1):
            row = pending[future]
            try:
                row['inspection'] = future.result()
                if row['lock_license'] != row['inspection']['declared_license']:
                    row['inspection']['flags'] = sorted(set(row['inspection']['flags']) | {'lock_shipped_licence_difference'})
            except Exception as error:
                # Safe static error category: no response body, arbitrary URL or environment.
                row['error'] = type(error).__name__
            if index % 50 == 0 or index == len(artifacts):
                print(f'Inspected {index}/{len(artifacts)} artifacts.', flush=True)
    report = {
        'review_status': 'human_review_required_not_installation_approval',
        'schema_version': 1, 'candidate_sha256': json_digest(candidate), 'lock_sha256': json_digest(lock),
        'scope': 'Forensic login/shell runtime and Parcel/Compiled/TypeScript/ADS lint development graph; all locked platform options. Not approved for installation.',
        'resolution_overrides': candidate.get('overrides', {}),
        'summary': {'lock_entries': len(records), 'unique_artifacts': len(artifacts),
                    'inspected_artifacts': sum('inspection' in row for row in artifacts),
                    'errors': sum('error' in row for row in artifacts),
                    'declared_licenses': dict(sorted(Counter(row.get('inspection', {}).get('declared_license', '') for row in artifacts).items()))},
        'artifacts': artifacts,
    }
    (ASSETS / 'BROWSER_DEPENDENCY_REVIEW_LOCK.json').write_bytes(lock_raw)
    (ASSETS / 'BROWSER_DEPENDENCY_REVIEW.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (ASSETS / 'BROWSER_DEPENDENCY_REVIEW.md').write_text(render(report), encoding='utf-8')
    print(json.dumps(report['summary'], sort_keys=True))
    return bool(report['summary']['errors'])


if __name__ == '__main__':
    raise SystemExit(main())
