# 경로 승인 조회·실행 AI 변경 준비·복구 자식 기록: 213~222단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 213~222단계를 수행한다. 시작 Pipeline은 6,100줄이다.
채팅 제어의 조회/판단 준비와 복구 자식 요청의 기록 수명을 분리한다. 기존 미커밋 변경·공개
API·저장/CLI/RPC, 승인·기존 잠금·SDK/정책/실행 수명·최종 Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 213 | 경로 제안/승인 기록 조회 계약 정의 | 완료 |
| 214 | 결과 snapshot·현재 제안/과거 승인 연결의 읽기 규칙 분리 | 완료 |
| 215 | 현재 제안·취소/변경/도구 결과·기존 승인 경계 확인 | 완료 |
| 216 | 채팅 실행 AI 변경 준비 계약 정의 | 완료 |
| 217 | 요청/대상/시도·단일 Task 선택·현재 profile 근거 기록 분리 | 완료 |
| 218 | 명시적 변경/재시도·동명 Task·stale 저장 차단 확인 | 완료 |
| 219 | 복구 자식 요청의 기록 수명 계약 정의 | 완료 |
| 220 | 부모/자식 연결·취소/단계 검사·성공/오류 기록 분리 | 완료 |
| 221 | 실제 복구 진입·부모 보존·오류/중단 관련 확인 | 완료 |
| 222 | 본문/순서·공개 계약·의존 관계·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `queries.scope_approval`는 명시적 Run/operation/최근 operation 조회 callback으로 승인 결과와
  제안이 실제 안내됐는지 읽는다. 현재 실패 fingerprint·동일 제안·취소/기존 승인·도구 결과 경계를
  보존하고 상태를 저장하거나 승인을 부여하지 않는다. Pipeline의 조회 순서/시점을 유지한다.
- `execution.chat_profiles`에 변경 준비 서비스를 추가한다. Pipeline의 request-control 잠금 안에서
  기존 요청/대상·단일 Task/실행/시도와 profile 근거를 확인해 decision을 기록한다. 실제 profile 저장/
  재시도·run/chat 잠금과 계획/Run 전이는 기존 소유자에 유지한다.
- `execution.chat_recovery`에 자식 기록 scope를 추가한다. 기존 요청 제어 잠금 factory와 좁은 조회/
  저장/대상 검증·대화 기록 API만 받는다. 기존 yield/부모/자식·오류/성공 기록 순서를 유지하며
  새로운 잠금이나 실행/Run 전이·승인 권한을 만들지 않는다. Pipeline의 contextmanager 진입점은 유지한다.
- 전체 Pipeline/Store/Config/Git을 전달하지 않는다. `pipeline.py`, 위 모듈·아키텍처/계획과 직접
  관련 테스트만 다룬다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자 저장소의
  commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 전체 본문·callback·조회/조건/기록·잠금/yield/오류/후속 처리 순서를
대조한다. 변경 Python의 구문·전역 참조·150자/공백·diff 및 공개 계약/모델/RPC/의존 관계를
확인한다. 기존 경로 승인/제안, 실행 AI 변경/재시도·복구 진입 관련 case만 선택하고 충분하면
테스트를 추가하지 않는다. 전체 테스트·renderer·빌드/패키징은 실행하지 않고 필요한 확인 후 종료한다.

## 진행과 결과

### 213~215단계: 경로 승인 조회

- `queries.scope_approval.ScopeApprovalQueries`에 Run/operation/최근 operation 조회 API만 전달했다.
  승인 결과의 자식/Run/오류 조회 순서, 현재 실패/제안·과거 안내/승인/취소/도구 결과의 경계를
  그대로 읽는다. 기존 제안 ID/승인 문구의 순수 규칙을 재사용하며 저장이나 승인을 부여하지 않는다.
- MCP 승인/재전달 결과, 미실행 과거 승인 후 현재 안내 복원과 철회/변경/도구 결과를 넘지 않는
  case가 통과했다. 전체 조회/조건/반환 본문도 snapshot AST와 같다.

