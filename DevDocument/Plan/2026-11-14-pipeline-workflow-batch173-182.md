# 프로젝트 채팅 문맥·판단 호출·경로 승인 기록: 173~182단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 173~182단계를 수행한다. 시작 Pipeline은 6,309줄이다.
프로젝트 채팅의 문맥 구성·읽기 전용 판단 호출과 경로 승인 결과 기록을 분리한다.
기존 미커밋 변경·공개 API·저장/CLI/RPC와 승인·잠금·SDK/정책 수명·Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 173 | 프로젝트 판단 문맥의 명시적 계약 정의 | 완료 |
| 174 | 실행/통합·scope·Task 근거·대화/도구 결과 구성 분리 | 완료 |
| 175 | 실제 결과 문맥·대상 변경 보호 확인 | 완료 |
| 176 | 제어 판단의 읽기 전용 AI 호출 계약 정의 | 완료 |
| 177 | 프로젝트/경로 승인 prompt·profile·기록·호출/파싱 분리 | 완료 |
| 178 | 읽기 전용 권한·판단/취소·기록 순서 확인 | 완료 |
| 179 | 경로 승인 판단 결과의 기록 계약 정의 | 완료 |
| 180 | 요청/대상 재검증·승인/거부/추가 질문 기록 분리 | 완료 |
| 181 | 승인 단독·명시적 계속·취소/대상 변경 차단 확인 | 완료 |
| 182 | 본문/순서·공개 계약·의존 관계·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `planning.control_decisions`는 필요한 문맥 조회 callback으로 실행/통합·현재 범위/Task 근거와
  대화/도구 결과를 구성한다. 별도 호출 계약으로 기존 planning profile을 읽기 전용/승인 거부로
  제한하고 prompt/log 경로·기록·기존 effort scope·실제 planning invocation API와 파싱을 조합한다.
- Pipeline의 사전 제어 분기·chat 잠금/Run 조회와 실제 SDK/정책/프로세스 수명은 유지한다.
  profile 구성→문맥 생성→prompt/기록→effort scope/호출→파싱의 기존 순서를 보존한다.
- `execution.scope_consent`는 기존 request-control 잠금 안에서 최신 요청/대상·제안 재검증과
  판단 payload/phase 기록을 처리한다. Pipeline이 잠금·후속 승인 준비/대화 기록과 실제 scope 적용을 유지한다.
- 각 서비스는 좁은 callback과 기존 계약/모델만 받으며 전체 Pipeline/Store/Config를 전달하지 않는다.
  `pipeline.py`, 위 모듈·아키텍처/계획과 직접 관련 테스트만 다룬다. 실제 외부 AI/계정/화면·다른
  저장소/Rust/공개 checkout 및 사용자 저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 문맥/본문·callback·읽기 전용 설정·잠금/기록/effort scope·호출/파싱·
예외/후속 승인 순서를 대조한다. 변경 Python의 구문·전역 참조·150자/공백·diff와 공개 계약/
모델/RPC/의존 관계를 확인한다. 기존 프로젝트 판단/취소·대상 변경, 경로 승인/단독 승인/취소
case만 선택하고 충분하면 테스트를 추가하지 않는다. 전체 테스트·renderer·빌드/패키징은
실행하지 않고 필요한 확인 통과 후 종료한다.

## 진행과 결과

### 173~175단계: 프로젝트 판단 문맥

- `planning.control_decisions.ProjectDecisionContext`로 실행/통합 상태, 허용 행동/남은 복구 횟수,
  현재 경로 제안/승인·Task 범위/오류 근거와 대화/실제 도구 결과의 문맥 구성을 옮겼다.
  각 조회는 원래 callback을 사용하고 profile 구성 이후 원래 위치에서 실행한다.
- 선택한 프로젝트 case에서 실제 완료 결과가 후속 AI 문맥에 들어가고 계획/대화/시도/실행/취소로
  대상이 바뀌면 늦은 AI 행동이 적용되지 않는 것을 확인했다. 문맥 dict 전체도 snapshot AST와 같다.

### 176~178단계: 읽기 전용 판단 호출

- `ControlPlanningInvocation`에 기존 profile 구성·run 경로/대화 기록·effort scope·planning invocation
  API만 전달한다. 프로젝트/경로 승인별 읽기 전용/승인 거부 profile, prompt/log 경로와 session ID,
  기존 기록 시점과 호출/파싱 순서를 유지한다. Pipeline의 사전 제어 분기·chat 잠금/Run 조회와
  실제 SDK/정책/프로세스 수명은 그대로다.
- 실제 결과 후속 판단과 AI 판단 중 취소, 현재 경로 제안의 승인 및 단독 승인 case가 통과했다.
  읽기 전용 설정과 모든 호출 keyword·파싱/effort scope·예외의 순서는 AST로 대조했다.

### 179~181단계: 승인 판단 결과 기록

- `execution.scope_consent.ScopeConsentRecorder`가 기존 request-control 잠금 안에서 최신 요청의
  취소/phase·대상/제안을 확인하고 승인/거부/불명확 payload와 phase를 기록한다. 후속 승인 준비와
  사용자 대화 기록은 기존 잠금이 해제된 뒤 Pipeline이 처리한다. 실제 경로 적용 권한은 이동하지 않았다.
- 명시적 승인 후 계속과 승인만 하는 구분, 취소·시도/계약 변경 뒤 경로 적용 차단 case가 통과했다.
  거부/추가 질문과 기록 중 최신 요청/대상 변경 등의 모든 본문·저장/오류 순서는 AST로 확인했다.

### 182단계: 묶음 종료

- `tests/test_project_chat.py tests/test_chat_scope_approval.py`에서 아래 여섯 기존 함수를 `-k`로
  선택했다. 매개변수 사례를 포함해 **20 passed**(2.27초)였다. 실제 AI 대신 기존 fixture/mock을 사용했다.
  - `test_continue_executes_once_then_ai_reports_actual_result`
  - `test_late_ai_action_cannot_change_a_new_target`
  - `test_cancellation_while_ai_is_thinking_discards_its_command`
  - `test_current_proposal_approval_becomes_a_tool_after_the_consent_decision`
  - `test_direct_approval_requires_all_exact_paths_and_preserves_approval_only`
  - `test_cancelled_or_changed_approval_never_dispatches_scope_apply`
- 이동 전 snapshot AST로 문맥/전체 본문·명시적 callback·잠금·profile/기록/호출/파싱·후속 승인
  순서를 대조했다. 기존 Pipeline 서명/데코레이터와 범위 밖 메서드 423개가 그대로다. 좁은 invocation
  factory 하나만 추가했으며 새 모듈에 전체 Store/Config/Pipeline/Git이나 직접 Run 전이 권한을 주지 않았다.
- 변경 Python 3개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로가 유지된다.
  코어 163개 모듈 import 선언에 순환/기능 역참조가 없다. 기존 pipeline의 prompt/parser 네 함수
  import도 명시적 별칭으로 유지하고 원래 함수와 동일한 객체인지 확인했다.
- Pipeline은 **6,309 → 6,271줄(38줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 문서/주석 정리를 위해 통과한 동작 검사를 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 실제 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
