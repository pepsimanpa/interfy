import React, { useMemo } from 'react';
import { Layers, Network, Plus } from 'lucide-react';
import { groupTransportLinks } from './systemTopologyData.js';
export { pairKey, groupTransportLinks } from './systemTopologyData.js';

/** Node/edge rendering intentionally reuses the existing Interface Design graph CSS. */
function compactName(value, limit = 15) {
  const text = String(value || '');
  return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
}

function ringLayout(nodes, focusIds = []) {
  const visible = focusIds.length ? nodes.filter(item => focusIds.includes(item.node_id)) : nodes;
  const map = new Map(), centerX = 450, centerY = 195;
  if (visible.length === 1) {
    map.set(visible[0].node_id, { x: centerX, y: centerY });
    return map;
  }
  if (visible.length === 2 && focusIds.length === 2) {
    map.set(visible[0].node_id, { x: 285, y: centerY });
    map.set(visible[1].node_id, { x: 615, y: centerY });
    return map;
  }
  const inner = visible.length > 8 ? visible.slice(0, 5) : visible;
  const outer = visible.length > 8 ? visible.slice(5) : [];
  function place(items, rx, ry, offset = -Math.PI / 2) {
    items.forEach((node, index) => {
      const angle = offset + 2 * Math.PI * index / Math.max(items.length, 1);
      map.set(node.node_id, { x: centerX + Math.cos(angle) * rx, y: centerY + Math.sin(angle) * ry });
    });
  }
  place(inner, inner.length > 6 ? 240 : 310, inner.length > 6 ? 105 : 135);
  place(outer, 338, 151);
  return map;
}

function edgePath(relation, positions) {
  const a = positions.get(relation.fromId), b = positions.get(relation.toId);
  if (!a || !b) return '';
  if (relation.fromId === relation.toId) {
    return `M ${a.x + 40} ${a.y - 8} C ${a.x + 135} ${a.y - 110}, ${a.x - 135} ${a.y - 110}, ${a.x - 40} ${a.y - 8}`;
  }
  const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
  const nx = dx / length, ny = dy / length;
  const side = Math.abs(dx) > Math.abs(dy) ? Math.sign(dx) : 0;
  const ax = a.x + (side ? side * 49 : nx * 27);
  const ay = a.y + (side ? 0 : ny * 22);
  const bx = b.x - (side ? side * 49 : nx * 27);
  const by = b.y - (side ? 0 : ny * 22);
  // A constant side offset relative to travel direction ensures A→B and
  // B→A curve on opposite sides, instead of drawing over each other.
  const bend = 18;
  const offX = -ny * bend, offY = nx * bend;
  return `M ${ax} ${ay} Q ${(ax+bx)/2+offX} ${(ay+by)/2+offY} ${bx} ${by}`;
}

