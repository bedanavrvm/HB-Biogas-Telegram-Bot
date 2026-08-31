#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const roots = [
  path.join(root, 'core', 'static', 'admin'),
  path.join(root, 'core', 'static', 'miniapp'),
  path.join(root, 'core', 'tests_js'),
  path.join(root, 'core', 'tests_browser'),
  path.join(root, 'scripts'),
];

function sourceFiles(directory) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(candidate);
    if (!entry.isFile() || path.extname(entry.name) !== '.js') return [];
    if (entry.name.startsWith('vendor-')) return [];
    return [candidate];
  });
}

const files = [...new Set(roots.flatMap(sourceFiles))].sort();
const failures = [];
for (const filename of files) {
  const result = spawnSync(process.execPath, ['--check', filename], {
    cwd: root,
    encoding: 'utf8',
  });
  if (result.status !== 0) {
    failures.push(path.relative(root, filename));
    process.stderr.write(result.stderr || result.stdout || 'JavaScript syntax check failed.\n');
  }
}

if (failures.length) {
  console.error(`First-party JavaScript syntax failed for ${failures.length} file(s).`);
  process.exit(1);
}
console.log(`First-party JavaScript syntax passed (${files.length} file(s); vendored bundles excluded).`);
