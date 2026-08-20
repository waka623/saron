/**
 * 共通ユーティリティ
 */

function toDate_(value) {
  if (value instanceof Date) return value;
  if (!value) return null;
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

function toNumber_(value) {
  if (value === '' || value === null || value === undefined) return 0;
  const n = Number(value);
  return isNaN(n) ? 0 : n;
}

function formatValue_(v) {
  if (v === null || v === undefined) return 'ー';
  return typeof v === 'number' ? String(Math.round(v * 10) / 10) : String(v);
}

function formatPct_(v) {
  if (v === null || v === undefined) return 'ー';
  const sign = v > 0 ? '+' : '';
  return `${sign}${Math.round(v * 10) / 10}%`;
}

function formatDate_(d) {
  return Utilities.formatDate(d, Session.getScriptTimeZone() || 'Asia/Tokyo', 'yyyy/MM/dd');
}
