import React, { useEffect, useId, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft,
  Copy,
  Download,
  Folder,
  GripVertical,
  History,
  Layers,
  LogOut,
  MessageSquare,
  Plus,
  RefreshCw,
  Save,
  Search,
  Moon,
  Sun,
  Settings,
  Tag,
  Trash2,
  Upload,
  UserCircle,
} from 'lucide-react';
import './style.css';

function resolveApiBase() {
  const configured = (import.meta.env.VITE_API_BASE_URL || '').trim();

  // Default to the same-origin Vite proxy. This avoids direct browser access
  // to port 8000, which can be blocked by firewall/CORS/hostname differences.
  if (!configured || configured.toLowerCase() === 'auto') {
    return '/api';
  }

  return configured.replace(/\/$/, '');
}

const API_BASE = resolveApiBase();
const SUPPORTED_TYPES = ['bool', 'char', 'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64', 'float', 'double'];
const ENUM_UNDERLYING_TYPES = ['int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64'];
const PROTOCOL_OPTIONS = ['TCP', 'UDP', 'RS232', 'RS422', 'RS485', 'DDS'];
const TYPE_BYTE_SIZES = { bool: 1, char: 1, int8: 1, uint8: 1, int16: 2, uint16: 2, int32: 4, uint32: 4, int64: 8, uint64: 8, float: 4, double: 8 };
const IDENTIFIER_REGEX = /^[A-Za-z_][A-Za-z0-9_]*$/;
const IDENTIFIER_HELP = '영문, 숫자, _ 만 사용할 수 있으며 숫자로 시작할 수 없습니다.';
function sanitizeIdentifier(value) { return String(value || '').replace(/[^A-Za-z0-9_]/g, ''); }
function generatedNameOf(message) { return message?.struct_name || message?.name || ''; }
function displayNameWithStruct(message) { const typeName = generatedNameOf(message); return message?.name && message.name !== typeName ? `${typeName} (${message.name})` : typeName; }
function sanitizePeriod(value) { return String(value || '').replace(/[^0-9]/g, ''); }
function normalizePeriodInput(value) {
  const text = String(value ?? '').trim();
  return text === '비주기' || text === '0' ? '' : sanitizePeriod(text);
}
function sanitizeInfocode(value) { return String(value || '').replace(/[^0-9]/g, ''); }
function uniqueSorted(values = []) {
  const seen = new Set();
  const result = [];
  (values || []).forEach(value => {
    const text = String(value || '').trim();
    if (!text) return;
    const key = text.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    result.push(text);
  });
  return result.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
}
function uniqueInInputOrder(values = []) {
  const seen = new Set();
  const result = [];
  (values || []).forEach(value => {
    const text = String(value || '').trim();
    if (!text) return;
    const key = text.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    result.push(text);
  });
  return result;
}
function splitProtocols(value) {
  const rawValues = Array.isArray(value) ? value : [value];
  const result = [];
  const seen = new Set();
  rawValues.forEach(raw => {
    String(raw ?? '').split(/(?:\r?\n|[,;|+]|\s+\/\s+)/).forEach(part => {
      const text = String(part || '').trim();
      if (!text || text === '-') return;
      const key = text.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      result.push(text);
    });
  });
  const order = new Map(PROTOCOL_OPTIONS.map((item, index) => [item.toLowerCase(), index]));
  const fixed = result.filter(item => order.has(item.toLowerCase())).sort((a, b) => order.get(a.toLowerCase()) - order.get(b.toLowerCase()));
  const custom = result.filter(item => !order.has(item.toLowerCase()));
  return [...fixed, ...custom];
}
function normalizeProtocols(value) { return splitProtocols(value).join(', '); }
function messageProtocols(message) { return splitProtocols(message?.protocols ?? message?.protocol); }
function messageHasProtocol(message, protocol) {
  const key = String(protocol || '').trim().toLowerCase();
  return !key || messageProtocols(message).some(item => item.toLowerCase() === key);
}
function collectProtocolSuggestions(messages = []) {
  const fixed = new Set(PROTOCOL_OPTIONS.map(item => item.toLowerCase()));
  return uniqueSorted((messages || [])
    .filter(message => !isEnumDefinition(message))
    .flatMap(message => messageProtocols(message)))
    .filter(protocol => !fixed.has(protocol.toLowerCase()));
}
function collectUnitSuggestions(...sources) {
  const values = [];
  sources.forEach(source => {
    if (Array.isArray(source)) {
      source.forEach(item => {
        if (Array.isArray(item?.fields)) item.fields.forEach(field => values.push(field?.unit));
        else values.push(item?.unit);
      });
      return;
    }
    if (Array.isArray(source?.fields)) source.fields.forEach(field => values.push(field?.unit));
    else if (source?.unit !== undefined) values.push(source.unit);
  });
  return uniqueSorted(values);
}
function findInfocodeOwner(messages, infocode, excludeMessageId = null) {
  const value = String(infocode || '').trim();
  if (!value) return null;
  return (messages || []).find(message => !isEnumDefinition(message) && message.id !== excludeMessageId && String(message.infocode || '').trim() === value) || null;
}
function isValidIdentifier(value) { return IDENTIFIER_REGEX.test(String(value || '')); }
function definitionTypeOf(item) { return String(item?.definition_type || 'STRUCT').toUpperCase(); }
function isEnumDefinition(item) { return definitionTypeOf(item) === 'ENUM'; }
function getUserTimeZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; }
  catch { return 'UTC'; }
}

function parseUtcDate(value) {
  if (!value) return null;
  const raw = String(value);
  const hasExplicitTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  return new Date(hasExplicitTimezone ? raw : `${raw}Z`);
}

function formatDate(value) {
  if (!value) return '-';
  try {
    const date = parseUtcDate(value);
    if (!date || Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(undefined, { timeZoneName: 'short' });
  }
  catch { return String(value); }
}


const THEME_STORAGE_KEY = 'interfy-theme';

function getInitialTheme() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function ThemeToggle({ theme, onToggle }) {
  const isDark = theme === 'dark';
  return (
    <button
      type="button"
      className="ghost theme-toggle"
      onClick={onToggle}
      title={isDark ? '현재 밝은 테마로 변경' : 'VS Code 스타일 다크 테마로 변경'}
      aria-label={isDark ? '밝은 테마로 변경' : '다크 테마로 변경'}
    >
      {isDark ? <Sun size={17}/> : <Moon size={17}/>}
      <span>{isDark ? '라이트' : '다크'}</span>
    </button>
  );
}

function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [me, setMe] = useState(null);
  const [error, setError] = useState('');
  const [theme, setTheme] = useState(getInitialTheme);
  const api = useMemo(() => createApi(token, setError), [token]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    try { localStorage.setItem(THEME_STORAGE_KEY, theme); } catch { /* ignore storage restrictions */ }
  }, [theme]);

  useEffect(() => {
    if (!token) return;
    api.get('/auth/me').then(setMe).catch(() => logout());
  }, [token]);

  function logout() {
    localStorage.removeItem('token');
    setToken('');
    setMe(null);
  }

  const toggleTheme = () => setTheme(current => current === 'dark' ? 'light' : 'dark');

  if (!token) {
    return <Login onLogin={(nextToken) => { localStorage.setItem('token', nextToken); setToken(nextToken); }} />;
  }

  return (
    <div className="app-shell">
      {error && <div className="toast" onClick={() => setError('')}>{error}</div>}
      <ProjectRouter api={api} me={me} onLogout={logout} theme={theme} onToggleTheme={toggleTheme} />
    </div>
  );
}

function normalizeApiError(raw, fallback = '요청 처리 중 오류가 발생했습니다.') {
  let message = fallback;
  try {
    const data = raw ? JSON.parse(raw) : null;
    if (Array.isArray(data?.detail)) {
      message = data.detail.map(item => item.msg || item.message || String(item)).join('\n');
    } else if (typeof data?.detail === 'string') {
      message = data.detail;
    } else if (raw) {
      message = raw;
    }
  } catch {
    if (raw) message = raw;
  }

  if (message.includes('String should have at least 3 characters') || message.includes('String should have at least 6 characters')) {
    return '패스워드는 3자리 이상으로 설정하세요.';
  }
  if (message.includes('아이디는 사번')) {
    return '아이디는 사번으로 입력하세요.';
  }
  return message;
}

function createApi(token, setError) {
  async function request(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (!(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (!res.ok) {
      const message = normalizeApiError(await res.text(), `API 오류: ${res.status}`);
      setError?.(String(message));
      throw new Error(message);
    }
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) return res.json();
    return res.text();
  }
  return {
    get: (path) => request(path),
    post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) }),
    postForm: (path, formData) => request(path, { method: 'POST', body: formData }),
    patch: (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body) }),
    del: (path) => request(path, { method: 'DELETE' }),
    login: async (email, password) => {
      const body = new URLSearchParams();
      body.set('username', email);
      body.set('password', password);
      const res = await fetch(`${API_BASE}/auth/login`, { method: 'POST', body });
      if (!res.ok) throw new Error(normalizeApiError(await res.text(), '로그인 실패'));
      return res.json();
    }
  };
}

function Login({ onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState('login');
  const [message, setMessage] = useState('');
  const api = createApi('', setMessage);

  function switchMode() {
    const nextMode = mode === 'login' ? 'register' : 'login';
    setMode(nextMode);
    setMessage('');
    if (nextMode === 'register') {
      setEmail('');
      setPassword('');
    } else {
      setEmail('');
      setPassword('');
    }
  }

  async function submit(e) {
    e.preventDefault();
    setMessage('');
    try {
      if (mode === 'register') {
        if (!/^\d{5}$/.test(email.trim())) {
          setMessage('아이디는 사번으로 입력하세요.');
          return;
        }
        if (password.length < 3) {
          setMessage('패스워드는 3자리 이상으로 설정하세요.');
          return;
        }
        await api.post('/auth/register', { email: email.trim(), password });
        setMode('login');
        setEmail(email.trim());
        setPassword('');
        setMessage('회원가입이 완료되었습니다. 로그인하세요.');
        return;
      }
      const data = await api.login(email.trim(), password);
      onLogin(data.access_token);
    } catch (err) {
      setMessage(err.message);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="brand-mark"><MessageSquare size={28} /></div>
          <div>
            <h1>Interfy</h1>
            <p>프로젝트 별 메시지와 필드를 생성하고 관리합니다.</p>
          </div>
        </div>
        <label>아이디<input value={email} onChange={e => setEmail(e.target.value)} placeholder={mode === 'login' ? 'admin 또는 사번' : '사번'} inputMode={mode === 'register' ? 'numeric' : 'text'} maxLength={mode === 'register' ? 5 : undefined} /></label>
        <label>비밀번호<input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="password" /></label>
        {message && <div className="notice">{message}</div>}
        <button type="submit">{mode === 'login' ? '로그인' : '회원가입'}</button>
        <button type="button" className="ghost" onClick={switchMode}>
          {mode === 'login' ? '계정 만들기' : '로그인 화면으로'}
        </button>
      </form>
    </div>
  );
}

function ProjectRouter({ api, me, onLogout, theme, onToggleTheme }) {
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [showAccountManage, setShowAccountManage] = useState(false);

  if (showAccountManage) {
    return <AccountManagePage api={api} me={me} onBack={() => setShowAccountManage(false)} />;
  }

  if (!selectedProjectId) {
    return <ProjectSelectPage api={api} me={me} onLogout={onLogout} theme={theme} onToggleTheme={onToggleTheme} onManageAccounts={() => setShowAccountManage(true)} onEnterProject={(project) => setSelectedProjectId(project.id)} />;
  }

  return (
    <MessageManagementPage
      api={api}
      me={me}
      projectId={selectedProjectId}
      onBackToProjects={() => setSelectedProjectId(null)}
      onLogout={onLogout}
      theme={theme}
      onToggleTheme={onToggleTheme}
    />
  );
}

function ProjectSelectPage({ api, me, onLogout, theme, onToggleTheme, onManageAccounts, onEnterProject }) {
  const [projects, setProjects] = useState([]);
  const [query, setQuery] = useState('');
  const [form, setForm] = useState({ name: '', acronym: '', description: '' });
  const [showCreate, setShowCreate] = useState(false);
  const importInputId = useId();

  async function loadProjects() {
    setProjects(await api.get('/projects'));
  }

  useEffect(() => { loadProjects(); }, []);

  const filteredProjects = projects.filter(project => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return project.name.toLowerCase().includes(q) || (project.acronym || '').toLowerCase().includes(q) || (project.description || '').toLowerCase().includes(q);
  });

  async function createProject(e) {
    e.preventDefault();
    if (me?.role !== 'ADMIN') { alert('관리자만 프로젝트를 생성할 수 있습니다.'); return; }
    const created = await api.post('/projects', form);
    setForm({ name: '', acronym: '', description: '' });
    setShowCreate(false);
    await loadProjects();
    onEnterProject(created);
  }

  async function importProjectJson(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (me?.role !== 'ADMIN') { alert('관리자만 프로젝트 JSON을 가져올 수 있습니다.'); return; }
    if (!confirm('선택한 JSON 파일을 새 프로젝트로 가져올까요? 기존 프로젝트는 변경되지 않습니다.')) return;
    const formData = new FormData();
    formData.append('file', file);
    const created = await api.postForm('/projects/import/json', formData);
    await loadProjects();
    alert(`${created.name} 프로젝트를 가져왔습니다.`);
    onEnterProject(created);
  }

  return (
    <div className="project-select-page">
      <header className="landing-header">
        <div className="landing-title">
          <div className="brand-mark"><MessageSquare size={24} /></div>
          <div>
            <h1>Interfy</h1>
            <p className="eyebrow">프로젝트를 선택하거나 새로 생성하세요.</p>
          </div>
        </div>
        <div className="user-box">
          <span>{me?.email}</span><b>{me?.role}</b>
          {me?.role === 'ADMIN' && <button className="ghost" onClick={onManageAccounts}><UserCircle size={15}/> 계정관리</button>}
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <button className="ghost" onClick={onLogout}><LogOut size={15}/> 로그아웃</button>
        </div>
      </header>

      <main className="landing-main">
        <section className="project-toolbar card">
          <div>
            <h2>프로젝트</h2>
            <p>프로젝트를 선택하면 해당 프로젝트의 인터페이스 설계 화면으로 이동합니다.{me?.role !== 'ADMIN' ? ' 프로젝트 생성은 관리자만 가능합니다.' : ''}</p>
          </div>
          <div className="toolbar-actions">
            <div className="search-box light"><Search size={16}/><input placeholder="프로젝트 검색" value={query} onChange={e => setQuery(e.target.value)} /></div>
            <button className="ghost" onClick={loadProjects}><RefreshCw size={16}/> 새로고침</button>
            {me?.role === 'ADMIN' && <>
              <input id={importInputId} type="file" accept="application/json,.json" style={{ display: 'none' }} onChange={importProjectJson} />
              <button className="ghost" onClick={() => document.getElementById(importInputId)?.click()}><Upload size={16}/> JSON 가져오기</button>
              <button onClick={() => setShowCreate(!showCreate)}><Plus size={16}/> 새 프로젝트</button>
            </>}
          </div>
        </section>

        {me?.role === 'ADMIN' && showCreate && (
          <section className="card create-project-card">
            <div className="card-title"><div><h2>프로젝트 생성</h2><p>프로젝트 이름, 영문약어, 설명을 입력하세요.</p></div></div>
            <form className="create-project-form" onSubmit={createProject}>
              <label>프로젝트 이름<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
              <label>영문약어<input required placeholder="예: MCMC2" value={form.acronym} onChange={e => setForm({ ...form, acronym: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '') })} /></label>
              <label>설명<textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label>
              <div className="button-row"><button><Plus size={16}/> 생성 후 들어가기</button><button type="button" className="ghost" onClick={() => setShowCreate(false)}>취소</button></div>
            </form>
          </section>
        )}

        <section className="project-card-grid">
          {filteredProjects.map(project => (
            <button className="project-card" key={project.id} onClick={() => onEnterProject(project)}>
              <div className="project-card-icon"><Folder size={22}/></div>
              <div>
                <div className="project-card-title-row"><h3>{project.name}</h3><em>{project.acronym || 'NO_CODE'}</em></div>
                <p>{project.description || '설명이 없습니다.'}</p>
              </div>
              <span>인터페이스 설계로 이동</span>
            </button>
          ))}
          {filteredProjects.length === 0 && <EmptyState title="표시할 프로젝트가 없습니다." />}
        </section>
      </main>
    </div>
  );
}

