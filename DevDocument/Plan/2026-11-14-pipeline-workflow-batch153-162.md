# 계획 내용·대화 적용 기록·기능 계획 구성: 153~162단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 153~162단계를 수행한다. 시작 Pipeline은 6,445줄이다.
기획 결과를 반영하는 세 흐름의 데이터 처리와 기록 책임을 분리한다. 기존 미커밋 변경·공개
API·저장/CLI/RPC 계약을 보존하고 승인·잠금·SDK/정책 수명·최종 Run 전이의 소유자는 바꾸지 않는다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 153 | 계획 내용 적용의 명시적 계약 정의 | 완료 |
| 154 | 문서 snapshot·모델/리뷰 근거 보존·기술 결정/기본 구조 구성 분리 | 완료 |
| 155 | 기존/신규 프로젝트의 계획 적용과 프로필 보존 확인 | 완료 |
| 156 | 대화 계획 적용/요청 기록 계약 정의 | 완료 |
| 157 | 문맥/확정 구성 검사·실제 계획 적용·성공 지표 기록 분리 | 완료 |
| 158 | 요청 snapshot·성공/실패·기술 결정 보존 경계 확인 | 완료 |
| 159 | 검증한 기본 구조 이후 기능 계획 구성 계약 정의 | 완료 |
| 160 | 기능 Task/출력 계획·대화 기록 구성 분리 | 완료 |
| 161 | 기준선 보존·성공·실패 후 재시도 확인 | 완료 |
| 162 | 본문/순서·공개 계약·의존 방향·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `planning.plan_application`에 세 명시적 서비스 계약을 둔다. 하나의 계획 적용 책임 안에서
  전체 객체를 넘기지 않고 각 흐름이 필요한 callback만 받는다. 기존 계약/검증·callback 타입을 재사용한다.
- 계획 내용 적용은 문서 snapshot·기존 Task 실행 프로필 출처/리뷰 근거 보존·기술 결정/기본 구조
  구성을 처리한다. Pipeline의 planning profile 고정·revision/출력·최종 단계/저장을 유지한다.
- 대화 적용은 저장된 문맥/확정 기술 구성을 검증해 기존 계획 적용 API를 호출하고 요청의 성공
  상태/시각/추가·수정·유지 지표를 기록한다. Pipeline이 최초 단계/사전 저장과 실패 기록·예외를 유지한다.
- 기능 계획 구성은 검증한 기준선에 기능 Task를 붙이고 계획 파일/대화 응답을 구성한다. SDK 세션
  종료·실제 AI 계획 생성·성공/실패 Run 전이·복구/재시도 기록은 Pipeline에 유지한다.
- `pipeline.py`, 위 기획 모듈·아키텍처/계획과 직접 관련 테스트만 다룬다. 실제 사용자 저장소의
  Git 작업·외부 원격/AI/계정/화면·Rust·공개 checkout과 commit/push/deploy는 범위에 포함하지 않는다.

## 검증

이동 전 snapshot AST로 본문·callback·문맥/조건·대상·저장/예외/전이 순서를 대조한다.
변경 Python의 구문·전역 참조·150자/공백·diff 및 공개 API/모델/RPC/의존 방향을 확인한다.
계획 교체의 프로필 보존, 대화 요청 적용/기술 결정 보호, 기능 계획 성공/실패의 기존 case만
선택한다. 기존 case가 충분하면 테스트를 추가하거나 변경하지 않는다. 전체 테스트·renderer·
빌드/패키징은 실행하지 않으며 필요한 검사 통과 후 종료한다.

## 진행과 결과

### 153~155단계: 계획 내용 적용

- `planning.plan_application.PlanContentApplication`으로 문서 snapshot·기존 Task의 프로필 출처/
  추론 강도/리뷰 정책 근거 보존·기술 결정/기본 구조 구성을 옮겼다. 설정은 원래 읽던 시점에
  좁은 callback으로 조회한다. 계획 profile 고정·revision/파일·대화 기록·최종 단계/저장은 Pipeline에 남겼다.
- 기존 수동 NVIDIA 프로필의 미리보기/재기획 보존과 신규 프로젝트의 질문·기술 선택·단일 기본 구조
  계획 전환 case를 확인했다. 모든 보존 조건/순서와 문서 snapshot callback은 AST로 대조했다.

### 156~158단계: 대화 계획 적용 기록

- `ConversationPlanApplication`은 snapshot 문서/문맥·source index 조회와 확정한 기술 구성 보호,
  기존 계획 적용 callback·성공 요청 시각/추가·수정·유지 지표 저장을 처리한다. 최초 draft/단계·
  사전 저장, 실패 요청/Run 기록과 예외는 Pipeline이 동일하게 처리한다.
- revision 안전성/중복 적용 방지, 실패 시 Task/receipt 보존, 확정 구성 변경 거부와 같은 요청의
  재시도 case가 통과했다. 성공 시각은 기존 `utc_now`를 그대로 사용한다.

### 159~161단계: 기본 구조 이후 기능 계획 구성

- `FeaturePlanApplication`이 기존 검증 기준선으로 기능 Task·계획 출력과 안내 대화를 구성한다.
  기존 `feature_plan_tasks`와 Task 변경용 builder/대화 callback 타입을 재사용했다. Pipeline의
  SDK 대화 종료·실제 계획 생성·성공 전이와 실패 시 기준선/재시도 보존은 그대로다.
- 검증한 기본 구조/완료 Task를 보존하는 성공 case와 기능 계획 생성 실패 후 검증 상태를 유지하는
  case가 통과했다. 기존 `pipeline.feature_plan_tasks` import는 같은 함수의 명시적 호환 별칭으로 유지했다.

### 162단계: 묶음 종료

- `tests/test_pipeline.py`에서 아래 일곱 case만 `-k`로 선택했다. 결과는 **7 passed, 4 subtests passed**
  (23.70초)다. 임시 저장소/기존 fixture와 mock을 사용했고 실제 AI/외부 원격은 호출하지 않았다.
  - `test_planning_preview_and_cached_replanning_preserve_manual_nvidia_execution`
  - `test_planning_apply_request_is_revision_safe_and_idempotent`
  - `test_planning_apply_failure_preserves_tasks_and_receipt`
  - `test_greenfield_bootstrap_plan_failure_preserves_the_confirmed_choice_for_retry`
  - `test_greenfield_plan_accepts_only_questions_then_one_bootstrap_task`
  - `test_verified_bootstrap_generates_feature_plan_and_preserves_completed_task`
  - `test_feature_plan_failure_preserves_verified_bootstrap_for_retry`
- snapshot AST로 이동한 전체 본문과 callback·저장/예외/Run 단계·SDK 순서를 대조했다. 기존 모든
  Pipeline 서명/데코레이터와 범위 밖 메서드 422개가 그대로이며 새 facade 메서드는 추가하지 않았다.
  새 모듈이 전체 Store/Config/Pipeline/Git이나 직접 Run 단계 변경 권한을 받지 않는 것도 확인했다.
- 변경 Python 2개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명, 모델 80개·호환 오류/모델/기획 import·RPC 122개 경로가 유지된다.
  코어 160개 모듈 import 선언에 순환/기능 역참조가 없다. 기획 기본 import의 재노출 구성은 바꾸지 않았다.
- Pipeline은 **6,445 → 6,372줄(73줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 테스트는 문서/docstring 정리를 이유로 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 실제 사용자
  저장소의 commit/merge/push/deploy는 이번 분리 확인에 필요하지 않아 실행하지 않았다.
