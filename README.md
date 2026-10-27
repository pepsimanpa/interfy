# Interfy

연동 메시지·자료형 명세를 설계하고 코드 산출물을 생성하는 Docker 기반 웹서비스입니다.

## 포함 기능

- 계정 기반 로그인 / 회원가입
- 기본 관리자 계정 자동 생성
- 프로젝트 CRUD 및 프로젝트 영문약어 관리
- 프로젝트별 메시지 CRUD
- 메시지 필드 CRUD
- 필드 자료형 콤보박스 지원
- 배열 필드 및 배열 크기 관리
- 필드 구조 변경 시 스키마 버전 자동 증가
- - 프로젝트 영문약어 기반 `.h`, `.idl` 다운로드
- 이력 관리: 메시지 변경 이력 및 백업 이력

## Rancher Desktop (Windows, Docker Desktop 대체)

**Docker Desktop 없이 Rancher Desktop에서 기존 Interfy 컨테이너 3개를 실행할 수 있습니다.**
Rancher Desktop을 설치한 뒤 Container Engine을 **dockerd (moby)**로 설정하고
저장소 루트에서 아래 명령을 실행하세요.

```bat
rancher.cmd up moby
```

`containerd` 엔진을 사용할 경우 `rancher.cmd up containerd`도 지원합니다.
기존 Docker Desktop DB 볼륨은 Rancher Desktop으로 자동 이전되지 않으니
전환 전에 반드시 백업하세요. 설정, 사용법, 데이터 이전 방법은
**[RANCHER_DESKTOP.md](RANCHER_DESKTOP.md)**를 참고하세요.

## 실행 방법

```bash
docker compose up --build
```

접속 주소:

- Frontend: http://localhost:3000
- Backend API Docs: http://localhost:8000/docs
- Backend Health Check: http://localhost:8000/health

## 기본 관리자 계정

```text
id: admin
password: admin1234
```

관리자 계정은 `docker-compose.yml`의 환경변수로 변경할 수 있습니다.

```yaml
ADMIN_EMAIL: admin
ADMIN_PASSWORD: admin1234
```

## 출력 파일명 규칙

- 프로젝트 전체: `프로젝트영문약어.h`, `프로젝트영문약어.idl`

`.idl`은 DDS IDL에서 사용하는 `module`, `struct`, `type field;` 형식으로 출력합니다. 메시지 주기와 스키마 버전은 DDS 타입 문법을 해치지 않도록 주석으로 포함합니다.

## 주요 API

### Auth

```text
POST /auth/register
POST /auth/login
GET  /auth/me
```

### Projects

```text
GET    /projects
POST   /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
DELETE /projects/{project_id}
```

### Messages

```text
GET    /projects/{project_id}/messages
POST   /projects/{project_id}/messages
GET    /messages/{message_id}
PATCH  /messages/{message_id}
DELETE /messages/{message_id}
```

### Fields

```text
GET    /messages/{message_id}/fields
POST   /messages/{message_id}/fields
PATCH  /fields/{field_id}
DELETE /fields/{field_id}
```

### Export

```text
GET /projects/{project_id}/export/header
GET /projects/{project_id}/export/idl
```

### History

```text
GET /history
GET /history?project_id={project_id}
```

`/history`는 관리자만 조회할 수 있습니다.

## 지원 자료형

```text
bool
char
int8
uint8
int16
uint16
int32
uint32
int64
uint64
float
double
string
```

`.h` 출력 시 내부적으로 아래와 같이 매핑합니다.

| 공통 타입 | C/C++ 타입 |
|---|---|
| bool | bool |
| char | char |
| int8 | int8_t |
| uint8 | uint8_t |
| int16 | int16_t |
| uint16 | uint16_t |
| int32 | int32_t |
| uint32 | uint32_t |
| int64 | int64_t |
| uint64 | uint64_t |
| float | float |
| double | double |
| string | char 배열 |

## 참고 사항

- 현재 버전은 MVP입니다. `Base.metadata.create_all()`로 테이블을 생성합니다.
- 운영 환경에서는 Alembic 마이그레이션, HTTPS, 강력한 JWT Secret, 관리자 비밀번호 변경, 프로젝트별 권한 체계를 추가하는 것을 권장합니다.
- `.idl` 포맷은 범용 텍스트 포맷으로 구현되어 있습니다. 실제 LDL 문법이 확정되면 `backend/app/services/exporters.py`의 `render_idl()`만 교체하면 됩니다.


## Troubleshooting: frontend `vite: not found`

If the frontend exits with `sh: vite: not found`, remove existing Docker volumes and rebuild:

```bash
docker compose down -v
docker compose build --no-cache
docker compose up
```

The frontend container also runs `npm install` at startup so mounted source folders do not hide dependencies.


## Docker frontend note

The frontend container does not bind-mount `./frontend:/app`. This avoids Windows/Docker volume conflicts that can corrupt `node_modules` and cause `vite: not found` or npm `ENOTEMPTY` errors. Rebuild with:

