# 공유 Main 검사·Push 근거·검증 수정 작업공간: 143~152단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 143~152단계를 진행한다. 시작 Pipeline은 6,532줄이다.
기존 미커밋 변경과 142단계까지의 동작·공개 API·저장/RPC/CLI 계약을 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 143 | 공유 Main 반영 전 검사 계약 정의 | 완료 |
| 144 | Task/검증/작업 branch/Main 근거 검사 분리 | 완료 |
| 145 | 공유 로컬/원격·검토 승인 관련 확인 | 완료 |
| 146 | Push 준비/원격 확인 기록의 명시적 계약 정의 | 완료 |
| 147 | 공유·분리 경로 사전 검사와 remote receipt 기록 분리 | 완료 |
| 148 | 변경 branch/원격 불일치·정상 receipt 경계 확인 | 완료 |
| 149 | 검증 실패 수정 후보의 Git 수명 계약 정의 | 완료 |
| 150 | 작업공간 준비/범위 검사/commit·근거 보존/정리 분리 | 완료 |
| 151 | 수정 성공/실패·후보/완료 작업 보존 경계 확인 | 완료 |
| 152 | 본문/순서·공개 계약·의존 방향·diff 및 기록 확인 | 완료 |

## 책임과 영향 파일

- `integration.main_preflight`에 공유 Main 반영 전 검사도 둔다. 기존 Git adapter와 repo 경로,
  공유 경계/invalidation callback만 받는다. remote 유무는 기존 호출 시점의 명시적 값으로 전달한다.
  Pipeline의 승인·project/run 잠금·claim/step과 실제 반영/Run 전이는 그대로 둔다.
- `integration.publishing`은 Push 사전 검사와 원격 HEAD/중복 receipt·operation 근거를 처리한다.
  Git adapter, 원격 값 조회·기록/작업공간 준비 callback만 받는다. 실제 Push, 승인·잠금·최종 전이는
  기존 Pipeline에 유지하며 remote 조회와 저장 순서를 바꾸지 않는다.
- `integration.verification_repair`는 기존 수정 runner의 제안 API와 좁은 경로/범위 검사·기록 API로
  수정 후보 작업공간 준비·commit/통합 branch 갱신·근거 보존·finally 정리를 수행한다. 실행 Agent 선택,
  SDK/정책/취소 수명과 최종 Run 전이는 기존 소유자에 남긴다. 전체 Pipeline/Store/Config를 전달하지 않는다.
- 변경 범위는 `pipeline.py`, 위 integration 모듈, 아키텍처/계획과 직접 관련 테스트다. 새 동작·승인이나
  저장 필드를 추가하지 않는다. 실제 사용자 저장소의 commit/merge/push/deploy, Rust/공개 checkout은 다루지 않는다.

## 검증

이동 전 snapshot과 AST로 본문·명시적 callback·승인/잠금/기록·오류/정리 순서를 대조한다.
변경 Python의 구문·전역 참조·150자/공백과 diff, 공개 API/모델/RPC/의존 방향을 정적으로 확인한다.
공유 Main 로컬/원격 경로와 Push 불일치·검증 수정의 기존 case만 선택한다. 기존 case가 충분하면
새 테스트를 만들지 않는다. 임시 로컬 bare Git 검사는 이전 묶음에서 확인된 sandbox 제한을 고려해
도구의 승인 절차로 실행할 수 있다. 실제 원격/AI/계정/화면은 사용하지 않는다.
전체 테스트·renderer·빌드/패키징은 실행하지 않고 필요한 검사 통과 후 종료한다.

## 진행과 결과

### 143~145단계: 공유 Main 사전 검사

- `SharedMainApplyPreflight`가 기존 원격 유무에 따른 단계·모든 Task 완료·검증/Push 근거와
  작업 branch/Main HEAD를 검사하고 현재 Main HEAD를 반환한다. 검증 무효화는 기존 callback을
  사용한다. Pipeline의 claim/step/실제 반영·오류 처리와 기존 분리 작업 사전 검사 본문은 그대로다.
