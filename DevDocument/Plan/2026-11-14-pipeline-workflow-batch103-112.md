# 경로 승인 반영·보관·삭제 수명: 103~112단계

**상태: 103~112단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

다음 10단계 요청에 따라 103~112단계를 수행한다. 시작 Pipeline은 7,080줄이다.
앞선 완료 기록과 기존 미커밋 변경을 보존하고 이번 묶음의 구현·국소 확인·기록 후 종료한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 103 | 승인된 경로 반영의 기록/실제 적용과 결과 계약 정의 | 완료 |
| 104 | 현재 승인·계획 변경 검증/claim·반영 결과 기록 분리 | 완료 |
| 105 | 정확한 경로·취소·승인만/재시도·실패 경계 확인 | 완료 |
| 106 | 보관 snapshot/manifest/operation 기록 계약 정의 | 완료 |
| 107 | 보관 요청 재생·원본 보존·정리 시작/실패 기록 분리 | 완료 |
| 108 | 완료/중복·저장 실패·부분 정리 보존 확인 | 완료 |
| 109 | 그룹 삭제의 작업공간 정리/결과 계약 정의 | 완료 |
| 110 | 소유 경계/시간 예산을 유지한 worktree·branch 정리 분리 | 완료 |
| 111 | 승인·잠금·외부/미기록 경로 보존·시간 예산/잔여 정리 확인 | 완료 |
| 112 | 이동 순서·공개 계약/의존 관계·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 범위

- 경로 승인 반영 모듈은 현재 부모/승인·범위 제안/미리보기/정책의 일치·일회성 요청을 검증하고
  기존 계획 적용 callback과 반영 결과를 조합한다. Pipeline은 run/chat 잠금과 반영 후 취소 확인,
  실제 실행 session·선택 Task 재시도를 유지한다. 기존 요청 제어 잠금 API만 사용한다.
- 보관 모듈은 좁은 기록 API와 기존 Git adapter/조회·요약/commit 보호·정리 callback으로 snapshot/
  manifest/operation을 조합한다. Pipeline의 승인·입력 검증·Git 준비·project/run/chat 잠금과
  실제 정리 callback을 유지하며 원문 저장 전에 정리를 시작하지 않는다.
- 삭제 모듈은 기존 Git adapter와 소유 경계/대상 조회 callback으로 worktree/branch를 정리하고
  삭제 결과 DTO를 만든다. Pipeline의 승인·공유 시간 예산·실행 잠금 확인/획득·SDK 정리와 최종
  기록 삭제/대화 종료 순서를 유지한다. 경로 소유권 판단과 미기록/외부 경로 차단 규칙을 바꾸지 않는다.
- `pipeline.py`, 관련 execution/integration 하위 모듈·아키텍처와 직접 관련 테스트만 다룬다.
  전체 Pipeline/Store/Config를 전달하지 않는다. 기존 public/private signature·문구/예외와
  저장/CLI/RPC/MCP 계약·승인/부작용 범위를 유지하며 실제 사용자 그룹의 보관/삭제는 실행하지 않는다.

## 검증

이동 전 snapshot과 AST로 본문·callback·기록/오류/잠금·삭제 순서를 대조한다. 변경 Python의
구문/전역 참조/줄 길이/공백/diff와 관련 공개 계약·의존 관계를 확인한다. 기존 경로 반영/취소,
보관 원본/저장 실패와 삭제 소유권/시간 예산의 case만 선택하고 관찰이 충분하면 테스트를 추가하지 않는다.
임시 저장소 fixture 안에서만 정리를 확인하며 실제 사용자 데이터는 대상으로 삼지 않는다.
전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
commit/push/deploy는 포함하지 않으며 통과한 검사는 후속 변경의 영향을 받지 않으면 반복하지 않는다.

## 진행과 결과

### 103~105단계: 승인된 경로 반영

- `execution.scope_approval`에 기록 API와 `ScopeApprovalWorkflow`/반영 결과 DTO를 추가했다.
  현재 부모/승인·제안/미리보기/정책·정확한 경로 변경과 일회성 요청을 확인하고 기존 계획 적용
  callback과 결과 기록을 조합한다. Pipeline의 run/chat 잠금·반영 후 부모 취소 확인·실행 session과
  실제 선택 Task 재시도는 유지했다. module은 기존 요청 제어 잠금 API만 사용한다.