```bash
docker compose down -v --remove-orphans
docker compose build --no-cache frontend
docker compose up
```

## Interfy Docker 명칭

Docker Compose 프로젝트명, 사용자 정의 이미지명, 컨테이너명, 네트워크명 및 DB 볼륨명은 `interfy-*` 기준으로 통일합니다. PostgreSQL 공식 이미지는 오프라인 패키징 과정에서 `interfy-postgres:16`으로 태그하여 사용합니다. 기존 `messageforge-project` JSON 형식은 계속 가져올 수 있습니다.

기존 `msgforge_db_volume` 데이터를 유지해야 하는 경우 새 `interfy_db_volume`으로 1회 복사한 후 실행해야 합니다. 데이터 볼륨을 삭제하는 `docker compose down -v` 명령은 사용하지 마십시오.

## 부분 업데이트 (2026-08)
- 기존 `interfy-project` JSON을 현재 프로젝트와 비교하는 별도 페이지를 제공합니다.
- Preview 단계에서는 DB를 변경하지 않습니다.
- 메시지 이름(`struct_name`) 기준으로 신규/변경/동일을 판별합니다.
- 메시지/필드/Enum/송신·수신 노드의 추가·변경·삭제를 텍스트 diff로 표시합니다.
- 체크한 메시지만 적용하며, 체크하지 않은 메시지는 변경하지 않습니다.
- 기존 태그/그룹은 부분 업데이트에서 유지합니다.
- 한 번의 부분 업데이트는 하나의 변경 이력으로 저장됩니다.


## 협력사 오프라인 편집기 (Partner Editor)

이 기능은 로그인된 Interfy에서 담당 노드를 **여러 개 선택**하여 메시지 작업 패키지를 배포할 때 사용합니다.

1. Interfy 프로젝트의 **출력 → 협력사 오프라인 작업 패키지**에서 노드를 선택합니다.
2. **선택한 노드 JSON 내보내기**로 `*-partner-package.json`을 다운로드합니다.
3. **오프라인 HTML 편집기**로 `Interfy-Partner-Editor.html`을 다운로드합니다.
4. 두 파일을 협력사에 전달합니다. HTML은 단일 파일이며, 브라우저에서 서버·Docker·인터넷 없이 실행합니다.
5. 협력사는 HTML을 열고 **JSON 열기**로 패키지를 불러옵니다.
6. 노드 추가/이름/설명/삭제, 메시지·Enum 추가/복사/수정/삭제, 필드·Enum 값, 프로토콜·송신/수신 관계를 편집한 후 **검증 → JSON 저장**을 누릅니다.
7. 회신받은 JSON을 우리 Interfy의 **부분 업데이트 → JSON 선택**으로 엽니다.
8. 필요한 경우 **노드 변경**, **메시지/Enum 이름 변경**, **삭제된 메시지**를 각각 미리보기에서 확인한 뒤 승인하고, 나머지 메시지는 기존 **부분 업데이트**의 체크박스로 선택 반영합니다.

### 반영 시 주의사항

- 협력사 패키지는 원본 프로젝트 ID 및 노드/메시지 식별자를 포함합니다. 다른 프로젝트의 패키지는 가져올 수 없습니다.
- 메시지 내용 변경은 원본과 비교하여 미리보기에서 선택 반영합니다. 협력사 패키지에는 **필드·프로토콜·송수신의 'JSON 기준 교체'**가 처음 선택됩니다. 추가만 하고 싶을 경우 병합 모드로 바꿀 수 있습니다.
- **이름 변경을 먼저 적용**한 뒤 메시지 내용 업데이트를 진행하십시오. 노드·메시지 삭제는 별도의 승인 버튼을 사용하며, 다른 메시지에서 참조 중인 STRUCT/ENUM 삭제는 차단됩니다.
- 협력사가 추가·변경·삭제하는 내용에는 노드별 편집 권한 제한이 없습니다. 단, Interfy DB 반영 시에는 검토가 필요합니다.
- 노드/메시지의 이름 변경·삭제는 적용 전 프로젝트 전체 상태를 **자동 백업**합니다.
- 이 패키지는 비밀정보 보호 또는 서명 검증 기능을 제공하지 않습니다. **전달 전에 포함된 외부 노드명/메시지를 확인하고 승인된 경로로만 공유**하십시오.
- 오프라인 HTML은 외부 CDN과 네트워크 요청 없이 작동하며, 브라우저의 파일 선택 및 다운로드 방식으로만 JSON을 읽고 저장합니다.
- 패키지를 내보낸 뒤 같은 정의를 우리 Interfy에서 동시에 수정했다면 충돌 가능성이 있으므로 미리보기와 이력을 확인하고 최신 패키지로 재작업하는 것을 권장합니다.

회귀 테스트는 backend 디렉터리에서 실행할 수 있습니다.

```bash
python -m unittest discover -s tests -v
```