- 아래 Main/Push 관련 선택 테스트에서 로컬 Main 반영과 원격 설정 경로의 반영/정리를 확인했다.
  검토 ID를 전달하는 claim/적용 경로와 검증 근거 누락·변경 HEAD의 전체 조건은 snapshot AST로 대조했다.

### 146~148단계: Push 준비와 원격 근거

- `integration.publishing.PushPreflight`로 공유/분리 작업의 사전 조건을 옮겼다. `PushConfirmation`은
  operation 저장 뒤 remote 조회, HEAD 일치와 receipt 중복 검사·결과 commit 기록을 같은 순서로 처리한다.
  실제 Push·승인/project/run 잠금·단계 기록·실패 처리·Run 전이는 Pipeline에 유지했다.
- 기존 `pipeline.PushReceipt` import는 명시적 호환 별칭으로 유지했다. 공유 branch와 Main의 정상
  receipt, 원래 Main branch 불일치 차단·원격 commit 불일치 시 receipt 미생성 및 분리 Push를 확인했다.
- `tests/test_pipeline.py`에서 아래 다섯 case를 `-k`로 선택해 **5 passed**(14.54초)였다.
  이전 묶음에서 확인된 sandbox의 임시 Git 원격 준비 제한 때문에 도구 승인 절차로 실행했다.
  모든 Git 원격은 저장소 `.tmp`의 임시 로컬 bare 저장소이고 실제 외부 원격을 호출하지 않았다.
  - `test_shared_run_without_remote_applies_locally_and_can_be_archived`
  - `test_shared_work_branch_and_main_are_pushed_before_cleanup`
  - `test_shared_work_branch_push_rejects_original_branch_mismatch`
  - `test_shared_work_branch_push_fails_when_remote_commit_does_not_match`
  - `test_legacy_merged_run_can_verify_and_push`

### 149~151단계: 검증 수정 후보의 작업공간

- `integration.verification_repair.VerificationRepairWorkspace`에 기존 Git adapter·경로/청결/범위
  검사·기록 API와 `VerificationRepairRunner.propose`를 전달한다. 분리 후보 준비/공유 경계 확인,
  범위 검사 뒤 commit·통합 branch 갱신, 원래 Main/Task 근거 보존과 finally 정리가 동일하다.
  Agent 선택과 실제 provider/SDK/취소 수명은 기존 소유자에 유지했다.
- `pytest -q tests/execution/test_verification_repair.py`는 **7 passed**(0.66초)였다. 기존 fixture/mock으로
  공유·분리 성공, provider 실패·중단·범위 거부·새 commit 없음의 미반영/정리와 Agent 없음의 사전 거부를 확인했다.
  실제 AI나 계정을 사용하지 않았고 완료 Task 계약과 취소 요청 ID 보존도 기존 검사를 통과했다.

### 152단계: 묶음 종료

- snapshot AST로 이동한 모든 조건/기록/예외/finally 본문, callback 연결과 Root의 승인/잠금/실제
  Push·Main 반영·최종 단계/오류 순서를 대조했다. 범위 밖 Pipeline 메서드 420개와 기존 모든 서명/
  데코레이터가 그대로다. 새 private Push 사전 검사 factory 하나만 추가했다.
- 변경 Python 4개 파일의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline
  112개·Store 91개·응용 API 121개 서명과 모델 80개·호환 오류/모델/기획 import·RPC 122개 경로를
  유지한다. 코어 159개 모듈 import 선언에 순환/기능 역참조가 없고 전체 소유 객체를 전달하지 않는다.
- 관련 테스트 합계는 **12개 통과**다. 새 테스트나 기존 테스트/기대값 변경은 없다. 동작 검사 통과 뒤
  문서/docstring 정리는 해당 정적 검사만 수행했고 통과한 테스트를 반복하지 않았다.
- Pipeline은 **6,532 → 6,445줄(87줄 감소)**이다. Main 사전 검사 모듈은 94줄이며 새 Push/수정
  작업공간 모듈은 각각 78/72줄이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 실제 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
