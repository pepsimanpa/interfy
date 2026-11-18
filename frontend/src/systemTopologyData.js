/** Shared transport topology grouping, independent of React/SVG. */
export function pairKey(serverNodeId, clientNodeId) {
  return String(serverNodeId) + '->' + String(clientNodeId);
}

export function groupTransportLinks(connections = []) {
  const grouped = new Map();
  for (const item of connections) {
    if (item.server_node_id == null || item.client_node_id == null) continue;
    const key = pairKey(item.server_node_id, item.client_node_id);
    if (!grouped.has(key)) grouped.set(key, {
      key, fromId: item.server_node_id, toId: item.client_node_id,
      connections: [], protocols: new Set(),
    });
    const relation = grouped.get(key);
    relation.connections.push(item);
    relation.protocols.add(item.protocol);
  }
  return [...grouped.values()].map(row => ({ ...row, protocols: [...row.protocols] }));
}

export function filterTransportConnections(connections = [], selectedNodes = [], selectedPairKey = null, protocolFilter = 'ALL') {
  return connections.filter(item => {
    if (protocolFilter !== 'ALL' && item.protocol !== protocolFilter) return false;
    if (selectedPairKey) return pairKey(item.server_node_id, item.client_node_id) === selectedPairKey;
    if (selectedNodes.length === 1) {
      return item.server_node_id === selectedNodes[0] || item.client_node_id === selectedNodes[0];
    }
    if (selectedNodes.length === 2) {
      return selectedNodes.includes(item.server_node_id) && selectedNodes.includes(item.client_node_id);
    }
    return true;
  });
}
