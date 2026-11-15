# 작업 로그·작업공간 상태 조회: 283~292단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 283~292단계를 수행한다. 시작 Pipeline은 5,677줄이다.
작업 로그의 제한된 읽기와 진단 표시 조합, 작업공간 목록의 시간 예산/병렬 조회를 관련 모듈로
모은다. 기존 API·로그 문구/파일 경로·설정/저장/RPC와 실패/조회 순서·승인/잠금을 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 283 | 로그 부분 읽기 계약 정의 | 완료 |
| 284 | byte 제한/디코딩·개행/잘림 안내 분리 | 완료 |
| 285 | 큰 로그의 제한과 기존 static 읽기 진입점 보존 확인 | 완료 |
| 286 | Task 로그 표시 조합 계약 정의 | 완료 |
| 287 | 환경/실행/검증 로그와 최종 실패 안내 조합 분리 | 완료 |
| 288 | 등록 Task 조회·로그 순서/실패·원본 보존 확인 | 완료 |
| 289 | 작업공간 목록의 읽기 전용 조회 계약 정의 | 완료 |
| 290 | 공통 deadline·공유/개별 대상·bounded 병렬/순서 분리 | 완료 |
| 291 | 실제 조회 timeout·결과 순서/안전 판단 보존 확인 | 완료 |
| 292 | 본문/호출 순서·서명/의존 방향·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- 새 `execution.task_logs`에 byte 제한을 받는 읽기 함수와 Task/실행 ID·기록 디렉터리/읽기
  callback 기반 표시 조합 함수를 둔다. Run/Task의 조회·검증과 제한값 선택은 Pipeline에 유지한다.
  등록된 Task의 경로와 기존 오류를 보존하고 새 저장/실행/권한을 만들지 않는다.
- 기존 `integration.workspaces`에 읽기 전용 목록 조회 서비스를 추가한다. Git 준비/작업공간
  목록·Run 목록/단건·공유 여부/개별 상태 callback만 받는다. 전체 GitWorkspace/Store/Pipeline/
  Config·SDK를 새 서비스에 넘기지 않는다. 기존 inspector와 실제 안전 판단은 그대로 사용한다.
- `pipeline.py`, 위 실행/통합 모듈·아키텍처/계획과 직접 관련 검사만 다룬다. 정리/삭제·승인/
  잠금·Run 단계/정책·SDK/프로세스 수명은 변경하지 않는다.
- 기존 미커밋 변경을 보존한다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및
  사용자 저장소의 commit/merge/push/deploy·작업공간 삭제/로그 조회는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 본문·읽기/디코딩/표시·deadline/조회/병렬/오류 순서와 callback을
대조한다. 기존 메서드 서명/데코레이터와 범위 밖 구현·기존 workspace 선언을 유지한다. 변경
Python 구문·전역 참조·150자/공백·diff 및 공개 계약/모델/RPC·의존 관계를 확인한다. 기존
등록 Task/큰 로그·최종 실패 안내와 병렬 상태/변경된 작업공간의 안전 판단 사례만 선택한다.
기존 검사로 충분하면 새 테스트를 추가하지 않고 통과 후 종료한다. 전체 테스트·renderer·
빌드/패키징은 실행하지 않는다.

## 진행과 결과

- 기존 코드와 직접 호출부·관련 검사를 확인했고 구현 전에 책임/범위와 검증 기준을 기록했다.

### 283~285단계: 로그 부분 읽기

- `execution.task_logs.read_task_log_tail`로 byte 범위 읽기와 UTF-8 대체 디코딩·개행 정규화/
  잘림 안내를 옮겼다. 기존 static 진입점은 Pipeline의 `TASK_LOG_DISPLAY_LIMIT_BYTES`를 전달한다.
  현재 64 KiB 제한과 원문 경로 표시·읽기 오류를 보존했다.
- 큰 로그의 최근 부분만 표시하고 마지막 개행/전체 경로 안내를 유지하는 기존 사례가 통과했다.
  읽기/디코딩/안내 전체 본문도 제한값 치환을 제외하고 snapshot AST로 대조했다.

### 286~288단계: Task 로그 조합

- 같은 모듈의 `render_task_log`로 환경/실행/검증 로그와 최종 Task 실패 안내를 조합하는 처리를
  옮겼다. Run/Task 조회·존재 검증은 Pipeline에 남기고 실제 기록 디렉터리/읽기 함수를 callback으로
  전달한다. 구간 순서·단일 구간 반환과 복수 구간의 끝 개행 제거 규칙을 보존했다.
- 등록된 Task 로그만 표시하고 누락 Task를 거부하는 사례, 성공한 provider 로그 뒤 최종 실패를
  표시하며 원본을 바꾸지 않는 사례가 통과했다. 파일 경로/존재·읽기/오류 조건도 AST로 대조했다.

### 289~291단계: 작업공간 상태 목록

- `integration.workspaces.WorkspaceStatusQueries`로 전체/단건 Run·등록 작업공간 조회와 공유
  작업공간 대표 Task/개별 Task 구성, 공통 deadline과 최대 네 개 thread의 조회를 옮겼다.
  Git/Run 조회와 공유 여부·개별 상태 callback만 받으며 결과 순서와 Future 오류 전파를 유지한다.
- 병렬 실행/timeout·deadline 전달과 원래 Task 순서, 실제 변경된 작업공간의 정리 거부 사례가
  통과했다. 기존 inspector 선언과 안전 판단/승인·삭제 구현은 변경하지 않았다.

### 292단계: 묶음 종료

- `.venv/Scripts/python.exe -m py_compile`로 변경 Python 3개를 확인했다.
- `.venv/Scripts/python.exe -m pytest -q`에 다음 기존 5개 node ID를 선택하고
  `--basetemp=.tmp/pytest-batch283-292 --junitxml=.tmp/batch283-292-tests.xml`을 사용했다.
  **5 passed (5.62초)**였고 기존 임시 저장소/fixture/mock만 사용했다. 사용자 로그나 작업공간은 조회/정리하지 않았다.
  - `tests/test_pipeline.py::PipelineTest::test_task_log_returns_bounded_tail_for_large_existing_log`
  - `tests/test_pipeline.py::PipelineTest::test_task_log_reads_only_registered_task_log`
  - `tests/test_pipeline.py::PipelineTest::test_task_log_includes_final_failure_after_successful_provider_log`
  - `tests/test_pipeline.py::PipelineTest::test_workspace_statuses_are_bounded_parallel_and_keep_task_order`
  - `tests/test_pipeline.py::PipelineTest::test_workspace_cleanup_refuses_dirty_merged_worktree`
- `.tmp/check_batch283_292.py`로 snapshot과 전체 본문·읽기/디코딩/표시·deadline/조회/병렬/오류
  순서 및 callback을 대조했다. 기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 430개,
  기존 workspace 선언은 같다. 변경 전역 참조·150자/공백과 읽기 전용 callback·직접 소유 객체/
  쓰기 권한 없음, 기존 제한값과 executor import 별칭도 확인했다.
- `.tmp/check_stage27.py`로 공개 Pipeline 112개·Store 91개·응용 API 121개 서명, 모델 80개와
  기존 오류/모델/기획 import·RPC 122개 경로를 확인했다. 코어 174개 모듈 import 선언에 순환이나
  기능 역참조가 없다. `git diff --check`와 변경 문서의 참조/완료 기록도 확인했다.
- Pipeline은 **5,677 → 5,636줄(41줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy·작업공간 삭제/로그 조회는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
