# Pipeline 재설계 이행 계획

- 상태: **P1~P5 완료**
- 상세 계약: [명시적 진입점과 명령 소유권](../Design/Technical/2026-11-15-pipeline-orchestration-redesign.md)
- 공개 API: [112개 소유권 표](../Design/Technical/2026-11-15-pipeline-api-ownership.md)
- 내부 계약: [376개 소유권·자원/잠금·hook 이전표](../Design/Technical/2026-11-15-pipeline-private-ownership.md)
- 기준: 2026-11-15, Pipeline 5,495줄·직접 정의 411개(공개 112/private 299), 별칭 75개·runtime endpoint 2개

## 목표와 승인 범위

설계 승인 뒤 P1~P5를 완료했다. 마지막 “ㅇㅇ 진행 해줘”의 승인 범위까지 구현·선택 검증을 마쳤다.
이행 목표는 facade를 1,000줄 이하의 명시적 공개 진입점으로 만들고, 실제 조정/조립·자원 소유권과
테스트 경계를 분리하는 것이다. 공개 API를 삭제하거나 같은 self를 다른 파일로 옮겨 달성하지 않는다.

앞선 302단계와 [호출/위임 축소](2026-11-15-pipeline-facade-reduction.md)는 구현 당시의 완료 기록이다.
그 번호를 이어서 수백 개의 작은 단계를 추가하지 않는다. **새 구현은 아래 5개 큰 단계**로 진행한다.
이 문서 작성이 5단계 전체의 구현 승인을 뜻하지 않는다. 이후 별도 범위 지정이 없는 “다음 작업”은
아래의 다음 한 단계다. 단계 내부의 필수 선언/호출부·기존 테스트 이전과 관련 검증은 함께 완결한다.

## 이행 순서

| 단계 | 실제 범위 | 공개 API 배정 | 완료 조건 | 현재 |
|---|---|---:|---|---|
| P1 구성/공통 기반 | 공개/내부 계약 확정, bootstrap·자원/정책/step 수명·공유 phase 배정 | facade 유지 | 자원/소유권 목록과 실제 구성 분리, 공개 계약 고정, 중복 수명/역참조 없음 | 완료 |
| P2 조회/정책 | RunQueries·ProviderQueries·EffortCommands와 해당 테스트 경계 | 27 | 27개 API가 새 소유자로 delegation, 원래의 오류/unknown·정책 부작용/자원 갱신 보존 | 완료 |
| P3 기획 | PlanningCommands와 대화/미리보기/확정·복원·기획 phase | 26 | 기획 API/phase가 facade callback을 받지 않으며 revision·대화/재전달·rollback 보존 | 완료 |
| P4 실행/관제 | ExecutionCommands·RunControlCommands·필요한 실행/검증 내부 phase | 32 | 다음 Task·중단/재개·정책·관제 요청 소유권/호출과 원래 잠금 경계 보존 | 완료 |
| P5 통합/정리·종료 | IntegrationCommands·LifecycleCommands, 남은 호환 bridge 제거 | 27 | 112개 배정 완료, facade ≤1,000줄·계약/의존/선택 회귀 통과, 미해결 필수 항목 없음 | 완료 |

27 + 26 + 32 + 27 = 112개다. P1은 수명/조립 기반을 만들며 공개 명령을 미리 빈 객체로 옮기지 않는다.
다른 기능 소유의 phase가 선행 단계에서 필요하면 실제 소비자와 함께 먼저 옮긴다. 그 기능의 공개
wrapper 이전을 기다리거나 새 facade-back-callback으로 연결하지 않는다. phase는 한 곳에만 구현한다.

### P1에서 반드시 확정할 것

- 현재 public constructor/112개 signature와 src/tests에서 import하는 16개 오류/상수/타입의 계약을
  저장 가능한 manifest와 작은 계약 검사로 고정한다. 공개 메서드의 annotation 이름을 줄 수 절감을 위해 바꾸지 않는다.
- private 299개/별칭 75개/endpoint 2개와 module-level helper를 실제 소유자에 배정한다. 정적 호출
  도달성 107개 단일/175개 공유/17개 미도달은 이동 후보 조사 자료이며 삭제 판정이 아니다.
- `ApprovalRequired`의 오류 소유 모듈과 re-export, `_StoredStopSignal`의 load-control port를 확정한다.
  실제 facade import가 없어야 phase/명령 객체를 bootstrap에서 조립할 수 있다.
- Config/StateStore/Git/SDK·credential snapshot·RLock·Planning ContextVar/정책 binding의 실제 owner와
  수명을 표로 고정한다. runtime을 기능마다 복제하지 않는다. registry/실제 SDK 종료는 기존 진입점에 남긴다.
