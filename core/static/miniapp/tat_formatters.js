(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TatMiniAppFormatters = api;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const TAT_LOCALE = 'en-KE';
  const TAT_TIME_ZONE = 'Africa/Nairobi';

  function parseTatInstant(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    const legacyNairobi = text.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})\s+(\d{1,2}):(\d{2})/);
    const normalized = legacyNairobi
      ? `${legacyNairobi[3].length === 2 ? `20${legacyNairobi[3]}` : legacyNairobi[3]}-${legacyNairobi[2].padStart(2, '0')}-${legacyNairobi[1].padStart(2, '0')}T${legacyNairobi[4].padStart(2, '0')}:${legacyNairobi[5]}:00+03:00`
      : text;
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function formatNairobiDateTime(value) {
    const parsed = parseTatInstant(value);
    if (!parsed) return String(value || '');
    const parts = Object.fromEntries(new Intl.DateTimeFormat(TAT_LOCALE, {
      timeZone: TAT_TIME_ZONE, day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(parsed).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    return `${parts.day}-${parts.month}-${parts.year} ${parts.hour}:${parts.minute}`;
  }

  function formatNairobiDate(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    const dateOnly = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (dateOnly) return `${dateOnly[3]}-${dateOnly[2]}-${dateOnly[1]}`;
    const numeric = text.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})/);
    if (numeric) {
      const year = numeric[3].length === 2 ? `20${numeric[3]}` : numeric[3];
      return `${numeric[1].padStart(2, '0')}-${numeric[2].padStart(2, '0')}-${year}`;
    }
    const parsed = parseTatInstant(text);
    if (!parsed) return text;
    const parts = Object.fromEntries(new Intl.DateTimeFormat(TAT_LOCALE, {
      timeZone: TAT_TIME_ZONE, day: '2-digit', month: '2-digit', year: 'numeric',
    }).formatToParts(parsed).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    return `${parts.day}-${parts.month}-${parts.year}`;
  }

  function nairobiDateInputValue(value) {
    const parsed = parseTatInstant(value);
    if (!parsed) return '';
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
      timeZone: TAT_TIME_ZONE, day: '2-digit', month: '2-digit', year: 'numeric',
    }).formatToParts(parsed).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function nairobiDateTimeInputValue(value) {
    const parsed = parseTatInstant(value);
    if (!parsed) return '';
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
      timeZone: TAT_TIME_ZONE, day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(parsed).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }

  function nairobiDateTimeInputToIso(value) {
    const text = String(value || '').trim();
    const match = text.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2}))?$/);
    if (!match) return '';
    return `${match[1]}:${match[2] || '00'}+03:00`;
  }

  function formatLocalizedNumber(value, options) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '';
    return new Intl.NumberFormat(TAT_LOCALE, options || {}).format(number);
  }

  function formatLocalizedPercent(value, maximumFractionDigits) {
    const formatted = formatLocalizedNumber(value, {
      maximumFractionDigits: maximumFractionDigits == null ? 1 : maximumFractionDigits,
    });
    return formatted ? `${formatted}%` : '';
  }

  function formatAdaptiveDurationMinutes(value) {
    if (value == null || value === '') return '\u2014';
    const minutes = Number(value);
    if (!Number.isFinite(minutes)) return '\u2014';
    const sign = minutes < 0 ? '\u2212' : '';
    let seconds = Math.round(Math.abs(minutes) * 60);
    if (seconds < 60) return `${sign}${seconds}s`;
    let wholeMinutes = Math.floor(seconds / 60);
    if (wholeMinutes < 60) return `${sign}${wholeMinutes}m`;
    const days = Math.floor(wholeMinutes / 1440);
    wholeMinutes %= 1440;
    const hours = Math.floor(wholeMinutes / 60);
    const remainderMinutes = wholeMinutes % 60;
    if (days) return `${sign}${days}d ${hours}h ${remainderMinutes}m`;
    return `${sign}${hours}h ${remainderMinutes}m`;
  }

  return {
    TAT_LOCALE,
    TAT_TIME_ZONE,
    formatNairobiDateTime,
    formatNairobiDate,
    nairobiDateInputValue,
    nairobiDateTimeInputValue,
    nairobiDateTimeInputToIso,
    formatLocalizedNumber,
    formatLocalizedPercent,
    formatAdaptiveDurationMinutes,
  };
}));
