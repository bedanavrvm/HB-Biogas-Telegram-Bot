(function (root) {
  'use strict';
  function today() {
    return new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10);
  }
  function validate(field, value) {
    if (value === '' || value === null || value === undefined) return '';
    const rules = field.validation || {};
    const text = String(value);
    if (rules.format === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text)) return 'Enter a valid email address.';
    if (['number', 'money'].includes(field.type)) {
      if (typeof value === 'boolean' || !/^-?(?:\d+|\d*\.\d+)$/.test(text) || !Number.isFinite(Number(text))) return 'Enter a valid number.';
      if (rules.integer && !/^-?\d+(?:\.0+)?$/.test(text)) return 'Enter a whole number.';
      const places = (text.split('.')[1] || '').replace(/0+$/, '').length;
      if (rules.decimal_places != null && places > rules.decimal_places) return `Use no more than ${rules.decimal_places} decimal places.`;
      if (rules.min != null && rules.min !== '' && Number(text) < Number(rules.min)) return `Enter a value of at least ${rules.min}.`;
      if (rules.max != null && rules.max !== '' && Number(text) > Number(rules.max)) return `Enter a value no greater than ${rules.max}.`;
    }
    if (field.type === 'date') {
      const parsed = new Date(text + 'T00:00:00Z');
      if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== text) return 'Enter a valid date.';
      if (rules.min_date && text < rules.min_date) return `Choose a date on or after ${rules.min_date}.`;
      if (rules.max_date && text > rules.max_date) return `Choose a date on or before ${rules.max_date}.`;
      if (rules.no_future && text > today()) return 'Choose today or an earlier date.';
    }
    if (field.type === 'choice' && !(field.options || []).some(option => (typeof option === 'object' ? option.active !== false && option.code : option) === value)) return 'Choose an available option.';
    if (field.type === 'boolean' && typeof value !== 'boolean') return 'Choose yes or no.';
    if (field.type === 'national_id' && !/^\d{1,9}$/.test(text)) return 'Enter a National ID using 1 to 9 digits only.';
    if (field.type === 'phone' && root.MiniAppUtils?.normalizeKenyanPhone && !root.MiniAppUtils.normalizeKenyanPhone(text)) return 'Enter a valid Kenyan mobile number.';
    if (['text', 'textarea', 'phone', 'national_id'].includes(field.type)) {
      if (rules.min_length != null && text.length < rules.min_length) return `Enter at least ${rules.min_length} characters.`;
      if (rules.max_length != null && text.length > rules.max_length) return `Enter no more than ${rules.max_length} characters.`;
      if (rules.pattern) {
        try { if (!new RegExp(`^(?:${rules.pattern})$`, 'u').test(text)) return 'Enter the value in the required format.'; }
        catch (_) { return 'This field has invalid configured rules.'; }
      }
    }
    return '';
  }
  const api = {validate, today};
  root.OriginationFieldRules = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
