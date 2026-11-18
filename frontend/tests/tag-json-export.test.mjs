import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const main = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const source = readFileSync(new URL('../src/UnifiedExportPanel.jsx', import.meta.url), 'utf8');
const editor = readFileSync(new URL('../public/Interfy-Partner-Editor.html', import.meta.url), 'utf8');

test('tag JSON export remains available in unified format selection', () => {
  assert.match(main, /<UnifiedExportPanel/);
  assert.match(source, /\{ key: 'json', label: 'JSON', extension: 'json' \}/);
  assert.match(source, /\/labels\/[' ]*\+ label\.id \+ '\/export\/'/);
  assert.match(source, /scope === 'tag'/);
});

test('tag and partner JSON remain compatible with offline editor and partial update', () => {
  assert.match(source, /'\/projects\/' \+ project\.id \+ '\/collaboration\/export'/);
  assert.match(source, /'\/projects\/' \+ project\.id \+ '\/project-json'/);
  assert.match(source, /Interfy-Partner-Editor\.html/);
  assert.match(source, /수정 JSON 반영/);
  assert.match(editor, /dataObject\.format!=='interfy-project'/);
  assert.match(editor, /JSON 저장/);
});