- 공개 속성의 접근/재할당도 확인한다. 현재 테스트의 `config` 17, `git` 5, `agents` 2,
  `dotnet_executable` 4, `store` 1 후보를 단순 eager capture로 깨뜨리지 않는다. 명시적 compatibility
  property와 좁은 adapter 또는 소유 객체 fixture로 처리하며 새로운 자동 재설정을 도입하지 않는다.
- lock scope와 `*_locked` phase의 실제 진입 조건/호출자를 기록한다. 위임 후 같은 run lock을 다시
  잡거나, 중단 요청이 실행 중인 run lock을 기다리게 만들지 않는다. 전체 명령에 공통 lock decorator를 붙이지 않는다.
- 별칭을 포함한 360곳/57개 private callable test hook의 이전 대상을 정한다. 이동한 소유자의 port/factory를 주입하도록
  바꾸며 기존 상태/오류/receipt 기대를 유지한다. private 호환을 영구적으로 facade에 재생성하지 않는다.

## 단계별 검증과 중단 기준

문서·이행 준비만 한 부분은 링크/배정/계약/diff로 확인한다. 코드 이동 후에는 바뀐 파일 구문과
공개 계약·의존 방향, 실제로 이동한 흐름의 기존 관련 사례만 실행한다. 아래는 범위 선택 기준이며
나열한 테스트 파일 전체를 매번 실행하라는 목록이 아니다.

| 단계 | 필요한 회귀 경계 |
|---|---|
| P1 | 공개 signature/import identity, 자원/ContextVar/lock 동일성·정책 중첩, key snapshot·SDK 비소유, lazy 구성/자원 재할당 |
| P2 | 완료/실행 중 상태 조회·주의 항목·순서/timeout·None/0, 계정 한도/가용성, 강도 revision/예약과 수동 프로필 |
| P3 | 준비→실행 인계·색인/원문, 미리보기/stale 거부·재전달·실패 rollback, Claude 대화/기술 선택·기능 기획 |
| P4 | 병렬 Task 대상과 stop/attempt, 정책 prepare/start/finish, 중단 후 기존 Task 유지·관제 허용 행동·부분 실패 |
| P5 | 검증 실패·HEAD 변경·Main 부분 반영/복구, push/배포 승인, 보관 선기록/부분 정리·경로 보호/삭제, 결과 실행 근거 |

- 기존 테스트의 패치 위치/fixture만 이전하고 assertion을 약화하지 않는다. 빠진 경계가 확인될 때만
  새 테스트를 추가한다. facade 통합 검사는 공개 입출력·오류/저장 결과를 확인하며 private 구현을 고정하지 않는다.
- 이전 통과 결과가 여전히 적용되는 부분은 재사용한다. 파일 수가 늘었다는 이유로 전체 suite를 돌리지 않는다.
- 동작/공개 계약/저장·잠금/실패 의미가 바뀌는 문제가 생기면 해당 부분을 고치고 관련 검사만 다시 확인한다.
  현재 요청과 무관한 결함/미사용 코드·다른 프로젝트/Rust를 정리하지 않는다.
- 단계별로 기존 API의 단일 실행 경로를 바꾼다. 실제 AI/Git에 구/신 경로를 동시에 실행하는 shadow 비교는 하지 않는다.
- 프로덕션 빌드/패키징·실계정/제품 화면·commit/push/deploy는 별도 근거/요청이 있을 때만 수행한다.

## 범위와 완료 보고

예정 코드 범위는 facade/새 bootstrap·orchestration, 실제 이동하는 기존 기능/port와 직접 관련 테스트다.
기존 dirty 작업은 보존하고 저장 형식/공개 transport/사용자 UI/등록 프로젝트·외부 저장소는 바꾸지 않는다.

각 단계 보고에는 이전한 API 수와 남은 수, 제거한 facade-back-reference/private bridge, 자원/잠금
소유권, 실제 검증과 미수행 범위를 남긴다. 줄 수 감소만으로 완료라고 판단하지 않는다.
P5에서는 **112개 소유권 일치 + facade 책임 제거/≤1,000줄 + 모듈 역참조 없음 + 관련 검사 통과**를 모두 확인한다.
완료 조건을 충족하면 종료하고 새 작은 분리 후보를 이유로 P6 이후를 자동 추가하지 않는다.

## 이번 설계 작업의 결과

- 소스/기존 설계와 facade의 411개 정의·공개 112개 배정, private 참조/테스트 hook과 import 계약을 확인했다.
- 8개 소유자에 112개 이름을 중복/누락 없이 배정한 표를 작성했다. facade 내 참조 SCC는 두 개의
  factory/callback 쌍이며 module 순환 버그로 오인하지 않았다.
- module/phase·잠금/자원·호환/테스트 이전을 포함한 상세 설계와 5개 큰 구현 단계를 작성했다.
- 프로덕션 코드/테스트는 수정하거나 실행하지 않았다. 검증은 문서의 참조/배정·실측값/diff 확인이다.

## P1 구현 범위

