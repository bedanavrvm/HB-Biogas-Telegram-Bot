(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TatCaseValidation = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function clean(value) {
    return String(value == null ? '' : value).replace(/,/g, '').trim();
  }

  function numericValue(value) {
    const text = clean(value);
    if (!text || !/^-?(?:\d+\.?\d*|\.\d+)$/.test(text)) return null;
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function formatKes(value) {
    const parsed = numericValue(value);
    if (parsed === null) return '';
    return parsed.toLocaleString('en-KE', { maximumFractionDigits: 2 });
  }

  function amountRangeText(product) {
    if (!product) return 'Select a product to see its allowed amount range.';
    const minimum = formatKes(product.min_amount);
    const maximum = formatKes(product.max_amount);
    if (minimum && maximum) return `Allowed range: KES ${minimum}–${maximum}.`;
    if (minimum) return `Allowed amount: KES ${minimum} or more.`;
    if (maximum) return `Allowed amount: up to KES ${maximum}.`;
    return '';
  }

  function amountValidationMessage(value, product) {
    const text = clean(value);
    if (!text) return '';
    const amount = numericValue(text);
    if (amount === null) return 'Enter a valid amount.';
    if (!product) return 'Select a product before entering the amount.';
    const minimum = numericValue(product.min_amount);
    const maximum = numericValue(product.max_amount);
    const label = clean(product.label) || 'Selected product';
    if (minimum !== null && amount < minimum) {
      return `${label} amount must be at least KES ${formatKes(product.min_amount)}.`;
    }
    if (maximum !== null && amount > maximum) {
      return `${label} amount must be at most KES ${formatKes(product.max_amount)}.`;
    }
    return '';
  }

  function configureAmountInput(input, help, product) {
    if (!input) return;
    const minimum = clean(product && product.min_amount);
    const maximum = clean(product && product.max_amount);
    input.min = minimum || '0';
    if (maximum) input.max = maximum;
    else input.removeAttribute('max');
    if (help) help.textContent = amountRangeText(product);
  }

  function validateAmountInput(input, product, options) {
    if (!input) return true;
    const message = amountValidationMessage(input.value, product);
    input.setCustomValidity(message);
    if (message && options && options.report) input.reportValidity();
    return !message;
  }

  return {
    amountRangeText,
    amountValidationMessage,
    configureAmountInput,
    validateAmountInput,
  };
});
