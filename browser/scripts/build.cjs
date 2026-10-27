'use strict';

const { check } = require('./check-dependencies.cjs');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { Parcel } = require('@parcel/core');

function packageOwner(filename, root) {
  let directory = path.dirname(filename);
  while (directory.startsWith(root)) {
    const candidate = path.join(directory, 'package.json');
    if (fs.existsSync(candidate)) {
      const manifest = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      // Some packages repeat identity in export subdirectories. Notices belong
      // to the installed archive root, not its nested ESM/package descriptor.
      if (manifest.name && manifest.version && directory.endsWith(path.sep + path.join('node_modules', manifest.name))) return { directory, manifest };
    }
    if (directory === root) break;
    directory = path.dirname(directory);
  }
  throw new Error('No package owner for a bundled module.');
}

function notices(owners, artifacts, root) {
  const output = ['JBL staff browser: third-party notices', '', 'Only identified open-source package code is used. No Atlassian trademark or proprietary asset permission is implied.', ''];
  const apache = fs.readFileSync(path.join(root, 'node_modules/@atlaskit/button/LICENSE'), 'utf8');
  for (const { directory, manifest } of [...owners.values()].sort((a, b) => a.manifest.name.localeCompare(b.manifest.name))) {
    const evidence = artifacts.find(row => row.name === manifest.name && row.version === manifest.version);
    if (!evidence) throw new Error(`Unreviewed bundled package: ${manifest.name}`);
    const license = typeof manifest.license === 'string' ? manifest.license : manifest.license?.type;
    if (!['Apache-2.0', 'MIT', 'ISC', 'BSD-2-Clause', 'BSD-3-Clause', '0BSD', 'CC0-1.0', '(MIT OR CC0-1.0)'].includes(license)) throw new Error(`Review bundled licence: ${manifest.name}: ${license}`);
    output.push('='.repeat(72), `${manifest.name}@${manifest.version}`, `Declared licence: ${license}`, `Archive: ${evidence.resolved}`, `Integrity: ${evidence.integrity}`, '');
    const texts = [];
    for (const item of evidence.inspection.license_files) {
      const relative = item.path.split('/').slice(1).join('/');
      const source = path.join(directory, relative);
      if (!fs.existsSync(source)) throw new Error(`An inspected licence file is missing: ${manifest.name}/${relative}`);
      const raw = fs.readFileSync(source);
      if (crypto.createHash('sha256').update(raw).digest('hex') !== item.sha256) throw new Error('Installed licence text differs from reviewed artifact.');
      texts.push(`${relative}\n\n${raw.toString('utf8')}`);
    }
    if (!texts.length) {
      if (['@atlaskit/platform-feature-flags', '@atlaskit/top-layer'].includes(manifest.name)) texts.push('Atlassian Pty Ltd. This package declares Apache-2.0; the full standard terms below are retained from the same publisher\'s inspected button archive.\n\n' + apache);
      else if (manifest.name === '@compiled/react') texts.push('Full licence retained from the official Compiled repository; see notice-sources/README.md for source/hash.\n\n' + fs.readFileSync(path.join(root, 'notice-sources/compiled-LICENSE.txt'), 'utf8'));
      else if (manifest.name === '@statsig/client-core') texts.push('Licence retained from the official repository at the package\'s published gitHead; see notice-sources/README.md.\n\n' + fs.readFileSync(path.join(root, 'notice-sources/statsig-LICENSE.txt'), 'utf8'));
      else throw new Error(`No reviewed bundled licence text for ${manifest.name}`);
    }
    output.push(...texts, '');
  }
  return output.join('\n');
}

