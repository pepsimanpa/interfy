import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  FIELD_COLUMN_KEYS, FIELD_COLUMN_HEADERS, FIELD_COLUMN_MIN_WIDTHS,
  FIELD_COLUMN_MAX_WIDTH, normalizeFieldColumnWidths, resizeFieldColumn, fieldColumnTotalWidth,
} from '../src/fieldColumns.js';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const initial = Object.fromEntries(
  FIELD_COLUMN_KEYS.map((key, index) => [key, FIELD_COLUMN_MIN_WIDTHS[key] + 35 + index])
);

test('all ten message columns have labels, minima and a stable order', () => {
  assert.deepEqual(FIELD_COLUMN_KEYS, [
    'order','type','name','purpose','array','size','range','unit','note','actions',
  ]);
  for (const key of FIELD_COLUMN_KEYS) {
    assert.ok(FIELD_COLUMN_HEADERS[key]);
    assert.ok(FIELD_COLUMN_MIN_WIDTHS[key] > 0);
  }
});

test('saved column widths must be a valid complete pixel layout', () => {
  assert.deepEqual(normalizeFieldColumnWidths(initial), initial);
  assert.equal(normalizeFieldColumnWidths(null), null);
  assert.equal(normalizeFieldColumnWidths([]), null);
  assert.equal(normalizeFieldColumnWidths({ ...initial, name: '100' }), null);
  assert.equal(normalizeFieldColumnWidths({ ...initial, type: 0 }), null);
  assert.equal(normalizeFieldColumnWidths({ ...initial, purpose: FIELD_COLUMN_MAX_WIDTH + 1 }), null);
  const missing = { ...initial };
  delete missing.note;
  assert.equal(normalizeFieldColumnWidths(missing), null);
});

test('dragging a boundary changes only that column and respects minimum/maximum', () => {
  const result = resizeFieldColumn(initial, 'name', 42);
  assert.equal(result.name, initial.name + 42);
  for (const key of FIELD_COLUMN_KEYS.filter(key => key !== 'name')) {
    assert.equal(result[key], initial[key]);
  }
  assert.equal(initial.name, FIELD_COLUMN_MIN_WIDTHS.name + 37, 'input remains unchanged');
  assert.equal(resizeFieldColumn(initial, 'name', -10000).name, FIELD_COLUMN_MIN_WIDTHS.name);
  assert.equal(resizeFieldColumn(initial, 'name', 10000).name, FIELD_COLUMN_MAX_WIDTH);
  assert.strictEqual(resizeFieldColumn(initial, 'missing', 10), initial);
  assert.strictEqual(resizeFieldColumn(initial, 'name', Number.NaN), initial);
  assert.equal(fieldColumnTotalWidth(result) - fieldColumnTotalWidth(initial), 42);
});

test('resizing controls are confined to message field editing; reset is separate from save', () => {
  const messageStart = source.indexOf('function MessageFieldPanel(');
  const enumStart = source.indexOf('function EnumValuePanel(');
  assert.ok(messageStart >= 0 && enumStart > messageStart);
  const panel = source.slice(messageStart, enumStart);
  const enumPanel = source.slice(enumStart, source.indexOf('function ', enumStart + 12));
  assert.match(panel, /role="separator"/);
  assert.match(panel, /onPointerDown=\{event => beginFieldColumnResize\(event, key\)\}/);
  assert.match(panel, /onKeyDown=\{event => handleFieldColumnResizeKeyDown\(event, key\)\}/);
  assert.match(panel, /localStorage\.setItem\(FIELD_COLUMN_STORAGE_KEY/);
  assert.match(panel, /setFieldColumnWidths\(null\).*열 너비 초기화|열 너비 초기화/);
  assert.match(panel, /fieldResizeCleanup\.current\?\.\(\)/);
  assert.doesNotMatch(enumPanel, /field-column-resizer|beginFieldColumnResize/);
  assert.match(styles, /\.field-columns-customized \.message-field-table/);
  assert.match(styles, /width: var\(--field-table-width, 100%\)/);
  assert.match(styles, /touch-action: none/);
});
