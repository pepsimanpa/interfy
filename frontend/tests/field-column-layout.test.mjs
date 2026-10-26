import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const stylesheet = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

test('column sizing is scoped to the ten-column message field editor, not Enum tables', () => {
  const messageStart = source.indexOf('function MessageFieldPanel(');
  const enumStart = source.indexOf('function EnumValuePanel(');
  assert.ok(messageStart >= 0 && enumStart > messageStart);
  const messagePanel = source.slice(messageStart, enumStart);
  const enumPanel = source.slice(enumStart, source.indexOf('function ', enumStart + 12));
  assert.match(messagePanel, /<table className="message-field-table">/);
  assert.doesNotMatch(enumPanel, /message-field-table/);
  const group = messagePanel.match(/<colgroup>([\s\S]*?)<\/colgroup>/);
  assert.ok(group, 'message field editor has its own column sizing group');
  const cols = [...group[1].matchAll(/className="field-col-([\w-]+)"/g)].map(match => match[1]);
  assert.deepEqual(cols, ['order','type','name','purpose','array','size','range','unit','note','actions']);
});

test('description, allowed range and notes are wider than compact information columns', () => {
  const widthByColumn = Object.fromEntries(
    [...stylesheet.matchAll(/\.message-field-table \.field-col-(\w+) \{ width: (\d+)%; \}/g)]
      .map(match => [match[1], Number(match[2])])
  );
  assert.equal(Object.values(widthByColumn).reduce((sum, width) => sum + width, 0), 100);
  for (const wide of ['purpose', 'range', 'note']) {
    for (const compact of ['type','name','array','unit']) {
      assert.ok(widthByColumn[wide] > widthByColumn[compact], wide + ' must be wider than ' + compact);
    }
  }
  assert.match(stylesheet, /\.compact-message-editor \.message-fields-card \.message-field-table/);
  assert.match(stylesheet, /min-width: 1520px/);
  assert.match(stylesheet, /\.message-field-table \.array-size-label\.compact \{ min-width: 0; \}/);
  assert.match(stylesheet, /\.message-field-table \.type-picker\.compact/);
});

test('the type combo is materially narrower than before, including its inner controls', () => {
  const widths = Object.fromEntries(
    [...stylesheet.matchAll(/\\.message-field-table \\.field-col-(\\w+) \\{ width: (\\d+)%; \\}/g)]
      .map(match => [match[1], Number(match[2])])
  );
  assert.equal(widths.type, 11);
  assert.equal(widths.purpose, 20);
  assert.equal(widths.range, 19);
  assert.equal(widths.note, 17);

  const typePicker = stylesheet.match(/\\.message-field-table \\.type-picker\\.compact \\{([\\s\\S]*?)\\}/);
  assert.ok(typePicker);
  assert.match(typePicker[1], /max-width: 170px/);
  assert.match(typePicker[1], /grid-template-columns: 62px minmax\\(0, 1fr\\)/);
  assert.match(stylesheet, /\\.message-field-table \\.type-picker\\.compact > select \\{[\\s\\S]*?font-size: 12px;/);

  const typeComponent = source.slice(source.indexOf('function TypeSelect('), source.indexOf('function ArraySizeControl('));
  assert.match(typeComponent, /title=\\{currentRefName\\}/);
  assert.match(typeComponent, /title=\\{value\\?\\.type \\|\\| "uint32"\\}/);
});