async function main() {
  const { root, lock, review, artifacts } = check();
  process.env.PARCEL_WORKERS = '2';
  process.chdir(root);
  const development = process.argv.includes('--development');
  const complaintsDemo = process.argv.includes('--complaints-demo');
  const operations = process.argv.includes('--complaints-operations');
  const productionBrowser = process.argv.includes('--production-browser');
  const complaints = process.argv.includes('--complaints');
  if (complaintsDemo && (operations || complaints || process.argv.includes('--authentication'))) throw new Error('Build the synthetic Complaints demo separately.');
  if (operations && complaints) throw new Error('Build restricted reads and operations separately.');
  const authentication = process.argv.includes('--authentication') || complaints || operations;
  if (productionBrowser && (!operations || development || complaintsDemo)) throw new Error('Production browser delivery requires the native production Complaints operations entry.');
  const dist = path.join(root, productionBrowser ? 'dist-production' : operations ? (development ? 'dist-complaints-operations-development' : 'dist-complaints-operations') : complaintsDemo ? (development ? 'dist-complaints-demo-development' : 'dist-complaints-demo') : complaints ? (development ? 'dist-complaints-development' : 'dist-complaints') : authentication ? (development ? 'dist-authentication-development' : 'dist-authentication') : (development ? 'dist-development' : 'dist'));
  const parcel = new Parcel({
    entries: operations ? [path.join(root, 'src/complaints-operations.html')] : complaintsDemo ? [path.join(root, 'src/complaints-demo.html')] : complaints ? [path.join(root, 'src/complaints.html')] : authentication ? [path.join(root, 'src/access.html')] : [path.join(root, 'src/index.html'), path.join(root, 'src/review.html')],
    defaultConfig: require.resolve('@parcel/config-default'),
    mode: development ? 'development' : 'production',
    shouldAutoInstall: false,
    shouldDisableCache: true,
    targets: { preview: {
      context: 'browser',
      distDir: dist,
      publicUrl: productionBrowser ? '/staff/assets/' : '/',
      includeNodeModules: true,
      isLibrary: false,
      sourceMap: false,
      engines: { browsers: ['last 2 Chrome versions', 'last 2 Firefox versions', 'last 2 Safari versions'] },
    } },
    env: { NODE_ENV: development ? 'development' : 'production' },
  });
  const { bundleGraph } = await parcel.run();
  const modules = new Set();
  const bundles = bundleGraph.getBundles();
  for (const bundle of bundles) bundle.traverseAssets(asset => modules.add(asset.filePath));
  const owners = new Map();
  for (const filename of modules) {
    const relative = path.relative(root, filename).split(path.sep).join('/');
    if (relative.startsWith('../') || /\.(woff2?|ttf|otf|eot|png|jpe?g|svg|gif|webp|node|wasm)$/i.test(relative)) throw new Error('Excluded external/binary/font/image asset in the browser graph.');
    if (authentication && /(?:^|\/)complaints-demo[^/]*\.[jt]sx?$/.test(relative)) throw new Error('Synthetic workflow code is forbidden in the native staff artifact.');
    if (/@atlaskit\/icon[^/]*\/(?:.*\/)?(?:glyph|svgs|core|utility)\/(?:atlassian|jira|confluence|rovo|trello|bitbucket|compass)(?:[/.\-]|$)/i.test(relative)) throw new Error('Excluded brand glyph in the browser graph.');
    if (relative.includes('node_modules/@atlaskit/logo/')) throw new Error('Atlassian logo code is excluded; use company text.');
    if (relative.startsWith('node_modules/')) {
      const owner = packageOwner(filename, root);
      owners.set(`${owner.manifest.name}@${owner.manifest.version}`, owner);
    }
  }
  for (const required of ['react@18.3.1', 'react-dom@18.3.1', '@atlaskit/button@25.5.0', '@atlaskit/form@18.2.0', '@atlaskit/textfield@10.2.6', '@atlaskit/tokens@20.6.1']) {
    if (!owners.has(required)) throw new Error(`The browser target must bundle its actual runtime dependency: ${required}`);
  }
  const noticeFile = path.join(dist, 'THIRD_PARTY_NOTICES.txt');
  fs.writeFileSync(noticeFile, notices(owners, artifacts, root));
  const files = [...new Set([...bundles.map(bundle => bundle.filePath), noticeFile])].sort().map(filename => {
    const name = path.relative(dist, filename).split(path.sep).join('/');
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*\.(html|js|css|txt)$/.test(name)) throw new Error('Unexpected output path; do not expose it through the preview server.');
    const raw = fs.readFileSync(filename);
    return { name, bytes: raw.length, sha256: crypto.createHash('sha256').update(raw).digest('hex') };
  });
  const sources = [...modules].filter(filename => filename.startsWith(path.join(root, 'src') + path.sep)).sort().map(filename => ({
    path: 'browser/' + path.relative(root, filename).split(path.sep).join('/'),
    sha256: crypto.createHash('sha256').update(fs.readFileSync(filename, 'utf8').replace(/\r\n/g, '\n')).digest('hex'),
  }));
  fs.writeFileSync(path.join(dist, 'build-manifest.json'), JSON.stringify({ schemaVersion: 1, demoOnly: !authentication, localComplaintsDemo: complaintsDemo, closedAuthentication: authentication, closedComplaints: complaints, closedComplaintOperations: operations, productionBrowser, assetPrefix: productionBrowser ? '/staff/assets/' : '/', mode: development ? 'development' : 'production', node: process.versions.node, dependencyLock: review.lock_sha256, sources, files, modules: [...modules].map(filename => path.relative(root, filename).split(path.sep).join('/')).sort(), packages: [...owners.keys()].sort(), lockEntries: Object.keys(lock.packages).length - 1 }, null, 2) + '\n');
  console.log(`Built real React/ADS ${development ? 'development' : 'production'} ${authentication ? 'closed authentication' : 'demo'}: ${files.length} assets, ${owners.size} noticed packages, ${files.reduce((n, file) => n + file.bytes, 0)} bytes; no excluded assets.`);
}

main().catch(error => { console.error(error); process.exitCode = 1; });