- public API/constructor와 16개 export의 고정 manifest·계약 검사를 추가한다. 내부 소유권 목록은
  현재 299개 정의/75개 별칭/2개 endpoint를 기준으로 작성하고 실제 P1 이동 항목을 표시한다.
- `pipeline_bootstrap`이 현재 생성 순서대로 자원과 공통 실행 객체를 구성한다. facade의 공개 속성과
  아직 이전하지 않은 private 자원 속성은 명시적인 compatibility property로 같은 자원에 연결한다.
  Config 변경 시 agents를 자동 재구성하는 등 기존에 없던 동작은 추가하지 않는다.
- `ApprovalRequired`는 오류 모듈로, `_StoredStopSignal`은 load-control port를 받는 실행 제어 모듈로
  옮긴다. `_step`과 `_planning_effort_scope` 구현은 각각 실행 단계/기획 정책 수명 API로 옮긴다.
- 공유 scope는 bootstrap의 좁은 port로만 구성하며 Pipeline/전체 자원 holder를 feature에 전달하지 않는다.
  아직 Root에 있는 명령은 instance callable/명시적 bridge로 동일 scope를 사용하고 P3~P5에서 제거한다.
- 기존 credential factory를 patch하는 테스트는 실제 생성 소유자인 bootstrap으로 patch 위치만 옮긴다.
  공개 자원 교체·공유 lock/ContextVar·중단/실패/stale/성공·정책 nesting/예외 정리를 관련 사례로 확인한다.

## P1 구현 결과 — 2026-11-15

- `pipeline_bootstrap.py` 158줄에서 요청별 자원과 공통 실행 제어·단계/기획 정책 객체를 구성한다.
  SDK를 새로 만들거나 닫지 않으며 생성 시 Run 저장·Git 명령·AI 호출을 추가하지 않았다.
- step 130줄과 policy scope 98줄의 독립 소유자를 만들었다. 기능은 제한된 callable/기록 port만
  받고 facade/StateStore/Config/전체 자원 holder를 역참조하지 않는다. 기존 잠금·ContextVar와
  실패/중단/stale/성공의 저장 순서, credential snapshot·알림 callback의 초기 project 범위를 유지했다.
- `ApprovalRequired`는 오류 모듈에서 동일 클래스로 re-export한다. 중단 신호는 loader만 받고,
  생성 후 facade store를 교체해도 원래 실행의 control을 확인한다.
- 12개 명시적 자원 호환 property를 두고 공개 속성 재할당을 기존 자원과 연결했다. config 교체로
  agents/Git/Store를 자동 갱신하지 않는다. 공통 기록 port는 호출 시 현재 자원을 조회한다.
- constructor/112개 공개 signature·binding manifest와 기존 사용 export 16개의 계약 검사를 추가했다.
  376개 private 이름과 57개 test hook 후보 이름을 단일 동작 owner/이전 단계에 배정했다.
- **Pipeline 5,495 → 5,366줄(-129)**. 직접 정의한 비-property 메서드는 411 → 409개이며
  12개 property의 getter/setter 24개는 이 수에서 제외했다. 공개 112개 메서드의 본문/signature는
  그대로다. 공개 명령 이전은 **0/112개**, 남은 **112개**이며 P2의 27개부터 실제 명령 이전을 시작한다.
- `_step`/`_planning_effort_scope`의 class 구현을 제거했고 기존 명령은 같은 owner의 instance callable을
  임시 사용한다. 실행 제어 bridge와 기존 provider factory/endpoint는 현재 소비자를 위해 남기며
  소유권 표에 따라 P3~P5에서 제거한다. 기능마다 별도 lock/ContextVar/SDK를 복제하지 않았다.

### 실제 검증

공통 수명과 저장/제어 경계가 바뀌므로 해당 사례만 선택했다. 전체 테스트는 실행하지 않았다.

- 공개 계약 2개 + 새 자원/공유 scope 경계 4개 통과.
- 기존 중단/Task·검증 복구 3개, group receipt/stale 입력 2개, 기획 binding/저장 실패·보관 대화 3개 통과.
- 기존 provider 오류 변환/SDK 비소유 6개와 credential snapshot 1개 통과.
- fixture의 생성 owner를 옮긴 검증 실행 오류/로그 경계 5개 통과.
- 합계 **26개 테스트 + 2개 subtest 통과**. 전역 Python에는 pytest가 없어 저장소의 기존
  `.venv/Scripts/python.exe`를 사용했다. 새 의존성은 설치하지 않았다.
- AST 비교로 남은 facade 406개 메서드 본문과 이전한 step/policy/signal의 port 치환 외 제어 흐름이
  같음을 확인했다. 변경 소스의 구문/전역 이름·직접 의존 경계와 문서 참조/소유권/diff를 확인했다.

UI/TypeScript·공개 transport·저장 형식은 변경하지 않았다. 전체 suite·typecheck·프로덕션 빌드·패키징,
실제 AI/제품 화면·commit/push/외부 저장소 작업은 이번 범위에 없어 실행하지 않았다.

