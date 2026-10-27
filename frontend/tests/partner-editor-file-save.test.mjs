import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// The actual standalone HTML is executed in a stubbed browser environment.
// No server, dependencies or browser installation is required.
const html = readFileSync(new URL('../public/Interfy-Partner-Editor.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, 'standalone partner editor must have an inline script');

function harness({ openPicker, savePicker, secure = true } = {}) {
  const elements = new Map();
  const downloads = [];
  const alerts = [];
  const window = { isSecureContext: secure, addEventListener() {} };
  let inputClicks = 0;
  for (const id of ['open', 'file', 'save', 'validate', 'add', 'editor', 'tab-nodes',
                    'tab-messages', 'search', 'list', 'status', 'stats']) {
    elements.set(id, {
      listeners: {},
      classList: { toggle() {} },
      addEventListener(type, handler) { this.listeners[type] = handler; },
      click() { inputClicks++; },
      value: '',
      innerHTML: '',
      textContent: '',
      dataset: {},
      disabled: false
    });
  }
  if (openPicker) window.showOpenFilePicker = openPicker;
  if (savePicker) window.showSaveFilePicker = savePicker;
  const document = {
    getElementById(id) { return elements.get(id); },
    createElement() {
      const a = {
        download: '', href: '', remove() {},
        click() { downloads.push({ filename: a.download, href: a.href }); }
      };
      return a;
    },
    body: { appendChild() {} }
  };
  const context = {
    window, document, Blob, Set,
    confirm: () => true, alert: msg => alerts.push(msg),
    URL: { createObjectURL: () => 'blob:local', revokeObjectURL() {} },
    setTimeout() {}
  };
  vm.runInNewContext(script, context, { filename: 'Interfy-Partner-Editor.html' });
  return { elements, downloads, alerts, get inputClicks() { return inputClicks; } };
}
function sampleFile(name = 'partner.json') {
  return {
    name,
    async text() {
      return JSON.stringify({ format: 'interfy-project', project: { name: 'Test' },
                              integration_targets: [], messages: [] });
    }
  };
}
function handle(name = 'partner.json', { fail = false } = {}) {
  const writes = [];
  return {
    name, writes,
    async getFile() { return sampleFile(name); },
    async createWritable() {
      if (fail) throw Error('write permission denied');
      return {
        async write(contents) { writes.push(contents); },
        async close() {}
      };
    }
  };
}

test('opened JSON is saved to the original handle, never downloaded or renamed', async () => {
  const original = handle();
  let requested = 0;
  const app = harness({ openPicker: async () => { requested++; return [original]; } });
  await app.elements.get('open').listeners.click();
  assert.equal(requested, 1);
  assert.match(app.elements.get('status').textContent, /원본 덮어쓰기 가능/);
  app.elements.get('add').listeners.click();
  assert.match(app.elements.get('stats').textContent, /미저장/);
  await app.elements.get('save').listeners.click();
  assert.equal(original.writes.length, 1);
  assert.equal(JSON.parse(original.writes[0]).integration_targets[0].name, 'NEW_NODE');
  assert.equal(app.downloads.length, 0);
  assert.match(app.elements.get('status').textContent, /원본 JSON에 덮어썼습니다: partner.json/);
  assert.doesNotMatch(app.elements.get('stats').textContent, /미저장/);
});

test('save failure never creates a download and retains unsaved edits', async () => {
  const denied = handle('original.json', { fail: true });
  const app = harness({ openPicker: async () => [denied] });
  await app.elements.get('open').listeners.click();
  app.elements.get('add').listeners.click();
  await app.elements.get('save').listeners.click();
  assert.equal(app.downloads.length, 0);
  assert.match(app.elements.get('stats').textContent, /미저장/);
  assert.match(app.elements.get('status').textContent, /저장 실패/);
  assert.ok(app.alerts.length > 0);
});

test('unsupported browsers keep file-input opening and download fallback', async () => {
  const app = harness({ secure: false });
  await app.elements.get('open').listeners.click();
  assert.equal(app.inputClicks, 1);
  app.elements.get('file').listeners.change({ target: {
    files: [sampleFile('old.json')], value: 'old.json'
  } });
  await new Promise(resolve => setImmediate(resolve));
  await app.elements.get('save').listeners.click();
  assert.equal(app.downloads.length, 1);
  assert.equal(app.downloads[0].filename, 'old.json');
  assert.match(app.elements.get('status').textContent, /원본 파일은 덮어쓰지 않았습니다/);
});

test('file-input opening can explicitly choose a destination using save picker', async () => {
  const chosen = handle('chosen.json');
  const app = harness({ savePicker: async () => chosen });
  app.elements.get('file').listeners.change({ target: {
    files: [sampleFile('source.json')], value: 'source.json'
  } });
  await new Promise(resolve => setImmediate(resolve));
  await app.elements.get('save').listeners.click();
  assert.equal(chosen.writes.length, 1);
  assert.equal(app.downloads.length, 0);
  await app.elements.get('save').listeners.click();
  assert.equal(chosen.writes.length, 2);
  assert.match(app.elements.get('status').textContent, /원본 JSON에 덮어썼습니다: chosen.json/);
});
