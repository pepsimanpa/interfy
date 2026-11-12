import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

const multilineStart = source.indexOf('function ExpandableFieldTextarea(');
const multilineEnd = source.indexOf('function SuggestionInput(', multilineStart);
const component = source.slice(multilineStart, multilineEnd);

const editorStart = source.indexOf('function MessageFieldPanel(');
const editorEnd = source.indexOf('function EnumValuePanel(', editorStart);
const editor = source.slice(editorStart, editorEnd);

test('native textarea allows Enter for line breaks and grows on focus', () => {
  assert.ok(multilineStart > 0 && multilineEnd > multilineStart);
  assert.match(component, /<textarea/);
  assert.match(component, /rows=\{1\}/);
  assert.match(component, /onChange=\{event => onChange\?\.\(event\.target\.value\)\}/);
  assert.match(component, /onFocus=\{\(\) => setFocused\(true\)\}/);
  assert.match(component, /onBlur=\{\(\) => setFocused\(false\)\}/);
  assert.match(component, /element\.scrollHeight/);
  assert.match(component, /element\.style\.height = 'auto'/);
  assert.match(component, /element\.style\.height = ''/);
  assert.match(component, /\[focused, text\]/);
});

test('only saved field range and note and the new-field row use expandable inputs', () => {
  assert.equal((editor.match(/<ExpandableFieldTextarea/g) || []).length, 4);
  assert.match(editor, /ariaLabel="허용 값 범위" value=\{field\.value_range/);
  assert.match(editor, /ariaLabel="비고" value=\{field\.note/);
  assert.match(editor, /placeholder="허용 값 범위" value=\{fieldForm\.value_range/);
  assert.match(editor, /placeholder="비고" value=\{fieldForm\.note/);
  assert.match(editor, /onChange=\{value_range => updateDraftField\(fieldKey, \{ value_range \}\)\}/);
  assert.match(editor, /onChange=\{note => updateDraftField\(fieldKey, \{ note \}\)\}/);
});

test('collapse style stays one row, editing style expands and wraps text', () => {
  assert.match(css, /\.message-field-table td textarea\.expandable-field-textarea/);
  assert.match(css, /height: 34px;/);
  assert.match(css, /resize: none;/);
  assert.match(css, /white-space: nowrap;/);
  assert.match(css, /\.message-field-table td textarea\.expandable-field-textarea:focus/);
  assert.match(css, /white-space: pre-wrap;/);
});

test('hover title displays multiline complete text and field payload retains newlines', () => {
  const tooltip = source.slice(source.indexOf('function updateOverflowInputTitle('), source.indexOf('function SuggestionInput('));
  assert.match(tooltip, /text\.includes\('\\n'\)/);
  assert.match(component, /\.\.\.overflowInputHandlers\(text\)/);
  const payload = source.slice(source.indexOf('function buildFieldSavePayload('),source.indexOf('function comparableField('));
  assert.match(payload, /value_range: field\.value_range \|\| ''/);
  assert.match(payload, /note: field\.note \|\| ''/);
  assert.doesNotMatch(payload, /replace\(/);
});