## P2 구현 범위

- 조회 16개·provider 5개·강도 6개 공개 API의 실제 흐름을 세 명령/조회 객체로 이전한다.
  생성자·static API는 지연 자원 생성 계약을 유지하고 facade에는 명시적 delegation만 남긴다.
- 새 객체는 제한된 기록·설정·기능 port로 구성한다. 상태 요약/대기 안내에 필요한 integration control,
  retry 문맥과 강도 적용에 필요한 계획 파일 입출력·가용성은 첫 소비자와 함께 소유자로 옮긴다.
  facade/전체 자원 holder를 callback으로 숨겨 전달하거나 완료된 API가 다시 facade로 돌아오지 않는다.
- 남은 P3~P5 소비자의 private 연결은 실제 owner의 공개 동작으로 연결하고 제거 시점을 기록한다.
  기존 테스트의 해당 private patch는 owner/명시적 port fixture로 옮기며 결과 assertion은 유지한다.
- lock 전후 snapshot·unknown/예외 허용 차이, status/목록 정렬·시간 제한, 계정 인증·quota fallback,
  정책 revision/예약·수동 프로필/계획 저장의 관련 사례만 선택한다. 전체 suite/빌드/실제 AI는 수행하지 않는다.

## P2 구현 결과 — 2026-11-15

- `orchestration.queries.RunQueries` 16개, `providers.ProviderQueries` 5개,
  `effort.EffortCommands` 6개 공개 API의 실제 흐름과 조합을 이전했다. facade의 공개 이름·binding·
  annotation·기본값은 그대로이고 이 27개 본문은 명시적 delegation만 수행한다.
- lock snapshot/실행·통합 제어는 `queries.control`, 범위 제안·fingerprint는 `queries.scope_proposals`,
  Run/Task lookup은 `persistence.run_lookup`, 계획 파일 입출력은 `planning.plan_files`로 이전했다.
  retry 문맥은 기존 기능 owner를 bootstrap에서 직접 구성하며 Root를 다시 호출하지 않는다.
- 가용성/리뷰 호환과 연결 집합·preview 검증을 실제 기능 owner로 연결했다. summary→waiting,
  연결 집합→상태 조회, 강도 조회/계획 적용→preview도 기능 API 사이에서 직접 협력한다.
  기능이 facade/새 명령 객체로 돌아오는 callback을 만들지 않았다.
- 설정·Store·Git·SDK 재할당을 호출 시 반영하는 제한된 port를 구성했다. static 계정/Claude 연결
  조회는 Pipeline/runtime/SDK를 생성하지 않는다. credential snapshot·SDK 비소유는 유지했다.
- instance별 `ProviderConnectionProbes`로 실행 파일/인증 fake의 격리를 유지했고 해당 fixture를
  실제 owner로 옮겼다. 기존 테스트의 결과·오류·호출 횟수 assertion은 약화하지 않았다.
- 사용이 끝난 private 연결 **12개를 제거**했다. 남은 기획·실행·통합 소비자는 동일 owner의 임시
  연결을 사용하며 P3~P5에서 제거한다. 최초 private 376개 표는 기준 목록으로 유지하고 P2 실제 owner를 갱신했다.
- **Pipeline 5,366 → 5,013줄(-353)**, 최초 재설계 기준 5,495줄 대비 **482줄 감소**.
  비-property 직접 정의 메서드는 409 → 377개이며 공개 API는 112개 그대로다.
  공개 이전은 **27/112개 완료**, 남은 **85개**다. 다음 단계는 **P3 기획 API 26개**다.

### P2 실제 검증과 제한

- 공개 계약/자원 수명, 제어 lock 변화·오류 전파, 상태/주의 목록·대기 안내, 로그 경로/길이,
  최신 설정·SDK 참조, 계정/인증·한도 후보, 강도 적용·예약/revision/손상 정책의 선택 검사 통과.
  성공한 고유 사례는 **48개 테스트 + 3개 subtest**다. 기존 통과 결과는 재사용했고 전체 suite는 돌리지 않았다.
- 새 경계 테스트는 자원 재할당, lock 전후 변화/읽기 실패 구분, static API의 지연 구성을 다룬다.
  초기 새 fixture의 tuple/필수 stage 오류는 기존 모델 정의에 맞춰 수정하고 해당 2개만 재확인했다.
- 초기 3개 검사의 Windows 긴 TEMP 경로 오류는 제품 수정 없이 `.tmp` 아래의 기존 테스트 환경으로
  맞춘 뒤 해당 검사만 재실행했다. 새 의존성을 설치하지 않았다.
- AST로 facade 359개 기존 정의와 옮긴 34개 흐름의 port 치환 외 제어 흐름 동일성을 확인했다.
  기존 fixture 15개 파일의 assertion을 유지했고 필요한 입력/소유자만 바꿨다.
