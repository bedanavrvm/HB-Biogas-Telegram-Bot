'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const semver = require('semver');
const root = path.resolve(__dirname, '..');
const read = filename => JSON.parse(fs.readFileSync(path.resolve(root, filename), 'utf8'));
const ordered = value => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value;
const digest = value => crypto.createHash('sha256').update(JSON.stringify(ordered(value)).replace(/[\u007f-\uffff]/g, ch => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`)).digest('hex');

function check() {
  const manifest = read('package.json');
  const lock = read('package-lock.json');
  const review = read('dependency-review.json');
  assert.ok(semver.satisfies(process.versions.node, manifest.engines.node), 'Use the pinned Node 22 runtime.');
  assert.deepEqual(manifest.overrides, { '@atlaskit/analytics-next-stable-react-context@1.0.1': { react: '18.3.1' }, 'postcss-selector-parser': '7.1.6' });
  for (const field of ['dependencies', 'devDependencies', 'engines']) assert.deepEqual(manifest[field], lock.packages[''][field]);
  assert.equal(digest(lock), review.lock_sha256, 'The exact dependency review must be refreshed.');
  const base = read('../codebase-analysis-docs/assets/BROWSER_DEPENDENCY_REVIEW.json');
  assert.equal(digest(base), review.base_report_sha256);
  const artifacts = [...base.artifacts, ...review.new_artifacts];
  const key = item => JSON.stringify([item.name, item.version, item.resolved, item.integrity]);
  const inspected = new Map(artifacts.map(item => [key(item), item]));
  const exceptions = [];
  let peers = 0;
  let platformSkipped = 0;
  const reactPaths = [];
  for (const [location, entry] of Object.entries(lock.packages)) {
    if (!location) continue;
    const name = entry.name || location.split('node_modules/').at(-1);
    assert.ok(inspected.has(key({ name, ...entry })), `Unreviewed archive: ${name}@${entry.version}`);
    const directory = path.join(root, location);
    const filename = path.join(directory, 'package.json');
    if (!fs.existsSync(filename)) {
      assert.ok(entry.optional, `Missing nonoptional dependency: ${name}`);
      platformSkipped += 1;
      continue;
    }
    const shipped = JSON.parse(fs.readFileSync(filename, 'utf8'));
    assert.equal(shipped.name, name);
    assert.equal(shipped.version, entry.version);
    if (name === 'react' || name === 'react-dom') reactPaths.push([name, shipped.version, location]);
    for (const [peer, range] of Object.entries(shipped.peerDependencies || {})) {
      let current = directory;
      let provider;
      while (current.startsWith(root)) {
        const candidate = path.join(current, 'node_modules', peer, 'package.json');
        if (fs.existsSync(candidate)) { provider = JSON.parse(fs.readFileSync(candidate, 'utf8')); break; }
        if (current === root) break;
        current = path.dirname(current);
      }
      if (!provider && shipped.peerDependenciesMeta?.[peer]?.optional) continue;
      assert.ok(provider, `Missing required peer ${peer} for ${name}`);
      peers += 1;
      if (!semver.satisfies(provider.version, range)) {
        const exception = { name, version: shipped.version, peer, range, provider: provider.version };
        assert.deepEqual(exception, { name: '@atlaskit/analytics-next-stable-react-context', version: '1.0.1', peer: 'react', range: '^16.8.0', provider: '18.3.1' }, 'Additional original-peer mismatch is not approved.');
        exceptions.push(exception);
      }
    }
  }
  assert.equal(exceptions.length, 1, 'Re-review a changed/disappeared compatibility exception.');
  assert.deepEqual(reactPaths.sort(), [['react', '18.3.1', 'node_modules/react'], ['react-dom', '18.3.1', 'node_modules/react-dom']]);
  console.log(`Dependency review bound; ${peers} installed original peers checked, one documented context exception, ${platformSkipped} absent platform options, one React renderer.`);
  return { root, manifest, lock, review, artifacts, peers, exceptions };
}

if (require.main === module) check();
module.exports = { check, digest };
