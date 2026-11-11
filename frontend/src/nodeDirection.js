// Direction filters are always relative to the first (primary) selected node.
// The secondary node, when present, only limits which peer is visible.
export const NODE_DIRECTION_ALL = 'ALL';
export const NODE_DIRECTION_TX = 'TX';
export const NODE_DIRECTION_RX = 'RX';

export function relationMatchesNodeDirection(relation, primaryId, direction = NODE_DIRECTION_ALL) {
  if (primaryId == null || direction === NODE_DIRECTION_ALL) return true;
  if (direction === NODE_DIRECTION_TX) return Number(relation.fromId) === Number(primaryId);
  if (direction === NODE_DIRECTION_RX) return Number(relation.toId) === Number(primaryId);
  return true;
}

export function messageMatchesNodeDirection(message, primaryId, direction = NODE_DIRECTION_ALL) {
  if (primaryId == null) return true;
  const tx = (message.tx_targets || []).some(node => Number(node.id) === Number(primaryId));
  const rx = (message.rx_targets || []).some(node => Number(node.id) === Number(primaryId));
  if (direction === NODE_DIRECTION_TX) return tx;
  if (direction === NODE_DIRECTION_RX) return rx;
  return tx || rx;
}

export function nodeDirectionLabel(direction) {
  return direction === NODE_DIRECTION_TX ? '송신만' : direction === NODE_DIRECTION_RX ? '수신만' : '송신 + 수신';
}
