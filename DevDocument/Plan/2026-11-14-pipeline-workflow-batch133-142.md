# Main 작업 기록·반영 전 검증·충돌 후속 검증: 133~142단계

## 목표와 승인 범위

다음 10단계 요청에 따라 133~142단계를 수행한다. 시작 Pipeline은 6,636줄이다.
앞선 완료 기록과 기존 미커밋 변경을 보존하고 이번 묶음의 구현·국소 확인·기록 후 종료한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 133 | Main 요청 claim/재생/실패 기록의 명시적 계약 정의 | 완료 |
| 134 | 요청 ID/대상 digest·검토 ID·중복/실패 처리 분리 | 완료 |
| 135 | 성공 요청 재생·대상/상태 불일치·중단 복구 관련 확인 | 완료 |
| 136 | 분리 작업공간의 Main 반영 전 검증 계약 정의 | 완료 |
| 137 | Task/Main/통합 branch 근거와 invalidation 검사 분리 | 완료 |
| 138 | Main/Task 변경 차단·검증한 commit 반영 관련 확인 | 완료 |
| 139 | 충돌 해결 후 정리/검증과 후속 기록 계약 정의 | 완료 |
| 140 | 후보 정리·새 검증 attempt 연결/실패·성공 기록 분리 | 완료 |
| 141 | 적용 후 검증·실패/재전달·기록 보존 경계 확인 | 완료 |
| 142 | 이동 순서·공개 계약/의존 관계·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 범위

- Main 작업 기록은 좁은 operation 조회/claim/저장 API로 UUID/대상 digest·review ID 일치·완료
  재생·실패를 처리한다. 실제 Git 실행·승인·잠금·Run 단계 결정은 Pipeline에 유지한다.
- 분리 작업공간의 Main 반영 전 검증은 기존 Git adapter와 저장소 경로·branch/준비/invalidation
  callback으로 현재 Task/Main/통합 commit을 확인한다. Pipeline의 승인/project/run 잠금·공유
  작업공간 분기와 operation claim·실제 merge step/반영을 유지한다. invalidation은 기존 owner API만 호출한다.
- 충돌 해결 후속 처리는 기존 후보 적용이 끝나 run 잠금이 해제된 뒤 정리·전체 검증·operation/
  recovery 연결을 조합한다. 기존 Git adapter·기록 잠금 factory와 verify callback을 사용하고
  독립된 잠금이나 Run 전이를 만들지 않는다. 실제 검증·최종 단계 전이와 최초 적용 승인은 Pipeline에 남긴다.
- `pipeline.py`, 관련 integration 하위 모듈·아키텍처와 직접 관련 테스트만 다룬다. 전체 Pipeline/
  Store/Config를 전달하지 않는다. 기존 public/private signature·문구/예외·저장/CLI/RPC/MCP와
  승인/Git 부작용 범위를 유지한다. 실제 사용자 Main 반영·원격 전송·배포는 실행하지 않는다.

## 검증

이동 전 snapshot과 AST로 본문·callback·기록/오류/잠금·전이 순서를 대조한다. 변경 Python의
구문·전역 참조·줄 길이/공백/diff 및 관련 공개 계약/의존 관계를 확인한다. Main 요청 재생·반영
전 검증/차단과 충돌 적용 후속 검증의 기존 case만 선택하고 충분하면 테스트를 추가하지 않는다.
전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
commit/push/deploy는 포함하지 않으며 통과한 검사는 후속 변경의 영향을 받지 않으면 반복하지 않는다.

## 진행과 결과

### 133~135단계: Main 요청의 기록

- `integration.operations.GitOperationRecorder`에 operation 조회/claim/저장 callback을 전달한다.
  요청 UUID, 대상 digest와 review ID, 완료 요청 재생, 실패/다른 대상 요청 거부와 오류 기록을
  같은 순서로 처리한다. 기존 세 private 진입점·서명을 유지하고 실제 Git/Run 전이를 옮기지 않았다.
