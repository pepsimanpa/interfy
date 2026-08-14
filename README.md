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
