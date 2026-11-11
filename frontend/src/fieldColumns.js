// Shared column layout for the message field editor only.
// These widths are a browser preference and never form part of the message payload.
export const FIELD_COLUMN_KEYS = Object.freeze([
  'order', 'type', 'name', 'purpose', 'array',
  'size', 'range', 'unit', 'note', 'actions',
]);

export const FIELD_COLUMN_HEADERS = Object.freeze({
  order: '순서',
  type: '자료형',
  name: '필드 이름',
  purpose: '필드 용도',
  array: '배열',
  size: '크기(Byte)',
  range: '허용 값 범위',
  unit: '단위',
  note: '비고',
  actions: '관리',
});

export const FIELD_COLUMN_MIN_WIDTHS = Object.freeze({
  order: 56,
  type: 135,
  name: 95,
  purpose: 135,
  array: 90,
  size: 82,
  range: 135,
  unit: 75,
  note: 135,
  actions: 72,
});
export const FIELD_COLUMN_MAX_WIDTH = 1200;
export const FIELD_COLUMN_STORAGE_KEY = 'interfy-message-field-column-widths-v1';

export function normalizeFieldColumnWidths(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;

  const result = {};
  for (const key of FIELD_COLUMN_KEYS) {
    const width = value[key];
    if (!Number.isInteger(width) ||
        width < FIELD_COLUMN_MIN_WIDTHS[key] ||
        width > FIELD_COLUMN_MAX_WIDTH) return null;
    result[key] = width;
  }
  return result;
}

export function resizeFieldColumn(widths, key, deltaPx) {
  if (!FIELD_COLUMN_KEYS.includes(key) || !Number.isFinite(deltaPx)) return widths;
  const current = widths?.[key];
  if (!Number.isFinite(current)) return widths;
  const width = Math.max(
    FIELD_COLUMN_MIN_WIDTHS[key],
    Math.min(FIELD_COLUMN_MAX_WIDTH, Math.round(current + deltaPx))
  );
  return { ...widths, [key]: width };
}

export function fieldColumnTotalWidth(widths) {
  return FIELD_COLUMN_KEYS.reduce((sum, key) => sum + widths[key], 0);
}
