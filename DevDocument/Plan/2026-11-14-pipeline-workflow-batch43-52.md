# Pipeline 대화·재시도·검증 복구 흐름: 43~52단계

**상태: 43~52단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 범위

사용자의 계속 진행/10단계 묶음 요청에 따라 43~52단계를 일괄 수행한다. 앞선 1~42단계의
완료 기록은 유지하며 시작 Pipeline은 8,609줄이다. 아래 세 흐름을 계약·구현·연결/회귀 확인으로
각각 완결하고 52단계에서 이 승인 범위를 종료한다. 추가 단계는 자동으로 시작하지 않는다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 43 | 기획 대화 세션·기록·호출 계약 정의 | 완료 |
| 44 | 대화 이어가기·근거 prompt·시도/오류 조합을 planning runtime으로 이동 | 완료 |
| 45 | 기존 기획/완료/보관 대화와 Claude/Codex 세션 경계 연결/확인 | 완료 |
| 46 | 실패 Task 수정 지시/진단·재시도 근거 계약 정의 | 완료 |
| 47 | 실패/중지·시도/계약 fingerprint·scope/timeout 근거·지시 저장 흐름 분리 | 완료 |
| 48 | 기존 잠금/notification/실제 재시도 연결과 관련 case 확인 | 완료 |
| 49 | 검증/자동 수정 반복과 요청 기록의 callback 계약 정의 | 완료 |
| 50 | 검증/수정 한도·receipt·부분 실패/사용자 중지 조합 분리 | 완료 |
| 51 | 기존 실행 session·정책·실제 verify/repair·중지 전이 연결/확인 | 완료 |
| 52 | 세 흐름의 이동/공개 계약·의존 관계·diff/완료 기록 확인 | 완료 |

## 소유권과 호환성

- `planning.chat.PlanningChatRunner`는 repo/timeout 값과 기존 SDK·좁은 profile/문맥/prompt/진행/호출
  callback으로 기존 기획 대화의 세션 연속성·근거 문맥·기록·오류를 조합한다. SDK를 새로 만들거나 닫지
  않으며 연결 thread 종료/재개와 Claude 세션 확정 시점은 유지한다. Pipeline은 정책 scope·대화 잠금과
  최종 사용자/AI 메시지·계획/상태 반영을 소유한다. planning 기본 import에 runtime을 추가하지 않는다.
- `execution.retry_guidance.TaskRetryGuidance`는 run/수정 요청/실행 제어 조회·저장 callback과 Task 찾기/
  scope/timeout/head/알림 callback을 받는다. 과거 응답을 현재 시도로 표시하지 않고 실패/중지·계약 digest,
  중복 ID/오래된 fingerprint·scope/timeout 변경 근거·진단 중복·요청 저장 뒤 대기 알림 순서를 유지한다.
  잠금/문자열 검증·최종 실행/권한은 Pipeline에 남긴다. 실제 worker를 새로 실행하지 않는다.
- `execution.verification_repair.VerificationRepairWorkflow`는 기존 기록 API와 verify/repair/정책/채팅/
  완료/중지 callback으로 반복과 receipt만 조합한다. Pipeline은 request/parent 검증·run lock/실행 session,
  실제 verify/repair·기능 계획 전환의 chat lock과 중지 시 Run 복원/확인 소유권을 유지한다.
- 기존 public/private signature·오류/원인·메시지/호출 순서·SDK/credential/사용량 수명과
  CLI/RPC/MCP/저장 schema를 바꾸지 않는다. 전체 Pipeline/Store/Config·무제한 context를 전달하지 않는다.

## 영향 파일과 검증

`pipeline.py`, 신규 `planning/chat.py`, `execution/retry_guidance.py`, 기존
`execution/verification_repair.py`·공개 export, 아키텍처와 직접 관련 case만 수정한다.

구문/전역 참조·diff와 이동 본문/대화/기록/오류/상태·잠금 호출 순서를 대조한다. 각 흐름의 기존 검사를
우선 선택하고 필요한 경계가 없는 경우만 보강한다. 통과한 검사는 재사용하며 전체 테스트/renderer,
빌드/패키징·실제 AI/계정/도구/화면과 다른 저장소/Rust/공개 checkout·commit/push/deploy는 수행하지 않는다.

