'use strict';

const assert = require('node:assert/strict');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const Context = require('@atlaskit/analytics-next-stable-react-context').default;
const parser = require('postcss-selector-parser');

assert.equal(React.version, '18.3.1');
assert.strictEqual(Context, require('@atlaskit/analytics-next-stable-react-context').default);
function Consumer() {
  const value = React.useContext(Context);
  return React.createElement('span', null, value.getAtlaskitAnalyticsContext().join(','));
}
const expected = 'reviewed-context';
const element = React.createElement(React.StrictMode, null,
  React.createElement(Context.Provider, { value: { getAtlaskitAnalyticsContext: () => [expected], getAtlaskitAnalyticsEventHandlers: () => [] } }, React.createElement(Consumer)));
assert.equal(renderToStaticMarkup(element), `<span>${expected}</span>`);
assert.equal(renderToStaticMarkup(React.createElement(Consumer)), '<span></span>');

// Check the fixed major version against syntax exercised by Compiled tooling.
assert.equal(require('postcss-selector-parser/package.json').version, '7.1.6');
const selectors = ['.a:not(.b)', '[data-x="a,b"] > :is(.x, .y)', ':where(.a) + .b::before', '.a\\:b:hover', '.a'.repeat(2000)];
for (const selector of selectors) assert.equal(parser().processSync(selector), selector);
assert.equal(parser().astSync('.one, .two > .three').nodes.length, 2);
console.log('React 18 context singleton/provider/consumer and fixed selector-parser syntax checks passed.');
