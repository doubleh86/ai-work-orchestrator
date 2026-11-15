# 보관 정리 재시도·결과·commit 참조: 263~272단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 263~272단계를 수행한다. 시작 Pipeline은 5,770줄이다.
보관 정리 요청의 재전달/재시도와 대상별 결과 기록, 보존할 commit 참조 선택을 기존 통합 모듈로
옮긴다. 공개/기존 private API·저장/RPC 계약, 승인·프로젝트/run 잠금과 SDK/Git 수명을 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 263 | 보관 정리 재시도의 좁은 조회/기록 계약 정의 | 완료 |
| 264 | 보관/대상 확인·재전달/operation claim·재시도 기록 분리 | 완료 |
| 265 | 동일 요청·완료 대상/dirty 작업공간 재시도 보존 확인 | 완료 |
| 266 | 대상별 정리 결과 기록 계약 정의 | 완료 |
| 267 | 완료 대상 생략·blocked/failed·전체/부분 결과 기록 분리 | 완료 |
| 268 | 부분 실패/무시 파일/제거 잔여물과 SDK 호출 순서 보존 확인 | 완료 |
| 269 | 보관 commit 참조 선택 계약 정의 | 완료 |
| 270 | Task/통합/충돌 후보의 순서·중복 제거와 참조 이름 계산 분리 | 완료 |
| 271 | 실제 Git 참조 생성의 순서/실패와 보관 근거 보존 확인 | 완료 |
| 272 | 본문/호출 순서·서명/의존 방향·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `integration.archive_workflow`에 보관 정리 서비스와 좁은 조회/claim/저장·정리 callback을 추가한다.
  실제 Git/Store/Pipeline/SDK 전체를 새 서비스에 넘기지 않는다. 승인·request ID/프로젝트/run 잠금과
  보관 존재 확인·SDK idle client 정리는 Pipeline에 유지한다. 실제 대상 정리는 기존 소유자 callback이다.
- `integration.archive_views`에 commit 참조의 순서/중복 제거·이름 계산 iterator를 추가한다.
  실제 보호 참조 생성과 timeout/오류는 Pipeline이 유지한다. 참조를 하나씩 넘겨 Git 호출과의 순서도 보존한다.
- `pipeline.py`, 위 통합 모듈·아키텍처/계획과 직접 관련 검사만 다룬다. 보호 경로/clean 판단이나
  삭제 조건, Git 부작용·operation 저장·Run 단계의 의미를 바꾸지 않는다.
- 기존 미커밋 변경을 보존한다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및
  사용자 저장소의 commit/merge/push/deploy·보관/작업공간 삭제는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 본문·분기/오류·조회/저장/실제 Git 호출과 SDK/잠금 순서 및 callback을
대조한다. 기존 메서드 서명/데코레이터와 범위 밖 구현·기존 통합 모듈 선언을 유지한다. 변경
Python 구문·전역 참조·150자/공백·diff 및 공개 계약/모델/RPC·의존 관계를 확인한다. 기존 보관
기록/보호 참조·dirty 재시도/무시 파일·부분 실패/제거 잔여물 사례만 선택해 임시 저장소에서 확인한다.
기존 검사로 충분하면 새 테스트를 추가하지 않고 통과 후 종료한다. 전체 테스트·renderer·
빌드/패키징은 실행하지 않는다.

## 진행과 결과

- 기존 코드와 직접 호출부·관련 검사를 확인했고 구현 전에 책임/범위와 검증 기준을 기록했다.

### 263~265단계: 보관 정리 재시도

- `integration.archive_workflow.ArchiveCleanupWorkflow.retry_locked`로 보관/대상 fingerprint·
  완료 상태와 재전달/claim 검사, 요청/operation 기록을 옮겼다. Root의 승인/request ID 정규화와
  project/run 잠금은 그대로다. 실제 정리는 기존 `_apply_archive_cleanup` callback으로 돌아온다.
- 변경된 작업공간을 정리할 수 없는 상태와 이후 재시도·완료 대상 보존 사례가 통과했다.
  동일 요청의 재전달과 오류·조회/저장 순서 전체도 snapshot AST로 대조했다.

### 266~268단계: 대상별 결과 기록

- 같은 서비스의 `complete_targets`로 완료 대상 생략·blocked/failed 오류 보존과 전체/부분/보류
  결과·사건/operation 기록을 옮겼다. 보관 기록 존재 확인과 SDK `discard_idle_clients`는 Root에
  남겼다. 기존 대상 정리 callback과 매 대상 저장/최종 저장 순서를 유지했다.
- 무시 파일 보존·부분 정리 후 완료 대상 유지, Git 등록이 제거된 뒤 잔여물이 남는 경로의 재시도
  사례가 통과했다. 소유 경로/clean 조건과 실제 작업공간 제거 구현은 변경하지 않았다.

### 269~271단계: 보관 commit 참조 선택

- `integration.archive_views.archive_commit_references`로 Task/통합/충돌 후보 순서와 중복 제거·
  참조 이름 계산을 옮겼다. iterator로 참조를 하나씩 반환하며 실제 보호 참조 생성/timeout/실패와
  보호 근거 추가는 기존 Pipeline에 남겼다. 전체 참조를 먼저 만드는 동작을 추가하지 않았다.
- 임시 저장소의 보관/원본 기록 보존 사례가 통과했다. iterator와 Root의 실제 Git 호출을 이어
  원래 본문으로 복원한 AST 대조로 참조 선택/보호 호출/오류 전파와 근거 추가 순서가 같음을 확인했다.

### 272단계: 묶음 종료

- `.venv/Scripts/python.exe -m py_compile`로 변경 Python 3개를 확인했다.
- `.venv/Scripts/python.exe -m pytest -q`에 다음 기존 5개 node ID를 선택하고
  `--basetemp=.tmp/pytest-batch263-272 --junitxml=.tmp/batch263-272-tests.xml`을 사용했다.
  **5 passed (11.28초)**였고 기존 임시 저장소/fixture/mock만 사용했다. 사용자 작업공간은 정리하지 않았다.
  - `tests/test_pipeline.py::PipelineTest::test_completed_run_archive_preserves_records_and_removes_clean_owned_worktree`
  - `tests/test_pipeline.py::PipelineTest::test_archive_cleanup_can_retry_after_dirty_worktree_is_resolved`
  - `tests/test_pipeline.py::PipelineTest::test_archive_cleanup_preserves_ignored_files_on_repeated_attempts`
  - `tests/test_pipeline.py::PipelineTest::test_archive_partial_cleanup_records_blocked_candidate_without_losing_completed_target`
  - `tests/test_pipeline.py::PipelineTest::test_archive_cleanup_retries_residue_after_git_registration_was_removed`
- `.tmp/check_batch263_272.py`로 snapshot과 전체 본문·분기/오류·조회/저장 및 SDK/잠금/실제 Git
  호출 순서·callback을 대조했다. 기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 428개,
  기존 통합 모듈 선언은 같다. 변경 전역 참조·150자/공백과 좁은 callback·직접 Run/SDK/Git 권한
  없음 및 기존 보관 enum 별칭을 확인했다.
- `.tmp/check_stage27.py`로 공개 Pipeline 112개·Store 91개·응용 API 121개 서명, 모델 80개와
  기존 오류/모델/기획 import·RPC 122개 경로를 확인했다. 코어 172개 모듈 import 선언에 순환이나
  기능 역참조가 없다. `git diff --check`와 변경 문서의 참조/완료 기록도 확인했다.
- Pipeline은 **5,770 → 5,713줄(57줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 모듈/테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy·보관/작업공간 삭제는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