## 진행과 결과

### 43~45단계: 기획 대화 runtime

- `PlanningChatRunner`에 thread/session 연속성·문서/완료/보관/실행 근거 prompt·시도 저장·오류 처리를
  묶었다. SDK와 persist callback은 기존 인스턴스/기록 API이며 정책 scope·대화 잠금·최종 반영은 유지했다.
- 기존 대화 실패/완료/보관 기록 보존·실행 중 sidecar/시작 race, Codex thread 지속과 Claude 세션 재개/
  첫 실패 시 세션 미확정을 선택해 `8 passed, 5 subtests passed`(6.05초)였다. 실제 AI는 호출하지 않았다.

### 46~48단계: Task 재시도 근거와 지시

- `RetryGuidanceRecords`/`TaskRetryGuidance`에 수정 지시/계약 digest·현재 실패/중지 근거·scope/timeout
  복구 가능성과 진단/요청 저장을 묶었다. UUID/문자열 검증·잠금과 알림/실제 실행 callback 소유권은 유지했다.
- 기존 중복/오래된 지시·과거 시도 응답 배제·실패 단계/활성 잠금·원본/완료 계약·맞는 중지 확인과
  timeout 반복 조건을 선택했다. 진단 중복/오래된 실패 거부/Task 미변경 경계만 1개 보강했다.
  `17 passed, 1 failed`(0.94초)에서 실패는 새 fixture가 저장/복원 정규화 전 Task와 비교한 문제였다.
  저장/복원된 Task 전체를 기준으로 맞추고 해당 case만 재확인해 `1 passed`(0.34초)였다. 고유 18개 모두 통과다.

### 49~51단계: 검증/자동 수정 반복과 receipt

- `VerificationRepairRecords`/`VerificationRepairWorkflow`에 claim·검증/수정 반복·한도와 receipt를
  묶었다. run lock/parent 검증/실행 session, 실제 verify/repair·중지 Run 복원과 후속 기획 전환은 Pipeline에 유지했다.
- 기존 중지/파일 잠금 시 수정 차단·중복 채팅 receipt와 새 성공/수정 한도 2개 case를 확인해
  `5 passed`(0.57초)였다. 정적 검사에서 후속 기능 기획 callback의 run ID 전달 누락을 찾아 수정했다.
  실제 요청 그룹의 chat lock 아래 후속 기획이 실행되는 case를 추가하고 성공/중복 receipt만 재확인해
  `3 passed`(0.65초)였다. 고유 관련 case는 6개이며 새로 발견한 오류는 남아 있지 않다.

### 52단계: 묶음 완료 확인

- 세 흐름의 본문·위임과 기록/오류/최종 전이·잠금 순서를 AST로 대조했다. 나머지 Pipeline 메서드
  403개와 모든 기존 signature는 그대로다. 기존 worker 수정 본문과 policy scope도 바꾸지 않았다.
- 수정 Python 7개 파일의 구문과 제품 5개 파일의 전역 참조·변경 줄 길이/공백, 새 테스트와 직접 diff를 확인했다.
  고유 관련 검사 32개와 별도 subtest 5개가 통과했다. 실패/수정이 없는 통과 case는 반복하지 않았다.
- Pipeline 112개·Store 91개·응용 API 121개의 public signature·모델 80개/호환 오류와 RPC 122개 경로를
  확인했다. 코어 132개 모듈의 import 선언에 순환/역참조가 없고, planning 기본 import에 SDK/Git/runtime을
  추가하지 않았다. 이전 helper import와 Task 계약 digest의 동일 함수 별칭도 유지했다.
- Pipeline은 8,609줄에서 8,335줄로 274줄 줄었다. chat 모듈은 182줄, retry_guidance는 176줄,
  verification_repair는 기존 worker 준비를 포함해 253줄이다. 줄 수 감소가 전체 구조 정리의 완료를 뜻하지 않는다.
- 기존 미커밋 변경을 보존했다. 전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면, 다른 저장소·
  Rust·공개 checkout·실제 commit/push/deploy는 수행하지 않았다.

이번 **43~52단계 묶음은 완료**했다. 추가 진행은 다음 10단계 묶음의 범위를 정해 수행한다.