- 새 명령 모듈을 별도로 import해 facade/bootstrap/Store/application을 불러오지 않음을 확인했다.
  변경 Python 구문·전역 이름/의존 경계, 문서 참조·owner 배정과 자기 변경 diff를 확인했다.
- 추가로 선택한 MCP 세션 기반 external-plan 사례는 응답 대기가 끝나지 않아 중단했다.
  통과 개수에 포함하지 않았다. 이 변경의 MCP fixture 대상은 실제 연결 집합 owner로 옮겼으며
  assertion/호환 계약은 정적으로 확인했다. MCP 실연동 완료로 보고하지 않는다.

UI/TypeScript·RPC method/저장 형식은 변경하지 않았다. 전체 suite·TypeScript 검사·빌드/패키징,
실제 AI/제품 화면·commit/push/외부 저장소 작업은 이번 범위에 없어 실행하지 않았다.

## P3 구현 범위

- 후속 `다음 해줘`에 따라 기획 API 26개와 그 실행에 필요한 기획 접수/AI 세션·계획 적용·대화/
  미리보기/요청 흐름을 이전한다. 공개 signature·저장 형식·잠금·실패/rollback 의미는 유지한다.
- bootstrap이 기능을 좁은 records/port로 구성한다. 기획에서 먼저 사용하는 provider 실행과
  Task 준비 phase도 함께 이전하고 기존 실행/통합 소비자는 같은 owner에 연결한다.
- 메시지 라우팅은 명령 조정 계층으로 옮긴다. feature에서 facade/명령으로 역참조하지 않으며
  색인의 refresh는 같은 feature 내부에서 호출한다. 빈 phase나 전체 Pipeline/Store/Config context는 만들지 않는다.
- 실제 AI·MCP 세션 검사는 실행하지 않는다. 기획 profile/대화·미리보기 stale/재전달·적용 실패 복원,
  기술 구성/기능 기획과 직접 호출 경계만 선택하고 나머지는 정적 계약/의존·diff로 확인한다.

## P3 구현 결과 — 2026-11-15

- 공개 기획 26개를 `orchestration.planning.PlanningCommands`에 연결했다. 공개 signature·binding·
  기본값/반환은 유지하고 facade 본문은 명시적 delegation만 수행한다. 입력/잠금/요청 순서는 명령
  계층이 소유하며 메시지 라우터도 `orchestration.planning_routing`으로 옮겼다.
- `PlanningIntake`·`PlanningAI`·`PlanningLifecycle`·`PlanningMessages`·`ResultRevisionAI`가 각각
  접수, 정책 scope 안의 생성/호출, 적용/실패 복원, 메시지/채널 판정, 결과 제안/대화 정리를 소유한다.
  새 feature는 facade/명령 객체/전체 자원 holder를 받지 않는다. 기존 기능 API를 직접 연결했다.
- `pipeline_planning_bootstrap`·`pipeline_provider_bootstrap`으로 구성 책임을 나눴다. 자원 holder는
  구성 함수 안에서만 사용하고 feature에는 좁은 기록/설정/기능 port만 넘긴다. 구성 시 Run 저장·
  Git/AI 실행이나 SDK 생성을 추가하지 않았다. policy ContextVar·SDK/credential snapshot·host 종료 수명은 유지했다.
- 최초 소비자인 Task 준비와 provider 구성을 함께 옮겼다. 기존 실행/통합은 같은 owner를 공유한다.
  runtime/phase는 명시적 호출 경계를 가진 요청별 객체이며 설정 DTO와 달리 좁은 fake 입력을 주입할 수 있다.
- 56개 class 구현/조립 메서드를 facade에서 제거했다. 기획 helper의 불필요한 연결 33개도 제거했고,
  실행/통합이 쓰는 기획 연결 12개와 provider endpoint는 P4~P5에서 정리한다.
  색인의 `refresh_index` callback은 제거하고 같은 기능의 `refresh()`를 직접 호출한다.
- **Pipeline 5,013 → 4,116줄(-897)**. 재설계 최초 5,495줄 대비 **1,379줄 감소**.
  비-property 직접 정의는 377 → 321개이며 공개 메서드 112개는 유지했다.
  공개 이전은 **53/112개 완료**, 남은 **59개**다. 다음은 **P4 실행·관제 API 32개**다.

### P3 실제 검증과 제한

- 공개 계약/생성 지연과 공유 정책 scope, 기획 binding/저장 실패·보관 대화, 준비 상태 저장,
  색인 재사용/시간 제한, 미리보기 stale·재전달·실패 복원/대기 요청, Claude 세션/SDK 재시도,
  기술 구성/검증 후 기능 계획과 실패 재시도, 계획 편집/제외의 관련 사례만 선택했다.
