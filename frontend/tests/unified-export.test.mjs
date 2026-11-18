import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const main = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const ui = readFileSync(new URL('../src/UnifiedExportPanel.jsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/unifiedExport.css', import.meta.url), 'utf8');

test('the five older output cards are replaced with one unified output panel', () => {
  assert.match(main, /<UnifiedExportPanel/);
  assert.doesNotMatch(main, /<h2>협력사 오프라인 작업 패키지<\/h2>/);
  assert.doesNotMatch(main, /<h2>태그 출력<\/h2>/);
  assert.doesNotMatch(main, /<h2>노드별 출력<\/h2>/);
  assert.match(ui, /인터페이스 파일 출력/);
  assert.match(ui, /IDD 문서 출력/);
});

test('only the applicable selection fieldset can be edited', () => {
  assert.match(ui, /\{ value: 'all', label: '프로젝트 전체' \}/);
  assert.match(ui, /\{ value: 'tag', label: '태그' \}/);
  assert.match(ui, /\{ value: 'nodes', label: '노드 선택' \}/);
  assert.match(ui, /disabled=\{scope !== 'tag'\}/);
  assert.match(ui, /disabled=\{scope !== 'nodes'\}/);
  assert.match(css, /\.unified-export-condition\[disabled\]/);
  assert.match(ui, /const \[scope, setScope\] = useState\('all'\)/);
});

test('all scopes share the same format selection with supported export routes', () => {
  assert.match(ui, /\{ key: 'header', label: '\.h'/);
  assert.match(ui, /\{ key: 'idl', label: '\.idl'/);
  assert.match(ui, /\{ key: 'csharp', label: '\.cs'/);
  assert.match(ui, /\{ key: 'json', label: 'JSON'/);
  assert.match(ui, /'\/projects\/' \+ project\.id \+ '\/project-json'/);
  assert.match(ui, /'\/labels\/' \+ label\.id \+ '\/export\/'/);
  assert.match(ui, /'\/projects\/' \+ project\.id \+ '\/export\/nodes\/'/);
  assert.match(ui, /'\/projects\/' \+ project\.id \+ '\/collaboration\/export'/);
  assert.match(ui, /target_ids: selectedNodeIds, direction/);
});

test('per-scope settings remain selected when switching output ranges', () => {
  assert.match(ui, /const \[selectedLabelId, setSelectedLabelId\] = useState/);
  assert.match(ui, /const \[selectedNodeIds, setSelectedNodeIds\] = useState/);
  assert.match(ui, /const \[direction, setDirection\] = useState/);
  assert.match(ui, /onChange=\{\(\) => setScope\(item\.value\)\}/);
  assert.doesNotMatch(ui, /setScope\([^)]*\);\s*setSelectedNodeIds\(/);
});

test('offline editor/partial update remain in the top tools and IDD is separate', () => {
  assert.match(ui, /href="\/Interfy-Partner-Editor\.html"/);
  assert.match(ui, /onClick=\{onOpenPartialUpdate\}/);
  assert.match(ui, /exportIdd\('docx'\)/);
  assert.match(ui, /exportIdd\('hwpx'\)/);
  assert.match(ui, /scope === 'nodes' && selectedNodeIds\.length > 0/);
});
