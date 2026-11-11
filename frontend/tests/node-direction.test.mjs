import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  NODE_DIRECTION_ALL, NODE_DIRECTION_TX, NODE_DIRECTION_RX,
  relationMatchesNodeDirection, messageMatchesNodeDirection, nodeDirectionLabel,
} from '../src/nodeDirection.js';

const src = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');

const aToB = { id: 1, tx_targets: [{ id: 10 }], rx_targets: [{ id: 20 }] };
const bToA = { id: 2, tx_targets: [{ id: 20 }], rx_targets: [{ id: 10 }] };
const aToA = { id: 3, tx_targets: [{ id: 10 }], rx_targets: [{ id: 10 }] };
const onlyTx = { id: 4, tx_targets: [{ id: 10 }], rx_targets: [] };
const onlyRx = { id: 5, tx_targets: [], rx_targets: [{ id: 10 }] };
const unrelated = { id: 6, tx_targets: [{ id: 30 }], rx_targets: [{ id: 20 }] };
const links = [
  { fromId: 10, toId: 20 },
  { fromId: 20, toId: 10 },
  { fromId: 10, toId: 10 },
  { fromId: 30, toId: 20 },
];

test('single node direction filter shows only outgoing or incoming messages', () => {
  const list = [aToB,bToA,aToA,onlyTx,onlyRx,unrelated];
  assert.deepEqual(list.filter(m => messageMatchesNodeDirection(m, 10, NODE_DIRECTION_ALL)).map(m => m.id), [1,2,3,4,5]);
  assert.deepEqual(list.filter(m => messageMatchesNodeDirection(m, 10, NODE_DIRECTION_TX)).map(m => m.id), [1,3,4]);
  assert.deepEqual(list.filter(m => messageMatchesNodeDirection(m, 10, NODE_DIRECTION_RX)).map(m => m.id), [2,3,5]);
  assert.ok(messageMatchesNodeDirection(unrelated, null, NODE_DIRECTION_TX));
});

test('directions also filter graph edges relative to primary node', () => {
  assert.deepEqual(links.filter(link => relationMatchesNodeDirection(link, 10, NODE_DIRECTION_TX)), [links[0], links[2]]);
  assert.deepEqual(links.filter(link => relationMatchesNodeDirection(link, 10, NODE_DIRECTION_RX)), [links[1], links[2]]);
  assert.equal(relationMatchesNodeDirection(links[0], 20, NODE_DIRECTION_RX), true);
  assert.equal(relationMatchesNodeDirection(links[0], 20, NODE_DIRECTION_TX), false);
  assert.equal(relationMatchesNodeDirection(links[0], null, NODE_DIRECTION_RX), true);
});

test('direction names clearly describe the selected node', () => {
  assert.equal(nodeDirectionLabel(NODE_DIRECTION_ALL), '송신 + 수신');
  assert.equal(nodeDirectionLabel(NODE_DIRECTION_TX), '송신만');
  assert.equal(nodeDirectionLabel(NODE_DIRECTION_RX), '수신만');
});

test('node-centered graph and message list share direction and relation filters', () => {
  const designStart = src.indexOf('function InterfaceDesignPanel(');
  const designEnd = src.indexOf('function MessageNameSearch(');
  const design = src.slice(designStart,designEnd);
  assert.ok(designStart > 0 && designEnd > designStart);
  assert.match(design, /const \[nodeDirection, setNodeDirection\] = useState\(NODE_DIRECTION_ALL\)/);
  assert.match(design, /relationMatchesNodeDirection\(relation, selectedDeviceId, nodeDirection\)/);
  assert.match(design, /messageMatchesNodeDirection\(message, selectedDeviceId, nodeDirection\)/);
  assert.match(design, /isMessageInRelations\(message, graphRelations\)/);
  assert.match(design, /const selectedRelation = graphRelations\.find/);
  assert.match(design, /onNodeDirectionChange=\{direction =>/);
  assert.match(src, /aria-label="선택 노드 송수신 방향"/);
  assert.match(src, /<option value=\{NODE_DIRECTION_TX\}>송신만<\/option>/);
  assert.match(src, /<option value=\{NODE_DIRECTION_RX\}>수신만<\/option>/);
  assert.match(design, /setNodeDirection\(NODE_DIRECTION_ALL\)/);
  const viewerPart = src.slice(src.indexOf('function MessageCenteredVisualization('),src.indexOf('function DesignVisualizationTop('));
  assert.doesNotMatch(viewerPart, /design-node-direction-field/);
});
