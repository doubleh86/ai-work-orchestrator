# 계획 확정 준비·Task 제외·사용자 확인 기록: 203~212단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 203~212단계를 수행한다. 시작 Pipeline은 6,183줄이다.
계획의 검토/변경과 사용자 확인 gate의 검증·기록을 분리한다. 기존 미커밋 변경·공개 API·저장/
CLI/RPC, 승인·잠금·SDK/정책 수명·최종 Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 203 | 계획 확정 준비의 명시적 계약 정의 | 완료 |
| 204 | revision/기본 구조·강도/실행 상태·Task 후보 검사/정렬 분리 | 완료 |
| 205 | 확정/레거시·보호된 기본 구조·재확인 요구 관련 확인 | 완료 |
| 206 | Task 제외의 검증/기록 계약 정의 | 완료 |
| 207 | 미시작 Task/의존성/확인 계획·revision/출력·저장 분리 | 완료 |
| 208 | 중복 선택·빈 계획/선행/사용자 확인 보호 확인 | 완료 |
| 209 | 사용자 확인 결과 기록 계약 정의 | 완료 |
| 210 | revision/확인/commit·중복/확정·기록 처리 분리 | 완료 |
| 211 | stale/중복·실패/통과·Task/통합 gate 보존 확인 | 완료 |
| 212 | 본문/순서·공개 계약·의존 관계·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `planning.plan_review`는 계획 확정 전 revision/기본 구조·강도/Task 상태와 후보 검증/정렬을
  처리하고 기존 승인 API 직전의 Plan을 반환한다. 실제 `approve_plan`·출력/확정 사건·저장은
  Pipeline에 유지한다. run 잠금과 허용 단계 조회도 이동하지 않는다.
- 같은 모듈의 제외 서비스는 기존 ID/상태·남는 작업/의존성·사용자 확인 계약을 검증한 뒤
  revision/출력/기록을 처리한다. 선택 정규화와 run 잠금·허용 단계 조회는 Pipeline에 남긴다.
- `execution.user_checks`는 최신 revision/확인/기준 commit·중복/확정 상태를 검사하고 확인 결과를
  기록한다. commit 실재 확인은 기존 읽기 전용 Git 명령 callback으로 같은 시점에 수행한다.
  입력/결과 enum 검증·run 잠금·확정 계획 요구와 이후 그룹 전이/저장은 Pipeline이 유지한다.
- 각 서비스는 좁은 callback과 기존 모델/검증 규칙만 받고 전체 Pipeline/Store/Config/Git을
  전달받지 않는다. `pipeline.py`, 위 모듈·아키텍처/계획과 직접 관련 테스트만 다룬다. 실제 외부
  AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자 저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 본문·callback·검사/오류/후보·승인/잠금·기록/후속 전이 순서를 대조한다.
변경 Python의 구문·전역 참조·150자/공백·diff 및 공개 계약/모델/RPC/의존 관계를 확인한다.
기존 계획 확정/제외와 강도/기본 구조 보호·사용자 확인 관련 case만 선택하고 충분하면 테스트를
추가하지 않는다. 전체 테스트·renderer·빌드/패키징은 실행하지 않고 필요한 확인 통과 후 종료한다.

## 진행과 결과

### 203~205단계: 계획 확정 준비

- `planning.plan_review.PlanConfirmation`으로 revision/기본 구조·저장 강도/실행된 Task 검사와
  후보 검증·레거시 revision/정렬·보호된 기본 구조 재연결을 옮겼다. 기존 실제 `approve_plan`과
  확정 계획 출력/사건·저장, run 잠금과 허용 단계 조회는 Pipeline에 남겼다.
- 계획 편집/확정·검증한 기본 구조 이후 기능 계획의 완료 Task 보존·강도 변경 후 명시적 리뷰/
  재확정 요구 case가 통과했다. 후보 구성과 전체 조건/오류·후속 승인 순서도 AST로 대조했다.

### 206~208단계: Task 제외

- `TaskPlanExclusion`이 원래 선택 순서의 ID/상태·남는 Task/의존성·사용자 확인 계약을 검증하고
  Task/revision·계획 출력/사건/저장을 처리한다. 중복 ID 정규화와 빈 선택 거부·잠금/단계는 Pipeline에 유지했다.
- 중복 선택의 단일 제외·계획 재검토 요구, 의존 선행 Task/전체 Task 제외 거부와 사용자 확인의
  참조 Task 보호 case가 통과했다. 실패 시 `PlanningError` 원인과 미저장 순서도 그대로다.

### 209~211단계: 사용자 확인 근거

- `execution.user_checks.UserCheckRecorder`가 revision/확인/기준 commit·중복/확정 상태를 확인한 뒤
  기존 Git 읽기 callback·결과/UTC 시각·readiness/사건 기록을 처리한다. 동일 결과 재전달만
  `False`를 반환하며 실패는 원래 예외로 전파한다. Pipeline은 입력/enum·잠금/확정 계획 요구와
  기록 여부에 따른 중복 반환, 이후 그룹 전이/저장을 유지한다.
- 기존 사용자 확인 case에서 stale/미완료 기준, 중복·실패/통과 기록과 Task/통합 gate가 유지됨을
  확인했다. Git argv/repo/비대화/시간 제한과 실제 호출 시점·전체 기록/예외 순서는 AST로도 대조했다.

### 212단계: 묶음 종료

- 다음 기존 case 여섯 개만 선택해 **6 passed**(17.21초)였다. 임시 Git 저장소와 기존 fixture/mock을
  사용했고 실제 외부 AI/계정/원격은 호출하지 않았다.
  - `tests/test_pipeline.py::PipelineTest::test_updates_and_confirms_task_plan_before_execution`
  - `tests/test_pipeline.py::PipelineTest::test_excludes_selected_tasks_from_planned_run`
  - `tests/test_pipeline.py::PipelineTest::test_excluding_tasks_preserves_dependency_and_nonempty_plan`
  - `tests/test_pipeline.py::PipelineTest::test_verified_bootstrap_generates_feature_plan_and_preserves_completed_task`
  - `tests/test_effort_policy_preview.py::EffortPolicyPreviewTest::test_mode_application_requires_explicit_reviewer_and_plan_reconfirmation`
  - `tests/test_user_checks.py::test_user_checks_gate_only_their_dependents_and_integration`
- snapshot AST로 전체 본문·callback·검사/오류/잠금/승인·기록/후속 전이 순서를 대조했다. 기존 모든
  Pipeline 서명/데코레이터와 범위 밖 메서드 424개가 그대로다. 새 facade 메서드는 없으며 새 모듈은
  전체 소유 객체나 직접 Run/계획 승인 권한을 받지 않는다.
- 변경 Python 3개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로가 유지된다.
  코어 167개 모듈 import 선언에 순환/기능 역참조가 없다. 기존 `pipeline.UserCheckResult`와
  `pipeline.validate_user_checks` import도 명시적 별칭으로 유지하고 원래 객체와 같은지 확인했다.
- Pipeline은 **6,183 → 6,100줄(83줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 별칭/문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