- 기존 Main push 재시도의 성공 receipt 재생·증명 없는 Main 적용 거부·중단 뒤 점검 요구 case로
  관련 경계를 확인했다. sandbox에서는 임시 로컬 bare 원격 준비의 `git push`가 실패해 해당 경로의
  결과를 얻지 못했다. 같은 선택 검사를 sandbox 밖에서 실행해 통과했다. 실제 원격은 사용하지 않았다.

### 136~138단계: Main 반영 전 검사

- `integration.main_preflight.IsolatedMainApplyPreflight`에 Git adapter/저장소 경로와 branch 이름,
  Main 준비/invalidation callback을 전달한다. Task 완료·검증 근거와 변경된 Task/Main·통합 commit을
  같은 순서로 검사한다. 승인/project/run 잠금·검토 ID·공유 경로와 claim/step/실제 반영은 Pipeline에 유지했다.
- 기존 bounded Git/승인된 commit 반영·완료 재생과 Main 변경 뒤 재검증 요구 case가 통과했다.
  Task 변경·검증 근거 누락·통합 branch 소실 등 분리한 전체 조건은 이동 전후 AST로 대조했다.

### 139~141단계: 충돌 적용 뒤 후속 검증

- `integration.conflict_verification.ConflictResolutionVerification`에 Git adapter·조회/저장/operation
  기록과 기존 run 잠금 factory·verify callback을 전달한다. 후보 정리 뒤 새 검증 attempt 연결,
  실패 기록/원래 예외 재발생과 성공 receipt/commit 기록을 옮겼다. 최초 승인/후보 적용 잠금을
  먼저 해제하며 실제 검증·최종 Run 전이는 기존 Pipeline API가 수행한다.
- 기존 충돌 후보 생성/재전달·명시적 승인·적용 뒤 검증·recovery attempt 연결 case가 통과했다.
  실패와 선택적 Git 정리 오류 경로는 이동 전후 본문/잠금·저장·오류 순서가 같은지 AST로 확인했다.

### 142단계: 묶음 종료

- 세 작업 흐름 전체 본문과 callback 연결·대상/잠금·기록·예외 순서를 snapshot AST와 대조했다.
  기존 Pipeline 서명/데코레이터 전부와 범위 밖 메서드 418개가 그대로다. 새 private factory 하나만 추가했다.
- 변경 Python 4개의 구문·전역 참조·변경 줄 길이/공백과 diff를 확인했다. 공개 Pipeline 112개·Store
  91개·응용 API 121개 서명, 모델 80개·기존 오류/모델/기획 import·RPC 122개 경로가 유지된다.
  코어 157개 모듈 import 선언에 순환/기능 역참조가 없고 새 모듈은 전체 소유 객체를 받지 않는다.
- `tests/test_pipeline.py`에서 아래 여섯 case만 선택했다. 최종 결과는 **6 passed, 3 subtests passed**
  (29.79초)다. 새 테스트나 기존 테스트/기대값 변경은 없다. 정적 검사 뒤에는 통과한 동작 검사를 반복하지 않았다.
  - `test_shared_main_push_retry_sends_only_applied_commit_and_replays_receipt`
  - `test_shared_main_push_retry_rejects_unproven_main_apply_phase`
  - `test_interrupted_main_apply_requires_inspection_after_process_restart`
  - `test_legacy_main_apply_bounds_every_git_call`
  - `test_merge_requires_reverification_when_main_changes_after_verification`
  - `test_shared_main_conflict_can_generate_review_and_apply_isolated_candidate`
- Pipeline은 **6,636 → 6,532줄(104줄 감소)**이다. 기존 미커밋 변경을 보존했으며 다음 단계는 시작하지 않았다.
  전체 테스트/renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout과 commit/push/deploy는
  이번 분리 범위의 확인에 필요하지 않아 실행하지 않았다.
