// Shared, framework-independent rules for the node-centered relationship viewer.
export function nextNodePairSelection(primaryId, secondaryId, clickedId) {
  const clicked = Number(clickedId);
  if (primaryId == null) return { primaryId: clicked, secondaryId: null };
  const primary = Number(primaryId);
  if (clicked === primary) {
    return { primaryId: secondaryId == null ? null : Number(secondaryId), secondaryId: null };
  }
  if (secondaryId != null && clicked === Number(secondaryId)) {
    return { primaryId: primary, secondaryId: null };
  }
  // The third selection replaces the second; a maximum of two stay selected.
  return { primaryId: primary, secondaryId: clicked };
}

export function isRelationBetweenNodes(relation, primaryId, secondaryId) {
  if (primaryId == null || secondaryId == null) return false;
  const from = Number(relation.fromId), to = Number(relation.toId);
  const first = Number(primaryId), second = Number(secondaryId);
  return (from === first && to === second) || (from === second && to === first);
}

export function isMessageInRelations(message, relations) {
  return relations.some(relation =>
    (relation.messages || []).some(item => Number(item.id) === Number(message.id))
  );
}
