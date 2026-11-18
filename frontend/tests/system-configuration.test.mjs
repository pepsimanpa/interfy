import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const main = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const panel = readFileSync(new URL('../src/SystemConfigurationPanel.jsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/systemConfiguration.css', import.meta.url), 'utf8');

test('system configuration is a separate design menu, not a replacement', () => {
  assert.match(main, /인터페이스 설계<\/button>/);
  assert.match(main, /체계 구성<\/button>/);
  assert.match(main, /<SystemConfigurationPanel/);
  assert.match(main, /systemConfiguration: '체계 구성'/);
});

test('system configuration exposes three modules with CRUD forms', () => {
  for (const label of ['장비·SW', 'IP·NIC', '통신 연결']) {
    assert.ok(panel.includes(label));
  }
  assert.match(panel, /api\.put\(/);
  assert.match(panel, /api\.post\(/);
  assert.match(panel, /api\.patch\(/);
  assert.match(panel, /api\.del\(/);
});

test('device profile links to existing node identity and binding-based server/client endpoints', () => {
  assert.match(panel, /item\.node_id/);
  assert.match(panel, /hardware_name/);
  assert.match(panel, /software_id/);
  assert.match(panel, /server_binding_id/);
  assert.match(panel, /client_binding_id/);
  assert.match(styles, /\.system-config-form/);
});

test('sidebar follows the requested project, design, output and footer order', () => {
  const appStyles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const sidebarStart = main.indexOf('<aside className="message-sidebar compact-sidebar">');
  const sidebar = main.slice(sidebarStart, main.indexOf('</aside>', sidebarStart));
  const upper = sidebar.slice(sidebar.indexOf('<div className="sidebar-main">'), sidebar.indexOf('<div className="sidebar-footer">'));
  const footer = sidebar.slice(sidebar.indexOf('<div className="sidebar-footer">'));
  const upperItems = [
    '프로젝트 선택으로', '현재 프로젝트', '{project.name}', '프로젝트 설정</button>',
    '메시지 이름 / 용도 검색', '인터페이스 설계</button>', '체계 구성</button>', '출력</button>',
  ];
  const positions = upperItems.map(item => upper.indexOf(item));
  assert.ok(positions.every(position => position >= 0), 'all requested upper items must be present');
  assert.ok(positions.every((position, i) => i === 0 || position > positions[i - 1]), 'upper sidebar order must match the specification');
  assert.ok(!upper.includes('이력 관리</button>') && !upper.includes('계정</button>'), 'management controls belong in the footer');
  assert.ok(footer.indexOf('이력 관리</button>') >= 0 && footer.indexOf('계정</button>') > footer.indexOf('이력 관리</button>'));
  assert.ok(!sidebar.includes('>설계</div>') && !sidebar.includes('>관리</div>'), 'unrequested section headings should be absent');
  assert.match(appStyles, /\.compact-sidebar \.sidebar-footer \{[\s\S]*?margin-top: auto;/);
});

test('left editors precede their right-hand tables for IP, port and connections', () => {
  const ipSection = panel.slice(panel.indexOf("{loaded && tab === 'ips'"), panel.indexOf("{loaded && tab === 'connections'"));
  const connectionSection = panel.slice(panel.indexOf("{loaded && tab === 'connections'"));
  assert.equal((ipSection.match(/className="system-config-split"/g) || []).length, 2);
  assert.equal((connectionSection.match(/className="system-config-split"/g) || []).length, 1);
  for (const [section, editor, list] of [
    [ipSection, 'IP 할당 추가', 'IP 주소 할당'],
    [ipSection, 'IP / PORT 바인딩 추가', '<h3>포트 바인딩</h3>'],
    [connectionSection, '통신 연결 추가', 'system-connection-list'],
  ]) {
    assert.ok(section.indexOf(editor) >= 0 && section.indexOf(editor) < section.indexOf(list),
      `${editor} editor must precede its list`);
  }
  assert.equal((panel.match(/className="system-config-form system-config-form-compact"/g) || []).length, 4);
  assert.match(styles, /grid-template-columns: minmax\(400px, 465px\) minmax\(0, 1fr\)/);
  assert.match(styles, /\.system-config-table th, \.system-config-table td \{ padding: 7px 8px; font-size: 12px;/);
});

test('device and software node editor is on the left and uses a fixed title', () => {
  const appStyles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const nodeSection = panel.slice(panel.indexOf("{loaded && tab === 'nodes'"), panel.indexOf("{loaded && tab === 'ips'"));
  assert.equal((nodeSection.match(/className="system-config-split"/g) || []).length, 1);
  assert.ok(nodeSection.indexOf('노드 정보 편집') < nodeSection.indexOf('장비·SW 목록'), 'node editor must appear left of list');
  assert.match(nodeSection, /선택 노드: <strong>\{node.name\}<\/strong>/);
  assert.doesNotMatch(nodeSection, /\{node\.name\}\s*·\s*식별 정보 편집/);
  assert.match(nodeSection, /className="system-config-form system-config-form-compact" onSubmit=\{saveNode\}/);
  assert.match(nodeSection, /onClick=\{\(\) => setNodeId\(String\(item.node_id\)\)\}/);
  assert.match(appStyles, /\.side-project-card h2 \{[^}]*font-size: 16px;/);
});

test('communication connection editor has only necessary controls', () => {
  const section = panel.slice(panel.indexOf("{loaded && tab === 'connections'"));
  assert.match(section, /통신 연결 추가/);
  assert.match(section, /Server IP \/ PORT 바인딩/);
  assert.match(section, /Client IP \/ PORT 바인딩/);
  assert.doesNotMatch(section, /IP·PORT 설정<\/button>/);
  assert.doesNotMatch(section, /AUTO는 포트 번호를 사전에 지정하지 않습니다/);
  assert.match(section, /포트 바인딩이 아직 없습니다/);
});

test('IP allocation has no reserved IP control and prioritizes a wide notes column', () => {
  const ipSection = panel.slice(panel.indexOf("{loaded && tab === 'ips'"), panel.indexOf("{loaded && tab === 'connections'"));
  const allocationTable = ipSection.slice(ipSection.indexOf('<table className="system-config-table system-config-ip-table">'));
  assert.doesNotMatch(ipSection, /예약 IP|is_reserved|reserved1/);
  assert.doesNotMatch(allocationTable, /<th>상태<\/th>|'예약' : '사용'/);
  assert.match(allocationTable, /<th>IP 주소<\/th><th>비고<\/th><th>관리<\/th>/);
  assert.match(allocationTable, /colSpan=\{5\}>등록된 IP가 없습니다/);
  assert.match(styles, /\.system-config-ip-table \{ min-width: 900px; table-layout: fixed; \}/);
  assert.match(styles, /\.system-config-ip-table th:nth-child\(4\) \{ width: 38%; \}/);
  assert.match(ipSection, /onSubmit=\{saveIp\}/);
  assert.match(ipSection, /onClick=\{\(\) => selectIpForEdit\(item\)\}/);
});
