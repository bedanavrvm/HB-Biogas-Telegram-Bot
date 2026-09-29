'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const resultsDirectory = path.join(root, 'test-results');
const suppliedPath = process.argv[2];

function newestTrace(directory) {
  if (!fs.existsSync(directory)) return null;
  const pending = [directory];
  let newest = null;
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        pending.push(fullPath);
      } else if (entry.isFile() && entry.name.toLowerCase().endsWith('.zip')) {
        const modifiedAt = fs.statSync(fullPath).mtimeMs;
        if (!newest || modifiedAt > newest.modifiedAt) newest = { path: fullPath, modifiedAt };
      }
    }
  }
  return newest?.path || null;
}

const tracePath = suppliedPath
  ? path.resolve(process.cwd(), suppliedPath)
  : newestTrace(resultsDirectory);

if (!tracePath || !fs.existsSync(tracePath) || !tracePath.toLowerCase().endsWith('.zip')) {
  console.error(suppliedPath
    ? `Trace archive not found: ${tracePath}`
    : `No Playwright trace archive found under ${resultsDirectory}.`);
  process.exitCode = 1;
} else {
  const playwrightCli = path.join(path.dirname(require.resolve('playwright')), 'cli.js');
  const result = spawnSync(process.execPath, [playwrightCli, 'show-trace', tracePath], {
    cwd: root,
    stdio: 'inherit',
  });
  if (result.error) {
    console.error(`Could not start Playwright Trace Viewer: ${result.error.message}`);
    process.exitCode = 1;
  } else {
    process.exitCode = result.status ?? 1;
  }
}
