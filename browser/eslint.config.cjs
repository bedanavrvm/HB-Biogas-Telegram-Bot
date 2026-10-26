'use strict';

const parser = require('@typescript-eslint/parser');
const designSystem = require('@atlaskit/eslint-plugin-design-system');
const styling = require('@atlaskit/eslint-plugin-ui-styling-standard');
// Advisory migration guidance also blocks new browser pages from drifting.
const recommended = { ...designSystem.configs.recommended.rules, ...styling.configs.recommended.rules };
const required = Object.fromEntries(Object.entries(recommended).map(([name, value]) => [name, Array.isArray(value) ? ['error', ...value.slice(1)] : 'error']));
module.exports = [{
  files: ['src/**/*.{ts,tsx}'],
  languageOptions: { parser, ecmaVersion: 'latest', sourceType: 'module', parserOptions: { ecmaFeatures: { jsx: true } } },
  plugins: {
    '@atlaskit/design-system': designSystem,
    '@atlaskit/ui-styling-standard': styling,
  },
  linterOptions: { reportUnusedDisableDirectives: 'error' },
  rules: required,
}, {
  files: ['src/complaints-operations*.tsx', 'src/complaints-report*.tsx', 'src/complaints-date-control.tsx', 'src/complaints-ui.tsx', 'src/browser-interactions.tsx', 'src/workspace-task.tsx'],
  rules: { 'no-alert': 'error' },
}];