export default function SystemTopologyGraph({
  nodes = [], connections = [],
  selectedNodeIds = [], selectedPairKey = null,
  onSelectNode, onSelectPair, onShowAll, onEditNode, onOpenNodeManager,
  protocolFilter = 'ALL', onChangeProtocolFilter,
}) {
  const relations = useMemo(() => groupTransportLinks(connections.filter(
    row => protocolFilter === 'ALL' || row.protocol === protocolFilter,
  )), [connections, protocolFilter]);

  const focused = selectedNodeIds.length > 0;
  const graphEdges = relations.filter(relation => {
    if (!focused) return true;
    if (selectedNodeIds.length === 1) {
      return relation.fromId === selectedNodeIds[0] || relation.toId === selectedNodeIds[0];
    }
    return selectedNodeIds.includes(relation.fromId) && selectedNodeIds.includes(relation.toId);
  });
  const visibleIds = new Set();
  if (!focused) nodes.forEach(n => visibleIds.add(n.node_id));
  else {
    selectedNodeIds.forEach(id => visibleIds.add(id));
    graphEdges.forEach(edge => { visibleIds.add(edge.fromId); visibleIds.add(edge.toId); });
  }
  const visibleNodes = nodes.filter(node => visibleIds.has(node.node_id));
  const positions = ringLayout(visibleNodes, selectedNodeIds.length === 2 ? selectedNodeIds : []);
  const selectedSet = new Set(selectedNodeIds);

  return (
    <section className="system-topology-view" aria-label="체계 통신 연결 관계도">
      <aside className="design-device-pane system-topology-node-pane">
        <div className="design-pane-title"><strong>노드</strong><span>최대 2개 선택</span></div>
        <button type="button" className={!focused && !selectedPairKey ? 'design-device active' : 'design-device'} onClick={onShowAll}>
          <Layers size={14}/><span>전체</span>
        </button>
        {nodes.map(node => (
          <button key={node.node_id} type="button"
            className={selectedSet.has(node.node_id) ? 'design-device active' : 'design-device'}
            aria-pressed={selectedSet.has(node.node_id)}
            title={node.name + '\n클릭: 관계 필터 · 더블클릭: 노드 관리'}
            onClick={() => onSelectNode(node.node_id)}
            onDoubleClick={event => { event.preventDefault(); event.stopPropagation(); onEditNode(node.node_id); }}>
            <span className="device-dot"/><span>{node.name}</span>
          </button>
        ))}
      </aside>
      <div className="design-canvas-pane system-topology-canvas">
        <div className="design-toolbar system-topology-toolbar">
          <div className="design-filter-field">
            <span>프로토콜</span>
            <select aria-label="관계도 프로토콜 필터" value={protocolFilter} onChange={event => onChangeProtocolFilter(event.target.value)}>
              <option value="ALL">전체</option>
              <option value="TCP">TCP</option>
              <option value="UDP">UDP</option>
            </select>
          </div>
          <span className="design-toolbar-summary">{visibleNodes.length} 노드 · {graphEdges.length} 관계</span>
        </div>
        <button type="button" className="design-floating-add" title="노드 추가·관리" aria-label="노드 추가·관리" onClick={() => onOpenNodeManager()}><Plus size={19}/></button>
        <div className="design-svg-wrap">
          {nodes.length ? (
            <svg className="design-network" viewBox="0 0 900 390" role="img" aria-label="TCP UDP 노드 통신 연결 관계">
              <defs>
                <marker id="systemConnectionArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
                  <path d="M0 0 L8 4 L0 8z" className="design-arrow-head"/>
                </marker>
              </defs>
              {graphEdges.map(relation => {
                const path = edgePath(relation, positions);
                const active = relation.key === selectedPairKey;
                const centerFrom = positions.get(relation.fromId), centerTo = positions.get(relation.toId);
                if (!path || !centerFrom || !centerTo) return null;
                const dx = centerTo.x - centerFrom.x, dy = centerTo.y - centerFrom.y;
                const distance = Math.hypot(dx, dy) || 1;
                const mx = relation.fromId === relation.toId ? centerFrom.x : (centerFrom.x + centerTo.x) / 2 - dy / distance * 21;
                const my = relation.fromId === relation.toId ? centerFrom.y - 76 : (centerFrom.y + centerTo.y) / 2 + dx / distance * 21 - 12;
                const label = (relation.protocols.length === 1 ? relation.protocols[0] : 'TCP/UDP') + ' · ' + relation.connections.length + '건';
                const labelWidth = Math.max(76, label.length * 7 + 18);
                return (
                  <g key={relation.key} className={active ? 'design-edge active' : 'design-edge'}
                    role="button" tabIndex={0} aria-label={relation.key + ' 연결 ' + relation.connections.length + '건'}
                    onClick={() => onSelectPair(relation.key)}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelectPair(relation.key); } }}>
                    <path className="design-edge-hit" d={path}/>
                    <path className="design-edge-line" d={path} markerEnd="url(#systemConnectionArrow)"/>
                    <g className="design-edge-label" transform={`translate(${mx},${my})`}>
                      <rect x={-labelWidth / 2} y="-10" width={labelWidth} height="20" rx="10"/>
                      <text textAnchor="middle" dy="3.5">{label}</text>
                    </g>
                  </g>
                );
              })}
              {visibleNodes.map(node => {
                const p = positions.get(node.node_id) || { x: 450, y: 195 };
                return (
                  <g key={node.node_id} className={selectedSet.has(node.node_id) ? 'design-node active' : 'design-node'}
                    transform={`translate(${p.x},${p.y})`}
                    role="button" tabIndex={0} aria-label={node.name + ' 노드'}
                    onClick={() => onSelectNode(node.node_id)}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelectNode(node.node_id); } }}
                    onDoubleClick={e => { e.preventDefault(); e.stopPropagation(); onEditNode(node.node_id); }}>
                    <rect x="-68" y="-22" width="136" height="44" rx="8"/>
                    <text className="design-node-name" textAnchor="middle" y="-3" style={{fontSize:12}}>{compactName(node.name)}</text>
                    <text className="design-node-meta" textAnchor="middle" y="12">{node.device_id == null ? '노드' : 'Device ' + node.device_id}</text>
                  </g>
                );
              })}
            </svg>
          ) : <div className="design-empty-graph">
            <Network size={29}/><strong>등록된 노드가 없습니다.</strong>
            <span>+ 버튼으로 노드를 먼저 등록하세요.</span>
          </div>}
        </div>
      </div>
    </section>
  );
}
