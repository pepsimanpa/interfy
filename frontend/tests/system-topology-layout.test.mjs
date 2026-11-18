import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const panel = readFileSync(new URL('../src/SystemConfigurationPanel.jsx', import.meta.url), 'utf8');
const graph = readFileSync(new URL('../src/SystemTopologyGraph.jsx', import.meta.url), 'utf8');

test('system topology is a permanent top section, before the three management tabs', () => {
  const topology = panel.indexOf('<section className="card system-topology-card"');
  const tabs = panel.indexOf('<div className="system-config-tabs"');
  const connectionContent = panel.indexOf("{loaded && tab === 'connections'");
  assert.ok(topology >= 0 && topology < tabs && tabs < connectionContent);
  assert.equal(panel.split('<SystemTopologyGraph').length - 1, 1);
  assert.match(panel, /<h3>체계 구성도<\/h3>/);
  assert.doesNotMatch(panel, /인터페이스 설계의 노드를 기준으로 장비 ID/);
});

test('graph remains available across all three tabs', () => {
  for (const tab of ['nodes', 'ips', 'connections']) {
    assert.match(panel, new RegExp("tab === '" + tab + "'"));
  }
  assert.match(panel, /\{loaded \? \(\s*<SystemTopologyGraph/);
  assert.match(panel, /선택한 연결선의 TCP \/ UDP 목록/);
});

test('selecting graph connections opens the detail tab automatically', () => {
  assert.match(panel, /function selectGraphPair\(key\) \{\s*setTab\('connections'\);/);
  assert.match(panel, /function selectGraphNode\(id\) \{\s*setTab\('connections'\);/);
  assert.doesNotMatch(graph, /<strong>통신 연결 관계도<\/strong>/);
});
