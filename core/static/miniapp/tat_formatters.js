(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TatMiniAppFormatters = api;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

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
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Africa/Nairobi', day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(parsed).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    return `${parts.day}-${parts.month}-${parts.year} ${parts.hour}:${parts.minute} EAT`;
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

  return { formatNairobiDateTime, formatAdaptiveDurationMinutes };
}));