- **35개 테스트 + 2개 subtest 통과**. provider SDK 오류 변환/빌린 SDK 소유권과 외부 계획의
  AI/연결 조회 없는 재전달·저장 보존도 포함한다. 외부 계획은 MCP 세션 없이 공개 API로 확인했다.
- 초기 기획 호출 어댑터에서 누락된 기존 reasoning 검증 callback을 복구하고 해당 실패 사례만
  재확인했다. 색인 테스트의 patch 위치는 실제 owner로 옮기고 기존 호출/timeout 기대를 유지했다.
  새 외부 계획 fixture는 기존 필수 description 계약에 맞춰 보정했다. 오류를 기본값/성공으로 숨기지 않았다.
- 기획 profile의 agent 조회도 지연 getter로 연결했다. config/agents 교체 후 공개 `run_planning`이
  새 agent의 profile을 고정하는 경계를 추가 확인해 생성 시점 mapping의 잔류를 방지했다.
- AST로 이전한 핵심 22개 흐름과 라우터 class의 제어 흐름이 port/factory 치환 외에 같음을 확인했다.
  변경 밖 facade 정의 306개와 공개 112개 signature를 보존했고, 실제 이전한 26개는 단일 위임으로 확인했다.
- 기존 fixture의 입력/소유자를 이전했으며 expectation/실패 기준을 약화하지 않았다. 새 모듈의 직접
  의존/port shape·전역 이름, Python 구문과 자기 변경 diff·문서/소유권 참조를 확인했다.

전체 suite·빌드/패키징·UI/실제 AI·MCP 세션·commit/push/외부 저장소 작업은 범위 밖이므로 실행하지 않았다.
다음 한 단계는 **P4 실행·관제 API 32개**다.

## P4 구현 범위

- 실행 16개·관제 16개 API와 해당 실행/정책/Task·수동 완료·관제/복구 조정 책임을 실제 owner로 이전한다.
  공개 signature·저장 형식·승인/잠금·중단/부분 실패 의미는 유지한다.
- 필요한 검증/복구 phase는 첫 소비자인 관제와 함께 이전한다. P5 공개 API는 이번에 선행 이동하지 않으며
  남은 facade 소비자는 같은 phase owner를 사용한다. feature에서 Pipeline/전체 Store/Config를 받지 않는다.
- provider·기획·조회는 이전 단계의 실제 owner를 직접 사용한다. 관제 조정 workflow는 명령 계층으로
  분류하고 기존 기능 간 협력은 제한된 API/records로 연결한다.
- 실행/관제의 관련 실패·중단/대상 변경·정책 시작/종료·부분 복구 사례만 선택한다. 전체 suite·빌드·
  실제 AI/MCP 세션·외부 저장소·commit/push 작업은 수행하지 않는다.

## P4 구현 결과 — 2026-11-15

- 공개 실행 16개·관제 16개를 `orchestration.execution.ExecutionCommands`와
  `orchestration.control.RunControlCommands`에 연결했다. 공개 signature·기본값·오류 계약은 유지한다.
- 실행/재개·dispatch는 `execution.flow`, 정책 prepare/save/start·복원/finish는
  `execution.policy_lifecycle`, 프로필 예약·quota 대체는 `execution.profile_workflows`가 소유한다.
  작업·리뷰·수동 완료는 `execution.task_workflows`가 기존 기능 API를 조합한다.
- 관제가 먼저 사용하는 검증/복구 phase는 `integration.verification_flow`·`recovery_flow`와
  `execution.verification_commands`로 함께 옮겼다. 공유 workspace 접근은 `WorkspaceAccess`로 연결했다.
  P5의 공개 통합/수명 API 27개는 아직 이전하지 않았다.
- 경로 승인과 관제 조정 workflow는 `orchestration.scope_approval`·`chat_workflows`에 둔다.
  공개 관제의 실패 기록과 child 요청 scope를 내부 action phase와 구분해 보존했다.
- `pipeline_execution_bootstrap`은 구체적인 객체와 역할별 persistence port만 구성한다.
  feature에 전체 Pipeline/Store/Config나 자원 holder를 전달하지 않는다. 같은 실행 제어 객체의
  `owned_session`이 세션 생성·종료를 맡으며 동일 state lock·provider/SDK·기획 owner를 재사용한다.
- 구현/조립 메서드 145개와 사용처가 사라진 관련 별칭 22개를 facade에서 제거했다.
  기존 공통/기획/조회 연결 29개도 정리했다. P5 소비자가 쓰는 phase 연결 19개는 명시적으로 남겼다.
- **Pipeline 4,116 → 2,215줄(-1,901)**. 최초 5,495줄 대비 **3,280줄 감소**.
  비-property 직접 정의는 **321 → 176개**, 공개 메서드 112개는 유지한다.
  공개 이전은 **85/112개 완료**, 남은 **27개는 P5 통합 21개·수명 6개**다.

### P4 실제 검증과 제한