function MessageManagementPage({ api, me, projectId, onBackToProjects, onLogout, theme, onToggleTheme }) {
  const [project, setProject] = useState(null);
  const [projectForm, setProjectForm] = useState({ name: '', acronym: '', description: '' });
  const [messages, setMessages] = useState([]);
  const [selectedMessage, setSelectedMessage] = useState(null);
  const [groups, setGroups] = useState([]);
  const [labels, setLabels] = useState([]);
  const [integrationTargets, setIntegrationTargets] = useState([]);
  const [messageLabelFilter, setMessageLabelFilter] = useState('ALL');
  const [messageTxTargetFilter, setMessageTxTargetFilter] = useState('ALL');
  const [messageRxTargetFilter, setMessageRxTargetFilter] = useState('ALL');
  const [history, setHistory] = useState([]);
  const [backups, setBackups] = useState([]);
  const [backupEvents, setBackupEvents] = useState([]);
  const [activePanel, setActivePanel] = useState('design');
  const [messageForm, setMessageForm] = useState({ definition_type: 'STRUCT', name: '', struct_name: '', period: '', infocode: '', protocol: '', description: '', enum_underlying_type: 'uint32', label_ids: [], tx_target_ids: [], rx_target_ids: [] });
  const [query, setQuery] = useState('');
  const [draggingMessageId, setDraggingMessageId] = useState(null);
  const [hasUnsavedFieldChanges, setHasUnsavedFieldChanges] = useState(false);

  async function loadProject() {
    const data = await api.get(`/projects/${projectId}`);
    setProject(data);
    setProjectForm({ name: data.name, acronym: data.acronym || '', description: data.description || '' });
  }

  async function loadMessages(refreshSelected = true) {
    const data = await api.get(`/projects/${projectId}/messages`);
    setMessages(data);
    if (refreshSelected && selectedMessage) {
      const refreshed = data.find(m => m.id === selectedMessage.id);
      if (refreshed) setSelectedMessage(await api.get(`/messages/${refreshed.id}`));
      else setSelectedMessage(null);
    }
    return data;
  }

  async function loadGroups() {
    setGroups(await api.get(`/projects/${projectId}/groups`));
  }

  async function loadLabels() {
    setLabels(await api.get(`/projects/${projectId}/labels`));
  }

  async function loadIntegrationTargets() {
    setIntegrationTargets(await api.get(`/projects/${projectId}/integration-targets`));
  }

  async function loadHistory() {
    setHistory(await api.get(`/history?project_id=${projectId}`));
  }

  async function loadBackups() {
    setBackups(await api.get(`/projects/${projectId}/backups`));
  }

  async function loadBackupEvents() {
    setBackupEvents(await api.get(`/projects/${projectId}/backup-events`));
  }

  async function refreshAll() {
    await Promise.all([loadProject(), loadMessages(), loadGroups(), loadLabels(), loadIntegrationTargets(), loadHistory(), loadBackups(), loadBackupEvents()]);
  }

  useEffect(() => { refreshAll(); }, [projectId]);

  useEffect(() => {
    const handleBeforeUnload = (event) => {
      if (!hasUnsavedFieldChanges) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedFieldChanges]);

  function confirmLeaveFieldChanges() {
    if (!hasUnsavedFieldChanges) return true;
    const confirmed = confirm('변경사항이 저장되지 않을 수 있습니다.\n\n저장하지 않은 필드 변경사항이 사라질 수 있습니다. 계속 이동하시겠습니까?');
    if (confirmed) setHasUnsavedFieldChanges(false);
    return confirmed;
  }

  function changePanel(nextPanel) {
    if (nextPanel === activePanel) return;
    if (!confirmLeaveFieldChanges()) return;
    setActivePanel(nextPanel);
  }

  async function guardedRefreshAll() {
    if (!confirmLeaveFieldChanges()) return;
    await refreshAll();
  }

  function guardedBackToProjects() {
    if (!confirmLeaveFieldChanges()) return;
    onBackToProjects();
  }

  function guardedLogout() {
    if (!confirmLeaveFieldChanges()) return;
    onLogout();
  }

  const filteredMessages = messages.filter(message => (
    messageMatchesTextQuery(message, query) &&
    messageMatchesLabelFilter(message, messageLabelFilter) &&
    messageMatchesTargetFilter(message, messageTxTargetFilter, 'tx') &&
    messageMatchesTargetFilter(message, messageRxTargetFilter, 'rx')
  ));

  const canReorderFilteredMessages = messageLabelFilter === 'ALL' && messageTxTargetFilter === 'ALL' && messageRxTargetFilter === 'ALL' && !query.trim();

  async function saveProject(e) {
    e.preventDefault();
    const updated = await api.patch(`/projects/${projectId}`, projectForm);
    setProject(updated);
    setProjectForm({ name: updated.name, acronym: updated.acronym || '', description: updated.description || '' });
  }

  async function deleteProject() {
    if (me?.role !== 'ADMIN') { alert('관리자만 프로젝트를 삭제할 수 있습니다.'); return; }
    if (!confirm('프로젝트를 삭제할까요? 하위 메시지도 함께 삭제됩니다.')) return;
    await api.del(`/projects/${projectId}`);
    onBackToProjects();
  }

  async function createMessage(e) {
    e.preventDefault();
    const definitionName = messageForm.definition_type === 'ENUM' ? 'Enum' : '메시지';
    if (!isValidIdentifier(messageForm.struct_name)) { alert(`${definitionName} 이름: ${IDENTIFIER_HELP}`); return; }
    if (!String(messageForm.name || '').trim()) { alert(`${definitionName} 용도를 입력하세요.`); return; }
    if (messageForm.definition_type !== 'ENUM') {
      const infocodeOwner = findInfocodeOwner(messages, messageForm.infocode);
      if (infocodeOwner) {
        alert(`정보코드는 프로젝트 내에서 중복될 수 없습니다. 이미 사용 중인 메시지: ${generatedNameOf(infocodeOwner)}`);
        return;
      }
    }
    await api.post(`/projects/${projectId}/messages`, {
      ...messageForm,
      period: messageForm.definition_type === 'ENUM' ? '' : (messageForm.period === '0' ? '' : messageForm.period),
    });
    setMessageForm({ definition_type: 'STRUCT', name: '', struct_name: '', period: '', infocode: '', protocol: '', description: '', enum_underlying_type: 'uint32', label_ids: [], tx_target_ids: [], rx_target_ids: [] });
    await Promise.all([loadMessages(false), loadHistory()]);
    setActivePanel('design');
  }

  async function selectMessage(messageId, keepDesign = false) {
    if (selectedMessage?.id !== messageId && !confirmLeaveFieldChanges()) return;
    const fullMessage = await api.get(`/messages/${messageId}`);
    setSelectedMessage(fullMessage);
    if (!keepDesign) setActivePanel(isEnumDefinition(fullMessage) ? 'enumValues' : 'fields');
  }

  async function deleteMessage(messageId) {
    if (!confirm('메시지를 삭제할까요?')) return;
    await api.del(`/messages/${messageId}`);
    if (selectedMessage?.id === messageId) setSelectedMessage(null);
    await Promise.all([loadMessages(false), loadHistory()]);
    setActivePanel('design');
  }

  async function copyMessage(messageId) {
    const copied = await api.post(`/messages/${messageId}/copy`, {});
    await Promise.all([loadMessages(false), loadHistory()]);
    return copied;
  }

  async function createLabel(payload) {
    const label = await api.post(`/projects/${projectId}/labels`, payload);
    await loadLabels();
    return label;
  }

  async function updateLabel(labelId, payload) {
    const label = await api.patch(`/labels/${labelId}`, payload);
    await Promise.all([loadLabels(), loadMessages(false)]);
    return label;
  }

  async function deleteLabel(labelId) {
    await api.del(`/labels/${labelId}`);
    if (messageLabelFilter === String(labelId) || messageLabelFilter === labelId) setMessageLabelFilter('ALL');
    await Promise.all([loadLabels(), loadMessages(false)]);
  }

  async function createIntegrationTarget(payload) {
    const target = await api.post(`/projects/${projectId}/integration-targets`, payload);
    await loadIntegrationTargets();
    return target;
  }

  async function updateIntegrationTarget(targetId, payload) {
    const target = await api.patch(`/integration-targets/${targetId}`, payload);
    await Promise.all([loadIntegrationTargets(), loadMessages(false)]);
    return target;
  }

  async function deleteIntegrationTarget(targetId) {
    await api.del(`/integration-targets/${targetId}`);
    if (messageTxTargetFilter === String(targetId) || messageTxTargetFilter === targetId) setMessageTxTargetFilter('ALL');
    if (messageRxTargetFilter === String(targetId) || messageRxTargetFilter === targetId) setMessageRxTargetFilter('ALL');
    await Promise.all([loadIntegrationTargets(), loadMessages(false)]);
  }

  if (!project) return <div className="loading-page">프로젝트를 불러오는 중...</div>;

  return (
    <div className="manager-page compact-navigation">
      <aside className="message-sidebar compact-sidebar">
        <button className="back-button" onClick={guardedBackToProjects}><ArrowLeft size={16}/> 프로젝트 선택으로</button>
        <div className="side-project-card">
          <p className="eyebrow">현재 프로젝트 · {project.acronym || 'NO_CODE'}</p>
          <h2>{project.name}</h2>
          <p>{project.description || '설명이 없습니다.'}</p>
        </div>
        <div className="search-box"><Search size={16}/><input placeholder="메시지 이름 / 용도 검색" value={query} onChange={e => setQuery(e.target.value)} /></div>

        <div className="message-tree-title">설계</div>
        <button className={activePanel === 'design' || activePanel === 'partialUpdate' ? 'side-nav active' : 'side-nav'} onClick={() => changePanel('design')}><Layers size={16}/> 인터페이스 설계</button>

        <div className="message-tree-title sidebar-section-spacer">산출</div>
        <button className={activePanel === 'groups' ? 'side-nav active' : 'side-nav'} onClick={() => changePanel('groups')}><Download size={16}/> 출력</button>

        <div className="message-tree-title sidebar-section-spacer">관리</div>
        <button className={activePanel === 'settings' ? 'side-nav active' : 'side-nav'} onClick={() => changePanel('settings')}><Settings size={16}/> 프로젝트 설정</button>
        <button className={activePanel === 'history' ? 'side-nav active' : 'side-nav'} onClick={() => changePanel('history')}><History size={16}/> 이력 관리</button>
        <button className={activePanel === 'account' ? 'side-nav active' : 'side-nav'} onClick={() => changePanel('account')}><UserCircle size={16}/> 계정</button>
      </aside>

      <main className={activePanel === 'design' ? 'manager-content design-mode' : 'manager-content'}>
        <header className="manager-topbar">
          <div>
            <p className="eyebrow">{project.name}</p>
            <h1>{getPanelTitle(activePanel)}</h1>
          </div>
          <div className="user-box">
            <span>{me?.email}</span><b>{me?.role}</b>
            <button className="ghost" onClick={guardedRefreshAll}><RefreshCw size={15}/> 새로고침</button>
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
            <button className="ghost" onClick={guardedLogout}><LogOut size={15}/> 로그아웃</button>
          </div>
        </header>

        {activePanel === 'design' && (
          <InterfaceDesignPanel
            api={api}
            project={project}
            messages={messages}
            setMessages={setMessages}
            labels={labels}
            integrationTargets={integrationTargets}
            query={query}
            messageForm={messageForm}
            setMessageForm={setMessageForm}
            onCreateMessage={createMessage}
            selectedMessage={selectedMessage}
            setSelectedMessage={setSelectedMessage}
            onCloseSelectedMessage={() => { if (!confirmLeaveFieldChanges()) return false; setSelectedMessage(null); return true; }}
            onSelectMessage={(message) => selectMessage(message.id, true)}
            onDeleteMessage={deleteMessage}
            onCopyMessage={copyMessage}
            onCreateLabel={createLabel}
            onUpdateLabel={updateLabel}
            onDeleteLabel={deleteLabel}
            onCreateTarget={createIntegrationTarget}
            onUpdateTarget={updateIntegrationTarget}
            onDeleteTarget={deleteIntegrationTarget}
            onOpenPartialUpdate={() => changePanel('partialUpdate')}
            onReload={async () => { await Promise.all([loadMessages(false), loadLabels(), loadIntegrationTargets(), loadHistory()]); }}
            onDirtyChange={setHasUnsavedFieldChanges}
          />
        )}
        {activePanel === 'partialUpdate' && (
          <PartialUpdatePanel
            api={api}
            projectId={projectId}
            onBack={() => changePanel('design')}
            onApplied={async () => {
              await Promise.all([loadMessages(false), loadLabels(), loadIntegrationTargets(), loadHistory()]);
            }}
          />
        )}
        {activePanel === 'settings' && (
          <ProjectSettingsPanel
            projectForm={projectForm}
            setProjectForm={setProjectForm}
            onSaveProject={saveProject}
            onDeleteProject={deleteProject}
            me={me}
          />
        )}
        {activePanel === 'groups' && <ExportPanel api={api} project={project} labels={labels} integrationTargets={integrationTargets} />}
        {activePanel === 'history' && <HistoryPanel api={api} projectId={projectId} history={history} backups={backups} backupEvents={backupEvents} onReload={async () => { await Promise.all([loadHistory(), loadBackups(), loadBackupEvents()]); }} onRestored={refreshAll} />}
        {activePanel === 'account' && <AccountPanel api={api} me={me} onLogout={onLogout} />}
      </main>
    </div>
  );
}

function InterfaceDesignPanel({ api, project, messages = [], setMessages, labels = [], integrationTargets = [], query = '', messageForm, setMessageForm, onCreateMessage, selectedMessage, setSelectedMessage, onCloseSelectedMessage, onSelectMessage, onDeleteMessage, onCopyMessage, onCreateLabel, onUpdateLabel, onDeleteLabel, onCreateTarget, onUpdateTarget, onDeleteTarget, onOpenPartialUpdate, onReload, onDirtyChange }) {
  const [selectedDeviceId, setSelectedDeviceId] = useState(null);
  const [selectedRelationKey, setSelectedRelationKey] = useState(null);
  const [protocolFilter, setProtocolFilter] = useState('ALL');
  const [tagFilter, setTagFilter] = useState('ALL');
  const [unlinkedOnly, setUnlinkedOnly] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [copyNotice, setCopyNotice] = useState('');
  const [draggingMessageId, setDraggingMessageId] = useState(null);
  const [showProtocolOnGraph, setShowProtocolOnGraph] = useState(false);
  const [showMessageCountOnGraph, setShowMessageCountOnGraph] = useState(false);
  const [splitPercent, setSplitPercent] = useState(() => {
    const saved = Number(localStorage.getItem('interfy-design-split-percent'));
    return Number.isFinite(saved) && saved >= 20 && saved <= 80 ? saved : 50;
  });
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const [referencePanel, setReferencePanel] = useState({ open: false, tab: 'node', editTargetId: null });

  function openReferencePanel(tab = 'node', editTargetId = null) {
    setReferencePanel({ open: true, tab, editTargetId: tab === 'node' ? editTargetId : null });
  }

  function closeReferencePanel() {
    setReferencePanel(current => ({ ...current, open: false, editTargetId: null }));
  }

  useEffect(() => {
    localStorage.setItem('interfy-design-split-percent', String(splitPercent));
  }, [splitPercent]);

  function beginSplitResize(event) {
    event.preventDefault();
    const shell = event.currentTarget.parentElement;
    if (!shell) return;

    const rect = shell.getBoundingClientRect();
    const splitterHeight = 8;
    const usableHeight = Math.max(rect.height - splitterHeight, 1);
    setIsResizingSplit(true);
    document.body.classList.add('design-resizing');

    const onPointerMove = moveEvent => {
      const rawPercent = ((moveEvent.clientY - rect.top) / usableHeight) * 100;
      setSplitPercent(Math.min(80, Math.max(20, rawPercent)));
    };
    const onPointerUp = () => {
      setIsResizingSplit(false);
      document.body.classList.remove('design-resizing');
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  }

  function handleSplitKeyDown(event) {
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setSplitPercent(value => Math.max(20, value - 5));
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setSplitPercent(value => Math.min(80, value + 5));
    } else if (event.key === 'Home') {
      event.preventDefault();
      setSplitPercent(50);
    }
  }

  const splitGridStyle = {
    gridTemplateRows: `minmax(0, ${splitPercent}fr) 8px minmax(0, ${100 - splitPercent}fr)`,
  };

  const splitHandle = (
    <div
      className={`design-splitter ${isResizingSplit ? 'active' : ''}`}
      role="separator"
      aria-orientation="horizontal"
      aria-valuemin={20}
      aria-valuemax={80}
      aria-valuenow={Math.round(splitPercent)}
      tabIndex={0}
      title="드래그하여 상단/하단 높이 조절 · 더블클릭하면 50:50"
      onPointerDown={beginSplitResize}
      onDoubleClick={() => setSplitPercent(50)}
      onKeyDown={handleSplitKeyDown}
    >
      <span />
    </div>
  );

  const protocolOptions = useMemo(() => uniqueInInputOrder([
    ...PROTOCOL_OPTIONS,
    ...messages.filter(message => !isEnumDefinition(message)).flatMap(message => messageProtocols(message)),
  ]), [messages]);

  const filteredForGraph = useMemo(() => messages.filter(message => {
    if (isEnumDefinition(message)) return false;
    if (protocolFilter !== 'ALL' && !messageHasProtocol(message, protocolFilter)) return false;
    if (!messageMatchesLabelFilter(message, tagFilter)) return false;
    if (!messageMatchesTextQuery(message, query)) return false;
    return true;
  }), [messages, protocolFilter, tagFilter, query]);

  const relationMap = useMemo(() => {
    const map = new Map();
    filteredForGraph.forEach(message => {
      const tx = message.tx_targets || [];
      const rx = message.rx_targets || [];
      tx.forEach(from => rx.forEach(to => {
        const key = `${from.id}->${to.id}`;
        if (!map.has(key)) map.set(key, { key, fromId: from.id, toId: to.id, messages: [], protocols: new Set() });
        const relation = map.get(key);
        relation.messages.push(message);
        messageProtocols(message).forEach(protocol => relation.protocols.add(protocol));
      }));
    });
    return [...map.values()].map(item => ({ ...item, protocols: [...item.protocols] }));
  }, [filteredForGraph]);

  const selectedRelation = relationMap.find(relation => relation.key === selectedRelationKey) || null;
  const deviceMap = useMemo(() => new Map(integrationTargets.map(target => [Number(target.id), target])), [integrationTargets]);

  // The overview and a selected-device focus view use different layouts.
  // In focus view, only direct relations of the selected device are drawn.
  const graphRelations = useMemo(() => {
    if (!selectedDeviceId) return relationMap;
    return relationMap.filter(relation =>
      Number(relation.fromId) === Number(selectedDeviceId) ||
      Number(relation.toId) === Number(selectedDeviceId)
    );
  }, [relationMap, selectedDeviceId]);

  const graphTargets = useMemo(() => {
    if (!selectedDeviceId) return integrationTargets;
    const visibleIds = new Set([Number(selectedDeviceId)]);
    graphRelations.forEach(relation => {
      visibleIds.add(Number(relation.fromId));
      visibleIds.add(Number(relation.toId));
    });
    return integrationTargets.filter(target => visibleIds.has(Number(target.id)));
  }, [integrationTargets, graphRelations, selectedDeviceId]);

  const positions = useMemo(() => {
    const width = 900, height = 390;
    const cx = width / 2, cy = height / 2;
    const map = new Map();

    const placeRing = (targets, radiusX, radiusY, angleOffset = -Math.PI / 2) => {
      targets.forEach((target, index) => {
        const angle = angleOffset + (Math.PI * 2 * index / Math.max(targets.length, 1));
        map.set(Number(target.id), {
          x: cx + Math.cos(angle) * radiusX,
          y: cy + Math.sin(angle) * radiusY,
        });
      });
    };

    if (selectedDeviceId) {
      const selected = graphTargets.find(target => Number(target.id) === Number(selectedDeviceId));
      if (selected) map.set(Number(selected.id), { x: cx, y: cy });

      const neighbors = graphTargets.filter(target => Number(target.id) !== Number(selectedDeviceId));
      if (neighbors.length <= 10) {
        placeRing(neighbors, 315, 138);
      } else {
        const inner = neighbors.slice(0, 6);
        const outer = neighbors.slice(6);
        placeRing(inner, 190, 78, -Math.PI / 2 + Math.PI / Math.max(inner.length, 1));
        placeRing(outer, 338, 148);
      }
      return map;
    }

    const count = graphTargets.length;
    if (count === 1) {
      map.set(Number(graphTargets[0].id), { x: cx, y: cy });
      return map;
    }

    if (count <= 6) {
      placeRing(graphTargets, 310, 128);
      return map;
    }

    // Dense projects are split over two rings instead of forcing every device
    // onto one ellipse. This keeps node boxes readable as the device count grows.
    const innerCount = Math.min(6, Math.max(3, Math.round(count * 0.35)));
    const inner = graphTargets.slice(0, innerCount);
    const outer = graphTargets.slice(innerCount);
    placeRing(inner, 185, 78, -Math.PI / 2 + Math.PI / Math.max(inner.length, 1));
    placeRing(outer, 338, 148);
    return map;
  }, [graphTargets, selectedDeviceId]);

  const unlinkedMessages = useMemo(() => messages.filter(message => !isEnumDefinition(message) && (!(message.tx_targets || []).length || !(message.rx_targets || []).length)), [messages]);

  const displayedMessages = useMemo(() => messages.filter(message => {
    if (unlinkedOnly) {
      if (isEnumDefinition(message)) return false;
      if ((message.tx_targets || []).length && (message.rx_targets || []).length) return false;
    } else if (selectedRelation) {
      if (!selectedRelation.messages.some(item => item.id === message.id)) return false;
    } else if (selectedDeviceId) {
      if (isEnumDefinition(message)) return false;
      const related = [...(message.tx_targets || []), ...(message.rx_targets || [])].some(target => Number(target.id) === Number(selectedDeviceId));
      if (!related) return false;
    }
    if (!isEnumDefinition(message) && protocolFilter !== 'ALL' && !messageHasProtocol(message, protocolFilter)) return false;
    if (isEnumDefinition(message) && protocolFilter !== 'ALL') return false;
    if (!messageMatchesLabelFilter(message, tagFilter)) return false;
    if (!messageMatchesTextQuery(message, query)) return false;
    return true;
  }), [messages, unlinkedOnly, selectedRelation, selectedDeviceId, protocolFilter, tagFilter, query]);

  const canReorder = !selectedDeviceId && !selectedRelation && !unlinkedOnly && protocolFilter === 'ALL' && tagFilter === 'ALL' && !String(query || '').trim();

  const currentContext = useMemo(() => {
    if (unlinkedOnly) return { title: '미연결 메시지', detail: '송신 또는 수신 노드가 지정되지 않은 메시지' };
    if (selectedRelation) {
      const from = deviceMap.get(Number(selectedRelation.fromId));
      const to = deviceMap.get(Number(selectedRelation.toId));
      return { title: `${from?.name || '노드'} → ${to?.name || '노드'}`, detail: '선택한 송수신 관계의 메시지' };
    }
    if (selectedDeviceId) {
      const device = deviceMap.get(Number(selectedDeviceId));
      return { title: device?.name || '노드', detail: '선택한 노드의 송신 + 수신 메시지' };
    }
    return { title: '전체 메시지', detail: '노드나 관계를 선택하면 이 목록이 자동으로 필터링됩니다.' };
  }, [unlinkedOnly, selectedRelation, selectedDeviceId, deviceMap]);

  function selectDevice(targetId) {
    if (selectedMessage && onCloseSelectedMessage && !onCloseSelectedMessage()) return;
    if (!selectedMessage) setSelectedMessage(null);
    setSelectedRelationKey(null);
    setUnlinkedOnly(false);
    setSelectedDeviceId(current => Number(current) === Number(targetId) ? null : Number(targetId));
  }

  function selectRelation(key) {
    if (selectedMessage && onCloseSelectedMessage && !onCloseSelectedMessage()) return;
    if (!selectedMessage) setSelectedMessage(null);
    // Keep a selected device focused while drilling into one of its relations.
    setUnlinkedOnly(false);
    setSelectedRelationKey(current => current === key ? null : key);
  }

  function showAll() {
    if (selectedMessage && onCloseSelectedMessage && !onCloseSelectedMessage()) return;
    if (!selectedMessage) setSelectedMessage(null);
    setSelectedDeviceId(null);
    setSelectedRelationKey(null);
    setUnlinkedOnly(false);
  }

  function showUnlinked() {
    if (selectedMessage && onCloseSelectedMessage && !onCloseSelectedMessage()) return;
    if (!selectedMessage) setSelectedMessage(null);
    setSelectedDeviceId(null);
    setSelectedRelationKey(null);
    setUnlinkedOnly(true);
  }

  function prepareCreate() {
    const next = {
      ...messageForm,
      definition_type: 'STRUCT',
      tx_target_ids: [],
      rx_target_ids: [],
    };
    if (selectedRelation) {
      next.tx_target_ids = [Number(selectedRelation.fromId)];
      next.rx_target_ids = [Number(selectedRelation.toId)];
      if (protocolFilter !== 'ALL') next.protocol = protocolFilter;
      else if (selectedRelation.protocols.length === 1) next.protocol = selectedRelation.protocols[0];
    } else if (protocolFilter !== 'ALL') {
      next.protocol = protocolFilter;
    }
    setMessageForm(next);
    setShowCreate(true);
  }

  async function submitCreate(e) {
    await onCreateMessage(e);
    setShowCreate(false);
  }

  async function handleCopy(message) {
    const copied = await onCopyMessage(message.id);
    setCopyNotice(copied?.name ? `${generatedNameOf(copied)} 복사본을 생성했습니다.` : '메시지를 복사했습니다.');
  }

  async function reorderMessages(targetId) {
    if (!canReorder || !draggingMessageId || draggingMessageId === targetId) return;
    const ordered = [...messages];
    const fromIndex = ordered.findIndex(message => message.id === draggingMessageId);
    const toIndex = ordered.findIndex(message => message.id === targetId);
    if (fromIndex < 0 || toIndex < 0) return;
    const [moved] = ordered.splice(fromIndex, 1);
    ordered.splice(toIndex, 0, moved);
    setMessages(ordered);
    setDraggingMessageId(null);
    await api.post(`/projects/${project.id}/messages/reorder`, { message_ids: ordered.map(message => message.id) });
    await onReload?.();
  }

  async function deleteTargetFromPanel(targetId) {
    await onDeleteTarget?.(targetId);
    setMessageForm(current => ({
      ...current,
      tx_target_ids: (current.tx_target_ids || []).filter(id => Number(id) !== Number(targetId)),
      rx_target_ids: (current.rx_target_ids || []).filter(id => Number(id) !== Number(targetId)),
    }));
    if (Number(selectedDeviceId) === Number(targetId)) setSelectedDeviceId(null);
    setSelectedRelationKey(null);
  }

  async function deleteLabelFromPanel(labelId) {
    await onDeleteLabel?.(labelId);
    setMessageForm(current => ({ ...current, label_ids: (current.label_ids || []).filter(id => Number(id) !== Number(labelId)) }));
    if (String(tagFilter) === String(labelId)) setTagFilter('ALL');
  }

  const referencePanelElement = (
    <ReferenceSidePanel
      open={referencePanel.open}
      initialTab={referencePanel.tab}
      initialEditTargetId={referencePanel.editTargetId}
      labels={labels}
      targets={integrationTargets}
      onClose={closeReferencePanel}
      onCreateLabel={onCreateLabel}
      onUpdateLabel={onUpdateLabel}
      onDeleteLabel={deleteLabelFromPanel}
      onCreateTarget={onCreateTarget}
      onUpdateTarget={onUpdateTarget}
      onDeleteTarget={deleteTargetFromPanel}
    />
  );

  function pointAtNodeBoundary(center, toward, extraGap = 3) {
    const dx = toward.x - center.x;
    const dy = toward.y - center.y;
    const absDx = Math.abs(dx);
    const absDy = Math.abs(dy);
    if (absDx < 0.001 && absDy < 0.001) return { x: center.x, y: center.y };
    const halfWidth = 49 + extraGap;
    const halfHeight = 17 + extraGap;
    const scaleX = absDx > 0.001 ? halfWidth / absDx : Number.POSITIVE_INFINITY;
    const scaleY = absDy > 0.001 ? halfHeight / absDy : Number.POSITIVE_INFINITY;
    const scale = Math.min(scaleX, scaleY);
    return { x: center.x + dx * scale, y: center.y + dy * scale };
  }

  function relationGeometry(relation) {
    const a = positions.get(Number(relation.fromId));
    const b = positions.get(Number(relation.toId));
    if (!a || !b) return { path: '', label: { x: 0, y: 0 }, source: { x: 0, y: 0 } };

    if (Number(relation.fromId) === Number(relation.toId)) {
      const start = { x: a.x + 28, y: a.y - 17 };
      const end = { x: a.x + 49, y: a.y + 2 };
      return {
        path: `M ${start.x} ${start.y} C ${a.x + 80} ${a.y - 52}, ${a.x + 88} ${a.y + 28}, ${end.x} ${end.y}`,
        label: { x: a.x + 77, y: a.y - 17 },
        source: start,
      };
    }

    const reverseExists = graphRelations.some(other => Number(other.fromId) === Number(relation.toId) && Number(other.toId) === Number(relation.fromId));
    if (!reverseExists) {
      const start = pointAtNodeBoundary(a, b);
      const end = pointAtNodeBoundary(b, a);
      return {
        path: `M ${start.x} ${start.y} L ${end.x} ${end.y}`,
        label: { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 },
        source: start,
      };
    }

    // Keep the perpendicular direction stable for the unordered pair so A→B and B→A
    // bend to opposite sides instead of overlapping on the same curve.
    const fromId = Number(relation.fromId);
    const toId = Number(relation.toId);
    const lowId = Math.min(fromId, toId);
    const baseStart = positions.get(lowId);
    const baseEnd = positions.get(Math.max(fromId, toId));
    const baseDx = baseEnd.x - baseStart.x;
    const baseDy = baseEnd.y - baseStart.y;
    const baseLen = Math.max(Math.hypot(baseDx, baseDy), 1);
    const side = fromId === lowId ? 1 : -1;
    const bend = 28 * side;
    const control = {
      x: (a.x + b.x) / 2 - baseDy / baseLen * bend,
      y: (a.y + b.y) / 2 + baseDx / baseLen * bend,
    };
    const start = pointAtNodeBoundary(a, control);
    const end = pointAtNodeBoundary(b, control);
    // For bidirectional links, do not place both labels at the geometric midpoint.
    // Put each label a little closer to its own source. Since the reverse relation
    // traverses the curve in the opposite direction, the two labels naturally
    // occupy different sections of the connection instead of overlapping.
    const labelT = 0.36;
    const omt = 1 - labelT;
    const label = {
      x: omt * omt * start.x + 2 * omt * labelT * control.x + labelT * labelT * end.x,
      y: omt * omt * start.y + 2 * omt * labelT * control.y + labelT * labelT * end.y,
    };
    return {
      path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
      label,
      source: start,
    };
  }

  function relationPath(relation) {
    return relationGeometry(relation).path;
  }

  function relationLabelPosition(relation) {
    return relationGeometry(relation).label;
  }

  function relationSourcePosition(relation) {
    return relationGeometry(relation).source;
  }

  if (selectedMessage) {
    return (
      <div className="interface-design-shell" style={splitGridStyle}>
        <DesignVisualizationTop
          integrationTargets={integrationTargets}
          visibleTargets={graphTargets}
          relationMap={graphRelations}
          positions={positions}
          selectedDeviceId={selectedDeviceId}
          selectedRelationKey={selectedRelationKey}
          protocolFilter={protocolFilter}
          setProtocolFilter={setProtocolFilter}
          tagFilter={tagFilter}
          setTagFilter={setTagFilter}
          labels={labels}
          protocolOptions={protocolOptions}
          unlinkedCount={unlinkedMessages.length}
          unlinkedOnly={unlinkedOnly}
          onSelectDevice={selectDevice}
          onSelectRelation={selectRelation}
          onShowAll={showAll}
          onShowUnlinked={showUnlinked}
          onOpenReferences={() => openReferencePanel('node')}
          onEditNode={(target) => openReferencePanel('node', target.id)}
          relationPath={relationPath}
          relationLabelPosition={relationLabelPosition}
          relationSourcePosition={relationSourcePosition}
          showProtocol={showProtocolOnGraph}
          setShowProtocol={setShowProtocolOnGraph}
          showMessageCount={showMessageCountOnGraph}
          setShowMessageCount={setShowMessageCountOnGraph}
        />
        {splitHandle}
        <section className="design-lower design-editor-lower">
          <div className="design-lower-head">
            <div>
              <button type="button" className="ghost small-button" onClick={() => { if (!onCloseSelectedMessage || onCloseSelectedMessage()) setSelectedMessage(null); }}><ArrowLeft size={14}/> {currentContext.title}로 돌아가기</button>
              <strong className="design-editor-title">{generatedNameOf(selectedMessage)} · {selectedMessage.name}</strong>
            </div>
          </div>
          <div className="design-editor-scroll">
            {isEnumDefinition(selectedMessage) ? (
              <EnumValuePanel api={api} project={project} enumMessage={selectedMessage} labels={labels} integrationTargets={integrationTargets} setMessage={setSelectedMessage} onReload={onReload} onDirtyChange={onDirtyChange} onOpenReferencePanel={openReferencePanel} />
            ) : (
              <MessageFieldPanel api={api} project={project} message={selectedMessage} messages={messages} labels={labels} integrationTargets={integrationTargets} setMessage={setSelectedMessage} onReload={onReload} onDirtyChange={onDirtyChange} onOpenReferencePanel={openReferencePanel} compact />
            )}
          </div>
        </section>
        {referencePanelElement}
      </div>
    );
  }

  return (
    <div className="interface-design-shell" style={splitGridStyle}>
      <DesignVisualizationTop
        integrationTargets={integrationTargets}
        visibleTargets={graphTargets}
        relationMap={graphRelations}
        positions={positions}
        selectedDeviceId={selectedDeviceId}
        selectedRelationKey={selectedRelationKey}
        protocolFilter={protocolFilter}
        setProtocolFilter={setProtocolFilter}
        tagFilter={tagFilter}
        setTagFilter={setTagFilter}
        labels={labels}
        protocolOptions={protocolOptions}
        unlinkedCount={unlinkedMessages.length}
        unlinkedOnly={unlinkedOnly}
        onSelectDevice={selectDevice}
        onSelectRelation={selectRelation}
        onShowAll={showAll}
        onShowUnlinked={showUnlinked}
        onOpenReferences={() => openReferencePanel('node')}
        onEditNode={(target) => openReferencePanel('node', target.id)}
        onOpenPartialUpdate={onOpenPartialUpdate}
        relationPath={relationPath}
        relationLabelPosition={relationLabelPosition}
        relationSourcePosition={relationSourcePosition}
        showProtocol={showProtocolOnGraph}
        setShowProtocol={setShowProtocolOnGraph}
        showMessageCount={showMessageCountOnGraph}
        setShowMessageCount={setShowMessageCountOnGraph}
      />

      {splitHandle}

      <section className="design-lower">
        <div className="design-lower-head">
          <div>
            <div className="design-context-title">{currentContext.title}<span>{displayedMessages.length}</span></div>
            <p>{currentContext.detail}</p>
          </div>
          <div className="button-row compact">
            <button type="button" className="ghost" onClick={showAll}>전체 보기</button>
            <button type="button" onClick={prepareCreate}><Plus size={15}/> 메시지 / Enum 추가</button>
          </div>
        </div>

        {showCreate && (
          <form className={`design-create-form ${messageForm.definition_type === 'ENUM' ? 'enum' : ''}`} onSubmit={submitCreate}>
            <select value={messageForm.definition_type || 'STRUCT'} onChange={e => setMessageForm({ ...messageForm, definition_type: e.target.value })}>
              <option value="STRUCT">메시지</option><option value="ENUM">Enum</option>
            </select>
            <input required placeholder={messageForm.definition_type === 'ENUM' ? 'Enum 이름' : '메시지 이름'} value={messageForm.struct_name || ''} onChange={e => setMessageForm({ ...messageForm, struct_name: sanitizeIdentifier(e.target.value) })} />
            <input required placeholder={messageForm.definition_type === 'ENUM' ? 'Enum 용도' : '메시지 용도'} value={messageForm.name || ''} onChange={e => setMessageForm({ ...messageForm, name: e.target.value })} />
            {messageForm.definition_type === 'ENUM' ? (
              <select value={messageForm.enum_underlying_type || 'uint32'} onChange={e => setMessageForm({ ...messageForm, enum_underlying_type: e.target.value })}>{ENUM_UNDERLYING_TYPES.map(type => <option key={type}>{type}</option>)}</select>
            ) : <>
              <input inputMode="numeric" placeholder="주기(ms)" value={messageForm.period || ''} onChange={e => setMessageForm({ ...messageForm, period: sanitizePeriod(e.target.value) })} />
              <input inputMode="numeric" placeholder="정보코드" value={messageForm.infocode || ''} onChange={e => setMessageForm({ ...messageForm, infocode: sanitizeInfocode(e.target.value) })} />
              <ProtocolEditor value={messageForm.protocol || ''} onChange={protocol => setMessageForm({ ...messageForm, protocol })} suggestions={collectProtocolSuggestions(messages)} compact />
            </>}
            <input placeholder="설명" value={messageForm.description || ''} onChange={e => setMessageForm({ ...messageForm, description: e.target.value })} />
            <div className="design-create-wide"><span className="reference-inline-label">태그<button type="button" className="reference-inline-add" title="태그 추가/관리" onClick={() => openReferencePanel('tag')}><Plus size={12}/></button></span><LabelCheckboxes labels={labels} selectedIds={messageForm.label_ids || []} onChange={ids => setMessageForm({ ...messageForm, label_ids: ids })} /></div>
            {messageForm.definition_type !== 'ENUM' && <>
              <div className="design-create-wide"><span className="reference-inline-label">송신 노드<button type="button" className="reference-inline-add" title="노드 추가/관리" onClick={() => openReferencePanel('node')}><Plus size={12}/></button></span><LabelCheckboxes labels={integrationTargets} emptyText="등록된 노드가 없습니다." selectedIds={messageForm.tx_target_ids || []} onChange={ids => setMessageForm({ ...messageForm, tx_target_ids: ids })} /></div>
              <div className="design-create-wide"><span className="reference-inline-label">수신 노드<button type="button" className="reference-inline-add" title="노드 추가/관리" onClick={() => openReferencePanel('node')}><Plus size={12}/></button></span><LabelCheckboxes labels={integrationTargets} emptyText="등록된 노드가 없습니다." selectedIds={messageForm.rx_target_ids || []} onChange={ids => setMessageForm({ ...messageForm, rx_target_ids: ids })} /></div>
            </>}
            <div className="design-create-actions"><button type="button" className="ghost" onClick={() => setShowCreate(false)}>취소</button><button><Plus size={15}/> 추가</button></div>
          </form>
        )}

        {copyNotice && <div className="notice design-copy-notice">{copyNotice}</div>}
        <div className="design-message-table-wrap">
          <table className="design-message-table">
            <thead><tr><th>#</th><th>유형</th><th>메시지 이름</th><th>메시지 용도</th><th>태그</th><th>프로토콜</th><th>송신 노드</th><th>수신 노드</th><th>주기/기본형</th><th>정보코드</th><th>크기</th><th>필드/값</th><th></th></tr></thead>
            <tbody>
              {displayedMessages.map((message, index) => (
                <tr key={message.id} className={draggingMessageId === message.id ? 'dragging-row' : ''} onDragOver={e => { if (draggingMessageId) e.preventDefault(); }} onDrop={() => reorderMessages(message.id)} onClick={() => onSelectMessage(message)}>
                  <td><span className="order-cell">{canReorder && <GripVertical size={13} className="node-handle" draggable onDragStart={(e) => { e.stopPropagation(); e.dataTransfer.effectAllowed = 'move'; setDraggingMessageId(message.id); }} onDragEnd={(e) => { e.stopPropagation(); setDraggingMessageId(null); }} onClick={e => e.stopPropagation()} title="드래그해서 순서 변경"/>}<span className="order-pill">{messages.findIndex(item => item.id === message.id) + 1}</span></span></td>
                  <td><span className={isEnumDefinition(message) ? 'type-badge enum' : 'type-badge'}>{isEnumDefinition(message) ? 'Enum' : '메시지'}</span></td>
                  <td><strong>{generatedNameOf(message)}</strong></td>
                  <td>{message.name}</td>
                  <td><div className="message-labels">{(message.labels || []).map(label => <span className="mini-label" key={label.id}>{label.name}</span>)}{!(message.labels || []).length && <span className="muted small">-</span>}</div></td>
                  <td>{isEnumDefinition(message) ? '-' : <MessageProtocols value={message.protocol} />}</td>
                  <td>{isEnumDefinition(message) ? '-' : <MessageDevices targets={message.tx_targets || []} />}</td>
                  <td>{isEnumDefinition(message) ? '-' : <MessageDevices targets={message.rx_targets || []} />}</td>
                  <td>{isEnumDefinition(message) ? (message.enum_underlying_type || 'uint32') : (message.period ? `${message.period} ms` : '비주기')}</td>
                  <td>{isEnumDefinition(message) ? '-' : (message.infocode || '-')}</td>
                  <td>{messageSizeBytes(message, messages)} B</td>
                  <td>{isEnumDefinition(message) ? (message.enum_values || []).length : (message.fields || []).length}</td>
                  <td onClick={e => e.stopPropagation()}><div className="row-actions"><button type="button" className="icon ghost-icon" title="복사" onClick={() => handleCopy(message)}><Copy size={14}/></button><button type="button" className="icon danger-icon" title="삭제" onClick={() => onDeleteMessage(message.id)}><Trash2 size={14}/></button></div></td>
                </tr>
              ))}
              {!displayedMessages.length && <tr><td colSpan="13" className="muted">현재 조건에 해당하는 메시지가 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      {referencePanelElement}
    </div>
  );
}

function DesignVisualizationTop({ integrationTargets, visibleTargets = integrationTargets, relationMap, positions, selectedDeviceId, selectedRelationKey, protocolFilter, setProtocolFilter, tagFilter, setTagFilter, labels, protocolOptions, unlinkedCount, unlinkedOnly, onSelectDevice, onSelectRelation, onShowAll, onShowUnlinked, onOpenReferences, onEditNode, onOpenPartialUpdate, relationPath, relationLabelPosition, relationSourcePosition, showProtocol, setShowProtocol, showMessageCount, setShowMessageCount }) {
  // Draw the selected relation last so its line/label is never hidden by another relation.
  const renderRelations = [...relationMap].sort((a, b) => Number(a.key === selectedRelationKey) - Number(b.key === selectedRelationKey));
  const focusView = Boolean(selectedDeviceId);
  const denseOverview = !focusView && integrationTargets.length > 6;
  const [hoveredNodeId, setHoveredNodeId] = useState(null);
  const [nodeTooltipPosition, setNodeTooltipPosition] = useState(null);

  function compactDeviceName(value, maxLength = 10) {
    const text = String(value || '');
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }

  function compactTooltipText(value, maxLength = 46) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }

  function updateNodeTooltipPosition(event, targetId) {
    const svg = event.currentTarget?.ownerSVGElement;
    const screenMatrix = svg?.getScreenCTM?.();
    if (!svg || !screenMatrix) return;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(screenMatrix.inverse());
    setHoveredNodeId(Number(targetId));
    setNodeTooltipPosition({ x: local.x, y: local.y });
  }

  return (
    <section className="design-upper">
      <aside className="design-device-pane">
        <div className="design-pane-title"><strong>노드</strong></div>
        <button type="button" className={!selectedDeviceId && !selectedRelationKey && !unlinkedOnly ? 'design-device active' : 'design-device'} onClick={onShowAll}><Layers size={14}/><span>전체</span></button>
        {integrationTargets.map(target => <button type="button" key={target.id} title={target.description ? `${target.name}\n${target.description}\n\n더블클릭: 노드 수정` : `${target.name}\n\n더블클릭: 노드 수정`} className={Number(selectedDeviceId) === Number(target.id) ? 'design-device active' : 'design-device'} onClick={() => onSelectDevice(target.id)} onDoubleClick={(event) => { event.preventDefault(); onEditNode?.(target); }}><span className="device-dot"/><span>{target.name}</span></button>)}
        <button type="button" className={unlinkedOnly ? 'design-device warning active' : 'design-device warning'} onClick={onShowUnlinked}><span className="device-dot hollow"/><span>미연결</span><em>{unlinkedCount}</em></button>
      </aside>

      <div className="design-canvas-pane">
        <div className="design-toolbar">
          <div className="design-filter-field"><span>프로토콜</span><select value={protocolFilter} onChange={e => setProtocolFilter(e.target.value)}><option value="ALL">전체</option>{protocolOptions.map(protocol => <option key={protocol} value={protocol}>{protocol}</option>)}</select></div>
          <div className="design-filter-field"><span>태그</span><select value={tagFilter} onChange={e => setTagFilter(e.target.value)}><option value="ALL">전체</option><option value="NONE">태그 없음</option>{labels.map(label => <option key={label.id} value={String(label.id)}>{label.name}</option>)}</select></div>
          <div className="design-display-options" aria-label="관계 표시 옵션">
            <label><input type="checkbox" checked={showProtocol} onChange={e => setShowProtocol(e.target.checked)} /><span>프로토콜</span></label>
            <label><input type="checkbox" checked={showMessageCount} onChange={e => setShowMessageCount(e.target.checked)} /><span>메시지 수</span></label>
          </div>
          {focusView && <div className="design-focus-badge">포커스 보기</div>}
          {denseOverview && !showProtocol && !showMessageCount && <div className="design-density-hint">관계 정보 숨김</div>}
          <div className="design-toolbar-summary"><strong>{visibleTargets.length}</strong>{visibleTargets.length !== integrationTargets.length ? ` / ${integrationTargets.length}` : ''} 노드 · <strong>{relationMap.length}</strong> 관계</div>
          <button type="button" className="ghost design-partial-update-button" onClick={onOpenPartialUpdate}><Upload size={14}/> 부분 업데이트</button>
        </div>
        <button type="button" className="design-floating-add" title="노드 또는 태그 추가" aria-label="노드 또는 태그 추가" onClick={onOpenReferences}><Plus size={19}/></button>
        <div className="design-svg-wrap">
          {integrationTargets.length ? (
            <svg className="design-network" viewBox="0 0 900 390" role="img" aria-label={focusView ? "선택 노드 중심 송수신 관계" : "노드 간 송수신 관계"}>
              <defs>
                <marker id="designArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 8 4 L 0 8 z" className="design-arrow-head"/></marker>
              </defs>
              {renderRelations.map(relation => {
                const label = relationLabelPosition(relation);
                const source = relationSourcePosition(relation);
                const active = selectedRelationKey === relation.key;
                const protocolText = relation.protocols.length === 1 ? relation.protocols[0] : (relation.protocols.length > 1 ? `${relation.protocols.length} protocols` : '');
                const labelParts = [];
                if (showProtocol && protocolText) labelParts.push(protocolText);
                if (showMessageCount) labelParts.push(`메시지 ${relation.messages.length}`);
                const relationLabel = labelParts.join(' · ');
                const labelWidth = Math.max(54, Math.min(126, 18 + relationLabel.length * 7));
                return <g key={relation.key} className={active ? 'design-edge active' : 'design-edge'} onClick={() => onSelectRelation(relation.key)}>
                  <path className="design-edge-hit" d={relationPath(relation)} />
                  <path className="design-edge-line" d={relationPath(relation)} markerEnd="url(#designArrow)" />
                  <circle className="design-edge-source" cx={source.x} cy={source.y} r="3" />
                  {relationLabel && <g className="design-edge-label" transform={`translate(${label.x},${label.y})`}><rect x={-labelWidth / 2} y="-10" width={labelWidth} height="20" rx="10"/><text textAnchor="middle" dy="3.5">{relationLabel}</text></g>}
                </g>;
              })}
              {visibleTargets.map(target => {
                const pos = positions.get(Number(target.id)) || { x: 450, y: 195 };
                const active = Number(selectedDeviceId) === Number(target.id);
                return <g key={target.id} className={active ? 'design-node active' : 'design-node'} transform={`translate(${pos.x},${pos.y})`} onClick={() => onSelectDevice(target.id)} onDoubleClick={(event) => { event.preventDefault(); event.stopPropagation(); onEditNode?.(target); }} onMouseEnter={event => updateNodeTooltipPosition(event, target.id)} onMouseMove={event => updateNodeTooltipPosition(event, target.id)} onMouseLeave={() => { setHoveredNodeId(null); setNodeTooltipPosition(null); }}>
                  <rect x="-49" y="-17" width="98" height="34" rx="7"/>
                  <text className="design-node-name" textAnchor="middle" y="1">{compactDeviceName(target.name)}</text>
                </g>;
              })}
              {(() => {
                const target = visibleTargets.find(item => Number(item.id) === Number(hoveredNodeId));
                if (!target || !nodeTooltipPosition) return null;
                const name = compactTooltipText(target.name, 26);
                const description = compactTooltipText(target.description || '설명이 없습니다.', 34);
                const tooltipWidth = Math.max(112, Math.min(230, 18 + Math.max(name.length * 6.1, description.length * 5.2)));
                const tooltipHeight = 36;
                let tooltipX = nodeTooltipPosition.x + 12;
                let tooltipY = nodeTooltipPosition.y + 12;
                if (tooltipX + tooltipWidth > 892) tooltipX = nodeTooltipPosition.x - tooltipWidth - 12;
                if (tooltipY + tooltipHeight > 382) tooltipY = nodeTooltipPosition.y - tooltipHeight - 12;
                tooltipX = Math.max(8, tooltipX);
                tooltipY = Math.max(8, tooltipY);
                return <g className="design-node-tooltip" transform={`translate(${tooltipX},${tooltipY})`} pointerEvents="none">
                  <rect x="0" y="0" width={tooltipWidth} height={tooltipHeight} rx="5"/>
                  <text className="design-node-tooltip-name" x="8" y="13">{name}</text>
                  <text className="design-node-tooltip-description" x="8" y="27">{description}</text>
                </g>;
              })()}
            </svg>
          ) : <div className="design-empty-graph"><Layers size={32}/><strong>등록된 노드가 없습니다.</strong><span>우측 + 버튼에서 노드를 등록하세요.</span><button type="button" onClick={onOpenReferences}><Plus size={15}/> 노드 추가</button></div>}
        </div>
      </div>
    </section>
  );
}

function getPanelTitle(activePanel) {
  const titles = {
    design: '인터페이스 설계',
    messages: '인터페이스 설계',
    partialUpdate: '부분 업데이트',
    settings: '프로젝트 설정',
    groups: '출력',
    history: '이력 관리',
    account: '계정 관리',
    enumValues: 'Enum 값 관리',
  };
  return titles[activePanel] || '인터페이스 설계';
}


function LabelTabs({ labels = [], selected = 'ALL', onSelect, compact = false }) {
  return (
    <div className={compact ? 'label-tabs compact' : 'label-tabs'}>
      <button type="button" className={selected === 'ALL' ? 'active' : ''} onClick={() => onSelect?.('ALL')}>전체</button>
      <button type="button" className={selected === 'NONE' ? 'active' : ''} onClick={() => onSelect?.('NONE')}>태그 없음</button>
      {labels.map(label => (
        <button key={label.id} type="button" className={String(selected) === String(label.id) ? 'active' : ''} onClick={() => onSelect?.(String(label.id))}>
          <Tag size={compact ? 12 : 14} /> {label.name}
        </button>
      ))}
    </div>
  );
}


function SidebarFilterGroup({ title, children }) {
  return (
    <div className="sidebar-filter-group">
      <div className="sidebar-filter-title">{title}</div>
      {children}
    </div>
  );
}

function SidebarTargetTabs({ targets = [], selected = 'ALL', onSelect, noneText = '대상 없음' }) {
  return (
    <div className="label-tabs compact sidebar-target-tabs">
      <button type="button" className={selected === 'ALL' ? 'active' : ''} onClick={() => onSelect?.('ALL')}>전체</button>
      <button type="button" className={selected === 'NONE' ? 'active' : ''} onClick={() => onSelect?.('NONE')}>{noneText}</button>
      {targets.map(target => (
        <button key={target.id} type="button" className={String(selected) === String(target.id) ? 'active' : ''} onClick={() => onSelect?.(String(target.id))}>
          <Tag size={12} /> {target.name}
        </button>
      ))}
    </div>
  );
}

function TargetFilterTabs({ title, targets = [], selected = 'ALL', onSelect, noneText = '대상 없음' }) {
  return (
    <div className="target-filter-row">
      <strong>{title}</strong>
      <div className="label-tabs target-tabs">
        <button type="button" className={selected === 'ALL' ? 'active' : ''} onClick={() => onSelect?.('ALL')}>전체</button>
        <button type="button" className={selected === 'NONE' ? 'active' : ''} onClick={() => onSelect?.('NONE')}>{noneText}</button>
        {targets.map(target => (
          <button key={target.id} type="button" className={String(selected) === String(target.id) ? 'active' : ''} onClick={() => onSelect?.(String(target.id))}>
            <Tag size={14} /> {target.name}
          </button>
        ))}
      </div>
    </div>
  );
}

function messageMatchesLabelFilter(message, selectedLabelFilter) {
  if (selectedLabelFilter === 'ALL') return true;
  const ids = (message.labels || []).map(label => label.id);
  if (selectedLabelFilter === 'NONE') return ids.length === 0;
  return ids.includes(Number(selectedLabelFilter));
}

function messageMatchesTextQuery(message, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return true;
  return (
    String(message.name || '').toLowerCase().includes(q) ||
    String(generatedNameOf(message)).toLowerCase().includes(q) ||
    messageProtocols(message).join(' ').toLowerCase().includes(q) ||
    String(message.infocode || '').toLowerCase().includes(q) ||
    String(message.description || '').toLowerCase().includes(q)
  );
}

function messageMatchesTargetFilter(message, selectedTargetFilter, direction) {
  if (selectedTargetFilter === 'ALL') return true;
  if (isEnumDefinition(message)) return false;
  const key = direction === 'rx' ? 'rx_targets' : 'tx_targets';
  const ids = (message[key] || []).map(target => target.id);
  if (selectedTargetFilter === 'NONE') return ids.length === 0;
  return ids.includes(Number(selectedTargetFilter));
}

function filterDisplayName(items = [], selected = 'ALL', noneText = '없음') {
  if (selected === 'ALL') return '전체';
  if (selected === 'NONE') return noneText;
  return (items || []).find(item => String(item.id) === String(selected))?.name || '선택 항목';
}

function LabelCheckboxes({ labels = [], selectedIds = [], onChange, emptyText = '등록된 태그가 없습니다.' }) {
  const selectedSet = new Set((selectedIds || []).map(Number));
  function toggle(labelId) {
    const next = new Set(selectedSet);
    if (next.has(labelId)) next.delete(labelId);
    else next.add(labelId);
    onChange?.([...next]);
  }
  if (!labels.length) return <p className="muted small">{emptyText}</p>;
  return (
    <div className="label-checkboxes">
      {labels.map(label => (
        <label key={label.id} className="checkbox-pill">
          <input type="checkbox" checked={selectedSet.has(label.id)} onChange={() => toggle(label.id)} />
          <span>{label.name}</span>
        </label>
      ))}
    </div>
  );
}

function MessageCrudPanel({ api, project, messages, setMessages, messageForm, setMessageForm, onCreateMessage, onSelectMessage, onDeleteMessage, onCopyMessage, labels = [], integrationTargets = [], selectedLabelFilter = 'ALL', setSelectedLabelFilter, selectedTxTargetFilter = 'ALL', setSelectedTxTargetFilter, selectedRxTargetFilter = 'ALL', setSelectedRxTargetFilter, searchQuery = '', canReorderMessages = true, onCreateLabel, onDeleteLabel, onReload, showCreate = true, panelTitle = '메시지 목록', panelDescription = '' }) {
  const [draggingMessageId, setDraggingMessageId] = useState(null);
  const [copyNotice, setCopyNotice] = useState('');
  const [labelForm, setLabelForm] = useState({ name: '', description: '' });
  const protocolSuggestions = useMemo(() => collectProtocolSuggestions(messages), [messages]);
  const displayedMessages = messages.filter(message => (
    messageMatchesTextQuery(message, searchQuery) &&
    messageMatchesLabelFilter(message, selectedLabelFilter) &&
    messageMatchesTargetFilter(message, selectedTxTargetFilter, 'tx') &&
    messageMatchesTargetFilter(message, selectedRxTargetFilter, 'rx')
  ));
  const selectedLabelText = filterDisplayName(labels, selectedLabelFilter, '태그 없음');
  const selectedTxText = filterDisplayName(integrationTargets, selectedTxTargetFilter, '송신 노드 없음');
  const selectedRxText = filterDisplayName(integrationTargets, selectedRxTargetFilter, '수신 노드 없음');
  const relationText = selectedTxTargetFilter !== 'ALL' || selectedRxTargetFilter !== 'ALL' ? `${selectedTxText} → ${selectedRxText}` : '전체 송수신 관계';
  const filterActive = selectedLabelFilter !== 'ALL' || selectedTxTargetFilter !== 'ALL' || selectedRxTargetFilter !== 'ALL';

  async function handleCopyMessage(message) {
    setCopyNotice('');
    const copied = await onCopyMessage(message.id);
    if (copied?.name) {
      setCopyNotice(`${copied.name} 메시지가 생성되었습니다. 필요 시 메시지명을 변경하세요.`);
    }
  }

  async function submitLabel(e) {
    e.preventDefault();
    const name = labelForm.name.trim();
    if (!name) return;
    const created = await onCreateLabel?.({ name, description: labelForm.description });
    setLabelForm({ name: '', description: '' });
    if (created?.id) setSelectedLabelFilter?.(String(created.id));
  }

  async function handleDeleteLabel(labelId) {
    if (!confirm('태그를 삭제할까요? 메시지는 삭제되지 않습니다.')) return;
    await onDeleteLabel?.(labelId);
  }

  async function reorderMessages(targetMessageId) {
    if (!canReorderMessages || !draggingMessageId || draggingMessageId === targetMessageId) return;
    const current = [...messages];
    const fromIndex = current.findIndex(message => message.id === draggingMessageId);
    const toIndex = current.findIndex(message => message.id === targetMessageId);
    if (fromIndex < 0 || toIndex < 0) return;
    const [moved] = current.splice(fromIndex, 1);
    current.splice(toIndex, 0, moved);
    setMessages(current);
    await api.post(`/projects/${project.id}/messages/reorder`, { message_ids: current.map(message => message.id) });
    setDraggingMessageId(null);
    await onReload();
  }

  return (
    <section className="page-grid">
      {showCreate && <div className="card span-3 hero-card">
        <div>
          <p className="eyebrow">{project.name}</p>
          <h2>메시지를 생성/선택하세요</h2>
          <p>프로젝트를 선택한 뒤 이 화면에서 메시지를 관리합니다. 메시지를 선택하면 메시지 또는 Enum 설정 화면으로 이동합니다.</p>
        </div>
      </div>}
      {showCreate && <div className="card span-3">
        <div className="card-title"><div><h2>정의 생성</h2><p>정의 유형을 선택한 뒤 메시지 또는 Enum을 추가합니다.</p></div></div>
        <form className={`message-create ${messageForm.definition_type === 'ENUM' ? 'enum-create' : 'struct-create'}`} onSubmit={onCreateMessage}>
          <select className="definition-kind" aria-label="정의 유형" value={messageForm.definition_type || 'STRUCT'} onChange={e => setMessageForm({ ...messageForm, definition_type: e.target.value })}>
            <option value="STRUCT">메시지</option>
            <option value="ENUM">Enum</option>
          </select>
          <input className="definition-struct" required placeholder={messageForm.definition_type === 'ENUM' ? 'Enum 이름' : '메시지 이름'} title={IDENTIFIER_HELP} value={messageForm.struct_name || ''} onChange={e => setMessageForm({ ...messageForm, struct_name: sanitizeIdentifier(e.target.value) })} />
          <input className="definition-name" required placeholder={messageForm.definition_type === 'ENUM' ? 'Enum 용도' : '메시지 용도'} value={messageForm.name} onChange={e => setMessageForm({ ...messageForm, name: e.target.value })} />
          {messageForm.definition_type === 'ENUM' ? (
            <select className="definition-aux" aria-label="Enum 기본 자료형" value={messageForm.enum_underlying_type || 'uint32'} onChange={e => setMessageForm({ ...messageForm, enum_underlying_type: e.target.value })}>
              {ENUM_UNDERLYING_TYPES.map(type => <option key={type} value={type}>{type}</option>)}
            </select>
          ) : (
            <input className="definition-aux" inputMode="numeric" pattern="[0-9]*" placeholder="주기(ms)" title="주기 입력(ms)값이 없으면 비주기로 저장됩니다." value={messageForm.period} onChange={e => setMessageForm({ ...messageForm, period: sanitizePeriod(e.target.value) })} />
          )}
          {messageForm.definition_type !== 'ENUM' && (
            <input className="definition-infocode" inputMode="numeric" pattern="[0-9]*" placeholder="정보코드" title="정보코드는 숫자만 입력할 수 있으며 미입력도 가능합니다." value={messageForm.infocode || ''} onChange={e => setMessageForm({ ...messageForm, infocode: sanitizeInfocode(e.target.value) })} />
          )}
          {messageForm.definition_type !== 'ENUM' && <ProtocolEditor value={messageForm.protocol || ''} onChange={protocol => setMessageForm({ ...messageForm, protocol })} suggestions={protocolSuggestions} compact />}
          <input className="definition-description" placeholder="설명" value={messageForm.description} onChange={e => setMessageForm({ ...messageForm, description: e.target.value })} />
          <button className="definition-submit"><Plus size={16}/> 추가</button>
          <div className="form-wide compact-label-row">
            <p className="muted small">태그</p>
            <LabelCheckboxes labels={labels} selectedIds={messageForm.label_ids || []} onChange={(ids) => setMessageForm({ ...messageForm, label_ids: ids })} />
            {messageForm.definition_type !== 'ENUM' && <><p className="muted small">송신 노드</p><LabelCheckboxes labels={integrationTargets} emptyText="등록된 노드가 없습니다." selectedIds={messageForm.tx_target_ids || []} onChange={(ids) => setMessageForm({ ...messageForm, tx_target_ids: ids })} /><p className="muted small">수신 노드</p><LabelCheckboxes labels={integrationTargets} emptyText="등록된 노드가 없습니다." selectedIds={messageForm.rx_target_ids || []} onChange={(ids) => setMessageForm({ ...messageForm, rx_target_ids: ids })} /></>}
          </div>
        </form>
      </div>}
      <div className="card span-3">
        <div className="card-title"><div><h2>{panelTitle}</h2><p>{panelDescription || (canReorderMessages ? '드래그 앤 드롭으로 순서를 변경할 수 있으며, 행을 클릭하면 설정 페이지로 이동합니다.' : '필터 적용 목록은 조회용입니다. 순서 변경은 전체 보기에서 수행하세요.')}</p></div></div>
        <div className="message-filter-block">
          <div className="message-filter-header"><strong>태그</strong><LabelTabs labels={labels} selected={selectedLabelFilter} onSelect={setSelectedLabelFilter} /></div>
          <TargetFilterTabs title="송신 노드" targets={integrationTargets} selected={selectedTxTargetFilter} onSelect={setSelectedTxTargetFilter} noneText="송신 노드 없음" />
          <TargetFilterTabs title="수신 노드" targets={integrationTargets} selected={selectedRxTargetFilter} onSelect={setSelectedRxTargetFilter} noneText="수신 노드 없음" />
          <div className="current-filter-summary">
            <span>현재 보기: {selectedLabelText} / {relationText}</span>
            {filterActive && <button type="button" className="ghost small-button" onClick={() => { setSelectedLabelFilter?.('ALL'); setSelectedTxTargetFilter?.('ALL'); setSelectedRxTargetFilter?.('ALL'); }}>필터 초기화</button>}
          </div>
        </div>
        {copyNotice && <div className="notice inline-notice">{copyNotice}</div>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>순서</th><th>유형</th><th>메시지 이름</th><th>메시지 용도</th><th>태그</th><th>프로토콜</th><th>송신 노드</th><th>수신 노드</th><th>주기/기본형</th><th>정보코드</th><th>크기(Byte)</th><th>설명</th><th>필드/값 수</th><th>버전</th><th></th></tr></thead>
            <tbody>{displayedMessages.map((message, index) => <tr key={message.id} className={draggingMessageId === message.id ? 'dragging-row' : ''} onDragOver={(e) => { if (draggingMessageId) e.preventDefault(); }} onDrop={() => reorderMessages(message.id)} onClick={() => onSelectMessage(message)}>
              <td><span className="order-cell">{canReorderMessages && <span className="drag-handle" draggable title="드래그해서 순서 변경" onDragStart={(e) => { e.stopPropagation(); e.dataTransfer.effectAllowed = 'move'; setDraggingMessageId(message.id); }} onDragEnd={(e) => { e.stopPropagation(); setDraggingMessageId(null); }} onClick={e => e.stopPropagation()}>⋮⋮</span>}<span className="order-pill">{canReorderMessages ? index + 1 : (messages.findIndex(item => item.id === message.id) + 1)}</span></span></td><td><span className={isEnumDefinition(message) ? 'type-badge enum' : 'type-badge'}>{isEnumDefinition(message) ? 'Enum' : '메시지'}</span></td><td><strong><code>{generatedNameOf(message)}</code></strong></td><td>{message.name || '-'}</td><td><MessageLabels labels={message.labels || []} /></td><td>{isEnumDefinition(message) ? '-' : <MessageProtocols value={message.protocol} />}</td><td><MessageDevices targets={message.tx_targets || []} /></td><td><MessageDevices targets={message.rx_targets || []} /></td><td>{isEnumDefinition(message) ? message.enum_underlying_type : message.period}</td><td>{isEnumDefinition(message) ? '-' : (message.infocode || '-')}</td><td>{messageSizeBytes(message, messages)}</td><td>{message.description}</td><td>{isEnumDefinition(message) ? (message.enum_values?.length || 0) : (message.fields?.length || 0)}</td><td>v{message.version}</td>
              <td>
                <div className="row-actions">
                  <button className="icon ghost-icon" title="메시지 복사" onClick={(e) => { e.stopPropagation(); handleCopyMessage(message); }}><Copy size={15}/></button>
                  <button className="icon danger-icon" title="메시지 삭제" onClick={(e) => { e.stopPropagation(); onDeleteMessage(message.id); }}><Trash2 size={15}/></button>
                </div>
              </td>
            </tr>)}</tbody>
          </table>
          {displayedMessages.length === 0 && <EmptyState title="표시할 메시지가 없습니다." />}
        </div>
      </div>
    </section>
  );
}

function updateOverflowInputTitle(element, value, fallbackTitle = '') {
  if (!element) return;
  const text = String(value ?? '');
  const isOverflowing = Boolean(text) && element.scrollWidth > element.clientWidth + 1;
  element.title = isOverflowing ? text : fallbackTitle;
}

function overflowInputHandlers(value, fallbackTitle = '') {
  return {
    onMouseEnter: (event) => updateOverflowInputTitle(event.currentTarget, value, fallbackTitle),
    onMouseMove: (event) => updateOverflowInputTitle(event.currentTarget, value, fallbackTitle),
    onMouseLeave: (event) => { event.currentTarget.title = fallbackTitle; },
  };
}

function SuggestionInput({ value = '', onChange, fixedSuggestions = [], suggestions = [], placeholder = '', ariaLabel = '', title = '', required = false, className = '', fixedTitle = '고정값', suggestionTitle = '기존 입력값' }) {
  const [open, setOpen] = useState(false);
  const text = String(value || '');
  const fixed = uniqueInInputOrder(fixedSuggestions);
  const fixedKeys = new Set(fixed.map(item => item.toLowerCase()));
  const custom = uniqueSorted(suggestions).filter(item => !fixedKeys.has(item.toLowerCase()));
  const query = text.trim().toLowerCase();
  const fixedFiltered = fixed.filter(item => !query || item.toLowerCase().includes(query));
  const customFiltered = custom.filter(item => !query || item.toLowerCase().includes(query));
  const hasSuggestions = fixedFiltered.length > 0 || customFiltered.length > 0;

  function choose(nextValue) {
    onChange?.(nextValue);
    setOpen(false);
  }

  return (
    <div className={`suggestion-input ${className}`.trim()}>
      <input
        required={required}
        aria-label={ariaLabel || placeholder}
        title={title}
        placeholder={placeholder}
        value={text}
        {...overflowInputHandlers(text, title)}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onChange={e => { onChange?.(e.target.value); setOpen(true); }}
      />
      {open && hasSuggestions && (
        <div className="suggestion-menu" onMouseDown={e => e.preventDefault()}>
          {fixedFiltered.length > 0 && <div className="suggestion-group-title">{fixedTitle}</div>}
          {fixedFiltered.map(option => <button type="button" key={`fixed-${option}`} className="suggestion-item fixed" onClick={() => choose(option)}>{option}</button>)}
          {customFiltered.length > 0 && <div className="suggestion-group-title">{suggestionTitle}</div>}
          {customFiltered.map(option => <button type="button" key={`custom-${option}`} className="suggestion-item" onClick={() => choose(option)}>{option}</button>)}
        </div>
      )}
    </div>
  );
}

function ProtocolEditor({ value = '', onChange, compact = false, suggestions = [] }) {
  const [draft, setDraft] = useState('');
  const [open, setOpen] = useState(false);
  const selected = splitProtocols(value);
  const selectedKeys = new Set(selected.map(item => item.toLowerCase()));
  const query = draft.trim().toLowerCase();
  const options = uniqueInInputOrder([...PROTOCOL_OPTIONS, ...suggestions]).filter(item => !selectedKeys.has(item.toLowerCase()) && (!query || item.toLowerCase().includes(query)));

  function commit(rawValue = draft) {
    const additions = splitProtocols(rawValue);
    if (!additions.length) { setDraft(''); return; }
    onChange?.(normalizeProtocols([...selected, ...additions]));
    setDraft('');
  }

  function remove(protocol) {
    onChange?.(normalizeProtocols(selected.filter(item => item.toLowerCase() !== protocol.toLowerCase())));
  }

  return (
    <div className={`protocol-editor protocol-multi-editor ${compact ? 'compact' : ''}`.trim()}>
      <div className="protocol-selected">
        {selected.map(protocol => (
          <span key={protocol.toLowerCase()} className="protocol-chip">
            {protocol}
            <button type="button" aria-label={`${protocol} 제거`} onClick={() => remove(protocol)}>×</button>
          </span>
        ))}
        <div className="protocol-input-wrap">
          <input
            aria-label="프로토콜 추가"
            placeholder={selected.length ? '추가...' : '프로토콜'}
            value={draft}
            onFocus={() => setOpen(true)}
            onBlur={() => { setTimeout(() => setOpen(false), 120); if (draft.trim()) commit(); }}
            onChange={e => {
              const next = e.target.value;
              setDraft(next);
              setOpen(true);
              if (/[;,|+]$/.test(next) || /\n/.test(next)) commit(next);
            }}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === 'Tab') {
                if (draft.trim()) { e.preventDefault(); commit(); }
              } else if (e.key === 'Backspace' && !draft && selected.length) {
                remove(selected[selected.length - 1]);
              }
            }}
          />
          {open && options.length > 0 && (
            <div className="suggestion-menu protocol-suggestion-menu" onMouseDown={e => e.preventDefault()}>
              <div className="suggestion-group-title">프로토콜 선택</div>
              {options.map(option => (
                <button type="button" key={option.toLowerCase()} className={`suggestion-item ${PROTOCOL_OPTIONS.some(item => item.toLowerCase() === option.toLowerCase()) ? 'fixed' : ''}`} onClick={() => commit(option)}>{option}</button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function UnitInput({ value = '', onChange, suggestions = [], placeholder = '단위' }) {
  return (
    <SuggestionInput
      className="unit-editor"
      value={value}
      onChange={onChange}
      suggestions={suggestions}
      placeholder={placeholder}
      ariaLabel="단위"
      suggestionTitle="기존 단위"
    />
  );
}

function MessageLabels({ labels = [] }) {
  if (!labels.length) return <span className="muted small">-</span>;
  return <div className="message-labels">{labels.map(label => <span key={label.id} className="mini-label">{label.name}</span>)}</div>;
}

function MessageProtocols({ value = '' }) {
  const protocols = splitProtocols(value);
  if (!protocols.length) return <span className="muted small">-</span>;
  return <div className="message-protocol-list">{protocols.map(protocol => <span key={protocol.toLowerCase()} className="message-protocol-item">{protocol}</span>)}</div>;
}

function MessageDevices({ targets = [] }) {
  if (!targets.length) return <span className="muted small">-</span>;
  return (
    <div className="message-device-list">
      {targets.map((target, index) => <span key={target.id ?? `${target.name}-${index}`} className="message-device-item">{target.name}</span>)}
    </div>
  );
}

function PartialUpdatePanel({ api, projectId, onBack, onApplied }) {
  const fileInputId = useId();
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [selectedName, setSelectedName] = useState('');
  const [checkedNames, setCheckedNames] = useState(new Set());
  const [changedOnly, setChangedOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const rows = preview?.messages || [];
  const visibleRows = changedOnly ? rows.filter(row => row.status !== 'SAME') : rows;
  const selectedRow = rows.find(row => row.struct_name === selectedName) || visibleRows[0] || null;
  const checkedRows = rows.filter(row => checkedNames.has(row.struct_name) && row.status !== 'SAME');
  const selectedDeleteCount = checkedRows.reduce((sum, row) => sum + (row.diffs || []).filter(diff => diff.kind === 'DELETE').length, 0);

  function statusText(status) {
    if (status === 'NEW') return '신규';
    if (status === 'CHANGED') return '변경';
    return '동일';
  }

  async function previewFile(nextFile) {
    if (!nextFile) return;
    setBusy(true);
    setNotice('');
    try {
      const formData = new FormData();
      formData.append('file', nextFile);
      const result = await api.postForm(`/projects/${projectId}/partial-update/preview`, formData);
      setFile(nextFile);
      setPreview(result);
      setCheckedNames(new Set());
      const firstActionable = (result.messages || []).find(row => row.status !== 'SAME') || result.messages?.[0];
      setSelectedName(firstActionable?.struct_name || '');
    } finally {
      setBusy(false);
    }
  }

  async function chooseFile(event) {
    const nextFile = event.target.files?.[0];
    event.target.value = '';
    if (nextFile) await previewFile(nextFile);
  }

  function toggleChecked(row) {
    if (row.status === 'SAME') return;
    setCheckedNames(current => {
      const next = new Set(current);
      if (next.has(row.struct_name)) next.delete(row.struct_name);
      else next.add(row.struct_name);
      return next;
    });
  }

  function selectByStatus(status) {
    setCheckedNames(current => {
      const next = new Set(current);
      rows.filter(row => row.status === status).forEach(row => next.add(row.struct_name));
      return next;
    });
  }

  async function applySelected() {
    if (!file || checkedRows.length === 0) return;
    const deleteText = selectedDeleteCount > 0 ? `\n삭제되는 항목 ${selectedDeleteCount}건이 포함되어 있습니다.` : '';
    if (!confirm(`선택한 ${checkedRows.length}개 메시지를 현재 프로젝트에 반영할까요?${deleteText}\n\n체크하지 않은 메시지는 변경되지 않습니다.`)) return;
    setBusy(true);
    setNotice('');
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('selected_names', JSON.stringify(checkedRows.map(row => row.struct_name)));
      const result = await api.postForm(`/projects/${projectId}/partial-update/apply`, formData);
      await onApplied?.();
      await previewFile(file);
      setNotice(`${result.updated_count}개 메시지를 반영했습니다. 이력 관리에 부분 업데이트 기록이 저장되었습니다.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="partial-update-page">
      <div className="partial-update-head card">
        <div>
          <button type="button" className="ghost reference-back-button" onClick={onBack}><ArrowLeft size={15}/> 인터페이스 설계로</button>
          <h2>부분 업데이트</h2>
          <p>외부에서 수정한 JSON 파일을 불러와 현재 프로젝트와 비교한 뒤, 선택한 메시지만 반영합니다.</p>
        </div>
        <div className="partial-update-file-actions">
          <input id={fileInputId} type="file" accept="application/json,.json" style={{ display: 'none' }} onChange={chooseFile} />
          <button type="button" className="ghost" disabled={busy} onClick={() => document.getElementById(fileInputId)?.click()}><Upload size={16}/> {preview ? '다른 JSON 선택' : 'JSON 선택'}</button>
        </div>
      </div>

      {notice && <div className="notice partial-update-notice">{notice}</div>}

      {!preview ? (
        <div className="card partial-update-empty">
          <Upload size={32}/>
          <h3>업데이트할 JSON 파일을 선택하세요.</h3>
          <p>JSON 파일을 선택하면 메시지별 신규·변경·삭제 내용을 적용 전에 확인할 수 있습니다.</p>
          <button type="button" disabled={busy} onClick={() => document.getElementById(fileInputId)?.click()}><Upload size={16}/> JSON 선택</button>
        </div>
      ) : (
        <>
          <div className="partial-update-summary card">
            <div><span>파일</span><strong>{preview.filename}</strong></div>
            <div><span>신규</span><strong>{preview.summary?.new || 0}</strong></div>
            <div><span>변경</span><strong>{preview.summary?.changed || 0}</strong></div>
            <div><span>동일</span><strong>{preview.summary?.same || 0}</strong></div>
            <div><span>선택</span><strong>{checkedRows.length}</strong></div>
          </div>

          <div className="partial-update-toolbar card">
            <label className="inline-check"><input type="checkbox" checked={changedOnly} onChange={e => setChangedOnly(e.target.checked)} /> 변경 항목만 보기</label>
            <div className="button-row compact">
              <button type="button" className="ghost" onClick={() => selectByStatus('CHANGED')}>변경 전체 선택</button>
              <button type="button" className="ghost" onClick={() => selectByStatus('NEW')}>신규 전체 선택</button>
              <button type="button" className="ghost" onClick={() => setCheckedNames(new Set())}>선택 해제</button>
            </div>
          </div>

          <div className="partial-update-workspace">
            <div className="card partial-update-list-card">
              <div className="partial-update-list-head"><strong>메시지 목록</strong><span>{visibleRows.length}건</span></div>
              <div className="partial-update-list">
                {visibleRows.map(row => (
                  <div key={row.struct_name} className={`partial-update-row ${selectedRow?.struct_name === row.struct_name ? 'selected' : ''}`} onClick={() => setSelectedName(row.struct_name)}>
                    <input
                      type="checkbox"
                      aria-label={`${row.struct_name} 업데이트 선택`}
                      disabled={row.status === 'SAME'}
                      checked={checkedNames.has(row.struct_name)}
                      onClick={e => e.stopPropagation()}
                      onChange={() => toggleChecked(row)}
                    />
                    <div className="partial-update-row-main">
                      <strong>{row.struct_name}</strong>
                      <span>{row.name || '-'}</span>
                    </div>
                    <span className={`partial-status ${row.status.toLowerCase()}`}>{statusText(row.status)}</span>
                  </div>
                ))}
                {visibleRows.length === 0 && <div className="muted partial-update-no-rows">표시할 메시지가 없습니다.</div>}
              </div>
            </div>

            <div className="card partial-update-compare-card">
              {selectedRow ? (
                <>
                  <div className="partial-update-compare-head">
                    <div><p className="eyebrow">{selectedRow.definition_type === 'ENUM' ? 'ENUM' : 'MESSAGE'}</p><h3>{selectedRow.struct_name}</h3><span>{selectedRow.name}</span></div>
                    <span className={`partial-status ${selectedRow.status.toLowerCase()}`}>{statusText(selectedRow.status)}</span>
                  </div>
                  {selectedRow.dependencies?.length > 0 && (
                    <div className="partial-dependency-note">신규 참조 자료형: {selectedRow.dependencies.join(', ')} · 신규 자료형인 경우 함께 체크해야 적용할 수 있습니다.</div>
                  )}
                  <div className="partial-diff-list">
                    {(selectedRow.diffs || []).map((diff, index) => (
                      <div key={`${diff.kind}-${index}`} className={`partial-diff ${diff.kind.toLowerCase()}`}>
                        <span className="partial-diff-mark">{diff.kind === 'ADD' ? '+' : diff.kind === 'DELETE' ? '−' : '~'}</span>
                        <div><small>{diff.section}</small><p>{diff.text}</p></div>
                      </div>
                    ))}
                    {(selectedRow.diffs || []).length === 0 && <div className="partial-same-message">기존 메시지와 동일합니다. 반영할 내용이 없습니다.</div>}
                  </div>
                </>
              ) : <div className="partial-same-message">왼쪽에서 메시지를 선택하세요.</div>}
            </div>
          </div>

          <div className="partial-update-applybar card">
            <div>
              <strong>선택 {checkedRows.length}개</strong>
              <span>{selectedDeleteCount > 0 ? ` · 삭제 항목 ${selectedDeleteCount}건 포함` : ' · 삭제 항목 없음'}</span>
            </div>
            <div className="button-row compact">
              <button type="button" className="ghost" onClick={onBack}>취소</button>
              <button type="button" disabled={busy || checkedRows.length === 0} onClick={applySelected}>{busy ? '처리 중...' : `선택한 ${checkedRows.length}개 업데이트`}</button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function ProjectSettingsPanel({ projectForm, setProjectForm, onSaveProject, onDeleteProject, me }) {
  return (
    <section className="page-grid">
      <div className="card span-3">
        <div className="card-title"><div><h2>프로젝트 설정</h2><p>프로젝트 이름, 영문약어, 설명을 관리합니다.</p></div></div>
        <form className="project-editor" onSubmit={onSaveProject}>
          <label>프로젝트 이름<input required value={projectForm.name} onChange={e => setProjectForm({ ...projectForm, name: e.target.value })} /></label>
          <label>영문약어<input required value={projectForm.acronym} onChange={e => setProjectForm({ ...projectForm, acronym: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '') })} /></label>
          <label>설명<textarea value={projectForm.description} onChange={e => setProjectForm({ ...projectForm, description: e.target.value })} /></label>
          <div className="button-row"><button><Save size={16}/> 저장</button>{me?.role === 'ADMIN' && <button type="button" className="danger" onClick={onDeleteProject}><Trash2 size={16}/> 삭제</button>}</div>
        </form>
      </div>
    </section>
  );
}

function ReferenceSidePanel({ open, initialTab = 'node', initialEditTargetId = null, labels = [], targets = [], onClose, onCreateLabel, onUpdateLabel, onDeleteLabel, onCreateTarget, onUpdateTarget, onDeleteTarget }) {
  const [tab, setTab] = useState(initialTab);
  const [nodeForm, setNodeForm] = useState({ name: '', description: '' });
  const [tagForm, setTagForm] = useState({ name: '', description: '' });
  const [editingNodeId, setEditingNodeId] = useState(null);
  const [editingTagId, setEditingTagId] = useState(null);

  function resetNodeForm() {
    setEditingNodeId(null);
    setNodeForm({ name: '', description: '' });
  }

  function resetTagForm() {
    setEditingTagId(null);
    setTagForm({ name: '', description: '' });
  }

  function changeTab(nextTab) {
    setTab(nextTab);
    resetNodeForm();
    resetTagForm();
  }

  function beginEditNode(target) {
    setTab('node');
    setEditingNodeId(target.id);
    setNodeForm({ name: target.name || '', description: target.description || '' });
  }

  function beginEditTag(label) {
    setTab('tag');
    setEditingTagId(label.id);
    setTagForm({ name: label.name || '', description: label.description || '' });
  }

  useEffect(() => {
    if (!open) return;
    setTab(initialTab || 'node');
    resetNodeForm();
    resetTagForm();
    if (initialTab === 'node' && initialEditTargetId != null) {
      const target = targets.find(item => Number(item.id) === Number(initialEditTargetId));
      if (target) beginEditNode(target);
    }
  }, [open, initialTab, initialEditTargetId]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = event => {
      if (event.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  async function submitNode(event) {
    event.preventDefault();
    const name = nodeForm.name.trim();
    if (!name) return;
    if (editingNodeId != null) await onUpdateTarget?.(editingNodeId, { name, description: nodeForm.description });
    else await onCreateTarget?.({ name, description: nodeForm.description });
    resetNodeForm();
  }

  async function submitTag(event) {
    event.preventDefault();
    const name = tagForm.name.trim();
    if (!name) return;
    if (editingTagId != null) await onUpdateLabel?.(editingTagId, { name, description: tagForm.description });
    else await onCreateLabel?.({ name, description: tagForm.description });
    resetTagForm();
  }

  async function removeNode(target) {
    if (!confirm(`'${target.name}' 노드를 삭제할까요?\n메시지는 삭제되지 않으며 송수신 노드 연결만 해제됩니다.`)) return;
    await onDeleteTarget?.(target.id);
    if (Number(editingNodeId) === Number(target.id)) resetNodeForm();
  }

  async function removeTag(label) {
    if (!confirm(`'${label.name}' 태그를 삭제할까요?\n메시지는 삭제되지 않습니다.`)) return;
    await onDeleteLabel?.(label.id);
    if (Number(editingTagId) === Number(label.id)) resetTagForm();
  }

  if (!open) return null;

  const isNodeTab = tab === 'node';
  return (
    <div className="reference-drawer-layer" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose?.(); }}>
      <aside className="reference-drawer" role="dialog" aria-modal="true" aria-label="노드 및 태그 추가">
        <div className="reference-drawer-head">
          <div><strong>추가</strong><span>노드와 태그를 현재 화면에서 관리합니다.</span></div>
          <button type="button" className="icon ghost-icon reference-drawer-close" aria-label="닫기" title="닫기" onClick={onClose}>×</button>
        </div>

        <div className="reference-drawer-tabs" role="tablist" aria-label="추가 항목">
          <button type="button" role="tab" aria-selected={isNodeTab} className={isNodeTab ? 'active' : ''} onClick={() => changeTab('node')}>노드 <em>{targets.length}</em></button>
          <button type="button" role="tab" aria-selected={!isNodeTab} className={!isNodeTab ? 'active' : ''} onClick={() => changeTab('tag')}>태그 <em>{labels.length}</em></button>
        </div>

        {isNodeTab ? (
          <>
            <form className="reference-drawer-form" onSubmit={submitNode}>
              <div className="reference-drawer-form-title"><strong>{editingNodeId != null ? '노드 수정' : '노드 추가'}</strong>{editingNodeId != null && <button type="button" className="ghost small-button" onClick={resetNodeForm}>새 노드</button>}</div>
              <label>노드 이름<input autoFocus required placeholder="예: 통합통제 SW" value={nodeForm.name} onChange={event => setNodeForm({ ...nodeForm, name: event.target.value })} /></label>
              <label>설명<textarea placeholder="노드에 대한 설명 (선택)" value={nodeForm.description} onChange={event => setNodeForm({ ...nodeForm, description: event.target.value })} /></label>
              <div className="reference-drawer-form-actions">
                {editingNodeId != null && <button type="button" className="ghost" onClick={resetNodeForm}>취소</button>}
                <button>{editingNodeId != null ? <Save size={14}/> : <Plus size={14}/>} {editingNodeId != null ? '저장' : '추가'}</button>
              </div>
            </form>
            <div className="reference-drawer-list-head"><strong>등록된 노드</strong><span>더블클릭으로도 수정 패널을 열 수 있습니다.</span></div>
            <div className="reference-drawer-list">
              {targets.map(target => (
                <div key={target.id} className={Number(editingNodeId) === Number(target.id) ? 'reference-drawer-item editing' : 'reference-drawer-item'}>
                  <button type="button" className="reference-drawer-item-main" onClick={() => beginEditNode(target)} title={target.description ? `${target.name} · ${target.description}` : target.name}>
                    <strong>{target.name}</strong><span>{target.description || '설명 없음'}</span>
                  </button>
                  <div className="reference-drawer-item-actions"><button type="button" className="ghost" onClick={() => beginEditNode(target)}>수정</button><button type="button" className="ghost danger-text" onClick={() => removeNode(target)}><Trash2 size={13}/></button></div>
                </div>
              ))}
              {!targets.length && <div className="reference-drawer-empty">등록된 노드가 없습니다.</div>}
            </div>
          </>
        ) : (
          <>
            <form className="reference-drawer-form" onSubmit={submitTag}>
              <div className="reference-drawer-form-title"><strong>{editingTagId != null ? '태그 수정' : '태그 추가'}</strong>{editingTagId != null && <button type="button" className="ghost small-button" onClick={resetTagForm}>새 태그</button>}</div>
              <label>태그 이름<input autoFocus required placeholder="예: 상태정보" value={tagForm.name} onChange={event => setTagForm({ ...tagForm, name: event.target.value })} /></label>
              <label>설명<textarea placeholder="태그에 대한 설명 (선택)" value={tagForm.description} onChange={event => setTagForm({ ...tagForm, description: event.target.value })} /></label>
              <div className="reference-drawer-form-actions">
                {editingTagId != null && <button type="button" className="ghost" onClick={resetTagForm}>취소</button>}
                <button>{editingTagId != null ? <Save size={14}/> : <Plus size={14}/>} {editingTagId != null ? '저장' : '추가'}</button>
              </div>
            </form>
            <div className="reference-drawer-list-head"><strong>등록된 태그</strong></div>
            <div className="reference-drawer-list">
              {labels.map(label => (
                <div key={label.id} className={Number(editingTagId) === Number(label.id) ? 'reference-drawer-item editing' : 'reference-drawer-item'}>
                  <button type="button" className="reference-drawer-item-main" onClick={() => beginEditTag(label)} title={label.description ? `${label.name} · ${label.description}` : label.name}>
                    <strong>{label.name}</strong><span>{label.description || '설명 없음'}</span>
                  </button>
                  <div className="reference-drawer-item-actions"><button type="button" className="ghost" onClick={() => beginEditTag(label)}>수정</button><button type="button" className="ghost danger-text" onClick={() => removeTag(label)}><Trash2 size={13}/></button></div>
                </div>
              ))}
              {!labels.length && <div className="reference-drawer-empty">등록된 태그가 없습니다.</div>}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

function MessageFieldPanel({ api, project, message, messages = [], labels = [], integrationTargets = [], setMessage, onReload, onDirtyChange, onOpenReferencePanel, compact = false }) {
  const [messageForm, setMessageForm] = useState({ name: message.name, struct_name: generatedNameOf(message), period: normalizePeriodInput(message.period), infocode: message.infocode || '', protocol: message.protocol || '', description: message.description || '' });
  const [labelIds, setLabelIds] = useState(() => (message.labels || []).map(label => label.id));
  const [txTargetIds, setTxTargetIds] = useState(() => (message.tx_targets || []).map(target => target.id));
  const [rxTargetIds, setRxTargetIds] = useState(() => (message.rx_targets || []).map(target => target.id));
  const [fieldForm, setFieldForm] = useState(createEmptyFieldForm());
  const [draftFields, setDraftFields] = useState(() => fieldsToDraft(message.fields || []));
  const [draggingFieldKey, setDraggingFieldKey] = useState(null);
  const availableTypeMessages = useMemo(() => messages.filter(item => item.id !== message.id && !isEnumDefinition(item)), [messages, message.id]);
  const availableTypeEnums = useMemo(() => messages.filter(item => isEnumDefinition(item)), [messages]);
  const protocolSuggestions = useMemo(() => collectProtocolSuggestions(messages), [messages]);
  const unitSuggestions = useMemo(() => collectUnitSuggestions(messages, message, draftFields, fieldForm), [messages, message, draftFields, fieldForm]);

  const hasFieldChanges = useMemo(
    () => !areFieldDraftsEqual(message.fields || [], draftFields),
    [message.fields, draftFields]
  );

  useEffect(() => {
    setMessageForm({ name: message.name, struct_name: generatedNameOf(message), period: normalizePeriodInput(message.period), infocode: message.infocode || '', protocol: message.protocol || '', description: message.description || '' });
    setLabelIds((message.labels || []).map(label => label.id));
    setTxTargetIds((message.tx_targets || []).map(target => target.id));
    setRxTargetIds((message.rx_targets || []).map(target => target.id));
    setDraftFields(fieldsToDraft(message.fields || []));
    setFieldForm(createEmptyFieldForm());
    setDraggingFieldKey(null);
    onDirtyChange?.(false);
  }, [message.id, message.version]);

  useEffect(() => {
    onDirtyChange?.(hasFieldChanges);
  }, [hasFieldChanges, onDirtyChange]);

  useEffect(() => {
    const validIds = new Set(labels.map(item => Number(item.id)));
    setLabelIds(current => current.filter(id => validIds.has(Number(id))));
  }, [labels.map(item => item.id).join(',')]);

  useEffect(() => {
    const validIds = new Set(integrationTargets.map(item => Number(item.id)));
    setTxTargetIds(current => current.filter(id => validIds.has(Number(id))));
    setRxTargetIds(current => current.filter(id => validIds.has(Number(id))));
  }, [integrationTargets.map(item => item.id).join(',')]);

  useEffect(() => () => onDirtyChange?.(false), []);

  async function saveMessage(e) {
    e.preventDefault();
    if (!isValidIdentifier(messageForm.struct_name)) { alert(`메시지 이름: ${IDENTIFIER_HELP}`); return; }
    if (!String(messageForm.name || '').trim()) { alert('메시지 용도를 입력하세요.'); return; }
    const infocodeOwner = findInfocodeOwner(messages, messageForm.infocode, message.id);
    if (infocodeOwner) {
      alert(`정보코드는 프로젝트 내에서 중복될 수 없습니다. 이미 사용 중인 메시지: ${generatedNameOf(infocodeOwner)}`);
      return;
    }
    await api.patch(`/messages/${message.id}`, { ...messageForm, period: normalizePeriodInput(messageForm.period) });
    await api.post(`/messages/${message.id}/labels`, { label_ids: labelIds });
    const updated = await api.post(`/messages/${message.id}/integration-targets`, { tx_target_ids: txTargetIds, rx_target_ids: rxTargetIds });
    setMessage(updated);
    await onReload();
  }

  function addFieldToDraft(e) {
    e?.preventDefault?.();
    const nextField = normalizeFieldDraft({ ...fieldForm, client_id: makeTempFieldId() });
    const error = validateFieldDraft(nextField, draftFields);
    if (error) { alert(error); return; }
    setDraftFields([...draftFields, { ...nextField, order_index: draftFields.length + 1 }]);
    setFieldForm(createEmptyFieldForm());
  }

  function updateDraftField(fieldKey, changes) {
    setDraftFields(current => current.map(field => {
      if (getFieldKey(field) !== fieldKey) return field;
      return normalizeFieldDraft({ ...field, ...changes });
    }));
  }

  function deleteDraftField(fieldKey) {
    if (!confirm('필드를 삭제할까요?')) return;
    setDraftFields(current => current.filter(field => getFieldKey(field) !== fieldKey).map((field, index) => ({ ...field, order_index: index + 1 })));
  }

  function resetFieldChanges() {
    if (hasFieldChanges && !confirm('저장하지 않은 필드 변경사항을 취소할까요?')) return;
    setDraftFields(fieldsToDraft(message.fields || []));
    setFieldForm(createEmptyFieldForm());
  }

  async function saveFieldChanges() {
    const error = validateFieldDraftList(draftFields);
    if (error) { alert(error); return; }
    const payload = {
      fields: draftFields.map((field, index) => buildFieldSavePayload(field, index + 1)),
    };
    const updated = await api.post(`/messages/${message.id}/fields/bulk-save`, payload);
    setMessage(updated);
    onDirtyChange?.(false);
    await onReload();
  }

  function reorderDraftField(targetFieldKey) {
    if (!draggingFieldKey || draggingFieldKey === targetFieldKey) return;
    const current = [...draftFields];
    const fromIndex = current.findIndex(field => getFieldKey(field) === draggingFieldKey);
    const toIndex = current.findIndex(field => getFieldKey(field) === targetFieldKey);
    if (fromIndex < 0 || toIndex < 0) return;
    const [moved] = current.splice(fromIndex, 1);
    current.splice(toIndex, 0, moved);
    setDraftFields(current.map((field, index) => ({ ...field, order_index: index + 1 })));
    setDraggingFieldKey(null);
  }

  return (
    <section className={compact ? 'page-grid compact-message-editor' : 'page-grid'}>
      <div className="card span-3 message-meta-card">
        <div className="card-title"><div><p className="eyebrow">{project?.name}</p><h2>{generatedNameOf(message)} 메시지 설정</h2><p>메시지 이름/용도/주기/설명을 저장합니다.</p></div><span className="version-badge">버전 v{message.version}</span></div>
        <form className="message-edit" onSubmit={saveMessage}>
          <label>메시지 이름<input required title={IDENTIFIER_HELP} value={messageForm.struct_name || ''} onChange={e => setMessageForm({ ...messageForm, struct_name: sanitizeIdentifier(e.target.value) })} /></label>
          <label>메시지 용도<input required value={messageForm.name} {...overflowInputHandlers(messageForm.name)} onChange={e => setMessageForm({ ...messageForm, name: e.target.value })} /></label>
          <label>주기(ms)<input inputMode="numeric" pattern="[0-9]*" placeholder="주기 입력(ms)" title="주기 입력(ms)값이 없으면 비주기로 저장됩니다." value={normalizePeriodInput(messageForm.period)} onChange={e => setMessageForm({ ...messageForm, period: sanitizePeriod(e.target.value) })} /></label>
          <label>정보코드<input inputMode="numeric" pattern="[0-9]*" placeholder="정보코드" title="정보코드는 숫자만 입력할 수 있으며 미입력도 가능합니다." value={messageForm.infocode || ''} onChange={e => setMessageForm({ ...messageForm, infocode: sanitizeInfocode(e.target.value) })} /></label>
          <label>프로토콜<ProtocolEditor value={messageForm.protocol || ''} onChange={protocol => setMessageForm({ ...messageForm, protocol })} suggestions={protocolSuggestions} /></label>
          <label>설명<input value={messageForm.description} {...overflowInputHandlers(messageForm.description)} onChange={e => setMessageForm({ ...messageForm, description: e.target.value })} /></label>
          <div className="form-wide"><div className="reference-inline-label">태그<button type="button" className="reference-inline-add" title="태그 추가/관리" onClick={() => onOpenReferencePanel?.('tag')}><Plus size={12}/></button></div><LabelCheckboxes labels={labels} selectedIds={labelIds} onChange={setLabelIds} /></div>
          <div className="form-wide"><div className="reference-inline-label">송신 노드<button type="button" className="reference-inline-add" title="노드 추가/관리" onClick={() => onOpenReferencePanel?.('node')}><Plus size={12}/></button></div><LabelCheckboxes labels={integrationTargets} emptyText="등록된 노드가 없습니다." selectedIds={txTargetIds} onChange={setTxTargetIds} /></div>
          <div className="form-wide"><div className="reference-inline-label">수신 노드<button type="button" className="reference-inline-add" title="노드 추가/관리" onClick={() => onOpenReferencePanel?.('node')}><Plus size={12}/></button></div><LabelCheckboxes labels={integrationTargets} emptyText="등록된 노드가 없습니다." selectedIds={rxTargetIds} onChange={setRxTargetIds} /></div>
          <button><Save size={16}/> 메시지 저장</button>
        </form>
      </div>
      <div className="card span-3 message-fields-card">
        <div className="card-title field-list-header">
          <div><h2>필드 목록</h2><p>필드 변경 후 반드시 변경사항 저장을 눌러야 반영됩니다. 마지막 행에서 새 필드를 바로 추가할 수 있습니다.</p></div>
          <div className="field-save-actions">
            {hasFieldChanges && <span className="dirty-indicator">저장되지 않은 변경사항 있음</span>}
            <button type="button" className="ghost" disabled={!hasFieldChanges} onClick={resetFieldChanges}>변경 취소</button>
            <button type="button" disabled={!hasFieldChanges} onClick={saveFieldChanges}><Save size={16}/> 변경사항 저장</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>순서</th><th>자료형</th><th>필드 이름</th><th>필드 용도</th><th>배열</th><th>크기(Byte)</th><th>허용 값 범위</th><th>단위</th><th>비고</th><th>관리</th></tr></thead>
            <tbody>{draftFields.map((field, index) => {
              const fieldKey = getFieldKey(field);
              return <tr key={fieldKey} className={draggingFieldKey === fieldKey ? 'dragging-row' : ''} onDragOver={(e) => { if (draggingFieldKey) e.preventDefault(); }} onDrop={() => reorderDraftField(fieldKey)}>
                <td><span className="order-cell"><span className="drag-handle" draggable title="드래그해서 순서 변경" onDragStart={(e) => { e.stopPropagation(); e.dataTransfer.effectAllowed = 'move'; setDraggingFieldKey(fieldKey); }} onDragEnd={(e) => { e.stopPropagation(); setDraggingFieldKey(null); }}>⋮⋮</span><span className="order-pill">{index + 1}</span></span></td>
                <td><TypeSelect value={field} messages={availableTypeMessages} enums={availableTypeEnums} onChange={next => updateDraftField(fieldKey, next)} compact /></td>
                <td><input required title={IDENTIFIER_HELP} value={field.name || ''} {...overflowInputHandlers(field.name || '', IDENTIFIER_HELP)} onChange={e => { const name = sanitizeIdentifier(e.target.value); updateDraftField(fieldKey, { name, variable_name: name }); }} /></td>
                <td><input value={field.purpose || ''} {...overflowInputHandlers(field.purpose || '')} onChange={e => updateDraftField(fieldKey, { purpose: e.target.value })} /></td>
                <td><ArraySizeControl value={field} onChange={next => updateDraftField(fieldKey, next)} compact /></td>
                <td>{fieldSizeBytes(field, messages)}</td>
                <td><input value={field.value_range || ''} {...overflowInputHandlers(field.value_range || '')} onChange={e => updateDraftField(fieldKey, { value_range: e.target.value })} /></td>
                <td><UnitInput value={field.unit || ''} suggestions={unitSuggestions} onChange={unit => updateDraftField(fieldKey, { unit })} /></td>
                <td><input value={field.note || ''} {...overflowInputHandlers(field.note || '')} onChange={e => updateDraftField(fieldKey, { note: e.target.value })} /></td>
                <td><button type="button" className="icon danger-icon" onClick={() => deleteDraftField(fieldKey)}><Trash2 size={15}/></button></td>
              </tr>;
            })}
              {draftFields.length === 0 && <tr><td colSpan="10" className="muted">저장된 필드가 없습니다. 아래 입력 행에서 새 필드를 추가하세요.</td></tr>}
              <tr className="field-add-row">
                <td><span className="order-cell"><span className="order-pill">+</span></span></td>
                <td><TypeSelect value={fieldForm} messages={availableTypeMessages} enums={availableTypeEnums} onChange={next => setFieldForm(normalizeFieldDraft(next))} compact /></td>
                <td><input title={IDENTIFIER_HELP} placeholder="필드 이름" value={fieldForm.name || ''} {...overflowInputHandlers(fieldForm.name || '', IDENTIFIER_HELP)} onChange={e => { const name = sanitizeIdentifier(e.target.value); setFieldForm({ ...fieldForm, name, variable_name: name }); }} /></td>
                <td><input placeholder="필드 용도" value={fieldForm.purpose || ''} {...overflowInputHandlers(fieldForm.purpose || '')} onChange={e => setFieldForm({ ...fieldForm, purpose: e.target.value })} /></td>
                <td><ArraySizeControl value={fieldForm} onChange={next => setFieldForm(normalizeFieldDraft(next))} compact /></td>
                <td>{fieldSizeBytes(fieldForm, messages)}</td>
                <td><input placeholder="허용 값 범위" value={fieldForm.value_range || ''} {...overflowInputHandlers(fieldForm.value_range || '')} onChange={e => setFieldForm({ ...fieldForm, value_range: e.target.value })} /></td>
                <td><UnitInput placeholder="단위" value={fieldForm.unit || ''} suggestions={unitSuggestions} onChange={unit => setFieldForm({ ...fieldForm, unit })} /></td>
                <td><input placeholder="비고" value={fieldForm.note || ''} {...overflowInputHandlers(fieldForm.note || '')} onChange={e => setFieldForm({ ...fieldForm, note: e.target.value })} /></td>
                <td><button type="button" onClick={addFieldToDraft} disabled={!fieldForm.name}><Plus size={15}/> 추가</button></td>
              </tr></tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function EnumValuePanel({ api, project, enumMessage, labels = [], setMessage, onReload, onDirtyChange, onOpenReferencePanel }) {
  const [messageForm, setMessageForm] = useState({
    name: enumMessage.name,
    struct_name: generatedNameOf(enumMessage),
    description: enumMessage.description || '',
    enum_underlying_type: enumMessage.enum_underlying_type || 'uint32',
  });
  const [labelIds, setLabelIds] = useState(() => (enumMessage.labels || []).map(label => label.id));
  const [valueForm, setValueForm] = useState(createEmptyEnumValueForm(enumMessage.enum_values || []));
  const [draftValues, setDraftValues] = useState(() => enumValuesToDraft(enumMessage.enum_values || []));
  const [draggingValueKey, setDraggingValueKey] = useState(null);

  const hasValueChanges = useMemo(
    () => !areEnumValueDraftsEqual(enumMessage.enum_values || [], draftValues),
    [enumMessage.enum_values, draftValues]
  );

  useEffect(() => {
    setMessageForm({
      name: enumMessage.name,
      struct_name: generatedNameOf(enumMessage),
      description: enumMessage.description || '',
      enum_underlying_type: enumMessage.enum_underlying_type || 'uint32',
    });
    setLabelIds((enumMessage.labels || []).map(label => label.id));
    setDraftValues(enumValuesToDraft(enumMessage.enum_values || []));
    setValueForm(createEmptyEnumValueForm(enumMessage.enum_values || []));
    setDraggingValueKey(null);
    onDirtyChange?.(false);
  }, [enumMessage.id, enumMessage.version]);

  useEffect(() => { onDirtyChange?.(hasValueChanges); }, [hasValueChanges, onDirtyChange]);
  useEffect(() => {
    const validIds = new Set(labels.map(item => Number(item.id)));
    setLabelIds(current => current.filter(id => validIds.has(Number(id))));
  }, [labels.map(item => item.id).join(',')]);
  useEffect(() => () => onDirtyChange?.(false), []);

  async function saveEnumInfo(e) {
    e.preventDefault();
    if (!isValidIdentifier(messageForm.struct_name)) { alert(`Enum 이름: ${IDENTIFIER_HELP}`); return; }
    if (!String(messageForm.name || '').trim()) { alert('Enum 용도를 입력하세요.'); return; }
    await api.patch(`/messages/${enumMessage.id}`, messageForm);
    const updated = await api.post(`/messages/${enumMessage.id}/labels`, { label_ids: labelIds });
    setMessage(updated);
    await onReload();
  }

  function addValueToDraft(e) {
    e.preventDefault();
    const nextValue = normalizeEnumValueDraft({ ...valueForm, client_id: makeTempFieldId() });
    const error = validateEnumValueDraft(nextValue, draftValues, messageForm.enum_underlying_type || enumMessage.enum_underlying_type);
    if (error) { alert(error); return; }
    setDraftValues([...draftValues, { ...nextValue, order_index: draftValues.length + 1 }]);
    setValueForm(createEmptyEnumValueForm([...draftValues, nextValue]));
  }

  function updateDraftValue(valueKey, changes) {
    setDraftValues(current => current.map(value => getFieldKey(value) === valueKey ? normalizeEnumValueDraft({ ...value, ...changes }) : value));
  }

  function deleteDraftValue(valueKey) {
    if (!confirm('Enum 값을 삭제할까요?')) return;
    setDraftValues(current => current.filter(value => getFieldKey(value) !== valueKey).map((value, index) => ({ ...value, order_index: index + 1 })));
  }

  function resetValueChanges() {
    if (hasValueChanges && !confirm('저장하지 않은 Enum 값 변경사항을 취소할까요?')) return;
    setLabelIds((enumMessage.labels || []).map(label => label.id));
    setDraftValues(enumValuesToDraft(enumMessage.enum_values || []));
    setValueForm(createEmptyEnumValueForm(enumMessage.enum_values || []));
  }

  async function saveValueChanges() {
    const error = validateEnumValueDraftList(draftValues, messageForm.enum_underlying_type || enumMessage.enum_underlying_type);
    if (error) { alert(error); return; }
    const payload = { values: draftValues.map((value, index) => buildEnumValueSavePayload(value, index + 1)) };
    const updated = await api.post(`/messages/${enumMessage.id}/enum-values/bulk-save`, payload);
    setMessage(updated);
    onDirtyChange?.(false);
    await onReload();
  }

  function reorderDraftValue(targetValueKey) {
    if (!draggingValueKey || draggingValueKey === targetValueKey) return;
    const current = [...draftValues];
    const fromIndex = current.findIndex(value => getFieldKey(value) === draggingValueKey);
    const toIndex = current.findIndex(value => getFieldKey(value) === targetValueKey);
    if (fromIndex < 0 || toIndex < 0) return;
    const [moved] = current.splice(fromIndex, 1);
    current.splice(toIndex, 0, moved);
    setDraftValues(current.map((value, index) => ({ ...value, order_index: index + 1 })));
    setDraggingValueKey(null);
  }

  return (
    <section className="page-grid">
      <div className="card span-3">
        <div className="card-title"><div><p className="eyebrow">{project?.name}</p><h2>{generatedNameOf(enumMessage)} Enum 설정</h2><p>Enum 이름과 용도, 기본 자료형을 관리합니다. 기본 자료형은 값 전체에 공통 적용됩니다.</p></div><span className="version-badge">버전 v{enumMessage.version}</span></div>
        <form className="message-edit" onSubmit={saveEnumInfo}>
          <label>Enum 이름<input required title={IDENTIFIER_HELP} value={messageForm.struct_name || ''} onChange={e => setMessageForm({ ...messageForm, struct_name: sanitizeIdentifier(e.target.value) })} /></label>
          <label>Enum 용도<input required value={messageForm.name} onChange={e => setMessageForm({ ...messageForm, name: e.target.value })} /></label>
          <label>기본 자료형<select value={messageForm.enum_underlying_type} onChange={e => setMessageForm({ ...messageForm, enum_underlying_type: e.target.value })}>{ENUM_UNDERLYING_TYPES.map(type => <option key={type} value={type}>{type}</option>)}</select></label>
          <label>설명<input value={messageForm.description} {...overflowInputHandlers(messageForm.description)} onChange={e => setMessageForm({ ...messageForm, description: e.target.value })} /></label>
          <div className="form-wide"><div className="reference-inline-label">태그<button type="button" className="reference-inline-add" title="태그 추가/관리" onClick={() => onOpenReferencePanel?.('tag')}><Plus size={12}/></button></div><LabelCheckboxes labels={labels} selectedIds={labelIds} onChange={setLabelIds} /></div>
          <button><Save size={16}/> Enum 저장</button>
        </form>
      </div>
      <div className="card span-3">
        <div className="card-title"><div><h2>Enum 값 추가</h2><p>값 이름/숫자 값/설명을 입력하여 Enum 값 목록에 추가합니다.</p></div></div>
        <form className="field-create" onSubmit={addValueToDraft}>
          <label>값 이름<input required title={IDENTIFIER_HELP} value={valueForm.name} onChange={e => setValueForm({ ...valueForm, name: sanitizeIdentifier(e.target.value) })} /></label>
          <label>값<input required type="number" value={valueForm.value} onChange={e => setValueForm({ ...valueForm, value: e.target.value })} /></label>
          <label>설명<input value={valueForm.description} {...overflowInputHandlers(valueForm.description)} onChange={e => setValueForm({ ...valueForm, description: e.target.value })} /></label>
          <button><Plus size={16}/> 목록에 추가</button>
        </form>
      </div>
      <div className="card span-3 message-fields-card">
        <div className="card-title field-list-header">
          <div><h2>Enum 값 목록</h2><p>Enum 값 변경 후 반드시 변경사항 저장을 눌러야 반영됩니다. 모든 값은 위의 기본 자료형을 공통으로 사용합니다.</p></div>
          <div className="field-save-actions">
            {hasValueChanges && <span className="dirty-indicator">저장되지 않은 변경사항 있음</span>}
            <button type="button" className="ghost" disabled={!hasValueChanges} onClick={resetValueChanges}>변경 취소</button>
            <button type="button" disabled={!hasValueChanges} onClick={saveValueChanges}><Save size={16}/> 변경사항 저장</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>순서</th><th>Enum 값 이름</th><th>숫자 값</th><th>설명</th><th>관리</th></tr></thead>
            <tbody>{draftValues.map((value, index) => {
              const valueKey = getFieldKey(value);
              return <tr key={valueKey} className={draggingValueKey === valueKey ? 'dragging-row' : ''} onDragOver={(e) => { if (draggingValueKey) e.preventDefault(); }} onDrop={() => reorderDraftValue(valueKey)}>
                <td><span className="order-cell"><span className="drag-handle" draggable title="드래그해서 순서 변경" onDragStart={(e) => { e.stopPropagation(); e.dataTransfer.effectAllowed = 'move'; setDraggingValueKey(valueKey); }} onDragEnd={(e) => { e.stopPropagation(); setDraggingValueKey(null); }}>⋮⋮</span><span className="order-pill">{index + 1}</span></span></td>
                <td><input required title={IDENTIFIER_HELP} value={value.name} onChange={e => updateDraftValue(valueKey, { name: sanitizeIdentifier(e.target.value) })} /></td>
                <td><input required type="number" value={value.value} onChange={e => updateDraftValue(valueKey, { value: e.target.value })} /></td>
                <td><input value={value.description || ''} {...overflowInputHandlers(value.description || '')} onChange={e => updateDraftValue(valueKey, { description: e.target.value })} /></td>
                <td><button type="button" className="icon danger-icon" onClick={() => deleteDraftValue(valueKey)}><Trash2 size={15}/></button></td>
              </tr>;
            })}{draftValues.length === 0 && <tr><td colSpan="5" className="muted">Enum 값이 없습니다.</td></tr>}</tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function createEmptyEnumValueForm(existingValues = []) {
  const nextValue = existingValues.length ? Math.max(...existingValues.map(value => Number(value.value) || 0)) + 1 : 0;
  return { name: '', value: String(nextValue), description: '', order_index: 0 };
}

function normalizeEnumValueDraft(value) {
  return {
    ...value,
    name: value?.name || '',
    value: value?.value === 0 ? '0' : String(value?.value ?? ''),
    description: value?.description || '',
  };
}

function enumValuesToDraft(values) {
  return [...values]
    .sort((a, b) => (a.order_index || 0) - (b.order_index || 0) || (a.id || 0) - (b.id || 0))
    .map(value => normalizeEnumValueDraft(value));
}

function enumBounds(underlyingType) {
  return {
    int8: [-128, 127],
    uint8: [0, 255],
    int16: [-32768, 32767],
    uint16: [0, 65535],
    int32: [-2147483648, 2147483647],
    uint32: [0, 4294967295],
    int64: [Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER],
    uint64: [0, Number.MAX_SAFE_INTEGER],
  }[underlyingType || 'uint32'] || [0, 4294967295];
}

function validateEnumValueDraft(value, existingValues = [], underlyingType = 'uint32', currentKey = getFieldKey(value)) {
  if (!value.name || !value.name.trim()) return 'Enum 값 이름을 입력하세요.';
  if (!isValidIdentifier(value.name)) return `Enum 값 이름: ${IDENTIFIER_HELP}`;
  if (value.value === '' || value.value === null || value.value === undefined) return 'Enum 숫자 값을 입력하세요.';
  const numberValue = Number(value.value);
  if (!Number.isInteger(numberValue)) return 'Enum 숫자 값은 정수로 입력하세요.';
  const [minValue, maxValue] = enumBounds(underlyingType);
  if (numberValue < minValue || numberValue > maxValue) return `${value.name} 값은 ${underlyingType} 범위를 벗어났습니다.`;
  const duplicatedName = existingValues.some(existing => getFieldKey(existing) !== currentKey && String(existing.name || '').toLowerCase() === String(value.name || '').toLowerCase());
  if (duplicatedName) return '같은 Enum 안에서 값 이름은 중복될 수 없습니다.';
  const duplicatedValue = existingValues.some(existing => getFieldKey(existing) !== currentKey && Number(existing.value) === numberValue);
  if (duplicatedValue) return '같은 Enum 안에서 숫자 값은 중복될 수 없습니다.';
  return '';
}

function validateEnumValueDraftList(values, underlyingType = 'uint32') {
  const seenNames = new Set();
  const seenValues = new Set();
  for (const value of values) {
    const error = validateEnumValueDraft(value, [], underlyingType, getFieldKey(value));
    if (error) return error;
    const nameKey = String(value.name || '').toLowerCase();
    if (seenNames.has(nameKey)) return '같은 Enum 안에서 값 이름은 중복될 수 없습니다.';
    seenNames.add(nameKey);
    const numberValue = Number(value.value);
    if (seenValues.has(numberValue)) return '같은 Enum 안에서 숫자 값은 중복될 수 없습니다.';
    seenValues.add(numberValue);
  }
  return '';
}

function buildEnumValueSavePayload(value, orderIndex) {
  const payload = {
    name: value.name,
    value: Number(value.value),
    description: value.description || '',
    order_index: orderIndex,
  };
  if (typeof value.id === 'number') payload.id = value.id;
  return payload;
}

function arrayDimensionsFromField(field) {
  const arrayInfo = normalizeArraySizeValue(fieldArrayInputValue(field));
  return arrayInfo.isArray && arrayInfo.arrayDimensions ? arrayInfo.arrayDimensions.split(',').map(value => Number(value)).filter(value => Number.isInteger(value) && value > 0) : [];
}

function arrayElementCount(field) {
  return arrayDimensionsFromField(field).reduce((acc, value) => acc * value, 1);
}

function messageSizeBytes(message, allMessages = [], visiting = new Set()) {
  if (!message) return 0;
  if (message.size_bytes !== undefined && message.size_bytes !== null && !visiting.size) return Number(message.size_bytes) || 0;
  if (message.definition_type === 'ENUM') return TYPE_BYTE_SIZES[message.enum_underlying_type || 'uint32'] || 4;
  if (visiting.has(message.id)) return 0;
  visiting.add(message.id);
  const total = (message.fields || []).reduce((sum, field) => sum + fieldSizeBytes(field, allMessages, visiting), 0);
  visiting.delete(message.id);
  return total;
}

function fieldBaseSizeBytes(field, allMessages = [], visiting = new Set()) {
  const typeKind = String(field?.type_kind || 'BASIC').toUpperCase();
  if ((typeKind === 'MESSAGE' || typeKind === 'ENUM') && field?.ref_message_id) {
    const ref = allMessages.find(message => message.id === Number(field.ref_message_id));
    return messageSizeBytes(ref, allMessages, visiting);
  }
  return TYPE_BYTE_SIZES[field?.type || ''] || 0;
}

function fieldSizeBytes(field, allMessages = [], visiting = new Set()) {
  return fieldBaseSizeBytes(field, allMessages, visiting) * arrayElementCount(field);
}

function createEmptyFieldForm() {
  return { type: 'uint32', type_kind: 'BASIC', ref_message_id: null, name: '', variable_name: '', description: '', purpose: '', value_range: '', unit: '', note: '', is_array: false, array_size: '', array_dimensions: '' };
}

function normalizeArraySizeValue(value) {
  const raw = String(value ?? '').trim().replace(/\s+/g, '');
  if (raw === '') return { isArray: false, arraySizeText: '', arrayDimensions: null, arraySizeNumber: null, isValid: true };
  if (raw === '0') return { isArray: false, arraySizeText: raw, arrayDimensions: null, arraySizeNumber: null, isValid: true };
  const parts = raw.split(',');
  const isValid = parts.length > 0 && parts.every(part => /^\d+$/.test(part) && Number(part) > 0);
  if (!isValid) return { isArray: false, arraySizeText: raw, arrayDimensions: null, arraySizeNumber: null, isValid: false };
  const normalizedParts = parts.map(part => String(Number(part)));
  const dimensions = normalizedParts.join(',');
  return {
    isArray: true,
    arraySizeText: dimensions,
    arrayDimensions: dimensions,
    arraySizeNumber: Number(normalizedParts[0]),
    isValid: true,
  };
}

function fieldArrayInputValue(field) {
  if (field?.array_dimensions !== undefined && field?.array_dimensions !== null && field?.array_dimensions !== '') return String(field.array_dimensions);
  if (field?.is_array && field?.array_size) return String(field.array_size);
  return String(field?.array_size ?? '');
}

function arrayDisplaySuffix(field) {
  const arrayInfo = normalizeArraySizeValue(fieldArrayInputValue(field));
  if (!arrayInfo.isArray) return '';
  return arrayInfo.arrayDimensions.split(',').map(size => `[${size}]`).join('');
}

function makeTempFieldId() {
  return `tmp_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function getFieldKey(field) {
  return field.id ?? field.client_id;
}

function normalizeFieldDraft(field) {
  const arrayInfo = normalizeArraySizeValue(fieldArrayInputValue(field));
  const rawTypeKind = String(field?.type_kind || 'BASIC').toUpperCase();
  const typeKind = rawTypeKind === 'MESSAGE' || rawTypeKind === 'ENUM' ? rawTypeKind : 'BASIC';
  const refMessageId = typeKind !== 'BASIC' && field?.ref_message_id != null && field?.ref_message_id !== '' ? Number(field.ref_message_id) : null;
  const fieldName = field?.variable_name || field?.name || '';
  return {
    ...field,
    type: field?.type || (typeKind === 'BASIC' ? 'uint32' : ''),
    type_kind: typeKind,
    ref_message_id: Number.isFinite(refMessageId) ? refMessageId : null,
    name: fieldName,
    variable_name: fieldName,
    description: field?.description || '',
    purpose: field?.purpose || '',
    value_range: field?.value_range || '',
    unit: field?.unit || '',
    note: field?.note || '',
    is_array: arrayInfo.isArray,
    array_size: arrayInfo.arraySizeText,
    array_dimensions: arrayInfo.arrayDimensions || '',
  };
}

function fieldsToDraft(fields) {
  return [...fields]
    .sort((a, b) => (a.order_index || 0) - (b.order_index || 0) || (a.id || 0) - (b.id || 0))
    .map(field => normalizeFieldDraft({ ...field, array_size: fieldArrayInputValue(field) }));
}

function buildFieldSavePayload(field, orderIndex) {
  const arrayInfo = normalizeArraySizeValue(field.array_size);
  const payload = {
    type: field.type,
    type_kind: field.type_kind || 'BASIC',
    ref_message_id: field.type_kind === 'MESSAGE' || field.type_kind === 'ENUM' ? field.ref_message_id : null,
    name: field.name,
    variable_name: field.name,
    description: field.description || '',
    purpose: field.purpose || '',
    value_range: field.value_range || '',
    unit: field.unit || '',
    note: field.note || '',
    is_array: arrayInfo.isArray,
    array_size: arrayInfo.isArray ? arrayInfo.arraySizeNumber : null,
    array_dimensions: arrayInfo.isArray ? arrayInfo.arrayDimensions : null,
    order_index: orderIndex,
  };
  if (typeof field.id === 'number') payload.id = field.id;
  return payload;
}

function comparableField(field, orderIndex) {
  const arrayInfo = normalizeArraySizeValue(field.array_size);
  return {
    type: field.type,
    type_kind: field.type_kind || 'BASIC',
    ref_message_id: field.type_kind === 'MESSAGE' || field.type_kind === 'ENUM' ? field.ref_message_id : null,
    name: field.name,
    variable_name: field.name,
    description: field.description || '',
    purpose: field.purpose || '',
    value_range: field.value_range || '',
    unit: field.unit || '',
    note: field.note || '',
    is_array: arrayInfo.isArray,
    array_size: arrayInfo.isArray ? arrayInfo.arraySizeNumber : null,
    array_dimensions: arrayInfo.isArray ? arrayInfo.arrayDimensions : null,
    order_index: orderIndex,
  };
}

function areFieldDraftsEqual(sourceFields, draftFields) {
  const source = fieldsToDraft(sourceFields).map((field, index) => comparableField(field, index + 1));
  const draft = draftFields.map((field, index) => comparableField(field, index + 1));
  return JSON.stringify(source) === JSON.stringify(draft);
}

function validateFieldDraft(field, existingFields = [], currentKey = null) {
  if (field.type_kind === 'MESSAGE' && !field.ref_message_id) return '메시지 자료형을 선택하세요.';
  if (field.type_kind === 'ENUM' && !field.ref_message_id) return 'Enum 자료형을 선택하세요.';
  if (field.type_kind !== 'MESSAGE' && field.type_kind !== 'ENUM' && !SUPPORTED_TYPES.includes(field.type)) return '지원하지 않는 기본 자료형입니다.';
  if (!isValidIdentifier(field.name)) return `필드 이름: ${IDENTIFIER_HELP}`;
  const duplicated = existingFields.some(existing => getFieldKey(existing) !== currentKey && String(existing.name || '').toLowerCase() === String(field.name || '').toLowerCase());
  if (duplicated) return '같은 메시지 안에서 필드 이름은 중복될 수 없습니다.';
  const rawArraySize = fieldArrayInputValue(field).trim();
  if (rawArraySize !== '') {
    const arrayInfo = normalizeArraySizeValue(rawArraySize);
    if (!arrayInfo.isValid) return '배열 크기는 빈칸, 0, 또는 10 / 3,4 형식으로 입력하세요.';
  }
  return '';
}

function validateFieldDraftList(fields) {
  const seen = new Set();
  for (const field of fields) {
    const error = validateFieldDraft(field, [], getFieldKey(field));
    if (error) return error;
    const nameKey = String(field.name || '').toLowerCase();
    if (seen.has(nameKey)) return '같은 메시지 안에서 필드 이름은 중복될 수 없습니다.';
    seen.add(nameKey);
  }
  return '';
}

function normalizeFieldPayload(field) {
  const arrayInfo = normalizeArraySizeValue(field.array_size);
  return {
    type: field.type,
    type_kind: field.type_kind || 'BASIC',
    ref_message_id: field.type_kind === 'MESSAGE' || field.type_kind === 'ENUM' ? field.ref_message_id : null,
    name: field.name,
    variable_name: field.name,
    description: field.description || '',
    purpose: field.purpose || '',
    value_range: field.value_range || '',
    unit: field.unit || '',
    note: field.note || '',
    is_array: arrayInfo.isArray,
    array_size: arrayInfo.isArray ? arrayInfo.arraySizeNumber : null,
    array_dimensions: arrayInfo.isArray ? arrayInfo.arrayDimensions : null,
  };
}


function getTypeSelectValue(field) {
  if ((field?.type_kind === 'MESSAGE' || field?.type_kind === 'ENUM') && field?.ref_message_id) return `${field.type_kind}:${field.ref_message_id}`;
  return `BASIC:${field?.type || 'uint32'}`;
}

function applyTypeSelectValue(rawValue, messages, field) {
  const [kind, rawIdOrType] = String(rawValue || '').split(':');
  if (kind === 'MESSAGE' || kind === 'ENUM') {
    const refMessageId = Number(rawIdOrType);
    const refMessage = messages.find(message => message.id === refMessageId);
    return {
      ...field,
      type_kind: kind,
      ref_message_id: Number.isFinite(refMessageId) ? refMessageId : null,
      type: generatedNameOf(refMessage) || field?.type || '',
    };
  }
  const basicType = SUPPORTED_TYPES.includes(rawIdOrType) ? rawIdOrType : 'uint32';
  return {
    ...field,
    type_kind: 'BASIC',
    ref_message_id: null,
    type: basicType,
  };
}

function TypeSelect({ value, messages = [], enums = [], onChange, compact = false }) {
  const messageListId = useId();
  const enumListId = useId();
  const sortedMessages = [...messages].sort((a, b) => generatedNameOf(a).localeCompare(generatedNameOf(b)));
  const sortedEnums = [...enums].sort((a, b) => generatedNameOf(a).localeCompare(generatedNameOf(b)));
  const rawTypeKind = String(value?.type_kind || 'BASIC').toUpperCase();
  const typeKind = rawTypeKind === 'MESSAGE' || rawTypeKind === 'ENUM' ? rawTypeKind : 'BASIC';
  const currentRefList = typeKind === 'ENUM' ? sortedEnums : sortedMessages;
  const currentRefName = typeKind !== 'BASIC'
    ? (currentRefList.find(item => item.id === value?.ref_message_id)?.struct_name || currentRefList.find(item => item.id === value?.ref_message_id)?.name || value?.type || '')
    : '';

  function changeTypeKind(nextKind) {
    if (nextKind === 'MESSAGE') {
      onChange({ ...value, type_kind: 'MESSAGE', type: '', ref_message_id: null });
      return;
    }
    if (nextKind === 'ENUM') {
      onChange({ ...value, type_kind: 'ENUM', type: '', ref_message_id: null });
      return;
    }
    onChange({
      ...value,
      type_kind: 'BASIC',
      type: SUPPORTED_TYPES.includes(value?.type) ? value.type : 'uint32',
      ref_message_id: null,
    });
  }

  function changeBasicType(nextType) {
    onChange({
      ...value,
      type_kind: 'BASIC',
      type: SUPPORTED_TYPES.includes(nextType) ? nextType : 'uint32',
      ref_message_id: null,
    });
  }

  function changeRefName(nextName) {
    const candidates = typeKind === 'ENUM' ? sortedEnums : sortedMessages;
    const matched = candidates.find(item => generatedNameOf(item) === nextName);
    onChange({
      ...value,
      type_kind: typeKind,
      type: nextName,
      ref_message_id: matched?.id ?? null,
    });
  }

  return (
    <div className={compact ? 'type-picker compact' : 'type-picker'}>
      <select aria-label="자료형 종류" value={typeKind} onChange={e => changeTypeKind(e.target.value)}>
        <option value="BASIC">기본</option>
        <option value="MESSAGE">메시지</option>
        <option value="ENUM">Enum</option>
      </select>
      {typeKind === 'MESSAGE' || typeKind === 'ENUM' ? (
        <>
          <input
            aria-label={typeKind === 'ENUM' ? 'Enum 자료형' : '메시지 자료형'}
            list={typeKind === 'ENUM' ? enumListId : messageListId}
            placeholder={typeKind === 'ENUM' ? 'Enum명 검색' : '메시지명 검색'}
            value={currentRefName}
            onChange={e => changeRefName(e.target.value)}
          />
          <datalist id={messageListId}>
            {sortedMessages.map(message => <option key={message.id} value={generatedNameOf(message)} label={displayNameWithStruct(message)} />)}
          </datalist>
          <datalist id={enumListId}>
            {sortedEnums.map(enumItem => <option key={enumItem.id} value={generatedNameOf(enumItem)} label={displayNameWithStruct(enumItem)} />)}
          </datalist>
        </>
      ) : (
        <select aria-label="기본 자료형" value={value?.type || 'uint32'} onChange={e => changeBasicType(e.target.value)}>
          {SUPPORTED_TYPES.map(type => <option key={type} value={type}>{type}</option>)}
        </select>
      )}
    </div>
  );
}

function ArraySizeControl({ value, onChange, compact = false }) {
  const arraySize = fieldArrayInputValue(value);

  function updateArraySize(nextValue) {
    const sanitized = String(nextValue || '').replace(/[^0-9,]/g, '');
    const arrayInfo = normalizeArraySizeValue(sanitized);
    onChange({
      ...value,
      is_array: arrayInfo.isArray,
      array_size: arrayInfo.isArray ? arrayInfo.arraySizeText : sanitized,
      array_dimensions: arrayInfo.isArray ? arrayInfo.arrayDimensions : '',
    });
  }

  return (
    <label className={compact ? 'array-size-label compact' : 'array-size-label'}>
      {!compact && '배열'}
      <span className="array-size-control">
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9,]*"
          placeholder="배열 크기 예: 10 또는 3,4"
          title="빈칸 또는 0이면 비배열, 10은 1차원, 3,4는 2차원 배열로 저장됩니다."
          value={arraySize}
          onChange={e => updateArraySize(e.target.value)}
        />
      </span>
    </label>
  );
}



const HISTORY_ACTION_LABELS = {
  CREATE: '메시지 생성',
  UPDATE: '메시지 수정',
  DELETE: '메시지 삭제',
  FIELD_CREATE: '필드 추가',
  FIELD_UPDATE: '필드 변경',
  FIELD_DELETE: '필드 삭제',
  GROUP_CREATE: '그룹 생성',
  GROUP_UPDATE: '그룹 수정',
  GROUP_DELETE: '그룹 삭제',
  RESTORE: '복원',
};

const MESSAGE_HISTORY_LABELS = {
  name: '이름',
  period: '주기',
  description: '설명',
  version: '버전',
  order_index: '순서',
};

function getHistoryActionLabel(history) {
  if (history?.after_json?.partial_update) return '부분 업데이트';
  return HISTORY_ACTION_LABELS[String(history?.change_type || '')] || String(history?.change_type || '-');
}

function valueText(value) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  return String(value);
}

function fieldTypeText(field) {
  if (!field) return '-';
  return valueText(field.type);
}

function fieldArrayText(field) {
  if (!field) return '비배열';
  const suffix = arrayDisplaySuffix(field);
  return suffix ? `배열 ${suffix}` : '비배열';
}

function fieldBrief(field) {
  if (!field) return '-';
  const parts = [field.name || '-', fieldTypeText(field), fieldArrayText(field)];
  if (field.description) parts.push(field.description);
  return parts.join(' / ');
}

function fieldDiffText(before, after) {
  const changes = [];
  if (valueText(before?.name) !== valueText(after?.name)) changes.push(`이름 ${valueText(before?.name)} → ${valueText(after?.name)}`);
  if (fieldTypeText(before) !== fieldTypeText(after)) changes.push(`자료형 ${fieldTypeText(before)} → ${fieldTypeText(after)}`);
  if (fieldArrayText(before) !== fieldArrayText(after)) changes.push(`배열 ${fieldArrayText(before)} → ${fieldArrayText(after)}`);
  if (valueText(before?.description) !== valueText(after?.description)) changes.push(`설명 ${valueText(before?.description)} → ${valueText(after?.description)}`);
  return changes.join(', ');
}

function normalizeFieldListFromHistory(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.fields)) return value.fields;
  if (Array.isArray(value?.reordered_fields)) return value.reordered_fields;
  return [];
}

function orderSignature(fields) {
  return fields.map(field => field.name || `#${field.id}`).join(' → ');
}

function buildFieldBulkChangeLines(beforeValue, afterValue) {
  const beforeFields = normalizeFieldListFromHistory(beforeValue);
  const afterFields = normalizeFieldListFromHistory(afterValue);
  const beforeByName = new Map(beforeFields.map(field => [String(field.name || '').toLowerCase(), field]));
  const afterByName = new Map(afterFields.map(field => [String(field.name || '').toLowerCase(), field]));
  const lines = [];

  afterFields.forEach(field => {
    if (!beforeByName.has(String(field.name || '').toLowerCase())) {
      lines.push(`필드 추가: ${fieldBrief(field)}`);
    }
  });
  beforeFields.forEach(field => {
    if (!afterByName.has(String(field.name || '').toLowerCase())) {
      lines.push(`필드 삭제: ${fieldBrief(field)}`);
    }
  });
  afterFields.forEach(afterField => {
    const beforeField = beforeByName.get(String(afterField.name || '').toLowerCase());
    if (!beforeField) return;
    const diff = fieldDiffText(beforeField, afterField);
    if (diff) lines.push(`필드 수정: ${afterField.name} — ${diff}`);
  });

  const beforeNames = beforeFields.map(field => String(field.name || '').toLowerCase()).sort().join('|');
  const afterNames = afterFields.map(field => String(field.name || '').toLowerCase()).sort().join('|');
  if (beforeNames && beforeNames === afterNames && orderSignature(beforeFields) !== orderSignature(afterFields)) {
    lines.push(`필드 순서 변경: ${orderSignature(afterFields)}`);
  }
  if (afterValue?.version) lines.push(`버전: v${afterValue.version}`);
  return lines.length ? lines : ['필드 구조 변경사항 없음'];
}

function buildMessageChangeLines(beforeValue, afterValue) {
  if (afterValue?.reordered_messages) {
    return [`메시지 순서 변경: ${orderSignature(afterValue.reordered_messages)}`];
  }
  const before = beforeValue || {};
  const after = afterValue || {};
  const lines = [];
  Object.keys(MESSAGE_HISTORY_LABELS).forEach(key => {
    if (valueText(before[key]) !== valueText(after[key])) {
      lines.push(`${MESSAGE_HISTORY_LABELS[key]}: ${valueText(before[key])} → ${valueText(after[key])}`);
    }
  });
  return lines.length ? lines : ['메시지 정보 변경사항 없음'];
}

function buildHistoryDetailLines(history) {
  const type = String(history?.change_type || '');
  const before = history?.before_json;
  const after = history?.after_json;

  if (type === 'CREATE') {
    if (after?.message) {
      const lines = [`메시지 복사 생성: ${valueText(after.copied_from_message_name)} → ${valueText(after.message.name)}`];
      if (Array.isArray(after.fields)) lines.push(`복사된 필드: ${after.fields.length}개`);
      lines.push('필요 시 복사된 메시지명을 변경하세요.');
      return lines;
    }
    return [`메시지 생성: ${valueText(after?.name)} / 주기 ${valueText(after?.period)} / v${valueText(after?.version)}`];
  }
  if (type === 'DELETE') {
    return [`메시지 삭제: ${valueText(before?.name)}`];
  }
  if (type === 'UPDATE') {
    const partial = after?.partial_update;
    if (partial) {
      const lines = [`파일: ${valueText(partial.filename)}`, `적용 메시지: ${valueText(partial.message_count)}개`];
      let detailCount = 0;
      (partial.messages || []).forEach(message => {
        if (detailCount >= 24) return;
        lines.push(`${message.status === 'NEW' ? '신규' : '변경'}: ${valueText(message.name)}${message.purpose ? ` (${message.purpose})` : ''}`);
        detailCount += 1;
        (message.diffs || []).forEach(diff => {
          if (detailCount >= 24) return;
          lines.push(`  ${diff}`);
          detailCount += 1;
        });
      });
      const totalPossible = (partial.messages || []).reduce((sum, message) => sum + 1 + (message.diffs || []).length, 0);
      if (totalPossible > detailCount) lines.push(`외 ${totalPossible - detailCount}개 변경 내용`);
      return lines;
    }
    return buildMessageChangeLines(before, after);
  }
  if (type === 'FIELD_CREATE') {
    return [`필드 추가: ${fieldBrief(after)}`];
  }
  if (type === 'FIELD_DELETE') {
    return [`필드 삭제: ${fieldBrief(before)}`];
  }
  if (type === 'FIELD_UPDATE') {
    if (before?.fields || after?.fields || after?.reordered_fields || Array.isArray(before) || Array.isArray(after)) {
      return buildFieldBulkChangeLines(before, after);
    }
    const diff = fieldDiffText(before, after);
    return [diff ? `필드 수정: ${valueText(after?.name)} — ${diff}` : `필드 수정: ${valueText(after?.name)}`];
  }
  if (type.startsWith('GROUP_')) {
    return [`그룹 변경: ${valueText(after?.name || before?.name)}`];
  }
  if (type === 'RESTORE') {
    return ['백업 데이터 기준으로 복원되었습니다.'];
  }
  return ['상세 내용이 없습니다.'];
}

function HistoryDetail({ history }) {
  const lines = buildHistoryDetailLines(history);
  return (
    <ul className="history-detail-list">
      {lines.map((line, index) => <li key={index}>{line}</li>)}
    </ul>
  );
}

function ExportPanel({ api, project, labels = [], integrationTargets = [] }) {
  const [selectedLabelId, setSelectedLabelId] = useState(labels[0]?.id ? String(labels[0].id) : '');
  const [selectedTargetId, setSelectedTargetId] = useState(integrationTargets[0]?.id ? String(integrationTargets[0].id) : '');
  const [targetDirection, setTargetDirection] = useState('tx');

  useEffect(() => {
    if (selectedLabelId && !labels.some(label => String(label.id) === String(selectedLabelId))) {
      setSelectedLabelId(labels[0]?.id ? String(labels[0].id) : '');
    }
    if (!selectedLabelId && labels[0]?.id) {
      setSelectedLabelId(String(labels[0].id));
    }
  }, [labels.map(label => label.id).join(','), selectedLabelId]);

  useEffect(() => {
    if (selectedTargetId && !integrationTargets.some(target => String(target.id) === String(selectedTargetId))) {
      setSelectedTargetId(integrationTargets[0]?.id ? String(integrationTargets[0].id) : '');
    }
    if (!selectedTargetId && integrationTargets[0]?.id) {
      setSelectedTargetId(String(integrationTargets[0].id));
    }
  }, [integrationTargets.map(target => target.id).join(','), selectedTargetId]);

  async function downloadExport(path, filename) {
    const separator = path.includes('?') ? '&' : '?';
    const timezone = encodeURIComponent(getUserTimeZone());
    const res = await fetch(`${API_BASE}${path}${separator}timezone=${timezone}`, { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } });
    if (!res.ok) {
      const text = await res.text();
      alert(`출력 실패: ${res.status}\n${text}`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const selectedLabel = labels.find(label => String(label.id) === String(selectedLabelId));
  const selectedTarget = integrationTargets.find(target => String(target.id) === String(selectedTargetId));
  const targetDirectionText = targetDirection === 'rx' ? '수신 노드' : targetDirection === 'all' ? '송수신 전체' : '송신 노드';
  const targetFileSuffix = targetDirection === 'rx' ? 'RX' : targetDirection === 'all' ? 'ALL' : 'TX';

  return (
    <section className="page-grid compact-stack-page">
      <div className="card span-3">
        <div className="card-title"><div><h2>출력</h2><p>프로젝트 전체, 태그, 노드 기준으로 .h/.idl/.cs를 출력합니다.</p></div></div>
        <div className="export-actions">
          <button onClick={() => downloadExport(`/projects/${project.id}/export/header`, `${project.acronym || project.name}.h`)}><Download size={16}/> 프로젝트 전체 .h</button>
          <button onClick={() => downloadExport(`/projects/${project.id}/export/idl`, `${project.acronym || project.name}.idl`)}><Download size={16}/> 프로젝트 전체 .idl</button>
          <button onClick={() => downloadExport(`/projects/${project.id}/export/csharp`, `${project.acronym || project.name}.cs`)}><Download size={16}/> 프로젝트 전체 .cs</button>
          <button onClick={() => downloadExport(`/projects/${project.id}/project-json`, `${project.acronym || project.name}.json`)}><Download size={16}/> 프로젝트 JSON</button>
        </div>
      </div>

      <div className="card span-3">
        <div className="card-title"><div><h2>태그 출력</h2><p>선택한 태그에 속한 메시지를 .h/.idl/.cs로 바로 출력합니다. 참조되는 메시지/Enum은 함께 포함됩니다.</p></div></div>
        <div className="label-export-row">
          <select value={selectedLabelId} onChange={e => setSelectedLabelId(e.target.value)}>
            <option value="">태그 선택</option>
            {labels.map(label => <option key={label.id} value={label.id}>{label.name}</option>)}
          </select>
          <button disabled={!selectedLabel} onClick={() => selectedLabel && downloadExport(`/labels/${selectedLabel.id}/export/header`, `${project.acronym || project.name}_${selectedLabel.name}.h`)}>태그 .h</button>
          <button disabled={!selectedLabel} onClick={() => selectedLabel && downloadExport(`/labels/${selectedLabel.id}/export/idl`, `${project.acronym || project.name}_${selectedLabel.name}.idl`)}>태그 .idl</button>
          <button disabled={!selectedLabel} onClick={() => selectedLabel && downloadExport(`/labels/${selectedLabel.id}/export/csharp`, `${project.acronym || project.name}_${selectedLabel.name}.cs`)}>태그 .cs</button>
        </div>
        {!labels.length && <p className="muted small">등록된 태그가 없습니다. 인터페이스 설계의 + 추가 버튼에서 태그를 추가하세요.</p>}
      </div>

      <div className="card span-3">
        <div className="card-title"><div><h2>노드별 출력</h2><p>선택한 노드가 송신 노드 또는 수신 노드로 연결된 메시지를 .h/.idl/.cs로 바로 출력합니다. 참조되는 메시지/Enum은 함께 포함됩니다.</p></div></div>
        <div className="target-export-row">
          <select value={selectedTargetId} onChange={e => setSelectedTargetId(e.target.value)}>
            <option value="">노드 선택</option>
            {integrationTargets.map(target => <option key={target.id} value={target.id}>{target.name}</option>)}
          </select>
          <select value={targetDirection} onChange={e => setTargetDirection(e.target.value)} aria-label="노드 출력 기준">
            <option value="tx">송신 노드 기준</option>
            <option value="rx">수신 노드 기준</option>
            <option value="all">송수신 전체</option>
          </select>
          <button disabled={!selectedTarget} onClick={() => selectedTarget && downloadExport(`/integration-targets/${selectedTarget.id}/export/header?direction=${targetDirection}`, `${project.acronym || project.name}_${selectedTarget.name}_${targetFileSuffix}.h`)}>{targetDirectionText} .h</button>
          <button disabled={!selectedTarget} onClick={() => selectedTarget && downloadExport(`/integration-targets/${selectedTarget.id}/export/idl?direction=${targetDirection}`, `${project.acronym || project.name}_${selectedTarget.name}_${targetFileSuffix}.idl`)}>{targetDirectionText} .idl</button>
          <button disabled={!selectedTarget} onClick={() => selectedTarget && downloadExport(`/integration-targets/${selectedTarget.id}/export/csharp?direction=${targetDirection}`, `${project.acronym || project.name}_${selectedTarget.name}_${targetFileSuffix}.cs`)}>{targetDirectionText} .cs</button>
        </div>
        {!integrationTargets.length && <p className="muted small">등록된 노드가 없습니다. 인터페이스 설계의 + 추가 버튼에서 노드를 추가하세요.</p>}
      </div>
    </section>
  );
}

function HistoryPanel({ api, projectId, history, backups, backupEvents, onReload, onRestored }) {
  const [tab, setTab] = useState('message');
  const [notice, setNotice] = useState('');
  const [backupNote, setBackupNote] = useState('');

  async function createBackup() {
    setNotice('');
    await api.post(`/projects/${projectId}/backups`, { note: backupNote.trim() || null });
    setBackupNote('');
    setNotice('백업이 완료되었습니다.');
    await onReload();
  }

  async function restoreBackup(backup) {
    if (!confirm(`${formatDate(backup.created_at)} 백업 상태로 되돌릴까요?\n\n현재 메시지/필드/그룹/참조 관계/변경 이력이 백업 시점으로 변경됩니다. 복원 전 현재 상태는 자동 백업으로 저장됩니다.`)) return;
    setNotice('');
    await api.post(`/backups/${backup.id}/restore`, {});
    setNotice('백업 상태로 불러왔습니다. 메시지/필드/그룹/참조 관계와 변경 이력이 백업 시점으로 복원되었습니다. 복원 전 상태는 자동 백업으로 저장되었습니다.');
    await onRestored();
  }

  return (
    <section className="card standalone-card">
      <div className="card-title"><div><h2>이력 관리</h2><p>메시지 변경 이력과 프로젝트 백업 이력을 관리합니다.</p></div></div>
      <div className="tab-row">
        <button className={tab === 'message' ? 'tab active' : 'tab'} onClick={() => setTab('message')}>메시지 변경 이력</button>
        <button className={tab === 'backup' ? 'tab active' : 'tab'} onClick={() => setTab('backup')}>백업 이력</button>
      </div>
      {notice && <div className="notice">{notice}</div>}

      {tab === 'message' && (
        <div className="table-wrap">
          <table className="history-table">
            <thead><tr><th>일시</th><th>변경자</th><th>작업</th><th>메시지</th><th>상세 내용</th></tr></thead>
            <tbody>{history.map(h => (
              <tr key={h.id}>
                <td className="nowrap-cell">{formatDate(h.created_at)}</td>
                <td>{h.changed_by_name || h.changed_by || '-'}</td>
                <td><span className="history-action-badge">{getHistoryActionLabel(h)}</span></td>
                <td><strong>{h.message_name || '-'}</strong></td>
                <td><HistoryDetail history={h} /></td>
              </tr>
            ))}{history.length === 0 && <tr><td colSpan="5" className="muted">메시지 변경 이력이 없습니다.</td></tr>}</tbody>
          </table>
        </div>
      )}

      {tab === 'backup' && (
        <div>
          <div className="backup-toolbar">
            <div>
              <h3>백업 이력</h3>
              <p className="muted small">현재 프로젝트의 메시지/필드/그룹/메시지 변경 이력을 DB 단위로 저장하고, 필요할 때 해당 시점으로 되돌릴 수 있습니다.</p>
            </div>
            <div className="backup-create-actions">
              <input
                value={backupNote}
                onChange={e => setBackupNote(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') createBackup(); }}
                maxLength={500}
                placeholder="메모를 입력하세요 (선택)"
                aria-label="백업 메모"
              />
              <button onClick={createBackup}><Save size={16}/> 백업</button>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>백업 시간</th><th>구분</th><th>메모</th><th>백업자</th><th>메시지 수</th><th>필드 수</th><th></th></tr></thead>
              <tbody>
                {backups.map(backup => (
                  <tr key={backup.id}>
                    <td>{formatDate(backup.created_at)}</td>
                    <td>{backup.kind === 'AUTO_BEFORE_RESTORE' ? '복원 전 자동 백업' : '사용자 백업'}</td>
                    <td className="backup-note-cell" title={backup.note || ''}>{backup.note || '-'}</td>
                    <td>{backup.created_by_name || backup.created_by || '-'}</td>
                    <td>{backup.message_count}</td>
                    <td>{backup.field_count}</td>
                    <td><button className="ghost" onClick={() => restoreBackup(backup)}>불러오기</button></td>
                  </tr>
                ))}
                {backups.length === 0 && <tr><td colSpan="7" className="muted">백업 이력이 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="backup-toolbar backup-events-toolbar">
            <div>
              <h3>백업/복원 기록</h3>
            </div>
          </div>
          <div className="table-wrap backup-events-wrap">
            <table>
              <thead><tr><th>시간</th><th>유형</th><th>작업자</th><th>대상 백업</th><th>자동 백업</th></tr></thead>
              <tbody>
                {(backupEvents || []).map(event => (
                  <tr key={event.id}>
                    <td>{formatDate(event.created_at)}</td>
                    <td>{event.event_type === 'RESTORE' ? '복원' : '백업'}</td>
                    <td>{event.created_by_name || event.created_by || '-'}</td>
                    <td>{event.backup_id ? `#${event.backup_id}` : '-'}</td>
                    <td>{event.auto_backup_id ? `#${event.auto_backup_id}` : '-'}</td>
                  </tr>
                ))}
                {(!backupEvents || backupEvents.length === 0) && <tr><td colSpan="5" className="muted">백업/복원 기록이 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>

        </div>
      )}
    </section>
  );
}


function AccountManagePage({ api, me, onBack }) {
  const [users, setUsers] = useState([]);
  const [notice, setNotice] = useState('');

  async function loadUsers() {
    setNotice('');
    setUsers(await api.get('/auth/users'));
  }

  useEffect(() => { loadUsers(); }, []);

  async function updateUserRole(user, role) {
    if (user.id === me?.id) return;
    setNotice('');
    try {
      await api.patch(`/auth/users/${user.id}/role`, { role });
      await loadUsers();
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function deleteUser(user) {
    if (!confirm(`${user.email} 계정을 삭제할까요?`)) return;
    setNotice('');
    try {
      await api.del(`/auth/users/${user.id}`);
      await loadUsers();
    } catch (err) {
      setNotice(err.message);
    }
  }

  return (
    <div className="project-select-page">
      <header className="landing-header">
        <div className="landing-title">
          <div className="brand-mark"><UserCircle size={24} /></div>
          <div>
            <h1>계정 관리</h1>
            <p className="eyebrow">가입된 계정을 확인하고 권한을 관리할 수 있습니다.</p>
          </div>
        </div>
        <div className="user-box">
          <span>{me?.email}</span><b>{me?.role}</b>
          <button className="ghost" onClick={onBack}><ArrowLeft size={15}/> 프로젝트로 돌아가기</button>
        </div>
      </header>

      <main className="landing-main">
        <section className="card">
          <div className="card-title">
            <div><h2>가입 계정 목록</h2><p>관리자는 타 계정 권한을 변경하거나 계정을 삭제할 수 있습니다.</p></div>
            <button className="ghost" onClick={loadUsers}><RefreshCw size={16}/> 새로고침</button>
          </div>
          {notice && <div className="notice">{notice}</div>}
          <div className="table-wrap">
            <table>
              <thead><tr><th>아이디</th><th>권한</th><th>생성일시</th><th></th></tr></thead>
              <tbody>
                {users.map(user => (
                  <tr key={user.id}>
                    <td><strong>{user.email}</strong></td>
                    <td>
                      <select className="role-select" value={user.role} disabled={user.id === me?.id} onChange={e => updateUserRole(user, e.target.value)}>
                        <option value="USER">USER</option>
                        <option value="ADMIN">ADMIN</option>
                      </select>
                    </td>
                    <td>{formatDate(user.created_at)}</td>
                    <td>
                      <button className="icon danger-icon" disabled={user.id === me?.id} title={user.id === me?.id ? '현재 로그인된 계정은 여기서 삭제할 수 없습니다. 계정 화면의 회원탈퇴를 이용하세요.' : '계정 삭제'} onClick={() => deleteUser(user)}>
                        <Trash2 size={15}/>
                      </button>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && <tr><td colSpan="4" className="muted">가입된 계정이 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

function AccountPanel({ api, me, onLogout }) {
  const [notice, setNotice] = useState('');

  async function withdraw() {
    if (!confirm('회원탈퇴를 진행할까요? 탈퇴 후에는 현재 계정으로 다시 로그인할 수 없습니다.')) return;
    setNotice('');
    try {
      await api.del('/auth/users/me');
      onLogout();
    } catch (err) {
      setNotice(err.message);
    }
  }

  return (
    <section className="card standalone-card narrow-card">
      <div className="card-title"><div><h2>계정 관리</h2><p>현재 로그인된 계정 정보입니다.</p></div></div>
      {notice && <div className="notice">{notice}</div>}
      <div className="account-row"><span>아이디</span><strong>{me?.email}</strong></div>
      <div className="account-row"><span>권한</span><strong>{me?.role}</strong></div>
      {me?.email !== 'admin' && <div className="button-row account-actions"><button className="danger" onClick={withdraw}><Trash2 size={16}/> 회원탈퇴</button></div>}
    </section>
  );
}

function EmptyState({ title }) {
  return <section className="empty-state"><MessageSquare size={42}/><h2>{title}</h2></section>;
}

createRoot(document.getElementById('root')).render(<App />);
