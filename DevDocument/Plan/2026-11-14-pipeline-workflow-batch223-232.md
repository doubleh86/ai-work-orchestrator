# 방향 수정 접수·결과 제안 준비·기획 요청 기록: 223~232단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 223~232단계를 수행한다. 시작 Pipeline은 6,022줄이다.
기획 제어 요청의 접수/입력 구성·소유 기록을 분리한다. 기존 미커밋 변경·공개 API·저장/CLI/
RPC, 승인·기존 잠금·SDK/정책 수명·기획 중단/최종 Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 223 | 방향 수정 접수 계약 정의 | 완료 |
| 224 | 재전달/남은 Task·기존 preview/현재 작업·대화/대기 기록 분리 | 완료 |
| 225 | 실행 중 Task 보존·중복/새 요청의 preview 무효화 확인 | 완료 |
| 226 | 결과 수정 제안 입력 계약 정의 | 완료 |
| 227 | 읽기 전용 Agent/근거·prompt/산출물/대화 ID 준비 분리 | 완료 |
| 228 | 읽기 전용·지원 근거/제안/세션 정리 보존 확인 | 완료 |
| 229 | 기획 요청 소유 기록 계약 정의 | 완료 |
| 230 | 시작/재전달·대화 재분류·소유 조회/완료 기록 분리 | 완료 |
| 231 | 보관/중단·대상 유지·시작/완료 재전달 경계 확인 | 완료 |
| 232 | 본문/순서·공개 계약·의존 관계·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `planning.direction_changes`는 chat 잠금 안에서 동일 요청/남은 Task·실행 중 작업과 기존 preview를
  확인하고 방향 요청·대화/후속 지시를 기록한다. ID/길이 검증·chat 잠금/Run 조회는 Pipeline에 남긴다.
- `planning.result_revisions`에 제안 입력 준비를 추가한다. 기존 Agent 선택/읽기 전용·근거와
  prompt/산출물 경로·대화 ID를 명시적 DTO로 반환한다. 실제 provider 호출·timeout/usage/model
  전달과 SDK `finally` 정리·응답 검증은 Pipeline이 유지한다. 전체 Config/Store/SDK를 넘기지 않는다.
- `planning.request_records`는 요청 시작/재전달·보관 대화/기획 적용 재분류, 소유 조회와 완료 기록을
  처리한다. ID/kind/완료 phase 검증과 요청 잠금·실행 프로세스 종료 확인/기획 중단·Run 단계/
  SDK/대화 정리는 Pipeline에 그대로 둔다. 새로운 승인이나 잠금을 만들지 않는다.
- `pipeline.py`, 위 기획 모듈·아키텍처/계획과 직접 관련 테스트만 다룬다. 실제 외부 AI/계정/화면·
  다른 저장소/Rust/공개 checkout 및 사용자 저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 전체 본문·callback·입력/기록/오류·잠금/실제 호출/SDK 정리·기획 중단과
Run 전이 순서를 대조한다. 변경 Python의 구문·전역 참조·150자/공백·diff 및 공개 계약/모델/
RPC/의존 관계를 확인한다. 기존 방향 수정/결과 제안·기획 요청 중단/재전달 관련 case만 선택하고
충분하면 테스트를 추가하지 않는다. 전체 테스트·renderer·빌드/패키징은 실행하지 않고 필요한 확인 후 종료한다.

## 진행과 결과

### 223~225단계: 방향 수정 접수

- `planning.direction_changes.DirectionChangeIntake`로 재전달/남은 Task·현재 진행 작업과 이전
  preview 확인, 요청/UTC 시각·사용자 대화/후속 지시/사건 기록을 옮겼다. ID/길이·chat 잠금과
  Run 조회는 Pipeline이 유지한다. 작업을 실행하거나 최종 단계를 바꾸지 않는다.
- 실행 중 Task와 중복 요청 보존, 새 방향 요청이 이전 preview를 무효화하는 case가 통과했다.
  상태/기록·callback 순서 전체도 snapshot AST로 대조했다.

### 226~228단계: 결과 제안 준비

- 기존 `planning.result_revisions`에 `ResultRevisionProposalPreparation`과 명시적 준비 DTO를
  추가했다. 기존 Agent/읽기 전용 제한·근거, prompt/파일/대화 ID를 같은 순서로 구성한다.
  Pipeline의 실제 provider argv/timeout/model/usage 전달, SDK `finally` 정리와 응답 검증은 그대로다.
- 제안 cache/수용 뒤 실행 대기, 지원되지 않은 근거와 stale 수용 거부 case가 통과했다. 제안 문구
  전체와 DTO 값·실제 호출/SDK 정리/파싱 순서가 이동 전과 같음을 AST로 확인했다.

### 229~231단계: 기획 요청 기록

- `planning.request_records.PlanningRequestRecords`로 시작/같은 요청·보관 대화/명시적 적용의
  재분류, 소유 조회와 최종 operation 기록을 옮겼다. Pipeline의 ID/kind/phase 검사·요청 잠금과
  종료 확인·기획 중단·Run 단계/대화/SDK 정리를 유지했다.
- 실행/검증/Push 상태의 답변 중단이 작업을 바꾸지 않는 case, 계획 단계의 답변 중단이 기획 실패가
  되지 않는 case, 보관 대화 sidecar와 적용 요청의 중단 전 재분류 case가 통과했다. 시작/완료
  재전달·소유 오류를 포함한 전체 본문/조건/기록 순서도 AST로 대조했다.

### 232단계: 묶음 종료

- 다음 기존 함수 여덟 개만 선택했다. 상태 매개변수 포함 **10 passed**(3.38초)였다. 기존 임시
  저장소/fixture/mock을 사용했고 실제 외부 AI/계정/원격은 호출하지 않았다.
  - `tests/test_pipeline.py::PipelineTest::test_direction_change_is_idempotent_and_preserves_the_running_task`
  - `tests/test_pipeline.py::PipelineTest::test_new_direction_change_invalidates_previous_preview`
  - `tests/test_pipeline.py::PipelineTest::test_result_revision_ai_proposal_is_cached_and_retry_instruction_waits_for_confirmation`
  - `tests/test_pipeline.py::PipelineTest::test_result_revision_ai_proposal_rejects_unsupported_evidence_and_stale_acceptance`
  - `tests/test_chat_control_review.py::test_reply_interruption_keeps_original_run_and_tasks`
  - `tests/test_chat_control_review.py::test_planned_reply_interruption_is_not_a_planning_failure`
  - `tests/test_chat_control_review.py::test_archived_reply_interruption_writes_only_chat_sidecar`
  - `tests/test_chat_control_review.py::test_apply_request_is_reclassified_before_interruption`
- snapshot AST로 전체 본문·callback·입력/조회/저장/오류·잠금/기획 중단·실제 호출/SDK 정리 순서를
  대조했다. 기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 424개, 기존 결과 수정 선언이
  그대로다. 좁은 요청 기록 factory 하나만 추가했고 새 모듈에 전체 소유 객체/Run/SDK 권한을 주지 않았다.
- 변경 Python 4개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 이동 후 길이가
  초과한 호출 인자 한 줄은 줄바꿈으로 보정했다. 공개 Pipeline 112개·Store 91개·응용 API 121개
  서명, 모델 80개·기존 오류/모델/기획 import·RPC 122개 경로가 유지된다. 코어 170개 모듈 import
  선언에 순환/기능 역참조가 없다. `pipeline.DirectionChangeRequest`도 같은 모델 객체의 별칭으로 보존했다.
- Pipeline은 **6,022 → 5,970줄(52줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서/형식 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
