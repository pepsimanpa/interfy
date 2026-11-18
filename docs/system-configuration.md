# 체계 구성 (기능 브랜치 시험판)

작업 브랜치: `feature/system-configuration-v1`. `main`에는 자동 반영하지 않습니다.

## 메뉴와 설계 원칙

- **인터페이스 설계**: 송신·수신 노드 및 메시지 정의
- **체계 구성**: 노드별 Device ID, HW 탑재, Hostname, SW/HW 고유 ID, IP/NIC 및 통신 연결
- 노드의 기준 데이터는 기존 `integration_targets`입니다. 별도의 중복 노드를 생성하지 않습니다.
- `(reserved1)` 같은 IP는 별도 노드가 아니라 해당 노드의 **예약 IP**로 등록합니다.
- 통신 연결은 입력 문자열 대신 등록된 IP 식별자를 참조하므로 IP와 노드 이름을 수정해도 참조가 유지됩니다.
- IP 주소는 프로젝트 안에서 중복 등록할 수 없고, Device ID도 한 프로젝트 내 중복할 수 없습니다.
- Client PORT는 선택적으로 입력할 수 있습니다 (동적 로컬 포트 대응).
- 프로젝트의 DB 백업/복원에는 체계 구성 테이블 3개도 함께 포함합니다.

## 시험 방법 (기존 main과 별개)

작업 PC에서 `git status`로 로컬 변경사항을 먼저 확인하세요.
브랜치 시험 시 기존 Interfy DB를 사용한다면, 사전에 PostgreSQL 백업을 보관하세요.

```powershell
git fetch origin
git switch feature/system-configuration-v1
.\rancher.cmd up moby
```

실행 후 프로젝트를 선택하고, 왼쪽 **설계 → 체계 구성**에서
**장비·SW / IP·NIC / 통신 연결** 탭을 확인합니다.

신규 테이블만 추가하며, 기존 프로젝트·노드·메시지 데이터는
자동으로 변경하거나 예제 데이터로 채우지 않습니다.

```powershell
# 테스트는 backend 환경에서
python -m unittest discover -s tests -p "test_system_configuration.py" -v
```

원래 버전으로 돌아가려면 해당 브랜치에서 수정한 내용이 저장되어 있는지
확인한 다음 `git switch main`, `git pull origin main` 후 다시 빌드하세요.

## 향후 확장 (이번 시험판 미구현)

- 기존 장비 ID/IP/PORT 엑셀 시트 일괄 가져오기 및 내보내기
- 별도 HW 목록을 통한 다수 SW-단일 HW 탑재 모델
- TCP 연결도를 기존 메시지 송수신 관계도에 오버레이하는 기능
- IP/PORT/장비 식별자 변경 이력과 비교 화면


## IP 포트 바인딩 및 TCP/UDP 관계도 (추가 구현)

- **IP·NIC** 탭에서 IP 할당 후 포트 바인딩을 추가합니다.
  - `TCP` 또는 `UDP`
  - `FIXED`: 1~65535 범위의 지정 포트
  - `AUTO`: 사전 포트 번호 없음. 프로그램 실행 시 동적으로 할당된다는 의미로, 임의의 실제 포트 번호를 생성/예약하지 않습니다.
  - 하나의 IP에서 여러 고정 포트 바인딩을 사용할 수 있습니다.
- **통신 연결** 탭에서 등록된 `Server IP/PORT 바인딩`과 `Client IP/PORT 바인딩`을 선택합니다. 프로토콜이 다르면 연결을 막습니다.
- 위 **통신 연결 관계도**는 기존 인터페이스 설계의 SVG 노드/연결선 스타일과 오른쪽 `ReferenceSidePanel` 노드 관리 UI를 재사용합니다.
  - `+`: 기존 노드 추가/수정 패널 열기
  - 노드 클릭: 해당 노드 연결 필터, 최대 2개 선택
  - 노드 더블클릭: 기존 오른쪽 패널에서 노드 수정
  - 연결선 클릭: 같은 서버 노드 → 클라이언트 노드의 TCP/UDP 연결들을 하단 목록에 표시
  - 양방향 연결은 서로 구분하며 같은 방향 다중 포트 연결은 관계도에서 하나의 선으로 묶어 표시합니다.
  - TCP / UDP 필터 및 전체 보기 지원
- **기존 인터페이스 설계 데이터와 노드 ID를 공유**합니다. 메시지 관계도는 변경하지 않습니다.
- 사용 중인 포트 바인딩은 연결을 제거하기 전까지 삭제할 수 없고, 할당 IP가 있는 노드의 삭제·체계 정보가 포함된 소스 노드의 머지는 보호합니다.
- 기존 API의 직접 IP/PORT 등록 방식은 호환성을 위해 남겨 두지만, 새 UI는 포트 바인딩 ID를 참조합니다.
- 체계 구성 DB 백업·복원에 `system_port_bindings`와 `server_binding_id`/`client_binding_id`를 포함합니다.

### 새 테스트

```powershell
cd frontend
npm test
npm run build
cd ../backend
python -m unittest discover -s tests -p "test_system_ports.py" -v
python -m unittest discover -s tests -p "test_system_configuration.py" -v
```

GitHub 소스 커밋 및 정적/순수 JS 관계도 검사는 수행했으며,
실제 React 빌드와 Python DB 연동 테스트는 개발 PC에서 확인해야 합니다.
