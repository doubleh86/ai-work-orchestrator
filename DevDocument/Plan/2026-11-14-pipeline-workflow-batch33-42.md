# Pipeline 흐름 단위 분리: 33~42단계

**상태: 33~42단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

사용자가 요청한 10단계 묶음은 33~42단계다. 작은 함수마다 단계를 늘리지 않고 아래 세 개의
일관된 흐름을 계약·구현·호출부/회귀 확인으로 묶는다. 이 묶음이 끝나면 멈추며 다음 묶음은 별도 요청 범위다.
앞선 1~32단계 완료 기록은 유지한다. 시작 Pipeline은 9,219줄이다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 33 | 기획 미리보기의 기록/생성 callback·조회/검증 계약 정의 | 완료 |
| 34 | 미리보기 fingerprint/차이·조회/진행·생성 흐름을 planning에 구현 | 완료 |
| 35 | Pipeline 호환 연결과 미리보기/보호/재사용/동시 상태 관련 확인 | 완료 |
| 36 | 복구안 후보/요청 기록·재생/재개 계약 정의 | 완료 |
| 37 | 복구 후보 조회와 receipt 조합을 integration에 구현 | 완료 |
| 38 | 기존 복구 진입점 연결과 timeout/부분 성공/재시도 경계 확인 | 완료 |
| 39 | 통합 검증 후보 결과와 Git/진행 callback 계약 정의 | 완료 |
| 40 | 격리/공유 후보 통합·검증/충돌·입력 재검사 흐름을 integration에 구현 | 완료 |
| 41 | Pipeline 최종 상태 전이 연결과 후보/충돌/HEAD 변경/정리 확인 | 완료 |
| 42 | 세 흐름의 의존·공개 계약/오류·변경 diff와 완료 기록 점검 | 완료 |

## 책임과 호환성

- `planning.preview`는 기존 preview 기록 조회/저장 callback과 계획 생성·문맥/색인·파일 digest·요청 ID
  callback으로 fingerprint/Task 변경 비교·저장 후보 검증·공개 표시/실제 활동 판정·후보 생성을 조합한다.
  방향 변경 상태의 성공/실패 복원과 stale/owner/time/캐시 재사용·보호 Task/추가 질문 차단을 유지한다.
  Pipeline은 run/chat lock, 승인된 후보 적용과 최종 계획/상태 저장을 유지한다.
- `integration.recovery`는 Git adapter와 작업공간/청결·작업 초안·run/요약/operation/result/lock의 좁은
  callback으로 후보 탐색·bounded timeout·입력 digest와 요청 claim/재생/중단 복원/부분 적용 재개를 맡는다.
  실제 승인·복구 commit 반영/재계획 트랜잭션·정책 scope와 최종 Run 전이는 Pipeline에 남긴다.
- `integration.verification`은 Git adapter·repo/작업공간과 준비·queue/기존 검증·저장 callback으로
  격리/공유 후보 통합·충돌 근거/abort 확인·검증과 HEAD 재검사를 수행하고 검증 근거 DTO를 반환한다.
  기존 finally 정리·검증 후보 branch와 복구 근거 저장을 유지한다. Run의 VERIFIED 전이·bootstrap 완료와
  최종 검증 근거 반영은 Pipeline에서 수행한다. Main 반영/push/deploy 경계는 이동하거나 실행하지 않는다.
- `VerificationInputsChanged`는 공유 errors에 두고 기존 pipeline import와 동일 객체로 노출한다.
  기존 메서드 signature·호환 별칭·예외/원인·CLI/RPC/MCP/저장 schema와 오류 메시지는 유지한다.
- 전체 Pipeline/Store/Config·무제한 context를 새 객체에 전달하지 않는다. SDK·정책·credential·
  사용량 수명은 기존 호출부가 소유한다. 새 client/서비스/네트워크·의존성이나 빈 패키지는 만들지 않는다.

## 영향 파일과 검증

`pipeline.py`, `planning/preview.py`와 공개 export, 신규 `integration/recovery.py`,
`integration/verification.py`, 공유 errors/export·아키텍처와 직접 관련 검사만 수정한다.

이동 본문/위임 입력·Git/저장/오류·finally 순서를 대조하고 수정 Python 구문/전역 참조·diff를 확인한다.
각 흐름의 기존 case를 우선 선택하며 실제 필요한 경계가 없는 경우만 국소 회귀 검사를 보강한다.
이미 통과한 검사는 재사용하고 단계마다 전체 테스트를 반복하지 않는다. 실제 AI/계정/도구·화면·빌드·
패키징·다른 저장소/Rust/공개 checkout·commit/push/deploy는 실행하지 않는다.

