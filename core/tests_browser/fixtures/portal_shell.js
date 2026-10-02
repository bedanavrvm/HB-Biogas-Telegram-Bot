'use strict';
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const shell = fs.readFileSync(path.join(root, 'templates/base_shell.html'), 'utf8');

// Preserve the actual shell and production cascade. Do not construct a second
// approximation of headers or silently reorder stylesheet dependencies.
async function mountPortalShell(page, content) {
  // Real shell CSS contains an optional remote font import. Keep this fixture
  // offline and deterministic; no request may reach Google or Telegram.
  await page.route(/^https?:\/\//, route => route.abort());
  const styles = [...shell.matchAll(/<link[^>]+static 'miniapp\/([^']+\.css)'/g)].map(match => match[1]);
  const html = shell.replace(/{% block content %}[\s\S]*?{% endblock %}/, content)
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '')
    .replace(/{%[^]*?%}/g, '').replace(/{{[^]*?}}/g, '');
  await page.setContent(html);
  for (const name of styles) {
    const css = fs.readFileSync(path.join(root, 'static/miniapp', name), 'utf8');
    // Aborted @imports make addStyleTag reject. Omit only the optional remote
    // font import; retain every production layout rule and its cascade order.
    await page.addStyleTag({ content: css.replace(/@import\s+url\(['"]https?:[^)]*\)\s*;/g, '') });
  }
  await page.addScriptTag({ path: path.join(root, 'static/miniapp/vendor-lucide-1.44.0.min.js') });
  await page.evaluate(() => window.lucide.createIcons());
}
module.exports = { mountPortalShell };
