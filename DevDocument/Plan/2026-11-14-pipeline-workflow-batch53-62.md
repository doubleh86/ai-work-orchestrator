# 결과 수정·프로젝트 채팅 흐름: 53~62단계

**상태: 53~62단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

사용자의 다음 10단계 진행 요청에 따라 53~62단계를 수행한다. 앞선 1~52단계 완료 기록은
유지하며 시작 Pipeline은 8,335줄이다. 아래 세 흐름을 계약·구현·연결/국소 확인으로 완결하고
62단계에서 이번 묶음을 종료한다. 추가 단계는 자동으로 시작하지 않는다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 53 | 결과 수정 evidence/요청 기록·연결 기획 callback 계약 정의 | 완료 |
| 54 | 제안 재사용·수정 대상 검증/receipt·동일/연결 그룹 선택 조합 분리 | 완료 |
| 55 | 기존 제안/실패 재시도·완료/보관 결과 수정·요청 재생 경계 확인 | 완료 |
| 56 | 프로젝트 채팅 결정/기록과 runtime 결과 계약 정의 | 완료 |
| 57 | 결정 claim/한도·응답 재검증/취소·범위 질문/결과 기록 조합 분리 | 완료 |
| 58 | 기존 질문/명령/프로필/범위 동의와 오래된 응답 관련 확인 | 완료 |
| 59 | 준비된 행동과 실행 결과 기록의 명시적 계약 정의 | 완료 |
| 60 | 행동 claim/반복 거부·실제 결과/중지·후속 단계 기록 조합 분리 | 완료 |
| 61 | 실제 실행/잠금/session 연결과 중복/실패/취소/중지 case 확인 | 완료 |
| 62 | 세 흐름의 이동 순서·공개 계약/의존 관계·diff/완료 기록 확인 | 완료 |

## 책임과 호환성

- `planning.result_revisions`는 원래 결과 evidence/경로·요청 문맥과 제안 cache/receipt·수정 대상/
  오래된 제안·동일/연결 그룹 선택을 조합한다. 기록/일회용 retry lock과 좁은 기획/재시도/알림 callback만
  받으며 SDK/전체 Pipeline/Store/Config는 받지 않는다. 실제 제안 AI·연결 그룹 준비와 바깥 proposal/request
  잠금·입력 검증은 Pipeline에 남긴다. 이미 저장한 child/receipt 재생과 실패 후 중복 그룹 방지를 유지한다.
- `execution.project_chat`는 `ProjectChatRecords`로 요청 제어 잠금·run/operation 조회/저장을 받고,
  결정 workflow와 행동 결과 workflow를 맡는다. 판단 생성 결과는 명시적인 handled/payload DTO로,
  준비된 행동은 run/request/step·state/control/record/decision을 가진 제한된 도메인 DTO로 전달한다.
  전체 공용 앱/registry/Pipeline이나 임의 context를 넘기지 않는다.
- Pipeline은 프로필/범위 동의 fast path·planning lock/정책과 실제 AI 판단, 실제 clear/stop/repair/
  confirm/refine/resume/verify 및 run lock/실행 session을 유지한다. 실행 callback은 갱신된 operation을
  반환해 범위 승인 후 원래 reload/후속 기록 순서를 유지한다. 판단/실행 wrapper의 기존 오류 기록도 남긴다.
- 취소/대상 변경/모델 권한 주장과 사용자 동의를 구분하고, 동일 상태/행동 반복·수정 한도·실패 근거·
  사용자 중지·확인되지 않은 종료 차단을 유지한다. public/private signature·기존 예외/메시지·SDK/
  credential/usage 수명과 CLI/RPC/MCP/저장 schema를 바꾸지 않는다.

## 영향 파일과 검증

`pipeline.py`, 신규 `planning/result_revisions.py`, `execution/project_chat.py`·공개 export,
아키텍처와 직접 관련 case만 수정한다. 실제 AI/Git 작업의 권한을 새로 추가하지 않는다.

각 흐름의 기존 수정 제안/연결 그룹·프로젝트 채팅/범위 동의/실행/중지 case를 우선 선택한다.
새 경계의 관찰이 없을 때만 회귀 검사를 보강한다. 이동 본문·callback/기록/잠금·오류 순서를 정적으로
대조하고 필요한 구문/diff를 확인한다. 통과한 검사는 재사용하며 전체 테스트/renderer·빌드/패키징,
실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout·commit/push/deploy는 실행하지 않는다.