### 216~218단계: 실행 AI 변경 준비

- 기존 `execution.chat_profiles`에 `ChatProfileDecision`을 추가했다. 기존 요청 제어 잠금 안에서
  요청/대상·단일 Task 선택/실행/시도·재시도 조건을 확인하고 유효 profile 근거와 decision을 기록한다.
  실제 profile 저장/재시도와 run/chat 잠금·최종 Run 전이는 기존 Pipeline/서비스에 유지했다.
- 이름으로 고른 실패 작업의 변경만 저장하기, 명시적 변경 후 재시도, 동명 Task를 임의로 고르지
  않기와 저장 불가/시도 변경 뒤 예전 profile로 복구하지 않기 case가 통과했다.

### 219~221단계: 복구 자식 기록

- 기존 `execution.chat_recovery`에 `ChatRecoveryChildren.scope`를 추가했다. 기존 요청 제어 잠금
  factory와 조회/저장/대상 검증·대화 기록 API로 일반 부모/자식과 yield·오류/성공 기록을 처리한다.
  부모 없음/프로젝트 부모 경로는 Pipeline에 그대로 둬 해당 경로의 조기 반환과 API 접근도 유지했다.
- 실제 자식 복구의 단일 claim·부모 보존, 취소 뒤 늦은 자식의 작업 시작 거부 case가 통과했다.
  yield 이후 오류의 재발생/대화 기록과 완료/실패 operation 기록 전체도 AST로 대조했다.
  기존 contextmanager 진입점·데코레이터와 실제 실행/승인/Run 단계 소유권은 바꾸지 않았다.

### 222단계: 묶음 종료

- 아래 기존 함수 아홉 개를 선택했다. 승인 통합 case는 `mcp_approval` 매개변수 하나만 실행했고,
  매개변수 사례 포함 **15 passed**(10.36초)였다. 기존 임시 저장소와 fixture/mock을 사용했으며
  실제 외부 MCP/AI/계정/원격을 호출하지 않았다.
  - `tests/test_chat_scope_approval.py::test_approval_updates_plan_and_prompt_then_retries_only_the_failed_task[mcp_approval]`
  - `tests/test_chat_scope_approval.py::test_continue_recovers_the_current_offer_after_a_legacy_unhandled_human_approval`
  - `tests/test_chat_scope_approval.py::test_old_approval_offer_never_crosses_revocation_or_a_changed_execution`
  - `tests/test_project_chat.py::test_chat_saves_named_failed_task_profile_without_plan_approval_or_execution`
  - `tests/test_project_chat.py::test_chat_changes_profile_before_explicit_combined_retry`
  - `tests/test_project_chat.py::test_chat_does_not_guess_between_matching_failed_tasks`
  - `tests/test_project_chat.py::test_chat_does_not_recover_with_old_profile_when_change_cannot_be_saved`
  - `tests/test_chat_control_review.py::test_child_repair_claims_once_and_preserves_parent_identity`
  - `tests/test_chat_control_review.py::test_cancel_after_advance_rejects_the_late_child_before_any_work`
- snapshot AST로 전체 본문·callback·조회/조건/잠금/yield/오류/기록 순서를 대조했다. 기존 모든
  Pipeline 서명/데코레이터와 범위 밖 메서드 423개, 기존 실행 profile/복구 클래스들이 그대로다.
  조회 factory 하나만 추가했고 새 모듈에 전체 소유 객체나 직접 Run/승인 권한을 주지 않았다.
- 변경 Python 4개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로를 유지한다.
  코어 168개 모듈 import 선언에 순환/기능 역참조가 없다. 기존 `pipeline.scope_approval_reply`
  import도 명시적 별칭으로 보존하고 원래 함수와 같은 객체인지 확인했다.
- Pipeline은 **6,100 → 6,022줄(78줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서/주석 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
