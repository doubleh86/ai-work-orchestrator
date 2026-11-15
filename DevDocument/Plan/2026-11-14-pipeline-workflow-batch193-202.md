# 작업 호출 정책·호출 문맥·강도 계획 반영: 193~202단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 193~202단계를 수행한다. 시작 Pipeline은 6,249줄이다.
작업 AI 호출과 강도 계획 적용의 검증/문맥/기록을 분리한다. 기존 미커밋 변경·공개 API·저장/
CLI/RPC, 승인·잠금·정책 binding·SDK/프로세스/취소 수명과 최종 Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 193 | 작업 호출 전 정책 근거 계약 정의 | 완료 |
| 194 | started binding·snapshot/Agent/runtime·안내 문구 확인 분리 | 완료 |
| 195 | 기존/누락·불일치 정책과 호출 차단 확인 | 완료 |
| 196 | Task 호출 문맥/전달 계약 정의 | 완료 |
| 197 | command/model/reasoning·usage/시도·취소/진행/profile 연결 분리 | 완료 |
| 198 | 작업/리뷰의 실제 호출 옵션·근거/취소 보존 확인 | 완료 |
| 199 | 강도 계획 반영의 기록 계약 정의 | 완료 |
| 200 | revision/단계·preview/변경·출력/저장/대화 반영 분리 | 완료 |
| 201 | 명시적 리뷰·프로필/재전달·stale/실행 후 거부 확인 | 완료 |
| 202 | 본문/순서·공개 계약·의존 관계·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `execution.task_invocation`은 좁은 policy/Agent 조회·snapshot 검증 API로 기존 binding/snapshot/
  runtime 근거와 안내 문구를 확인하고 Task 호출 인자를 구성한다. 정책 binding의 생성/시작/복구와
  실제 설정 binding scope는 Pipeline에 남긴다. 기록·취소/실제 provider 호출은 기존 API만 사용한다.
- 취소 신호는 기존 구체 타입이 유지되도록 Generic 계약으로 전달한다. command/model/reasoning,
  usage/시도 ID·진행/profile callback과 작업/리뷰의 분기 의미를 바꾸지 않는다. SDK/프로세스/
  credential과 usage/도구 lease 수명은 기존 provider invocation 소유자가 유지한다.
- `execution.effort_plan`에 계획 반영 서비스를 추가한다. 기존 revision/실행 상태·선택 mode를
  확인하고 기존 preview/계획 변경 API의 결과를 같은 순서로 검증·출력·저장한다. 실제 변경 준비
  객체는 원래 위치에서 생성되도록 callback으로 전달한다. mode/입력 검증·run/chat 잠금과
  허용 단계 조회는 Pipeline에 유지한다. 최종 Run 전이/정책 binding 권한은 추가하지 않는다.
- 전체 Pipeline/Store/Config를 전달하지 않는다. `pipeline.py`, 위 실행 모듈·아키텍처/계획과
  직접 관련 테스트만 다룬다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 정책/호출/기록 본문·callback·평가/오류/저장·잠금/정책 scope의 순서를
대조한다. 변경 Python의 구문·전역 참조·150자/공백·diff 및 공개 계약/모델/RPC/의존 관계를
확인한다. 기존 정책 호출 근거/옵션·작업/리뷰와 강도 계획 적용/실패 case만 선택한다. 기존
case가 충분하면 테스트를 추가하거나 변경하지 않는다. 전체 테스트·renderer·빌드/패키징을
실행하지 않고 필요한 검사 통과 후 종료한다.

## 진행과 결과

### 193~195단계: 호출 전 정책 근거

- `execution.task_invocation.TaskInvocation.prepare_policy`로 기존 Run 참조/binding 시작 상태와
  정책 snapshot·Agent/runtime·안내 문구 확인을 옮겼다. 정책과 문구를 반환하고 binding 생성/
  시작/복구·검증 소유자와 실제 설정 binding scope는 Pipeline에 유지했다.
- 시작된 정책의 실행 순서/안내 문구, 계획/정책 snapshot 변경의 호출 차단과 리뷰 runtime 근거
  case가 통과했다. 누락/불일치·기존 참조 없는 경로를 포함한 전체 검증 본문은 snapshot AST와 같다.

### 196~198단계: Task 호출 문맥

- `TaskInvocation.run`이 기존 command/model/reasoning, worktree/prompt·usage/시도/호출 ID와
  취소/진행/profile callback을 구성해 기존 provider API로 전달한다. 작업/리뷰 분기·평가 순서가 동일하다.
  취소 신호는 Generic/반공변 호출 계약으로 구체 타입을 보존하며 SDK/credential·usage/도구 lease
  수명과 provider 오류 처리는 기존 소유자에 남겼다.
- 정책 안내를 포함하는 작업/리뷰 호출, 편집·확정 후 별도 Codex 리뷰 turn/프로필 보존 case가 통과했다.
  모든 provider keyword·진행/profile/취소 연결은 이동 전후 AST로도 대조했다.

### 199~201단계: 강도 계획 적용 기록

- 기존 `execution.effort_plan`의 프로필/리뷰 준비 규칙을 그대로 두고 `EffortPlanApplication`을 추가했다.
  revision/실행 상태·저장된 mode 검사 후 기존 preview와 지연 생성한 준비 API를 호출한다. Task graph/
  revision·경로/출력·이벤트·상태/대화 저장 순서가 동일하다. mode/입력 검사·run/chat 잠금·허용 단계는
  Pipeline에 유지했다. 최종 Run 전이와 binding 권한은 추가하지 않았다.
- 명시적 리뷰 선택/계획 재확정, 필수·기존 리뷰 보존과 mode 반영 후 작업/리뷰 실제 연결 case가 통과했다.
  stale/실행 후/다른 mode 거부를 포함한 전체 조건/저장 순서는 snapshot AST로 대조했다.

### 202단계: 묶음 종료

- 아래 기존 함수 여섯 개만 선택했다. 매개변수 사례 포함 **7 passed, 2 subtests passed**(1.15초)다.
  기존 fixture/mock을 사용했고 실제 AI/외부 원격은 호출하지 않았다.
  - `tests/test_effort_execution_binding.py::EffortExecutionBindingTest::test_execution_starts_before_ai_and_finishes_after_return`
  - `tests/test_effort_execution_binding.py::EffortExecutionBindingTest::test_plan_mismatch_and_snapshot_drift_block_ai`
  - `tests/test_effort_execution_binding.py::EffortExecutionBindingTest::test_reviewer_runtime_must_match_started_snapshot`
  - `tests/test_effort_policy_preview.py::EffortPolicyPreviewTest::test_mode_application_requires_explicit_reviewer_and_plan_reconfirmation`
  - `tests/test_effort_policy_preview.py::EffortPolicyPreviewTest::test_mode_application_preserves_required_and_legacy_review`
  - `tests/test_effort_desktop_controls.py::test_codex_review_survives_edit_confirmation_and_uses_separate_turn`
- snapshot AST로 정책/호출/계획 반영 전체와 callback·평가/오류/저장·잠금 순서를 대조했다.
  기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 425개, 기존 강도 프로필/리뷰 준비 클래스가
  그대로다. 새 facade 메서드 없이 좁은 계약을 연결했고 정책 binding 소유 메서드는 바꾸지 않았다.
- 변경 Python 3개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로를 유지한다.
  코어 165개 모듈 import 선언에 순환/기능 역참조가 없고 전체 Pipeline/Store/Config/Git을 전달하지 않는다.
- Pipeline은 **6,249 → 6,183줄(66줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서/docstring 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
