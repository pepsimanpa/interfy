import React, { useEffect, useMemo, useState } from 'react';
import { Cable, Cpu, EthernetPort, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import './systemConfiguration.css';
import SystemTopologyGraph from './SystemTopologyGraph.jsx';
import { filterTransportConnections } from './systemTopologyData.js';

const EMPTY_CONFIGURATION = { nodes: [], ip_assignments: [], port_bindings: [], connections: [] };
const EMPTY_IP = { node_id: '', interface_name: '', ip_address: '', note: '' };
const EMPTY_PORT = { ip_assignment_id: '', protocol: 'TCP', port_mode: 'FIXED', port: '', description: '' };
const EMPTY_CONNECTION = { server_binding_id: '', client_binding_id: '', note: '' };

function NodePicker({ nodes, value, onChange, label = '노드' }) {
  return (
    <label><span className="system-config-label-text">{label}</span>
                <select value={value} onChange={event => onChange(event.target.value)}>
        <option value="">노드 선택</option>
        {nodes.map(node => <option key={node.node_id} value={node.node_id}>{node.name}</option>)}
      </select>
    </label>
  );
}

export default function SystemConfigurationPanel({ api, projectId, integrationTargets = [], onOpenNodeManager }) {
  const [tab, setTab] = useState('connections');
  const [configuration, setConfiguration] = useState(EMPTY_CONFIGURATION);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [nodeId, setNodeId] = useState('');
  const [profile, setProfile] = useState({});
  const [ipDraft, setIpDraft] = useState(EMPTY_IP);
  const [editingIp, setEditingIp] = useState(null);
  const [portDraft, setPortDraft] = useState(EMPTY_PORT);
  const [editingPort, setEditingPort] = useState(null);
  const [connectionDraft, setConnectionDraft] = useState(EMPTY_CONNECTION);
  const [selectedGraphNodes, setSelectedGraphNodes] = useState([]);
  const [selectedPairKey, setSelectedPairKey] = useState(null);
  const [topologyFilter, setTopologyFilter] = useState('ALL');
  const [editingConnection, setEditingConnection] = useState(null);

  const base = `/projects/${projectId}/system-configuration`;
  const nodes = configuration.nodes;
  const ips = configuration.ip_assignments;
  const bindings = configuration.port_bindings || [];
  const connections = configuration.connections;
  const shownConnections = filterTransportConnections(
    connections, selectedGraphNodes, selectedPairKey, topologyFilter,
  );
  const bindingById = new Map(bindings.map(item => [String(item.id), item]));
  const chosenServerBinding = bindingById.get(String(connectionDraft.server_binding_id));
  const compatibleClientBindings = chosenServerBinding
    ? bindings.filter(binding => binding.protocol === chosenServerBinding.protocol)
    : bindings;
  const node = useMemo(() => nodes.find(item => String(item.node_id) === String(nodeId)), [nodes, nodeId]);

  async function reload() {
    const data = await api.get(base);
    setConfiguration(data);
    setLoaded(true);
    setNodeId(current => data.nodes.some(row => String(row.node_id) === String(current)) ? current : (data.nodes[0]?.node_id ? String(data.nodes[0].node_id) : ''));
    return data;
  }

  useEffect(() => {
    setLoaded(false);
    setNodeId('');
    setIpDraft(EMPTY_IP);
    setEditingIp(null);
    setPortDraft(EMPTY_PORT);
    setEditingPort(null);
    setSelectedGraphNodes([]);
    setSelectedPairKey(null);
    setConnectionDraft(EMPTY_CONNECTION);
    setEditingConnection(null);
    setNotice('');
    reload().catch(error => setNotice(error.message));
  }, [projectId, integrationTargets]);

  useEffect(() => {
    setProfile({
      device_id: node?.device_id == null ? '' : String(node.device_id),
      hardware_name: node?.hardware_name || '',
      hostname: node?.hostname || '',
      hardware_id: node?.hardware_id || '',
      software_id: node?.software_id || '',
      note: node?.note || '',
    });
  }, [nodeId, node?.device_id, node?.hardware_name, node?.hostname, node?.hardware_id, node?.software_id, node?.note]);

  async function execute(action, successMessage) {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      await action();
      await reload();
      setNotice(successMessage);
    } catch (error) {
      setNotice(`처리 실패: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveNode(event) {
    event.preventDefault();
    if (!nodeId) return;
    await execute(async () => {
      await api.put(`${base}/nodes/${nodeId}`, {
        ...profile, device_id: profile.device_id === '' ? null : Number(profile.device_id),
      });
    }, '장비·SW 식별 정보를 저장했습니다.');
  }

  function selectIpForEdit(item) {
    setEditingIp(item.id);
    setIpDraft({ node_id: String(item.node_id), interface_name: item.interface_name, ip_address: item.ip_address, note: item.note || '' });
  }

  function clearIpForm() {
    setEditingIp(null);
    setIpDraft({ ...EMPTY_IP, node_id: nodeId || (nodes[0]?.node_id ? String(nodes[0].node_id) : '') });
  }

  async function saveIp(event) {
    event.preventDefault();
    await execute(async () => {
      const body = { ...ipDraft, node_id: Number(ipDraft.node_id), ip_address: ipDraft.ip_address.trim() };
      if (editingIp !== null) await api.patch(`${base}/ips/${editingIp}`, body);
      else await api.post(`${base}/ips`, body);
      clearIpForm();
    }, editingIp !== null ? 'IP 할당을 수정했습니다.' : 'IP를 등록했습니다.');
  }

  async function deleteIp(item) {
    if (!confirm(`${item.node_name} · ${item.ip_address} 할당을 삭제할까요?`)) return;
    await execute(async () => {
      await api.del(`${base}/ips/${item.id}`);
      if (editingIp === item.id) clearIpForm();
    }, 'IP 할당을 삭제했습니다.');
  }

  function clearPortForm() {
    setEditingPort(null);
    setPortDraft({ ...EMPTY_PORT, ip_assignment_id: ips[0]?.id ? String(ips[0].id) : '' });
  }

  function selectPortForEdit(item) {
    setEditingPort(item.id);
    setPortDraft({
      ip_assignment_id: String(item.ip_assignment_id), protocol: item.protocol,
      port_mode: item.port_mode, port: item.port == null ? '' : String(item.port),
      description: item.description || '',
    });
    setTab('ips');
  }

  async function savePort(event) {
    event.preventDefault();
    const editing = editingPort;
    await execute(async () => {
      const body = {
        ip_assignment_id: Number(portDraft.ip_assignment_id),
        protocol: portDraft.protocol, port_mode: portDraft.port_mode,
        port: portDraft.port_mode === 'AUTO' ? null : Number(portDraft.port),
        description: portDraft.description,
      };
      if (editing !== null) await api.patch(`${base}/ports/${editing}`, body);
      else await api.post(`${base}/ports`, body);
      clearPortForm();
    }, editing !== null ? '포트 바인딩을 수정했습니다.' : '포트 바인딩을 등록했습니다.');
  }

  async function deletePort(item) {
    if (!confirm(`${item.node_name} · ${item.protocol} ${item.port_mode === 'AUTO' ? 'AUTO' : item.port} 바인딩을 삭제할까요?`)) return;
    await execute(async () => {
      await api.del(`${base}/ports/${item.id}`);
      if (editingPort === item.id) clearPortForm();
    }, '포트 바인딩을 삭제했습니다.');
  }

  function selectGraphNode(id) {
    setTab('connections');
    setSelectedPairKey(null);
    setSelectedGraphNodes(current => {
      if (current.includes(id)) return current.filter(value => value !== id);
      return current.length >= 2 ? [id] : [...current, id];
    });
  }

  function selectGraphPair(key) {
    setTab('connections');
    setSelectedGraphNodes([]);
    setSelectedPairKey(current => current === key ? null : key);
  }

  function showAllGraph() {
    setSelectedGraphNodes([]);
    setSelectedPairKey(null);
  }

  function selectConnectionForEdit(item) {
    setEditingConnection(item.id);
    setConnectionDraft({
      server_binding_id: item.server_binding_id == null ? '' : String(item.server_binding_id),
      client_binding_id: item.client_binding_id == null ? '' : String(item.client_binding_id),
      note: item.note || '',
    });
  }

  async function saveConnection(event) {
    event.preventDefault();
    await execute(async () => {
      const body = {
        ...connectionDraft,
        server_binding_id: Number(connectionDraft.server_binding_id),
        client_binding_id: Number(connectionDraft.client_binding_id),
      };
      if (editingConnection !== null) await api.patch(`${base}/connections/${editingConnection}`, body);
      else await api.post(`${base}/connections`, body);
      setEditingConnection(null);
      setConnectionDraft(EMPTY_CONNECTION);
    }, editingConnection !== null ? '통신 연결을 수정했습니다.' : '통신 연결을 추가했습니다.');
  }

  async function deleteConnection(item) {
    if (!confirm(`${item.server_ip}:${item.server_port} ↔ ${item.client_ip} 연결을 삭제할까요?`)) return;
    await execute(async () => {
      await api.del(`${base}/connections/${item.id}`);
      if (editingConnection === item.id) { setEditingConnection(null); setConnectionDraft(EMPTY_CONNECTION); }
    }, '통신 연결을 삭제했습니다.');
  }

  return (
    <div className="system-config-page">
      <section className="card system-topology-card" aria-label="체계 구성도">
        <div className="card-title">
          <h3>체계 구성도</h3>
          <div className="system-topology-actions">
            <button type="button" className="ghost" onClick={showAllGraph} disabled={!loaded}>전체 보기</button>
            <button type="button" className="ghost" onClick={() => execute(reload, '최신 정보를 불러왔습니다.')} disabled={busy}><RefreshCw size={15}/> 새로고침</button>
          </div>
        </div>
        {loaded ? (
            <SystemTopologyGraph
              nodes={nodes} connections={connections}
              selectedNodeIds={selectedGraphNodes} selectedPairKey={selectedPairKey}
              onSelectNode={selectGraphNode} onSelectPair={selectGraphPair}
              onShowAll={showAllGraph}
              onEditNode={nodeId => onOpenNodeManager(nodeId)}
              onOpenNodeManager={onOpenNodeManager}
              protocolFilter={topologyFilter} onChangeProtocolFilter={setTopologyFilter}
            />
        ) : <div className="system-topology-loading">체계 구성 정보를 불러오는 중...</div>}
      </section>

      <div className="system-config-tabs" role="tablist" aria-label="체계 구성 관리">
        <button type="button" role="tab" aria-selected={tab === 'nodes'} className={tab === 'nodes' ? 'active' : ''} onClick={() => setTab('nodes')}><Cpu size={16}/> 장비·SW</button>
        <button type="button" role="tab" aria-selected={tab === 'ips'} className={tab === 'ips' ? 'active' : ''} onClick={() => setTab('ips')}><EthernetPort size={16}/> IP·NIC</button>
        <button type="button" role="tab" aria-selected={tab === 'connections'} className={tab === 'connections' ? 'active' : ''} onClick={() => setTab('connections')}><Cable size={16}/> 통신 연결</button>
      </div>

      {notice && <div className="notice" role="status">{notice}</div>}

      {loaded && tab === 'nodes' && (
        <div className="system-config-stack">
          <div className="system-config-split">
            <section className="card system-config-input">
              <h3>노드 정보 편집</h3>
              {node ? (
                <>
                  <p className="system-config-node-choice">선택 노드: <strong>{node.name}</strong></p>
                  <form className="system-config-form system-config-form-compact" onSubmit={saveNode}>
              <label><span className="system-config-label-text">Device ID</span><input type="number" min="1" placeholder="예: 7" value={profile.device_id ?? ''} onChange={e => setProfile({ ...profile, device_id: e.target.value })}/></label>
              <label><span className="system-config-label-text">탑재 HW</span><input value={profile.hardware_name || ''} maxLength={120} placeholder="예: 체계관리기" onChange={e => setProfile({ ...profile, hardware_name: e.target.value })}/></label>
              <label><span className="system-config-label-text">Hostname</span><input value={profile.hostname || ''} maxLength={120} placeholder="장치 이름" onChange={e => setProfile({ ...profile, hostname: e.target.value })}/></label>
              <label><span className="system-config-label-text">SW 고유 ID</span><input value={profile.software_id || ''} maxLength={120} onChange={e => setProfile({ ...profile, software_id: e.target.value })}/></label>
              <label><span className="system-config-label-text">HW 고유 ID</span><input value={profile.hardware_id || ''} maxLength={120} onChange={e => setProfile({ ...profile, hardware_id: e.target.value })}/></label>
              <label className="wide"><span className="system-config-label-text">비고</span><textarea value={profile.note || ''} onChange={e => setProfile({ ...profile, note: e.target.value })}/></label>
              <div className="system-config-actions"><button disabled={busy} type="submit"><Save size={15}/> 저장</button></div>
            </form>
                </>
              ) : (
                <p className="system-config-node-choice">오른쪽 목록에서 편집할 노드를 선택하세요.</p>
              )}
            </section>
            <section className="card system-config-list">
            <div className="card-title">
              <div><h3>장비·SW 목록</h3><p>기존 인터페이스 노드를 재사용하므로 노드 이름을 변경해도 설정이 유지됩니다.</p></div>
              <button className="ghost" type="button" onClick={() => onOpenNodeManager()}><Plus size={15}/> 노드 추가·관리</button>
            </div>
            <div className="table-wrap"><table className="system-config-table">
              <thead><tr><th>노드(SW)</th><th>Device ID</th><th>탑재 HW</th><th>Hostname</th><th>비고</th></tr></thead>
              <tbody>{nodes.map(item => (
                <tr key={item.node_id} onClick={() => setNodeId(String(item.node_id))} className={String(item.node_id) === String(nodeId) ? 'selected' : ''}>
                  <td><strong>{item.name}</strong></td><td>{item.device_id ?? '—'}</td><td>{item.hardware_name || '—'}</td><td>{item.hostname || '—'}</td><td>{item.note || '—'}</td>
                </tr>
              ))}
              {!nodes.length && <tr><td colSpan={5}>노드가 없습니다. 인터페이스 설계에서 먼저 노드를 추가해 주세요.</td></tr>}</tbody>
            </table></div>
          </section>
          </div>
        </div>
      )}

      {loaded && tab === 'ips' && (
        <div className="system-config-stack">
          <div className="system-config-split">
          <section className="card system-config-input">
            <h3>{editingIp == null ? 'IP 할당 추가' : 'IP 할당 수정'}</h3>
            <form className="system-config-form system-config-form-compact" onSubmit={saveIp}>
              <NodePicker nodes={nodes} value={ipDraft.node_id} onChange={value => setIpDraft({ ...ipDraft, node_id: value })}/>
              <label><span className="system-config-label-text">NIC / IP 구분</span><input maxLength={120} placeholder="예: NIC1, eth0" value={ipDraft.interface_name} onChange={e => setIpDraft({ ...ipDraft, interface_name: e.target.value })}/></label>
              <label><span className="system-config-label-text">IP 주소</span><input required placeholder="192.168.7.70" value={ipDraft.ip_address} onChange={e => setIpDraft({ ...ipDraft, ip_address: e.target.value })}/></label>
              <label className="wide"><span className="system-config-label-text">비고</span><input value={ipDraft.note} onChange={e => setIpDraft({ ...ipDraft, note: e.target.value })}/></label>
              <div className="system-config-actions">
                {editingIp != null && <button type="button" className="ghost" onClick={clearIpForm}>수정 취소</button>}
                <button type="submit" disabled={busy || !ipDraft.node_id || !ipDraft.ip_address.trim()}><Save size={15}/> {editingIp == null ? 'IP 추가' : '변경 저장'}</button>
              </div>
            </form>
          </section>
          <section className="card system-config-list">
            <h3>IP 주소 할당</h3>
            <p>프로젝트 내 중복 IP는 등록할 수 없습니다.</p>
            <div className="table-wrap"><table className="system-config-table system-config-ip-table">
              <thead><tr><th>노드</th><th>NIC / 구분</th><th>IP 주소</th><th>비고</th><th>관리</th></tr></thead>
              <tbody>{ips.map(item => (
                <tr key={item.id}>
                  <td>{item.node_name}</td><td>{item.interface_name || '—'}</td><td className="mono">{item.ip_address}</td>
                  <td>{item.note || '—'}</td>
                  <td><div className="system-config-row-actions"><button type="button" className="ghost" onClick={() => selectIpForEdit(item)}>수정</button><button type="button" className="danger" onClick={() => deleteIp(item)} aria-label={`${item.ip_address} 삭제`}><Trash2 size={14}/></button></div></td>
                </tr>
              ))}
              {!ips.length && <tr><td colSpan={5}>등록된 IP가 없습니다.</td></tr>}</tbody>
            </table></div>
          </section>
          </div>
          <div className="system-config-split">
          <section className="card system-config-input">
            <h3>{editingPort == null ? 'IP / PORT 바인딩 추가' : 'IP / PORT 바인딩 수정'}</h3>
            <form className="system-config-form system-config-form-compact" onSubmit={savePort}>
              <label><span className="system-config-label-text">IP / NIC</span>
                <select required value={portDraft.ip_assignment_id} disabled={editingPort !== null} onChange={e => setPortDraft({ ...portDraft, ip_assignment_id: e.target.value })}>
                  <option value="">IP 선택</option>
                  {ips.map(item => <option key={item.id} value={item.id}>{item.node_name} · {item.interface_name || 'NIC'} · {item.ip_address}</option>)}
                </select>
              </label>
              <label><span className="system-config-label-text">프로토콜</span>
                <select value={portDraft.protocol} onChange={e => setPortDraft({ ...portDraft, protocol: e.target.value })}>
                  <option value="TCP">TCP</option><option value="UDP">UDP</option>
                </select>
              </label>
              <label><span className="system-config-label-text">바인딩 방식</span>
                <select value={portDraft.port_mode} onChange={e => setPortDraft({ ...portDraft, port_mode: e.target.value, port: e.target.value === 'AUTO' ? '' : portDraft.port })}>
                  <option value="FIXED">고정 포트</option><option value="AUTO">자동 (AUTO)</option>
                </select>
              </label>
              <label><span className="system-config-label-text">포트 번호</span>
                <input type="number" min={1} max={65535} required={portDraft.port_mode === 'FIXED'}
                  disabled={portDraft.port_mode === 'AUTO'} value={portDraft.port}
                  placeholder={portDraft.port_mode === 'AUTO' ? '자동 바인딩' : '예: 15010'}
                  onChange={e => setPortDraft({ ...portDraft, port: e.target.value })}/>
              </label>
              <label className="wide"><span className="system-config-label-text">용도 / 비고</span>
                <input value={portDraft.description} maxLength={255} placeholder="예: 상태 정보 수신" onChange={e => setPortDraft({ ...portDraft, description: e.target.value })}/>
              </label>
              <div className="system-config-actions">
                {editingPort !== null && <button type="button" className="ghost" onClick={clearPortForm}>수정 취소</button>}
                <button type="submit" disabled={busy || !portDraft.ip_assignment_id || (portDraft.port_mode === 'FIXED' && !portDraft.port)}><Save size={15}/>{editingPort === null ? '바인딩 추가' : '바인딩 저장'}</button>
              </div>
            </form>
          </section>
          <section className="card system-config-list">
            <div className="card-title">
              <div><h3>포트 바인딩</h3><p>IP/NIC별로 TCP·UDP 포트를 여러 개 등록할 수 있어요. AUTO는 동적 포트로, 번호를 사전에 지정하지 않습니다.</p></div>
              <span className="system-config-count">{bindings.length}개 바인딩</span>
            </div>
            <div className="table-wrap"><table className="system-config-table">
              <thead><tr><th>노드 / NIC</th><th>IP</th><th>프로토콜</th><th>포트</th><th>용도</th><th>관리</th></tr></thead>
              <tbody>{bindings.map(item => (
                <tr key={item.id} className={editingPort === item.id ? 'selected' : ''}>
                  <td>{item.node_name} / {item.interface_name || '기본'}</td>
                  <td className="mono">{item.ip_address}</td><td>{item.protocol}</td>
                  <td>{item.port_mode === 'AUTO' ? <strong>AUTO · 동적</strong> : item.port}</td>
                  <td>{item.description || '—'}</td>
                  <td><div className="system-config-row-actions">
                    <button type="button" className="ghost" onClick={() => selectPortForEdit(item)}>수정</button>
                    <button type="button" className="danger" onClick={() => deletePort(item)} aria-label={`${item.protocol} 포트 삭제`}><Trash2 size={14}/></button>
                  </div></td>
                </tr>
              ))}
              {!bindings.length && <tr><td colSpan={6}>등록된 포트 바인딩이 없습니다.</td></tr>}</tbody>
            </table></div>
          </section>
          </div>
        </div>
      )}

      {loaded && tab === 'connections' && (
        <div className="system-config-stack">
          <div className="system-config-split">
          <section className="card system-config-input">
            <h3>{editingConnection == null ? '통신 연결 추가' : '통신 연결 수정'}</h3>
            <form className="system-config-form system-config-form-compact" onSubmit={saveConnection}>
              <label><span className="system-config-label-text">Server IP / PORT 바인딩</span>
                <select required value={connectionDraft.server_binding_id} onChange={e => setConnectionDraft({
                  ...connectionDraft, server_binding_id: e.target.value, client_binding_id: '',
                })}>
                  <option value="">Server 바인딩 선택</option>
                  {bindings.map(item => <option key={item.id} value={item.id}>
                    {item.node_name} · {item.ip_address} : {item.port_mode === 'AUTO' ? 'AUTO' : item.port} ({item.protocol})
                  </option>)}
                </select>
              </label>
              <label><span className="system-config-label-text">Client IP / PORT 바인딩</span>
                <select required value={connectionDraft.client_binding_id} onChange={e => setConnectionDraft({ ...connectionDraft, client_binding_id: e.target.value })}>
                  <option value="">Client 바인딩 선택</option>
                  {compatibleClientBindings.map(item => <option key={item.id} value={item.id}>
                    {item.node_name} · {item.ip_address} : {item.port_mode === 'AUTO' ? 'AUTO' : item.port} ({item.protocol})
                  </option>)}
                </select>
              </label>
              <label><span className="system-config-label-text">프로토콜</span>
                <input disabled value={chosenServerBinding?.protocol || 'Server 선택 시 자동 결정'} readOnly/>
              </label>
              <label className="wide"><span className="system-config-label-text">비고</span>
                <input value={connectionDraft.note} onChange={e => setConnectionDraft({ ...connectionDraft, note: e.target.value })}/>
              </label>
              <div className="system-config-actions">
                {editingConnection !== null && <button type="button" className="ghost" onClick={() => { setEditingConnection(null); setConnectionDraft(EMPTY_CONNECTION); }}>수정 취소</button>}
                <button type="submit" disabled={busy || !connectionDraft.server_binding_id || !connectionDraft.client_binding_id || connectionDraft.server_binding_id === connectionDraft.client_binding_id}>
                  <Save size={15}/>{editingConnection === null ? '연결 추가' : '변경 저장'}
                </button>
              </div>
            </form>
            {!bindings.length && <p className="system-config-inline-hint">포트 바인딩이 아직 없습니다. IP·NIC 탭에서 TCP/UDP 포트를 등록하거나 AUTO로 바인딩해 주세요.</p>}
          </section>
          <section className="card system-config-list" id="system-connection-list">
            <div className="card-title">
              <div>
                <h3>{selectedPairKey ? '선택한 연결선의 TCP / UDP 목록' : selectedGraphNodes.length ? '선택한 노드의 TCP / UDP 목록' : '전체 TCP / UDP 연결 목록'}</h3>
                <p>{shownConnections.length}개 연결 · 관계도를 선택하면 해당 연결만 표시됩니다.</p>
              </div>
              {(selectedPairKey || selectedGraphNodes.length) && <button type="button" className="ghost" onClick={showAllGraph}>필터 해제</button>}
            </div>
            <div className="table-wrap"><table className="system-config-table">
              <thead><tr><th>프로토콜</th><th>Server 노드</th><th>Server IP : PORT</th><th>Client 노드</th><th>Client IP : PORT</th><th>비고</th><th>관리</th></tr></thead>
              <tbody>{shownConnections.map(item => (
                <tr key={item.id} className={editingConnection === item.id ? 'selected' : ''}>
                  <td><strong>{item.protocol}</strong></td><td>{item.server_node_name}</td>
                  <td className="mono">{item.server_ip} : {item.server_port_mode === 'AUTO' ? 'AUTO' : item.server_port}</td>
                  <td>{item.client_node_name}</td>
                  <td className="mono">{item.client_ip} : {item.client_port_mode === 'AUTO' ? 'AUTO' : item.client_port}</td>
                  <td>{item.note || '—'}</td>
                  <td><div className="system-config-row-actions">
                    <button type="button" className="ghost" onClick={() => selectConnectionForEdit(item)}>수정</button>
                    <button type="button" className="danger" onClick={() => deleteConnection(item)} aria-label={`${item.id} 연결 삭제`}><Trash2 size={14}/></button>
                  </div></td>
                </tr>
              ))}
              {!shownConnections.length && <tr><td colSpan={7}>해당 관계에 등록된 통신 연결이 없습니다. IP·NIC 탭에서 포트를 먼저 바인딩해 주세요.</td></tr>}</tbody>
            </table></div>
          </section>
          </div>
        </div>
      )}

    </div>
  );
}