## 진행과 결과

### 33~35단계: 기획 미리보기

- `PlanningPreviewRecords`와 `PlanningPreviewWorkflow`에 후보/진행 기록·생성 callback 계약을 정의하고
  fingerprint/차이·검증/공개 표시·활동 조회·생성/방향 변경 복원까지 한 객체로 묶었다.
  Pipeline은 run/chat lock과 실패 progress 표시·후보의 실제 반영/최종 저장을 유지한다.
- 기존 보호/stale/의존 Task 제외·생성 재사용/실패·방향 변경 수명과 실제 Task/리뷰/검증·동시 대화의
  활동 표시를 선택해 `19 passed, 6 deselected`(5.42초)였다. 새 테스트는 추가하지 않았다.
- planning 기본 import가 planner/Pipeline/Store/Git/SDK를 로드하지 않음을 확인했다. 생성 오류 tuple은
  기존 소유자가 동일 객체들로 전달하며 새 runtime 예외 의존성·실제 provider 호출은 추가하지 않았다.

### 36~38단계: 복구 후보와 요청 수명

- `RecoveryRecords`와 `RecoveryWorkflow`에 후보 비교·deadline·입력 digest·claim/중복/결과 재생,
  잠금 종료에 따른 기록 복원·부분 적용 재개와 오류 기록을 묶었다. 실제 commit 반영/재계획 코드는 그대로다.
- 기존 deadline/오류 시 잠금 해제·승인/오래된 계획 차단·통합 후 capacity/부분 성공의 재계획 재시도·
  조회 재생/발견·중단 복원을 선택해 `6 passed`(11.20초)였다. deadline 테스트의 clock patch 경로 1개만
  새 소유 모듈로 이동했으며 테스트 기대/실패 조건은 바꾸지 않았다.

### 39~41단계: 통합 검증 후보

- `VerifiedCandidate`와 `CandidateVerification`에 격리/공유 후보의 통합/검증·충돌 근거/abort·HEAD 검사와
  정리를 묶었다. 후보 완료 뒤 검증 근거/복구 head·bootstrap·VERIFIED·최종 저장 순서는 Pipeline에 유지했다.
  공유 `VerificationInputsChanged`는 기존 pipeline 경로와 같은 객체이며 오류/원인 처리는 그대로다.
- 기존 격리 후보/실패 후 Main 보존·dirty 검증 결과 정리, 공유 Main 충돌/후보 해결·최신 Main 기준
  정확한 검증 commit 반영, 입력 변경/stale와 기존 push 후 재검증을 선택해 `7 passed`(32.50초)였다.
  실제 사용자 저장소의 Main/push는 수행하지 않았고 테스트의 임시 Git 저장소만 사용했다.

### 42단계: 묶음 완료 확인

- 이동한 본문·위임/오류 tuple·복구 트랜잭션·Git/abort/finally와 Pipeline의 최종 검증 저장/전이 순서를
  AST로 대조했다. 나머지 Pipeline 메서드 389개와 모든 기존 signature는 그대로다.
- 변경 Python 8개 파일의 구문, 제품 7개 파일의 전역 참조·변경 줄 길이/공백과 직접 diff를 확인했다.
  새 테스트는 없으며 관련 검사 합계 32개가 통과했다. 통과한 검사는 반복하지 않았다.
- 기존 방식으로 Pipeline 112개·Store 91개·응용 API 121개의 public signature·모델 80개/호환 오류와
  RPC 122개 경로를 확인했다. 코어 130개 모듈 import 선언의 순환 의존·분리 기능의 역참조가 없으며
  새 흐름은 전체 Pipeline/Store/Config나 임의 context를 받지 않는다.
- Pipeline은 9,219줄에서 8,609줄로 610줄 줄었다. preview 모듈은 422줄, recovery는 281줄,
  verification은 219줄이다. 파일 길이 감소만을 전체 구조 정리의 완료로 해석하지 않는다.
- 기존 미커밋 변경을 보존했다. 실제 AI/계정/도구·화면·전체 테스트/renderer·빌드/패키징과 다른 저장소·
  Rust·공개 checkout·실제 commit/push/deploy는 실행/변경하지 않았다.

이번 승인 범위인 **33~42단계는 완료**했다. 전체 제품의 구조 개선이 모두 끝났다는 뜻은 아니며,
후속 진행 요청은 다음 10단계 묶음으로 범위를 정해 진행한다.
