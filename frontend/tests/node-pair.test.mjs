import test from 'node:test';
import assert from 'node:assert/strict';
import { nextNodePairSelection, isRelationBetweenNodes, isMessageInRelations } from '../src/nodePair.js';

test('single node expands to pair, and clicking the second node returns to one', () => {
  const single = nextNodePairSelection(null, null, 11);
  assert.deepEqual(single, { primaryId: 11, secondaryId: null });
  const pair = nextNodePairSelection(single.primaryId, single.secondaryId, 22);
  assert.deepEqual(pair, { primaryId: 11, secondaryId: 22 });
  assert.deepEqual(nextNodePairSelection(11, 22, 22), { primaryId: 11, secondaryId: null });
  assert.deepEqual(nextNodePairSelection(11, 22, 11), { primaryId: 22, secondaryId: null });
  assert.deepEqual(nextNodePairSelection(11, null, 11), { primaryId: null, secondaryId: null });
});

test('third node replaces second rather than adding a third or clearing focus', () => {
  assert.deepEqual(nextNodePairSelection(11, 22, 33), { primaryId: 11, secondaryId: 33 });
});

test('pair view shows A->B and B->A, not other edges or same-direction sender sets', () => {
  const relations = [
    { fromId: 11, toId: 22, messages: [{ id: 101 }] },
    { fromId: 22, toId: 11, messages: [{ id: 102 }] },
    { fromId: 11, toId: 33, messages: [{ id: 103 }] },
    { fromId: 22, toId: 33, messages: [{ id: 104 }] },
  ];
  const matching = relations.filter(relation => isRelationBetweenNodes(relation, 11, 22));
  assert.equal(matching.length, 2);
  assert.equal(isMessageInRelations({ id: 101 }, matching), true);
  assert.equal(isMessageInRelations({ id: 102 }, matching), true);
  assert.equal(isMessageInRelations({ id: 103 }, matching), false);
  assert.equal(isMessageInRelations({ id: 104 }, matching), false);
  assert.equal(isRelationBetweenNodes(relations[0], null, 22), false);
});

test('two nodes with no relation produce zero matches', () => {
  const relations = [{ fromId: 11, toId: 22, messages: [{ id: 101 }] }];
  const matching = relations.filter(relation => isRelationBetweenNodes(relation, 11, 33));
  assert.deepEqual(matching, []);
  assert.equal(isMessageInRelations({ id: 101 }, matching), false);
});
