# 기획 프로필·자동 강도·기술 구성 이력: 253~262단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 253~262단계를 수행한다. 시작 Pipeline은 5,827줄이다.
기획 프로필 구성·자동 강도 적용과 기술 구성 결정 이력을 기획 모듈로 분리한다. 기존 API·
설정/저장·RPC 계약, 수동/기존 프로필과 대화 재사용 조건·승인/잠금/최종 Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 253 | 기획 프로필 구성의 조회/정규화/검증 계약 정의 | 완료 |
| 254 | 명시적 설정/출처·Agent 검사·Claude 세션 메타데이터 처리 분리 | 완료 |
| 255 | 모델/강도 저장과 프로필 변경 시 대화 재사용 조건 보존 확인 | 완료 |
| 256 | 자동 기획 프로필 적용 계약 정의 | 완료 |
| 257 | 수동/기존 프로필 보호·모드 조회·강도 기준값/오류 처리 분리 | 완료 |
| 258 | 자동 Claude 모델과 수동 설정·재기획 보존 확인 | 완료 |
| 259 | 기술 구성 결정 이력 계약 정의 | 완료 |
| 260 | 기존 결정 대체·revision/답변/후보 사본 기록 분리 | 완료 |
| 261 | 기술 구성 선택/재계획·질문과 사용자 답변 보존 확인 | 완료 |
| 262 | 본문/호출 순서·서명/의존 방향·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- 새 `planning.profiles`는 필요한 Agent 조회/가용성·정규화/검증과 선택 모드 조회 callback만 받는다.
  전체 Config/Store/Pipeline·SDK를 넘기지 않고 실제 AI/정책 저장/잠금·세션 수명을 소유하지 않는다.
  Claude 대화 ID를 비우는 조건과 사건 기록은 기존 기획 프로필 메타데이터 처리 그대로 보존한다.
- 기존 `planning.bootstrap`에 기술 구성 결정 교체 함수를 추가한다. Run/Plan과 저장소 Path만
  사용해 revision·기존 결정 상태·사용자 답변/출처/후보 사본을 기록한다. 실제 구성 확정/승인은
  Pipeline의 기존 진입점과 잠금 안에서 처리한다.
- `pipeline.py`, 위 기획 모듈·아키텍처/계획과 직접 관련 검사만 다룬다. 실제 AI 호출/SDK와
  정책 binding·저장/Run 단계, 프로젝트 파일 생성·Git 부작용은 변경하지 않는다.
- 기존 미커밋 변경을 보존한다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및
  사용자 저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 본문·분기/오류·메타데이터 갱신/조회 순서와 callback 결선을 대조한다.
기존 Pipeline 서명/데코레이터·범위 밖 메서드와 bootstrap 선언을 보존한다. 변경 Python 구문·
전역 참조·150자/공백·diff 및 공개 계약/모델/RPC·의존 관계를 확인한다. 기존 기획 모델/대화·
수동 프로필/재기획·자동 Claude 모델과 기술 구성 질문/선택/대체 이력 사례만 선택한다.
기존 검사로 충분하면 새 테스트를 추가하지 않고 통과 후 종료한다. 전체 테스트·renderer·
빌드/패키징은 실행하지 않는다.

## 진행과 결과

- 기존 코드와 직접 호출부·관련 검사를 확인했고 구현 전에 책임/범위와 검증 기준을 기록했다.

### 253~255단계: 기획 프로필 구성

- `planning.profiles.PlanningProfiles.configure`로 기획 Agent/모델/강도의 명시적 설정과 수동 출처,
  가용성/정규화·검증, 기존 Claude 대화 ID를 비우는 조건/사건 기록을 옮겼다. 필요한 callback만
  전달하고 오류 발생 전후의 부분 메타데이터 갱신/검증 순서와 기존 private 진입점을 유지했다.
- 저장된 기획 모델/강도 변경·수동 출처와 Claude 대화 복원/재사용·프로필 변경 후 새 대화 사례가 통과했다.
  실제 대화 실행이나 SDK 세션 정리는 기존 소유자가 유지한다.

### 256~258단계: 자동 기획 프로필

- 같은 서비스의 `pin_automatic`으로 수동/기존 프로필과 비대상 Agent 조기 반환, 자동 Claude
  허용 조건·선택 모드/기준값과 지원 불가 오류를 옮겼다. 모드 조회는 기존 조건을 통과한 시점에만
  callback을 호출한다. 정책을 저장하거나 실행 binding을 만들지 않는다.
- 자동 Claude 모델/호출 프로필 일치와 수동 모델 보존, 재기획 시 동일한 수동 Task 프로필 보존
  사례가 통과했다. 본문·오류·기준값 갱신과 조회 순서도 snapshot AST로 대조했다.

### 259~261단계: 기술 구성 결정 이력

- `planning.bootstrap.replace_tech_stack_decision`에 기존 결정 대체·최대 revision 증가와 사용자
  답변/출처·후보 deep copy 기록을 옮겼다. 계획과 Run, 저장소 Path만 사용하며 구성 확정/승인은 하지 않는다.
- 기술 구성 질문 후 후보 갱신/확정과 stale revision 거부, 새 결정으로 대체되는 이력/상태 및
  프로젝트 파일을 만들지 않는 기존 사례가 통과했다. 전체 본문과 기존 bootstrap 선언도 AST로 대조했다.

### 262단계: 묶음 종료

- `.venv/Scripts/python.exe -m py_compile`로 변경 Python 3개를 확인했다.
- `.venv/Scripts/python.exe -m pytest -q`에 다음 기존 7개 node ID를 선택하고
  `--basetemp=.tmp/pytest-batch253-262 --junitxml=.tmp/batch253-262-tests.xml`을 사용했다.
  **7 passed (2.22초)**였고 기존 임시 저장소/fixture/mock만 사용했다.
  - `tests/test_pipeline.py::PipelineTest::test_clarification_updates_saved_planning_model`
  - `tests/test_pipeline.py::PipelineTest::test_claude_planning_chat_restores_then_resumes_same_session`
  - `tests/test_effort_policy_preview.py::EffortPolicyPreviewTest::test_explicit_planning_profile_change_records_manual_source`
  - `tests/test_effort_policy_preview.py::EffortPolicyPreviewTest::test_replanning_preserves_manual_source_only_when_profile_is_unchanged`
  - `tests/test_claude_model_selection.py::test_automatic_claude_planning_is_pinned_and_matches_invocation_without_changing_manual_choice`
  - `tests/test_pipeline.py::PipelineTest::test_greenfield_stack_confirmation_checks_revision_and_does_not_create_project_files`
  - `tests/test_pipeline.py::PipelineTest::test_greenfield_questions_block_confirmation_until_candidates_are_refreshed`
- `.tmp/check_batch253_262.py`로 snapshot과 전체 본문·분기/오류·조회/갱신 순서 및 callback을 대조했다.
  기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 427개, 기존 bootstrap 선언이 같다. 변경 전역
  참조·150자/공백과 좁은 callback, Run/SDK 수명 권한 없음 및 기존 모델/선택 함수 별칭을 확인했다.
- `.tmp/check_stage27.py`로 공개 Pipeline 112개·Store 91개·응용 API 121개 서명, 모델 80개와
  기존 오류/모델/기획 import·RPC 122개 경로를 확인했다. 코어 172개 모듈 import 선언에 순환이나
  기능 역참조가 없다. `git diff --check`와 변경 문서의 참조/완료 기록도 확인했다.
- Pipeline은 **5,827 → 5,770줄(57줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
