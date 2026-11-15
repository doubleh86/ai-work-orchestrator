# 수동 작업공간·보류/재개·완료 근거: 163~172단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 163~172단계를 수행한다. 시작 Pipeline은 6,372줄이다.
수동 작업의 작업공간 검사·보류/재개·검증/완료 근거를 명시적 execution 서비스로 분리한다.
기존 미커밋 변경과 공개 API·저장/CLI/RPC 계약, 승인·잠금·최종 Run 전이 소유권을 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 163 | 수동 작업공간 검사 계약 정의 | 완료 |
| 164 | 경로/branch 소유권·Git 등록·청결/HEAD 확인 분리 | 완료 |
| 165 | stale/dirty 작업공간·미커밋 보존 경계 확인 | 완료 |
| 166 | 수동 보류/재개 계약 정의 | 완료 |
| 167 | 상태/실행 점유·기준 commit·의존성·기록 처리 분리 | 완료 |
| 168 | 보류 후 공유 점유 전달·의존 작업 보호·재개 확인 | 완료 |
| 169 | 수동 완료의 검증/근거 기록 계약 정의 | 완료 |
| 170 | 검증 실패 보존·검증 HEAD·완료 commit/result 기록 분리 | 완료 |
| 171 | 검증 전 완료 차단·기존 commit 기록·후속 작업 보호 확인 | 완료 |
| 172 | 본문/순서·공개 계약·의존 관계·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `execution.manual_tasks`에 좁은 명시적 계약을 둔다. 기존 Git adapter와 필요한 검사/기록/
  다음 수동 작업 준비 callback만 전달하고 전체 Pipeline/Store/Config를 넘기지 않는다.
- 작업공간 검사는 기존 실행 준비 API 뒤 공유/분리 경로·branch·Git 등록·청결/HEAD를 확인한다.
  잘못된 소유권·미커밋 변경은 기존 오류로 거부하고 실제 사용자 작업공간을 정리하지 않는다.
- 보류/재개는 기존 run/chat 잠금·실행 단계 조회가 끝난 안쪽 본문만 옮긴다. 상태/실행 점유·
  기준 commit·작업공간 소유 작업을 확인하고 기존 의존성/수동 작업 준비 API와 저장 순서를 유지한다.
- 완료는 기존 리뷰 뒤 검증/실패 Task·완료 commit/result/event 기록만 옮긴다. 리뷰·실패 Run 단계,
  다음 작업 활성화 실패 처리와 최종 그룹 전이는 Pipeline에 남긴다.
- `pipeline.py`, 위 실행 모듈·아키텍처/계획과 직접 관련 테스트만 다룬다. 실제 외부 원격/AI/계정/
  화면·다른 저장소/Rust/공개 checkout 및 사용자 저장소의 commit/merge/push/deploy는 범위에 포함하지 않는다.

## 검증

이동 전 snapshot AST로 전체 본문·callback·잠금/조건·검증/저장/오류·후속 전이 순서를 대조한다.
변경 Python의 구문·전역 참조·150자/공백·diff 및 공개 API/모델/RPC/의존 방향을 확인한다.
기존 수동 작업공간 실패·보류/재개·완료/실패 관련 case만 선택한다. 기존 case가 충분하면
새 테스트나 기대값 변경은 하지 않는다. 전체 테스트·renderer·빌드/패키징을 실행하지 않고
필요한 정적 검사와 관련 검사 통과 후 종료한다.

## 진행과 결과

### 163~165단계: 작업공간 확인

- `execution.manual_tasks.ManualWorkspaceInspector`로 기존 실행 준비 뒤 공유/분리 경로·branch
  소유권과 Git 등록·청결/HEAD 확인을 옮겼다. 제한 시간/비대화 Git 호출·문구/예외가 동일하다.
  기존 `_clean_manual_workspace` 서명은 유지한다.
- 선택한 기존 case에서 잘못된 검증 revision/HEAD·미커밋 변경 차단과 파일 보존을 확인했다.
  분리 경로 소유권·Git 등록을 포함한 전체 검사 본문/순서는 snapshot AST로 대조했다.

### 166~168단계: 보류와 재개

- `ManualTaskDeferral`이 기존 단계 조회 이후의 Task/실행 점유·다른 작업의 공유 작업공간 점유와
  기준 commit을 검사한다. 보류 시 기존 수동 작업 준비, 재개 시 기존 의존성 반영 API를 호출하고
  상태/시작 commit·이벤트/저장을 같은 순서로 처리한다. run/chat 잠금과 허용 단계 조회는 Pipeline에 유지했다.
- 기존 보류 후 공유 작업공간 전달·선행 작업 의존성 차단·재개와 dirty/이미 변경된 commit의
  보류 거부 case가 통과했다. 중복 요청·활성 실행 거부 등의 모든 분기는 AST로도 대조했다.

### 169~171단계: 완료 근거

- `ManualTaskCompletion`이 리뷰 이후 Task 검증·명시적 수동 검증의 청결/HEAD 재확인, 실패 Task
  기록과 완료 commit/result/action/event를 처리한다. 기존 worktree 값을 전달해 리뷰 전후 경로
  의미를 유지한다. 리뷰와 실패 Run 단계·다음 작업 활성화/실패·최종 그룹 전이/저장은 Pipeline에 남겼다.
- 검증 전 완료 기록 차단, 기존 commit에 수동 검증 메모 기록·다음 의존 작업 해제, 검증 실패의
  미완료/실패 근거 보존과 재시도 case가 통과했다. 기존 callback 타입과 keyword 의미를 유지했다.

### 172단계: 묶음 종료

- `tests/test_pipeline.py`에서 아래 다섯 case만 `-k`로 선택해 **5 passed, 2 subtests passed**(23.27초)였다.
  기존 임시 저장소·fixture/mock을 사용했고 실제 외부 원격/AI/계정은 사용하지 않았다.
  - `test_manual_task_verification_runs_before_task_completion`
  - `test_manual_verification_records_existing_commit_and_releases_dependent_task`
  - `test_manual_verification_rejects_stale_or_dirty_workspace_and_keeps_failed_checks`
  - `test_deferred_manual_task_hands_off_shared_workspace_but_keeps_dependencies_blocked`
  - `test_manual_deferral_preserves_dirty_or_committed_work`
- snapshot AST로 이동 본문 전체·callback 연결·잠금/승인·검사/기록/오류·후속 Run 전이 순서를
  대조했다. 기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 422개가 그대로다. 새 facade 메서드는 없다.
  새 모듈은 전체 소유 객체를 받지 않고 Run 단계 변경 API를 직접 호출하지 않는다.
- 변경 Python 2개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명과 모델 80개·호환 오류/모델/기획 import·RPC 122개 경로가 유지된다.
  코어 161개 모듈 import 선언에 순환/기능 역참조가 없다. 새 실행 모듈은 134줄이다.
- Pipeline은 **6,372 → 6,309줄(63줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사를 문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 실제 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
