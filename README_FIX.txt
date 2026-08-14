수정 내역
- 메시지 목록에서 버전 열을 필드 수 우측으로 이동했습니다.
- 프로젝트 영문약어 예시를 예: MCMC2 로 변경했습니다.
- .h / .idl 내보내기 파일 상단에 전체 내보내기 대상 메시지들의 마지막 수정일시와 메시지 수를 주석으로 표시하도록 했습니다.
  예: // Last modified at across exported messages: 2026-05-13 08:31:05 UTC
- 백엔드 Python 컴파일 확인 및 프론트엔드 Vite 빌드 확인을 완료했습니다.

추가 수정 내역
- SQLite 기본 개발 DB에서도 backend startup이 실패하지 않도록 lightweight migration 로직을 DB dialect 독립 방식으로 보완했습니다.
- PostgreSQL 전용 ALTER TABLE ... ADD COLUMN IF NOT EXISTS 및 CONCAT 사용 구문을 분기 처리했습니다.
- SQLite 기반 TestClient 통합 검증으로 로그인/권한/메시지·필드·그룹/백업·복원/내보내기 동작을 확인했습니다.


[2026-08-04 backend startup fix]
- Removed ./backend:/app bind mount from docker-compose.yml.
- The bind mount could hide the application packaged in the image, especially when the source was on a Windows network drive such as Z:.
- Added PYTHONPATH=/app to backend image.
- Removed uvicorn --reload for offline/production execution.

[Theme]
- Light theme remains the default.
- Use the fixed theme button at the lower-right corner to switch between Light and VS Code-inspired Dark themes.
- The selected theme is saved in the browser and restored on the next visit.
