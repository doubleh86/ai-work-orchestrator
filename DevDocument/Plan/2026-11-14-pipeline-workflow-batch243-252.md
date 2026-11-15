# 통합 검증 명령·실패 후보·결과 기록: 243~252단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 243~252단계를 수행한다. 시작 Pipeline은 5,879줄이다.
통합 검증의 명령 선택·실패 후보와 결과 이력 기록을 기존 실행 모듈에 모은다. 새 패키지나
실행 권한을 만들지 않고 기존 API·설정/저장·RPC 계약과 승인·잠금·중단/최종 Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 243 | 검증 명령 선택/제외 판정 계약 정의 | 완료 |
| 244 | 프로젝트 명령 우선·Task 중복 제거와 관리 명령 제외 분리 | 완료 |
| 245 | 선택 순서·제외 목록과 실행 불가 오류 보존 확인 | 완료 |
| 246 | 검증 실패 후보 기록의 좁은 조회/저장 계약 정의 | 완료 |
| 247 | 환경/파일 잠금과 공통/Task 명령의 원인 후보 기록 분리 | 완료 |
| 248 | 단일 원인 미확정·실패 근거/저장·재시도 보존 확인 | 완료 |
| 249 | 검증 결과 이력 기록 계약 정의 | 완료 |
| 250 | 검증 attempt·commit 파일 근거와 중복 기록 방지 분리 | 완료 |
| 251 | 검증 성공 시점·보관/복원 결과 이력 보존 확인 | 완료 |
| 252 | 본문/호출 순서·서명/의존 방향·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `execution.run_verification`에 명령 선택/관리 명령 판정 함수와 실패 후보 기록 서비스를 추가한다.
  명령 선택은 설정 tuple·기존 제외 판정 callback만 받는다. 실패 기록은 프로젝트 검증 명령
  존재 여부·commit queue 조회·기존 저장 callback만 받으며 전체 Pipeline/Config/Store를 전달하지 않는다.
- `execution.results`에 그룹 검증 결과 이력 함수를 추가한다. 기존 commit 파일 조회 callback과
  Run/attempt 근거를 사용하고 기록 중복 방지·시각/오류를 보존한다. 실제 Git 조회는 기존 소유자가 한다.
- `pipeline.py`, 위 실행 모듈·아키텍처/계획과 직접 관련 검사만 다룬다. 검증 실행 명령이나
  승인/잠금·SDK/프로세스·정책 binding·취소/실패/성공 단계와 결과 기록 호출 시점은 변경하지 않는다.
- 기존 미커밋 변경을 보존한다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및
  사용자 저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 전체 본문·분기/오류·조회/저장 순서와 callback 결선을 대조한다.
기존 메서드의 서명/데코레이터·범위 밖 구현과 기존 실행 모듈 선언을 유지한다. 변경 Python
구문·전역 참조·150자/공백·diff 및 공개 계약/모델/RPC·의존 관계를 확인한다. 기존 명령 선택/
관리 명령 제외·원인 후보/파일 잠금과 최종 결과/검증 성공 기록 사례만 선택한다. 기존 검사로
충분하면 새 테스트를 추가하지 않는다. 전체 테스트·renderer·빌드/패키징은 실행하지 않는다.

## 진행과 결과

- 기존 코드/호출부와 관련 검사를 확인했고 구현 전에 책임·범위와 검증 기준을 기록했다.

### 243~245단계: 명령 선택/제외

- `execution.run_verification`에 명령 선택과 관리 명령 판정 함수를 추가했다. 프로젝트 설정 우선,
  Task 명령의 최초 등장 순서/중복 제거, `git worktree` 제외와 제외 목록을 보존했다. 기존 private
  메서드와 동적 제외 callback은 유지했다. 실제 실행/실행 불가 오류는 기존 Pipeline에 남긴다.
- 기존 설정 우선/중복 제거·관리 명령 제외 사례가 통과했고 전체 선택/판정 본문을 snapshot AST로 대조했다.

### 246~248단계: 실패 원인 후보

- 같은 모듈의 `VerificationFailureEvidence`에 환경/파일 잠금 실패와 실제 명령 실패의 후보 기록을
  옮겼다. 전체 Pipeline/Store/Config 없이 공통 명령 여부·commit queue 조회·저장 callback만 받는다.
  attempt 없음 조기 반환과 후보/설명/저장·조회 순서를 보존했다.
- 명령 선언 Task를 단일 원인으로 확정하지 않는 기존 사례와 파일 잠금 시 자동 수정을 중단하고
  원래 명령 전체를 재시도하는 사례가 통과했다. 공통/여러 Task/출처 없음 분기도 본문 AST로 대조했다.

### 249~251단계: 그룹 검증 결과 이력

- `execution.results.record_group_result`로 기존 attempt 확인·중복 방지와 commit 파일/시각/오류
  기록을 옮겼다. 실제 commit 조회는 기존 callback이고 파일 근거/결과 모델을 바꾸지 않았다.
- 최종 결과의 commit 파일/보관 복원과 검증 성공 시점의 기록 사례가 통과했다. 실패한 검증에는
  결과 이력이 추가되지 않는다. 호출 시점을 소유한 Pipeline `_step` 본문 전체는 변경하지 않았다.

### 252단계: 묶음 종료

- `.venv/Scripts/python.exe -m py_compile`로 변경 Python 3개를 확인했다. 이후 docstring/빈 줄만
  정리했고 최종 소스의 AST·전역 참조·150자/공백도 확인했다.
- `.venv/Scripts/python.exe -m pytest -q`에 다음 기존 6개 node ID를 선택하고
  `--basetemp=.tmp/pytest-batch243-252 --junitxml=.tmp/batch243-252-tests.xml`을 사용했다.
  **6 passed (1.97초)**였고 기존 임시 저장소/fixture/mock만 사용했다.
  - `tests/test_pipeline.py::PipelineTest::test_integration_verification_commands_prefer_config_and_deduplicate_tasks`
  - `tests/test_pipeline.py::PipelineTest::test_integration_verification_excludes_worktree_commands`
  - `tests/test_pipeline.py::PipelineTest::test_verification_failure_records_command_owner_as_candidate_not_direct_cause`
  - `tests/test_execution_control.py::test_file_lock_stops_auto_repair_preserves_evidence_and_allows_full_retry`
  - `tests/test_pipeline.py::PipelineTest::test_final_result_records_only_committed_files_and_survives_archive_summary`
  - `tests/test_pipeline.py::PipelineTest::test_group_result_is_saved_only_after_verification_step_succeeds`
- `.tmp/check_batch243_252.py`로 snapshot과 전체 본문·분기/오류·조회/저장 순서 및 callback을 대조했다.
  기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 426개, 기존 실행 모듈 선언은 그대로다.
  변경 전역 참조·줄 길이/공백·좁은 callback과 `pipeline.GroupResultRecord` 모델 별칭을 확인했다.
- `.tmp/check_stage27.py`로 공개 Pipeline 112개·Store 91개·응용 API 121개 서명, 모델 80개와
  기존 오류/모델/기획 import·RPC 122개 경로를 확인했다. 코어 171개 모듈 import 선언에 순환이나
  기능 역참조가 없다. `git diff --check`와 변경 문서의 참조/완료 기록도 확인했다.
- Pipeline은 **5,879 → 5,827줄(52줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 모듈/테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
