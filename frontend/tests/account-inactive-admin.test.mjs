import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const start = source.indexOf('function AccountManagePage(');
const end = source.indexOf('function AccountPanel(', start);
const panel = source.slice(start, end);

test('admin account table shows active and legacy-inactive users with a status column', () => {
  assert.ok(start > 0 && end > start);
  assert.match(panel, /<th>상태<\/th>/);
  assert.match(panel, /user\.is_deleted \? '기존 비활성화' : '활성'/);
  assert.match(panel, /accountIdLabel\(user\)/);
  assert.match(styles, /\.account-status-label\.inactive/);
});

test('legacy-inactive users have a working delete action but no role editing', () => {
  assert.match(panel, /disabled=\{user\.id === me\?\.id \|\| user\.is_deleted\}/);
  assert.match(panel, /api\.del\(\`\/auth\/users\/\$\{user\.id\}\`\)/);
  assert.match(panel, /onClick=\{\(\) => deleteUser\(user\)\}/);
  assert.match(panel, /완전히 삭제할까요/);
  assert.doesNotMatch(panel, /비활성화 버튼|onClick=.*deactivate/);
});

test('old deleted accounts can show historical IDs instead of internal placeholders', () => {
  assert.match(panel, /user\.display_name/);
  assert.match(panel, /기존 삭제 계정 #/);
});