## 진행과 결과

### 53~55단계: 원래 결과의 수정 요청

- evidence/확인된 경로/문맥·제안/요청 조회·cache/receipt/수정 대상과 동일/연결 그룹 선택을
  `ResultRevisionWorkflow`에 묶었다. 바깥 입력/잠금과 실제 제안 AI/연결 그룹 준비는 Pipeline에 남겼다.
- 추출 스크립트가 파일 쓰기 전에 중단되어 기준선 5개가 먼저 실행됐다. 범위를 조정해 실제 코드를 적용한
  뒤 같은 제안/근거·실패 재시도·동일/보관/연결 그룹·저장 실패 후 재사용 5개를 확인해 `5 passed`(3.60초)였다.
  기준선 통과는 적용 후 검증으로 계산하지 않았다. 테스트/기대값은 수정하지 않았다.

### 56~58단계: 프로젝트 채팅 판단과 기록

- `ProjectChatRecords`/`ProjectChatDecisionResult`/`ProjectChatDecisions`에 결정 claim/한도와
  응답 후 대상/취소/범위 검사·기록을 묶었다. 실제 AI/프로필/동의 fast path와 계획 잠금/정책은
  `_generate_project_chat_decision`에 원래 순서로 남기고 handled/payload 결과로만 교환했다.
- 기존 질문/명령·프로필 변경·응답 중 취소·대상 변경·현재 범위 동의/모델 권한 주장 거부·새 질문의
  scope binding을 선택해 `22 passed`(1.82초)였다. 새 테스트는 추가하지 않았다.

### 59~61단계: 준비된 행동과 실제 결과 기록

- `ProjectChatAction`/`ProjectChatActions`에 행동 claim/대상/반복 검사와 실행 후 결과·중지·후속 기록을
  묶었다. `_execute_project_chat_action`은 기존 실제 행동/run lock/session 본문과 갱신된 operation을
  반환한다. 범위 승인 후 operation reload와 legacy 계획 확인 뒤 expected 갱신도 원래 순서다.
- 기존 한 번 실행/프로필 결합 재시도·구현 지시 보존·실패/수정 한도·stale lock 해제 후 실제 잠금 관찰,
  사용자 중지/동시 목표 변경 차단·취소/변경된 승인·승인 후 계획/프롬프트/실패 Task 재시도를 골라
  `16 passed`(43.56초)였다. 실제 모델 대신 기존 mock/worker와 테스트 임시 저장소를 사용했다.

### 62단계: 묶음 완료 점검

- evidence/제안/요청·연결 그룹 준비, 판단/행동 본문과 DTO/handled 결과·잠금/오류/operation 갱신 순서를
  AST로 대조했다. 나머지 Pipeline 메서드 406개와 모든 기존 signature는 그대로다.
- 제품 Python 5개 파일의 구문·전역 참조·변경 줄 길이/공백과 직접 diff를 확인했다. 고유 관련 검사
  43개가 통과했고 새 테스트는 없다. 구현이 바뀌지 않은 통과 검사는 반복하지 않았다.
- Pipeline 112개·Store 91개·응용 API 121개의 public signature·모델 80개/기존 오류/호환 import와
  RPC 122개 경로를 확인했다. 코어 134개 모듈의 import 선언에 순환/역참조가 없고 planning 기본 import에
  SDK/Git/runtime을 추가하지 않았다. evidence/경로/문맥과 기존 MAX_DECISIONS import의 호환 별칭도 유지했다.
- Pipeline은 8,335줄에서 8,083줄로 252줄 줄었다. result_revisions 모듈은 248줄, execution.project_chat은
  두 workflow와 DTO를 합쳐 196줄이다. 줄 수 감소를 전체 구조 정리의 완료로 해석하지 않는다.
- 기존 미커밋 변경을 보존했다. 전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면과 다른 저장소·
  Rust·공개 checkout·실제 commit/push/deploy는 실행/변경하지 않았다.

이번 **53~62단계 묶음은 완료**했다. 추가 진행은 다음 10단계 묶음의 범위를 정해 수행한다.