- 공개 계약, 실행 정책 시작/중단 복원·실패 재개·snapshot drift, 병렬 Task 중단/세션 정리,
  관제의 대상 변경·취소/child 소유권·실패 한도, 범위 승인/재시도, quota 대체를 선택 확인했다.
- 수동 Task의 선택 인계·검증 후 의존 작업 해제, 검증 입력 변경의 stale 처리,
  통합 뒤 용량 실패의 부분 복구, 프로필 적용 중단/복원도 확인했다.
- **서로 다른 테스트 44개 + subtest 4개 통과**. wrapper 수정 후 직접 영향받는 관제 사례만
  재확인했으며 그 중 1개 재실행은 위 개수에 중복 산입하지 않았다.
- 자원 교체·생성 지연/빌린 SDK와 정책 scope 검사를 재사용했다. 기존 patch 대상은 실제 owner로
  이전하고 검증 명령 adapter의 patch도 새 모듈로 이동했다. 기대값/실패 기준은 약화하지 않았다.
- AST로 이전한 **177개 정의**의 흐름이 명시적 port/이름 치환 외에 같음을 확인했다.
  공개/내부 관제 메서드의 이름 충돌을 이 비교에서 발견해 구분했고, child scope·실패 기록 사례를
  재확인했다. 변경 밖 facade 정의 155개도 유지했다.
- 직접 feature 의존 방향·전역 이름·port shape, 수정 Python 구문·diff와 소유권/문서 참조를 확인했다.

전체 suite·빌드/패키징·UI·실제 AI/MCP 세션·commit/push·외부 저장소 작업은 실행하지 않았다.
다음 한 단계는 **P5 통합/수명 API 27개 이전과 facade 1,000줄 이하 마무리**다.

## P5 구현 범위

- 공개 통합 21개·수명 6개와 해당 Main 반영/복구·충돌/결과·push/deploy·보관/삭제 조정을 이전한다.
  기존 공개 signature·승인·잠금 순서·HEAD 재검증·실패/부분 성공 기록은 유지한다.
- 앞선 단계의 실행/검증·기획·workspace owner를 직접 연결하고 남은 facade private bridge/별칭을 정리한다.
  테스트 hook은 실제 owner로 옮기며 전체 Pipeline/Store/Config 전달이나 facade 역호출을 만들지 않는다.
- 112개 API와 알려진 import·자원 속성 계약을 보존한다. facade는 명시적 delegation과 호환 진입점만 남겨
  1,000줄 이하로 정리한다. 저장 형식·모델·UI·Rust·실제 대상 프로젝트는 변경하지 않는다.
- 공개 계약과 직접 영향받는 Main 부분 실패/재시도·충돌 승인·보관/삭제 보호 사례를 선택한다.
  전체 suite·빌드/패키징·UI/실제 AI·MCP·외부 저장소·commit/push/deploy는 실행하지 않는다.

## P5 구현 결과 — 2026-11-15

- 통합 21개·수명 6개를 `orchestration.integration.IntegrationCommands`와
  `orchestration.lifecycle.LifecycleCommands`로 이전했다. **공개 API 112/112개 배정 완료**다.
  생성자·112개 signature/binding·기본값과 알려진 모듈 import·자원 속성을 유지한다.
- `MainApplyFlow`는 Main 반영/완료·Push 확인·Git operation·배포 phase를,
  `ConflictFlow`는 후보 생성/조회·프로필·명령 조합을 소유한다.
  명령은 기존 승인·project/run/chat 잠금 순서를 유지하며 확보한 잠금 안에서 phase를 호출한다.
- `WorkspaceFlows`는 workspace 수명/상태·삭제 대상·SDK idle 정리와 지연 실패 기록을,
  `ArchiveFlow`는 기록 선저장 구성·commit 보호·정리/부분 실패를 조합한다.
  보관 factory도 기능 내부에 두어 command/facade callback을 받지 않는다.
- `pipeline_integration_bootstrap`은 제한된 records/getter와 구체적인 객체만 연결한다.
  전체 Pipeline/Store/Config·자원 holder를 feature에 전달하지 않는다. 기존 검증·기획·provider·SDK와
  state lock을 공유하며 SDK 생성/종료·저장 형식·Git 승인 권한을 추가하지 않았다.
- 존재 확인은 `RunLookup.require_known`으로 통일해 기존 ValueError와 관제/삭제의 순서를 유지한다.
  삭제 한도 상수는 삭제 기능이 소유하며 facade의 기존 import 이름/값을 유지한다.
- 남은 private 구현/조립 정의 **63개**, class 별칭 **61개**와 instance bridge를 제거했다.
  기존 기능에 이미 구현된 wrapper는 중복 복사하지 않고 해당 API를 직접 사용한다.
  의도적으로 노출하던 모듈 import와 자원 property는 보존했다.
