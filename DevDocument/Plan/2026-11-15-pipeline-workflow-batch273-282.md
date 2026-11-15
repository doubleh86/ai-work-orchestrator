# 기획 문서 색인 갱신·재사용·복원: 273~282단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 273~282단계를 수행한다. 시작 Pipeline은 5,713줄이다.
기획 문서 색인의 Git 준비 안내·공통 시간 예산과 갱신, 시작 시 재사용·실행 snapshot 복원을
기획 모듈로 모은다. 기존 API·색인/Run 저장 형식·CLI/RPC와 오류/조회 순서를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 273 | 색인 갱신의 경로/조회·시간 예산 계약 정의 | 완료 |
| 274 | Git 준비 안내·공통 deadline·Git 후보/기준 commit·색인 갱신 분리 | 완료 |
| 275 | Git 문서 선택·timeout 전달과 준비 실패 안내 보존 확인 | 완료 |
| 276 | 시작 시 색인 재사용 계약 정의 | 완료 |
| 277 | 기준 commit/경로·변경 여부와 기존 갱신 API fallback 분리 | 완료 |
| 278 | 변경 없는 재사용과 변경 시 재갱신·이전 snapshot 보존 확인 | 완료 |
| 279 | 실행별 색인 복원 계약 정의 | 완료 |
| 280 | 빈 경로/파일·저장 snapshot/부재 시 갱신 분리 | 완료 |
| 281 | 디렉터리 기획과 저장 snapshot/원문·출처 보존 확인 | 완료 |
| 282 | 본문/호출 순서·서명/의존 방향·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- 새 `planning.source_indexes`에 색인 서비스와 Git 준비 상태 DTO의 오류 안내 함수를 둔다.
  서비스는 저장소/기록 경로·실행 디렉터리, 작업공간 경로와 Git 준비/읽기 전용 조회·기존 갱신
  callback만 받는다. 전체 GitWorkspace/Store/Config/Pipeline·SDK를 전달하지 않는다.
- 실제 Git 준비 상태 확인은 기존 Pipeline의 inspector를 사용한다. 시간 잔량을 각 조회 전에
  같은 순서로 계산하며, 기존 색인 작성 함수와 public 갱신 API를 callback으로 연결한다.
  설정/정책/Run 단계·승인/잠금·Git 쓰기·SDK/프로세스 수명은 변경하지 않는다.
- `pipeline.py`, 새 기획 모듈·아키텍처/계획과 직접 관련 검사만 다룬다. 기존 document_index의
  문서 필터/캐시/저장 구현과 prepared 색인의 application 전달 계약은 그대로 둔다.
- 기존 미커밋 변경을 보존한다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및
  사용자 저장소의 commit/merge/push/deploy·기획 실행/색인 갱신은 실행하지 않는다.

## 검증

이동 전 snapshot AST로 본문·오류/경로 판정·deadline/조회/갱신 순서와 callback을 대조한다.
기존 메서드 서명/데코레이터와 범위 밖 구현을 유지한다. 변경 Python 구문·전역 참조·150자/
공백·diff 및 공개 계약/모델/RPC·의존 관계를 확인한다. 기존 Git 준비/문서 선택·공통 timeout·
색인 재사용/변경·실행 snapshot 사례만 임시 저장소에서 선택한다. 기존 검사로 충분하면 새
테스트를 추가하지 않고 통과 후 종료한다. 전체 테스트·renderer·빌드/패키징은 실행하지 않는다.

## 진행과 결과

- 기존 코드와 직접 호출부·관련 검사를 확인했고 구현 전에 책임/범위와 검증 기준을 기록했다.

### 273~275단계: 색인 갱신/시간 예산

- `planning.source_indexes.PlanningSourceIndexes.refresh`로 공통 deadline과 Git 후보/기준 commit·
  작업공간 제외 경로/색인 작성 호출을 옮겼다. 각 조회 전 잔여 timeout과 오류/호출 순서를 유지한다.
  기존 문서 색인 작성 함수를 callback으로 전달해 public 진입점과 기존 호출 대체 경계도 보존했다.
