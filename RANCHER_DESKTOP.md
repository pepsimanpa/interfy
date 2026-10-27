# Interfy - Rancher Desktop (Windows)

이 문서는 Windows에서 **Docker Desktop 대신 Rancher Desktop**으로 Interfy를 실행하는 방법입니다.
Interfy는 여전히 3개의 Linux 컨테이너(PostgreSQL, FastAPI, React/Vite)를 사용합니다.
협력사 오프라인 HTML 에디터와 기존 Docker 실행 방식은 변경하지 않습니다.

## 1. 준비

1. [Rancher Desktop](https://rancherdesktop.io/) 설치 및 실행 (Windows는 WSL 2 필요).
2. **Preferences → Container Engine**에서 **dockerd (moby)** 선택을 권장합니다.
   - Rancher Desktop은 Docker Desktop이 아닙니다. `docker compose` 명령은
     Rancher Desktop이 제공하는 Moby 엔진으로 컨테이너를 실행합니다.
   - Kubernetes를 사용하지 않으면 **Kubernetes → Enable Kubernetes** 해제 가능.
3. 기존 Docker Desktop을 사용하는 경우 **Docker Desktop을 종료**하세요.
   두 프로그램을 동시에 실행하지 않는 것이 좋습니다.
4. Rancher Desktop 엔진 실행이 완료된 뒤 **새 CMD/PowerShell 터미널**을 여세요.

## 2. 실행 (권장: Moby)

Interfy Git 저장소 루트에서:

```bat
rancher.cmd up moby
```

Windows에서 더블클릭으로 `rancher.cmd`를 실행해도 기본적으로 Moby 방식으로 시작합니다.
이 스크립트는 아래 두 Compose 파일을 함께 사용합니다.

- `docker-compose.yml`: 기존 서비스·네트워크·볼륨·포트
- `compose.rancher.yml`: 기존 `interfy-postgres:16` 대신 `postgres:16` 지정

실행 결과:

- Interfy 프런트엔드: http://localhost:3000
- 백엔드 API: http://localhost:8000/docs
- DB: PostgreSQL 16, 기존과 동일한 `interfy_db_volume` 이름의 **Rancher 측 볼륨**

스크립트에서 지원하는 명령:

```bat
rancher.cmd up moby
rancher.cmd ps moby
rancher.cmd logs moby
rancher.cmd down moby
```

`down`은 컨테이너만 정지/삭제하며 **데이터 볼륨을 지우지 않습니다**.
특히 `down -v`, Rancher Desktop의 Factory Reset, WSL 배포판 데이터 삭제는
DB가 사라질 수 있으니 백업 없이 실행하지 마세요.

## 3. Docker 명령을 전혀 쓰지 않고 containerd 사용하기 (선택)

Rancher Desktop의 Container Engine을 **containerd**로 선택하면:

```bat
rancher.cmd up containerd
rancher.cmd ps containerd
rancher.cmd logs containerd
rancher.cmd down containerd
```

내부적으로 `nerdctl compose`를 사용합니다. 두 런타임은 같은
Compose 파일을 읽지만 구현 차이가 있어 **Moby 쪽을 기본 권장**합니다.
`depends_on: condition: service_healthy` 및 빌드/네트워크/볼륨 동작은 실제
설치된 nerdctl 버전에서 확인하세요. Moby에서 만든 이미지·볼륨은
containerd로 자동 이전되지 않습니다.

## 4. 기존 Docker Desktop DB 데이터 이전

**주의: Docker Desktop의 `interfy_db_volume`과 Rancher Desktop의
같은 이름 볼륨은 별개입니다.** 프로그램만 바꾸면 기존 프로젝트가 자동으로
나타나지 않습니다. 먼저 이전 DB를 백업하세요.

Docker Desktop 쪽 기존 Interfy가 실행 중일 때 (PowerShell 또는 CMD):

```bat
docker exec interfy-db pg_dump -U message_user -d message_manager -Fc -f /tmp/interfy-backup.dump
docker cp interfy-db:/tmp/interfy-backup.dump .\interfy-backup.dump
```

덤프 파일이 생성됐는지 확인한 후 Docker Desktop을 종료하고 Rancher Desktop을
시작합니다. `rancher.cmd up moby`로 새 DB/앱을 띄운 후, 새 데이터에
중요한 내용이 없는 경우에만 복원합니다.

```bat
docker compose -f docker-compose.yml -f compose.rancher.yml stop backend frontend
docker cp .\interfy-backup.dump interfy-db:/tmp/interfy-backup.dump
docker exec interfy-db pg_restore -U message_user -d message_manager --clean --if-exists /tmp/interfy-backup.dump
docker compose -f docker-compose.yml -f compose.rancher.yml start backend frontend
```

복원 시 PostgreSQL 객체가 교체될 수 있습니다. **신규 환경에서 작성한 데이터를
보존해야 한다면 별도 백업·검증 후 진행**하세요. 권한/시퀀스/스키마가 변경되었거나
앱 버전이 다르면 복원 뒤 마이그레이션 확인이 필요합니다.

이전 DB를 유지하고 싶으면 Docker Desktop 데이터를 삭제하지 말고 백업 사본을
안전한 위치에 보관하세요. 컨테이너 이미지 `interfy-postgres:16`와 DB 볼륨은 별개입니다.

## 5. 자주 발생하는 문제

- **`rdctl` 또는 `docker`/`nerdctl`을 찾을 수 없음:** Rancher Desktop 설치 확인,
  Container Engine 설정 확인, 터미널 새로 열기.
- **컨테이너 엔진 연결 실패:** Rancher Desktop이 실행 중인지 확인.
  Moby 모드에서는 `docker info`, containerd 모드에서는 `nerdctl info`로 점검.
- **5432/3000/8000 포트 충돌:** 기존 Docker Desktop 컨테이너 또는
  로컬 서비스가 실행 중인지 확인.
- **`postgres:16` 다운로드 실패:** 처음 실행할 때 인터넷 접근이 필요합니다.
  폐쇄망에서는 적합한 이미지를 별도로 가져와 Rancher의 엔진에 로드해야 합니다.
- **빈 프로젝트 목록:** 새 볼륨으로 실행한 것일 수 있습니다. 4절을 참고하세요.
- **이전 Moby 이미지가 보이지 않음:** Rancher Desktop의 런타임/이미지 스토리지를
  변경했는지 확인하세요. 런타임끼리 이미지·볼륨을 자동 공유하지 않습니다.

공식 문서: https://docs.rancherdesktop.io/tutorials/working-with-containers/