- `pytest -q tests/test_chat_scope_approval.py`에서 실제 계획/프롬프트 반영의 complete/approve_only/
  cancel_after_apply/retry_failed와 취소/변경된 승인 거부의 `-k` 선택을 실행해 `7 passed`(24.54초)였다.
  실제 모델 대신 기존 mock/임시 저장소와 로컬 fixture worker를 사용했다.

### 106~108단계: 완료 그룹 보관

- `integration.archive_workflow`의 `ArchiveRecords`/`RunArchiver`로 요청 재생·원본 snapshot·commit
  참조 보호·요약/manifest·archive 상태와 정리 시작/오류 기록을 옮겼다. 승인·입력/저장소 준비와
  project/run/chat 잠금은 Pipeline에 남겼고 실제 정리는 기존 callback을 사용한다.
- `pytest -q tests/test_pipeline.py`에서 완료 그룹의 기록 보존/소유 worktree 정리, snapshot 저장
  실패 시 정리 미시작, 일부 정리 실패에서도 완료 대상 보존의 `-k` 선택을 실행해 `3 passed`(4.98초)였다.
  중복/이미 보관된 요청과 저장/정리 순서는 이동 전 본문과 AST로 대조했다.

### 109~111단계: 삭제 대상 작업공간 정리

- `integration.deletion.RunWorkspaceDeletion`으로 기존 소유 경계/대상과 verification/conflict
  작업공간·branch의 정리·수량/실패 기록을 옮겼다. Pipeline은 승인·공유 timeout closure·잠금 확인/
  획득과 SDK client 정리, 작업공간 제거 뒤 최종 기록 삭제와 대화 종료를 유지한다.
  소유권/미기록/외부 경로 보호는 기존 callback과 Git API로 그대로 검사한다.
- `pytest -q tests/test_pipeline.py`에서 승인/기본 삭제, 소유한 dirty 작업공간, 공유 Git 시간 예산,
  활성 잠금/외부 경로, 미기록 잔여 경로 보존, 기록한 conflict 잔여 정리/외부 Git marker 보존,
  중단된 verification 작업공간의 `-k` 선택을 실행해 `8 passed`(8.32초)였다. fixture의 임시 저장소만 정리했다.

### 112단계: 묶음 종료

- 이동 전 snapshot과 AST로 승인 경로/부모/정책·요청 제어 잠금/적용 기록과 Root의 후속 재시도,
  보관 요청/원문/manifest/정리·오류, 삭제 소유 경계/시간 예산/정리 순서와 최종 기록 삭제/SDK 종료를
  대조했다. 모든 callback과 기존 Pipeline 서명/데코레이터 및 범위 밖 메서드 420개가 그대로다.
- 수정 Python 4개 파일의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline
  112개·Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로를
  확인했다. 코어 149개 모듈 import 선언에 순환/기능 역참조가 없고 전체 소유 객체를 전달하지 않는다.
  명시적 integration Git adapter와 좁은 기록/경계 API만 사용한다. planning 기본 import와 새 모듈,
  기존 Pipeline의 RunArchive 호환 별칭도 확인했다.
- 관련 검사 합계는 18개다. 새 테스트와 기존 테스트/기대값 변경은 없다. 통과한 동작 검사는 반복하지
  않았으며 줄바꿈·호환 별칭/문서 정리 뒤에는 해당 정적 확인만 수행했다.
- Pipeline은 7,080줄에서 6,902줄로 178줄 줄었다. 대상 함수는 각각 96→40줄, 89→25줄,
  93→32줄이다. 신규 경로 승인/보관/삭제 모듈은 122/119/114줄이다. 전체 리팩터링의 완료를 뜻하지 않으며
  다음 단계는 시작하지 않았다.
- 기존 미커밋 변경과 실제 사용자 그룹/작업공간을 보존했다. 전체 테스트/renderer·빌드/패키징·실제
  AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과 commit/push/deploy는 이번 범위에 필요하지 않아 수행하지 않았다.
