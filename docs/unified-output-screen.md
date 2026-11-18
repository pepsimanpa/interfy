# Interfy 통합 출력 화면 (개발 브랜치)

브랜치: `feature/system-configuration-v1`. **main에는 머지하지 않았습니다.**

## 화면

출력 메뉴를 다음 두 영역으로 구성합니다.

- **인터페이스 파일 출력**: 출력 범위(프로젝트 전체 / 태그 / 노드 선택), 범위별 설정, 공통 파일 형식(.h / .idl / .cs / JSON), 출력 버튼
- **IDD 문서 출력**: 기존 Word(.docx) / 한글(.hwpx) 바로 다운로드

화면 우측 상단 도구: **오프라인 HTML 편집기 다운로드** 및 **수정 JSON 반영**.

### 출력 범위별 활성화

| 범위 | 태그 선택 | 노드 다중 선택 | 송수신 기준 | 파일 형식 |
|---|---|---|---|---|
| 프로젝트 전체 | 비활성 | 비활성 | 비활성 | 활성 |
| 태그 | 활성 | 비활성 | 비활성 | 활성 |
| 노드 선택 | 비활성 | 활성 | 활성 | 활성 |

비활성 설정은 화면에서 숨기지 않고 흐리게 표시합니다. 범위를 전환해도 이전 태그/노드/방향 선택은 유지합니다.

### API

기존 출력 경로는 그대로 유지합니다.

| 범위 | .h/.idl/.cs | JSON |
|---|---|---|
| 전체 | 기존 `GET /projects/{id}/export/{header,idl,csharp}` | 기존 `GET /projects/{id}/project-json` |
| 태그 | 기존 `GET /labels/{id}/export/{header,idl,csharp}` | 기존 `GET /labels/{id}/export/json` |
| 노드 | 신규 `POST /projects/{id}/export/nodes/{header,idl,csharp}` | 기존 `POST /projects/{id}/collaboration/export` 확장 |

노드 POST 요청 JSON:

```json
{"target_ids": [1, 2], "direction": "all"}
```

`direction`은 `tx`, `rx`, `all` 중 하나입니다.
기존 협력사 패키지 클라이언트는 direction을 생략하면 기본값 `all`로 동작합니다.

노드 범위에서는 여러 노드의 메시지를 중복 제거해 하나의 코드 파일로 출력합니다. 참조하는 STRUCT/Enum 정의도 함께 출력합니다. JSON은 기존 협력사 패키지 형식(`collaboration.base_messages`, `base_targets` 등)을 유지하여 오프라인 편집 및 부분 업데이트에 계속 사용합니다.

**주의**: 태그 JSON과 프로젝트 JSON은 협력사 패키지와 구별됩니다. JSON 내용의 태그/그룹 소속 자체는 기존 메시지 부분 업데이트에서 직접 적용하지 않습니다.

### 수동 검증

1. 프로젝트 전체를 선택했을 때 태그 및 노드 설정이 비활성화되는지 확인
2. 태그 선택으로 전환하면 태그 콤보박스만 활성화되는지 확인
3. 노드 선택으로 전환하면 다중 노드·송수신 방향만 활성화되는지 확인
4. 모든 범위에서 .h/.idl/.cs/JSON 출력 및 파일명 확인
5. 노드 2개 이상 선택 시 하나의 파일에 정의가 중복되지 않는지 확인
6. 오프라인 편집기에서 노드 JSON을 수정 후 부분 업데이트 미리보기 확인
7. IDD Word/HWPX 출력이 범위 설정과 독립적으로 동작하는지 확인
8. 모바일/좁은 화면 및 다크 테마에서 레이아웃 확인

개발용 테스트 (환경에 의존):

```powershell
cd frontend
npm test
npm run build
cd ../backend
python -m unittest discover -s tests -p "test_unified_export.py" -v
```

테스트 코드는 추가했지만 GitHub 커넥터 환경에서는 실제 빌드/백엔드 단위 테스트를 실행하지 못했습니다. 실기동 검증 후 머지합니다.
