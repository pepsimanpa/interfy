import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pairKey, groupTransportLinks, filterTransportConnections } from '../src/systemTopologyData.js';

const sample = [
  { id: 1, server_node_id: 7, client_node_id: 1, protocol: 'TCP' },
  { id: 2, server_node_id: 7, client_node_id: 1, protocol: 'TCP' },
  { id: 3, server_node_id: 7, client_node_id: 1, protocol: 'UDP' },
  { id: 4, server_node_id: 1, client_node_id: 7, protocol: 'TCP' },
  { id: 5, server_node_id: 7, client_node_id: 9, protocol: 'UDP' },
];

test('related TCP and UDP connections share one directed graph edge', () => {
  const edges = groupTransportLinks(sample);
  assert.equal(edges.length, 3);
  const pair = edges.find(edge => edge.key === pairKey(7, 1));
  assert.deepEqual(pair.connections.map(row => row.id), [1, 2, 3]);
  assert.deepEqual(pair.protocols, ['TCP', 'UDP']);
});

test('opposite directions remain separate links', () => {
  const edges = groupTransportLinks(sample);
  assert.ok(edges.find(edge => edge.key === '7->1'));
  assert.ok(edges.find(edge => edge.key === '1->7'));
});

test('clicking a graph edge lists only its exact TCP/UDP connections', () => {
  assert.deepEqual(
    filterTransportConnections(sample, [], '7->1').map(row => row.id),
    [1, 2, 3],
  );
  assert.deepEqual(
    filterTransportConnections(sample, [], '7->1', 'UDP').map(row => row.id),
    [3],
  );
});

test('selecting one or two nodes filters relations like Interface Design', () => {
  assert.deepEqual(
    filterTransportConnections(sample, [7]).map(row => row.id),
    [1, 2, 3, 4, 5],
  );
  assert.deepEqual(
    filterTransportConnections(sample, [7, 1]).map(row => row.id),
    [1, 2, 3, 4],
  );
});

test('unlinked nodes are represented only as node entries, not fake edges', () => {
  assert.deepEqual(groupTransportLinks([{ id: 1, server_node_id: null, client_node_id: 3 }]), []);
});

const main = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const panel = readFileSync(new URL('../src/SystemConfigurationPanel.jsx', import.meta.url), 'utf8');
const graph = readFileSync(new URL('../src/SystemTopologyGraph.jsx', import.meta.url), 'utf8');

test('system configuration uses the existing node manager drawer', () => {
  assert.match(main, /<ReferenceSidePanel[\s\S]*?nodeOnly/);
  assert.match(main, /onOpenNodeManager=\{editTargetId =>/);
  assert.match(panel, /onOpenNodeManager\(nodeId\)/);
  assert.match(graph, /className="design-floating-add"/);
});

test('IP/NIC supports fixed and AUTO port binding and selected binding links', () => {
  assert.match(panel, /포트 바인딩/);
  assert.match(panel, /자동 \(AUTO\)/);
  assert.match(panel, /port_mode === 'AUTO'/);
  assert.match(panel, /server_binding_id:/);
  assert.match(panel, /client_binding_id:/);
  assert.match(panel, /<SystemTopologyGraph/);
});

test('the graph selects a connection edge and filters its detail list below', () => {
  assert.match(graph, /onSelectPair\(relation\.key\)/);
  assert.match(panel, /filterTransportConnections\(/);
  assert.match(panel, /shownConnections\.map\(item =>/);
  assert.match(panel, /선택한 연결선의 TCP \/ UDP 목록/);
});