- **Pipeline 2,215 → 977줄(-1,238)**. 최초 **5,495 → 977줄(-4,518)**이다.
  비-property 정의 **176 → 113개**는 생성자 1개와 공개 API 112개다. 업무 private helper·class 별칭과
  동적 forwarding은 없다. signature 축약·mixin·숨은 전체 context 없이 목표를 달성했다.

### P5 실제 검증과 제한

- **테스트 21개 + subtest 3개 통과**. 공개 계약·Main 갱신 승인·검토 후 별도 Push 승인,
  Main Push 실패 재시도, 프로세스 중단 뒤 ref/index/작업 폴더와 stale 잠금 복구를 확인했다.
- 실제 임시 Git 저장소의 충돌 후보 생성/검토/적용과 수동 제작→검증→전송/배포,
  보관 snapshot 실패·부분 정리와 재시도, 삭제 승인·한도·외부 경로 보호를 선택 확인했다.
  결과물 등록의 commit/content 고정, 기획 agent 기본값, 자원 생성 지연/교체·빌린 SDK,
  stop signal의 원래 store 유지와 static 조회의 무구성 호출도 포함한다.
- 초기 로컬 bare 저장소 전송 2개는 제품 코드 진입 전 sandbox에서 실패했다.
  같은 경로의 읽기로 sandbox 제한임을 확인하고 해당 전송 사례만 권한 실행으로 재확인했다.
  Git은 file 프로토콜만 허용했으며 실제 외부 원격이나 대상 프로젝트에는 접근하지 않았다.
- AST로 이동한 원래 정의와 추출한 보관 factory **62개**가 명시적 port/이름 치환 외에 같음을 확인했다.
  112개 signature와 남긴 공개 본문·27개 새 delegation을 보존했고 최종 manifest의 생성자 포함
  **113개 signature/binding**도 현재 코드와 일치한다.
- 수정 Python **15개**와 기존 fixture **13개**의 구문, 전역 이름·port·의존 방향·중복 메서드,
  자기 변경 diff·공백·문서 참조를 확인했다. 기존 patch 위치를 실제 owner에 맞췄으며 기대값이나
  실패 조건은 약화하지 않았다.

P1~P5의 요청 범위에 남은 필수 구현 항목은 없다. 전체 suite·빌드/패키징·실제 UI/AI·MCP 세션,
실제 원격 push/deploy·commit·외부 저장소 작업은 범위 밖이므로 수행하지 않았다.
단계를 더 추가하지 않으며 이후 기능 변경이나 새 결함은 별도 요청 범위로 다룬다.

## 빌드·푸시 전 추가 검증 — 2026-11-15

- 사용자 요청에 따라 누적 변경의 production build·타입 확인과 CLI/RPC·상태/저장·알림·기능 경계를 확인한다.
- 첫 선택 검사에서 326개가 통과했고, 실행/기획 package import의 무 I/O 경계 2개가 실패했다.
  Git 오류/timeout과 annotation import가 실행 adapter를 불러오는 원인이다.
- 공개 package export를 유지한 채 Git의 순수 계약을 `git_contracts`로 분리해 기존 `git`에서 재노출하고,
  annotation 전용 GitWorkspace/PlanningSourceIndex는 TYPE_CHECKING 아래로 옮긴다.
  Git 예외의 계층·의미와 기존 import 객체의 동일성은 유지한다. 관련 실패 사례와 소비자만 재확인한다.
- 성공한 build/검증 결과를 재사용하고 개인정보·원격 전송 범위 확인 후 승인된 commit/push를 수행한다.

### 빌드·푸시 전 확인 결과

- 타입 검사와 Electron main/preload·renderer production build가 통과했다.
- 백엔드 선택 검사 328개 중 import 경계 2개를 수정해 재검사했고, Git 소비자 4개도 통과했다.
  최종 **Python 332개 + subtest 79개**, 알림/창 복원·갱신 진단 **JS 43개**가 통과했다.
  통과한 다른 검사는 반복하지 않았다.
- 공개 export는 삭제하지 않았다. GitError/로컬 한도는 순수 계약으로 공유하고 annotation import만
  TYPE_CHECKING으로 옮겨 두 package의 기존 무 I/O 계약을 복원했다. Git 예외 계층/alias 동일성도 확인했다.
- Python wheel 생성이 통과했고 현재 소스의 Python 모듈 221개가 빠짐/잔여 파일 없이 내용까지 일치했다.
  wheel에서 실제 CLI help와 최종 명령/API import를 확인했다. 빌드 frontend의 namespace 충돌은
  설치된 pip/setuptools로 처리했으며 Windows 임시 경로 길이 제한은 저장소 내부의 짧은 TEMP로 해결했다.
- 외부 AI/MCP 세션·실제 UI 조작·전체 suite·ZIP 릴리스/배포는 실행하지 않았다.
  릴리스는 별도 요청 범위이며 이번 산출물은 로컬 build 검증용이다.
