import React, { useEffect, useMemo, useState } from 'react';
import { Download, FileCode2, FileText, Upload } from 'lucide-react';
import './unifiedExport.css';

const OUTPUT_FORMATS = [
  { key: 'header', label: '.h', extension: 'h' },
  { key: 'idl', label: '.idl', extension: 'idl' },
  { key: 'csharp', label: '.cs', extension: 'cs' },
  { key: 'json', label: 'JSON', extension: 'json' },
];
const SCOPES = [
  { value: 'all', label: '프로젝트 전체' },
  { value: 'tag', label: '태그' },
  { value: 'nodes', label: '노드 선택' },
];
const DIRECTIONS = [
  { value: 'tx', label: '송신' },
  { value: 'rx', label: '수신' },
  { value: 'all', label: '송수신 전체' },
];
const cleanFilename = value => String(value || 'Interfy').replace(/[\\/:*?"<>|]/g, '_');
const extensionFor = key => OUTPUT_FORMATS.find(item => item.key === key)?.extension || 'json';

export default function UnifiedExportPanel({
  project, labels = [], integrationTargets = [], apiBase, onOpenPartialUpdate,
}) {
  const [scope, setScope] = useState('all');
  const [selectedLabelId, setSelectedLabelId] = useState('');
  const [selectedNodeIds, setSelectedNodeIds] = useState([]);
  const [direction, setDirection] = useState('all');
  const [format, setFormat] = useState('header');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    setSelectedLabelId(current =>
      labels.some(label => String(label.id) === String(current))
        ? current : (labels[0] ? String(labels[0].id) : '')
    );
  }, [labels]);

  useEffect(() => {
    const validIds = new Set(integrationTargets.map(node => node.id));
    setSelectedNodeIds(current => current.filter(id => validIds.has(id)));
  }, [integrationTargets]);

  const label = labels.find(item => String(item.id) === selectedLabelId);
  const chosenNodes = useMemo(
    () => integrationTargets.filter(item => selectedNodeIds.includes(item.id)),
    [integrationTargets, selectedNodeIds],
  );
  const isReady = scope === 'all'
    || (scope === 'tag' && !!label)
    || (scope === 'nodes' && selectedNodeIds.length > 0);
  const baseName = cleanFilename(project?.acronym || project?.name || 'interfy');
  const directionName = DIRECTIONS.find(item => item.value === direction)?.label || '송수신 전체';

  function toggleNode(id, checked) {
    setSelectedNodeIds(current =>
      checked ? (current.includes(id) ? current : [...current, id]) : current.filter(item => item !== id)
    );
  }

  async function download(path, filename, options = {}) {
    const {
      method = 'GET',
      body = null,
      addTimezone = false,
    } = options;
    const separator = path.includes('?') ? '&' : '?';
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const route = addTimezone ? path + separator + 'timezone=' + encodeURIComponent(timezone) : path;
    const response = await fetch(apiBase + route, {
      method,
      headers: {
        Authorization: 'Bearer ' + localStorage.getItem('token'),
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error('HTTP ' + response.status + ': ' + detail.slice(0, 300));
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      // Delayed cleanup avoids cancelling a download in some browsers.
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }

  async function perform(task, success) {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      await task();
      setNotice(success);
    } catch (error) {
      setNotice('출력 실패: ' + (error?.message || String(error)));
    } finally {
      setBusy(false);
    }
  }

  async function exportSelection() {
    if (!isReady || busy) return;
    const ext = extensionFor(format);
    const routeFormat = format;
    let path;
    let filename;
    let options = { addTimezone: format !== 'json' };

    if (scope === 'all') {
      path = format === 'json'
        ? '/projects/' + project.id + '/project-json'
        : '/projects/' + project.id + '/export/' + routeFormat;
      filename = baseName + '.' + ext;
    } else if (scope === 'tag') {
      path = '/labels/' + label.id + '/export/' + routeFormat;
      filename = baseName + '_' + cleanFilename(label.name) + '.' + ext;
    } else {
      const payload = { target_ids: selectedNodeIds, direction };
      path = format === 'json'
        ? '/projects/' + project.id + '/collaboration/export'
        : '/projects/' + project.id + '/export/nodes/' + routeFormat;
      filename = format === 'json'
        ? baseName + '-partner-package.json'
        : baseName + '_NODES_' + selectedNodeIds.length + '_' + direction.toUpperCase() + '.' + ext;
      options = { ...options, method: 'POST', body: payload };
    }

    await perform(
      () => download(path, filename, options),
      filename + ' 파일을 내보냈습니다.',
    );
  }

  function exportIdd(extension) {
    const output = extension === 'docx' ? 'idd-docx' : 'idd-hwpx';
    const filename = baseName + '_IDD.' + extension;
    perform(
      () => download('/projects/' + project.id + '/export/' + output, filename),
      filename + ' 문서를 내보냈습니다.',
    );
  }

  const scopeDescription = scope === 'all'
    ? '프로젝트 전체 메시지와 참조 자료형'
    : scope === 'tag'
      ? label ? '태그 ' + label.name + '의 메시지와 참조 자료형' : '태그를 선택하세요.'
      : selectedNodeIds.length
        ? '선택 노드 ' + selectedNodeIds.length + '개 (' + directionName + ')의 메시지와 참조 자료형'
        : '출력할 노드를 선택하세요.';
  const jsonMessage = scope === 'nodes'
    ? '노드 JSON에는 협력사 작업을 위한 원본 비교 정보가 포함됩니다.'
    : '프로젝트/태그 JSON은 기존 오프라인 편집기에서 열 수 있으며 메시지 변경은 부분 업데이트에서 선택해 반영합니다.';

  return (
    <section className="unified-export-page">
      <header className="unified-export-heading">
        <div className="unified-export-tools">
          <a href="/Interfy-Partner-Editor.html" download="Interfy-Partner-Editor.html" className="unified-export-tool">
            <FileCode2 size={15}/> 오프라인 HTML 편집기
          </a>
          <button type="button" className="unified-export-tool" onClick={onOpenPartialUpdate}>
            <Upload size={15}/> 수정 JSON 반영
          </button>
        </div>
      </header>

      <section className="card unified-export-card">
        <div className="unified-export-section-head">
          <FileCode2 size={19}/>
          <div><h3>인터페이스 파일 출력</h3><p>프로젝트 전체·태그·노드 선택 출력을 한곳에서 관리합니다.</p></div>
        </div>

        <fieldset className="unified-export-scope">
          <legend>1. 출력 범위</legend>
          <div className="unified-export-scope-options">
            {SCOPES.map(item => (
              <label key={item.value} className={'unified-export-scope-choice' + (scope === item.value ? ' selected' : '')}>
                <input type="radio" name="unified-export-scope" checked={scope === item.value} onChange={() => setScope(item.value)}/>
                <span>{item.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="unified-export-conditions">
          <fieldset className="unified-export-condition" disabled={scope !== 'tag'}>
            <legend>태그 선택</legend>
            <select aria-label="출력 태그" value={selectedLabelId} onChange={event => setSelectedLabelId(event.target.value)}>
              <option value="">태그 선택</option>
              {labels.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            {!labels.length && <p>태그가 없습니다. 인터페이스 설계에서 등록해 주세요.</p>}
          </fieldset>

          <fieldset className="unified-export-condition" disabled={scope !== 'nodes'}>
            <legend>출력 노드</legend>
            <div className="unified-export-node-toolbar">
              <span>{selectedNodeIds.length}개 선택</span>
              <div>
                <button type="button" className="ghost" disabled={scope !== 'nodes' || !integrationTargets.length} onClick={() => setSelectedNodeIds(integrationTargets.map(n => n.id))}>전체 선택</button>
                <button type="button" className="ghost" disabled={scope !== 'nodes' || !selectedNodeIds.length} onClick={() => setSelectedNodeIds([])}>선택 해제</button>
              </div>
            </div>
            <div className="unified-export-node-list">
              {integrationTargets.map(item => (
                <label key={item.id}>
                  <input type="checkbox" checked={selectedNodeIds.includes(item.id)} onChange={event => toggleNode(item.id, event.target.checked)}/>
                  <span>{item.name}</span>
                </label>
              ))}
              {!integrationTargets.length && <p>노드가 없습니다. 인터페이스 설계에서 등록해 주세요.</p>}
            </div>
            <div className="unified-export-direction">
              <span>송수신 기준</span>
              <div role="group" aria-label="노드 송수신 기준">
                {DIRECTIONS.map(item => (
                  <label key={item.value}>
                    <input type="radio" name="export-direction" checked={direction === item.value} onChange={() => setDirection(item.value)}/>
                    <span>{item.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </fieldset>
        </div>

        <fieldset className="unified-export-formats">
          <legend>2. 출력 형식</legend>
          <div className="unified-export-format-options">
            {OUTPUT_FORMATS.map(item => (
              <button key={item.key} type="button" aria-pressed={format === item.key}
                className={'unified-export-format' + (format === item.key ? ' selected' : '')}
                onClick={() => setFormat(item.key)} disabled={busy}>
                {item.key === 'json' ? <FileCode2 size={17}/> : <FileText size={17}/>}
                {item.label}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="unified-export-bottom">
          <div className="unified-export-summary">
            <strong>출력 예정</strong>
            <span>{scopeDescription} · {extensionFor(format).toUpperCase()}</span>
            {format === 'json' && <small>{jsonMessage}</small>}
          </div>
          <button type="button" className="unified-export-download" disabled={busy || !isReady} onClick={exportSelection}>
            <Download size={16}/> {busy ? '파일 생성 중...' : '선택 범위 출력'}
          </button>
        </div>
        {notice && <p className="unified-export-notice" role="status">{notice}</p>}
      </section>

      <section className="card unified-export-idd">
        <div className="unified-export-section-head">
          <FileText size={19}/>
          <div>
            <h3>IDD 문서 출력</h3>
            <p>인터페이스설계기술서(IDD) 3.1 연동 개념 · 3.2 연동 상세설계</p>
          </div>
        </div>
        <div className="unified-export-idd-actions">
          <button type="button" disabled={busy} onClick={() => exportIdd('docx')}><Download size={16}/> Word (.docx)</button>
          <button type="button" disabled={busy} onClick={() => exportIdd('hwpx')}><Download size={16}/> 한글 (.hwpx)</button>
        </div>
        <p className="unified-export-idd-help">표 5·6(인터페이스 목록), 표 7(사용자 인터페이스), 표 8·11(데이터요소), 표 9·12(통신방법), 표 10(프로토콜)을 작성하며 Interfy에 없는 값은 빈칸으로 남깁니다.</p>
      </section>
    </section>
  );
}