- `require_planning_git_ready`로 준비 상태 DTO의 안내/오류 표현을 옮겼다. 실제 inspector 호출은
  Pipeline에 그대로다. Git 문서 선택, 준비 실패 안내와 bounded Git preflight 사례가 통과했다.

### 276~278단계: 시작 시 색인 재사용

- `for_start`로 경로/기준 commit 일치와 변경 없음 검사·재사용 여부 반환을 옮겼다. 갱신이 필요하면
  기존 `Pipeline.refresh_planning_index` callback으로 같은 경로/commit을 전달한다. 문서 필터나
  기존 색인 저장 형식을 변경하지 않았다.
- 변경 없는 색인 재사용과 변경 시 재갱신, prepared 색인의 불필요한 Git 조회 생략과 기준 commit별
  기존 실행 snapshot 보존 사례가 통과했다. 재사용을 위해 외부 문서를 임의로 저장소 문서로 간주하지 않는다.

### 279~281단계: 실행별 snapshot 복원

- `snapshot`으로 빈 경로/파일 입력의 기존 None 반환, 실행별 저장 색인의 복원과 부재 시 갱신을
  옮겼다. 실행 디렉터리와 기존 public 갱신 callback만 받고 Run 상태를 저장하거나 단계를 바꾸지 않는다.
- 임시 디렉터리 기획의 저장 색인/원문·선택 출처와 기준 commit별 snapshot 사례가 통과했다.
  저장된 색인 읽기 오류·부재 시 호출/반환 조건을 포함한 전체 본문도 snapshot AST로 대조했다.

### 282단계: 묶음 종료

- `.venv/Scripts/python.exe -m py_compile`로 변경 Python 2개를 확인했다.
- `.venv/Scripts/python.exe -m pytest -q`에 다음 기존 6개 node ID를 선택하고
  `--basetemp=.tmp/pytest-batch273-282 --junitxml=.tmp/batch273-282-tests.xml`을 사용했다.
  **6 passed (5.53초)**였고 기존 임시 저장소/fixture와 테스트용 로컬 Python 응답 프로세스만 사용했다.
  실제 외부 AI나 사용자 프로젝트의 색인은 갱신하지 않았다.
  - `tests/test_pipeline.py::PipelineTest::test_planning_reports_git_readiness_before_git_command_failure`
  - `tests/test_pipeline.py::PipelineTest::test_refresh_planning_index_uses_git_visible_documents`
  - `tests/test_pipeline.py::PipelineTest::test_planning_start_reuses_matching_clean_source_index`
  - `tests/test_pipeline.py::PipelineTest::test_refresh_planning_index_bounds_git_preflight`
  - `tests/test_pipeline.py::PipelineTest::test_incremental_document_changes_keep_stable_snapshot_per_base_commit`
  - `tests/test_pipeline.py::PipelineTest::test_start_snapshots_planning_document_directory`
- `.tmp/check_batch273_282.py`로 snapshot과 전체 본문·오류/경로·deadline/조회/갱신 순서 및 callback을
  대조했다. 기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 428개는 같다. 변경 전역 참조·
  150자/공백과 좁은 callback·직접 Run/SDK/Git 소유권 없음 및 기존 색인 함수/오류 별칭도 확인했다.
- `.tmp/check_stage27.py`로 공개 Pipeline 112개·Store 91개·응용 API 121개 서명, 모델 80개와
  기존 오류/모델/기획 import·RPC 122개 경로를 확인했다. 코어 173개 모듈 import 선언에 순환이나
  기능 역참조가 없다. `git diff --check`와 변경 문서의 참조/완료 기록도 확인했다.
- Pipeline은 **5,713 → 5,677줄(36줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy·기획 실행/색인 갱신은 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
