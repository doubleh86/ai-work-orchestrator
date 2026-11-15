# 아키텍처

## 결정

AI Work Orchestrator는 **모듈러 모놀리스 코어 + 로컬 데스크톱 셸**로 개발한다.
도메인과 실행 규칙은 하나의 Python 패키지에 유지하고, CLI는 같은 프로세스에서,
Electron 데스크톱 앱은 설치 제품 내부의 Python 자식 프로세스들을 통해 이 코어를
호출한다. 내부 코드는 책임과 의존 방향이 명확한 모듈로 분리한다.

현재 문제는 한 로컬 제품 안에서 Git worktree, 에이전트 실행, 상태 저장과 승인
단계를 조정하는 것이다. Electron과 Python의 프로세스 분리는 UI sandbox와 생명주기
관리 경계일 뿐 독립 배포 서비스 경계가 아니다. 네트워크 서비스보다 제한된 로컬
IPC와 원자적인 상태 흐름을 우선한다.

## 배포와 런타임 경계

- 사용자 배포 단위는 CLI Python 패키지 또는 Electron 데스크톱 설치 앱이다.
- 진입점은 `ai-orchestrator` CLI와 Electron 데스크톱 앱이다.
  `ai-orchestrator desktop`과 `ai-orchestrator-desktop`은 같은 Electron launcher를
  호출한다.
- 실행 상태는 대상 저장소의 `.ai-orchestrator/` 아래에 저장한다.
- 신규 격리 작업 공간은 대상 저장소의 `.ai_auto_work/worktree/` 아래에 만든다.
  신규 그룹은 해석된 절대 root를 상태에 고정하며 기존 그룹과 사용자 지정 경로는
  저장된 실제 위치를 유지한다.
- Run worktree의 청결 검사는 설정된 상대 `state_dir` 아래의 untracked 런타임 생성물만
  제외한다. 같은 경로의 tracked 변경과 관리 경로 밖의 변경은 계속 차단한다.
- 프로젝트 registry는 운영체제별 사용자 설정 디렉터리에 JSON으로 저장한다.
- 공식 Codex SDK는 같은 앱 설정 root 아래 `codex`를 전용 CODEX_HOME으로 사용한다.
  CLI와 모든 desktop backend가 같은 앱 인증을 사용하며 Codex 앱·CLI의 공용 인증·환경
  자격 증명을 가져오지 않는다. 인증 파일은 SDK가 전용 home에서 관리한다.
- 대상 저장소에 설정 파일이 없는 등록 프로젝트의 기본 TOML은 registry와 같은 사용자
  설정 root 아래의 프로젝트별 관리 디렉터리에 저장한다.
- Electron main은 같은 `desktop_rpc` 모듈을 실행하는 제어용·Planning용·Task 작업용
  Python backend 자식 프로세스를 소유하고 각각 표준 입력과 출력의 JSON Lines RPC로만
  호출한다. localhost HTTP 서버나 임의 포트를 열지 않는다.
- 창 닫기는 트레이로 숨겨 renderer·Python 작업과 알림을 유지한다. 트레이의 열기로 같은
  창을 복원하고, 종료는 미저장 확인을 거쳐 모든 창의 닫기가 승인된 뒤 backend를 한 번
  정리한다. 종료를 취소하면 다시 숨김 동작을 적용한다. 트레이 생성 실패는 화면에 알리고
  일반 창 닫기를 허용한다.
- Planning 요청은 프로젝트·run ID별 소유권과 전용 자식 프로세스를 사용하여 같은
  프로젝트의 다른 대화도 동시에 처리한다. 같은 대화의 변경 요청은 직렬화하며,
  답변 중단은 해당 대화의 프로세스만 종료한다. 5분 동안 요청이 없는 대화 프로세스는
  정리하고, 앱 종료·재시작 시에도 소유한 모든 프로세스를 종료한다.
- React renderer는 `contextIsolation: true`, `sandbox: true`,
  `nodeIntegration: false`로 실행한다. preload는 method가 제한된 API만 노출하고
  raw `ipcRenderer`, 경로 접근 또는 command 실행 능력을 넘기지 않는다.
- 작업 기록 파일 열기는 고정 preload API가 프로젝트·그룹·작업 ID만 받는다.
  Electron main은 기존 Python 조회 RPC로 선택 작업을 검증한 뒤 임시 UTF-8 `.txt`
  사본을 만들고 OS 기본 편집기로 연다. 임의 renderer 경로나 실행 명령은 받지 않는다.
- Python backend가 registry, Pipeline, run lock, 상태 파일과 Git 부작용의 최종
  권한자다. stdout은 RPC frame 전용이고 진단 로그는 stderr로 분리한다.
- CLI와 Planning·Task 작업용 Python backend는 공식 Python Codex SDK client를 지연 생성해
  재사용한다. 배포본은 작업 PC에 설치된 Codex 실행 파일을 SDK에 전달한다. 소스 실행은
  기본적으로 SDK 런타임을 사용한다. 각 진입점은 종료 시 자신이 소유한 SDK client를 닫는다.
- `codex_sdk`는 종료가 확인된 안전한 503·모델 혼잡 실패만 같은 thread에서 지연 재시도한다.
  SDK 재접속 중에는 새 turn을 만들지 않으며 실제 도구·파일 행동이 시작됐으면 자동 반복하지 않는다.
  대기는 활동 증거와 구분하고, Pipeline callback으로 종료된 호출과 새 호출의 사용량 기록을 분리한다.
- Electron main은 Python backend의 표준 입출력을 UTF-8로 고정하고, backend 응답은
  ASCII-safe JSON escape를 사용한다. Windows locale 문자 집합이 표현하지 못하는 run
  상태 문자열도 JSON Lines frame 손실 없이 renderer로 전달한다.
- Python 모듈 사이에는 HTTP, 메시지 브로커 또는 별도 데이터베이스를 두지 않는다.

### UI·셸·엔진의 책임

이 절은 현재 Python 제품 내부의 경계다. 별도로 분리하는 Rust 프로젝트와의 엔진 교체·
API 통합·UI 공유는 이 설계의 대상에 포함하지 않는다.

React는 화면과 입력, Electron main은 창·트레이·파일 선택·OS 알림·native 확인·credential
저장과 backend 수명을 소유한다. Python은 계획·모델 배정·실행·검증·상태 전이와 Git 부작용의
최종 권한을 가진다. UI의 표시·최신 상태 확인·중복 클릭 방지는 코어 검증을 대체하지 않는다.

공용 응용 API는 `application.OrchestratorApplication`이다. 프로젝트 등록 snapshot·SDK 수명과
공개 기능 조합을 소유하며 화면이나 RPC transport에 의존하지 않는다. MCP는 이 API를 직접
사용하고 CLI는 같은 패키지의 `create_pipeline`으로 실행기를 구성한다.
`desktop_rpc.DesktopApplication`과 `RpcError`는 공용 클래스/오류의 호환 별칭으로 유지한다.

`application.summaries.ProjectSummaryQueries`는 프로젝트 상태 요약의 worker 4개·종류별 미완료
Future 캐시·잠금·5초 대기와 종료 시 대기 작업 취소를 소유한다. 프로젝트 이름 선택과 실제
Pipeline 조회는 공용 앱의 좁은 callback을 사용한다. 프로젝트별 오류·조회 종류별 캐시와 정렬을
유지하며, 공용 앱은 요약 조회 객체를 닫은 뒤 SDK를 닫는다. UI/RPC·실행/상태 변경은 맡지 않는다.

`application.planning_indexes.PreparedPlanningIndexes`는 프로젝트/정규화된 문서 경로별 준비 색인의
잠금과 일회용 인계를 소유한다. 공용 앱이 실제 색인 생성 뒤 등록하고 Planning 모델 선택 후 소비한다.
빈 문서 입력·generated_at 일치와 불일치 소비 순서를 유지하며 실제 생성/재검증·기획 실행은 Pipeline에 둔다.

`application.project_settings.ProjectSettingsService`는 작업 도구 설정/연결 확인·작업공간/역량·
코드 스타일 조회/수정을 소유한다. 프로젝트 조회·도구 목록·도구/스타일 수정 callback만 받고 registry나
Pipeline 전체를 받지 않는다. 승인/형식/revision 검사·probe 전후 확인·도구 lease와 최종 registry 쓰기를
유지한다. `registered_project_config`는 설정 repo 일치를 검증하며 공용 앱은 최신 등록 snapshot을 먼저
확인한 뒤 이 API를 사용해 기존 tool override·SDK/credential의 Pipeline 구성을 수행한다.

`rpc`는 연결·프로젝트·기획·실행·통합·그룹 기능별 handler와 정확한 메서드 allowlist를 소유한다.
요청 범위는 global/project/run으로 선언하고 params·메서드·project·run·세부 필드의 기존 검증
순서를 유지한다. 공통 요청/route·성공/실패 frame 타입을 명시하며 wire 형식·native 승인·
요청 ID·revision을 바꾸지 않는다. `desktop_rpc`는 JSON Lines 입출력·credential 요청 범위·
마스킹과 상태/제어/장기 executor·프로세스 종료를 소유한다.

`run_queries`는 실행 상태·사용자 확인·주의 항목·그룹 분류의 읽기 판정을 소유한다.
상태/잠금/실행 기록 DTO와 좁은 조회 callback만 받는다. `queries.summaries`는 실행 목록·
주의 항목·활동 그룹·사용자 확인 목록을, `queries.waiting`은 현재 근거에 맞는 다음 단계 안내를
조합한다. 조회 callback으로 잠금 전후 snapshot을 비교하며 Store/Pipeline/Config/Git 객체나
쓰기 API를 받지 않는다. 목록의 Git 조회 오류 허용과 주의 항목의 오류 전파 차이를 유지한다.
Pipeline은 실제 Git 조회와 실행·승인·상태 변경의 최종 권한을 유지한다.

`execution.invocation`은 caller의 transport 앞뒤로 작업 도구 lease·연결 검사와 사용량 기록을
조합한다. 작업 도구는 execute/revise에만 제공하며 재시도별 사용량과 실패/취소/timeout 종료를
유지한다. `planning.invocation`은 명시적으로 넘긴 정책 문맥·기록/command/provider callback으로
고정 프로필 검증과 호출 준비·진행 기록을 수행한다. ContextVar scope·정책 binding은
`planning.policy_scope.PlanningPolicyScope`가 소유하고 기존 기획 invocation과 같은 ContextVar를 사용한다.
기존 잠금·SDK/credential/process 수명은 해당 실행 소유자에 남긴다. 기획 invocation은 명시적
runtime import이며 `planning` 기본 import에 추가하지 않는다.
`execution.provider_runtime.ProviderRuntime`은 invocation/runner factory와 오류 변환 callback으로
공급자 호출 인자를 전달한다. Pipeline의 기존 instance 호출 hook을 bound callable로 연결하되
자원은 실제 요청마다 factory에서 구성한다. 현재 SDK/설정/인증키와 instance transport 대체를
보존하며 runtime에는 전체 Pipeline/Store/Config·SDK나 인증키를 전달하지 않는다.
인자·기본값·반환과 전달 방식이 소유 함수와 같은 private static 위임은 명시적 static 별칭으로
연결한다. 공개 메서드·실제 검증/변환·승인/잠금과 수명 조정 코드는 이 기준으로 생략하지 않는다.

`planning.preparation`은 최초 기획의 입력/문서·색인·초기 상태를 준비하고 원문 snapshot을 기록한다.
정규화/준비 확인/색인 조회 callback과 명시적 설정 값만 받는다. 예약 ID 존재·실제 Git 조회와
프로젝트 maturity/스타일 검사·초기 정책 저장 및 REVIEWED 전이는 Pipeline이 유지한다.
`planning.source_indexes`는 Git 준비 상태 DTO의 오류 안내와 기획 색인의 공통 deadline·갱신,
시작 시 변경 없는 색인 재사용과 실행별 snapshot 복원을 담당한다. 경로·실행 디렉터리와 읽기 전용
Git 조회/작업공간 경로·기존 색인 작성/갱신 callback만 받는다. 실제 준비 상태 검사는 Pipeline에
남기며 전체 GitWorkspace/Store/Config·SDK나 Run 단계/정책 쓰기 권한은 받지 않는다. snapshot 부재나
변경된 소스는 기존 public 갱신 API로 되돌려 보내고 오류를 빈 색인으로 숨기지 않는다.
`execution.task_logs`는 byte 제한을 받은 부분 읽기와 환경/실행/검증 로그·최종 실패 안내 조합을
담는다. Run/등록 Task 조회와 표시 제한값은 Pipeline에 유지하며 기록 디렉터리/읽기 callback을
사용한다. 로그 파일이나 상태를 쓰지 않고 기존 단일/복수 구간의 개행·잘림 안내와 오류를 보존한다.
`integration.workspaces.WorkspaceStatusQueries`는 읽기 전용 callback으로 공통 deadline·공유/개별
조회 대상을 구성하고 최대 네 개 thread로 상태를 읽어 원래 대상 순서로 반환한다. 실제 개별 상태와
안전 판단은 기존 inspector를 사용하며 정리/삭제·승인/잠금·Run 전이 권한은 받지 않는다.
`planning.features`는 검증한 기본 구조/기술 결정의 일치와 기능 요청 문맥·모델 결과를 검증한다.
실제 AI/SDK·시도/실패 기록·최종 단계 전이는 Pipeline에 남긴다. `planning.task_apply`는 기존 그룹
변경 전 snapshot·요청 claim·계획 병합·결과/실패 receipt를 맡으며 실행 준비·단계 결정과 실패 복원은
호출자에 남긴다. 기존 run/기획 잠금 아래에서만 사용하며 전체 Pipeline/Store/Config를 받지 않는다.

`integration.archive_views`는 보관 가능 사유·fingerprint·Task/통합 결과 근거의 요약과 보관 조회 표현을
만든다. 상태/정리 대상 DTO와 원격/배포 여부·기록 디렉터리 callback만 받으며 실제 Git·snapshot
저장/정리와 승인/잠금은 소유하지 않는다. `archive_commit_references`는 Task/통합/충돌 후보 commit의
순서/중복 제거와 참조 이름만 하나씩 반환하고 실제 Git 보호 참조 생성·timeout/오류는 Pipeline에 남긴다.
`planning.apply_requests`는 명시적 입력/준비 결과 DTO와
request ID·기술 구성/기획 반영의 revision/재전달 검증을 소유한다. 순수 검증의 기존 Pipeline
static 진입점을 유지하며 승인·잠금/실제 반영·최종 Run 전이는 옮기지 않는다.
조회/기록·검증/프로필/실제 적용 callback으로 반영 요청의 재생·대기·적용을 조합한다. 실행 중에는
Pipeline의 대화 잠금만, 즉시 적용에는 기존 run/chat 잠금 모두를 사용한다. 최종 적용/전이는
Pipeline의 callback을 통해 수행하며 조회 후 잠금 안의 재검증 순서를 유지한다.
`execution.project_chat.ChatControlAdvancement`는 기존 요청 제어 잠금/operation API로 중지
확인과 오래된 대상·복구 가능 여부를 검사해 다음 행동 응답 또는 보류 기록을 만든다. 프로젝트
채팅의 진행/중단 분기도 이 기록 경계를 사용한다. 실제 stop/repair/verify와 SDK 수명은 소유하지 않는다.

`execution.preparation.TaskExecutionPreparation`은 명시적인 Git adapter와 경로/경계/프롬프트·
기록 callback으로 공유/개별 작업공간과 실행 파일을 준비한다. 기존 경계 검사·선택 Task·persist
옵션과 호출 순서를 유지하며 잠금/승인/정책·최종 Run 단계는 소유하지 않는다.
`execution.chat_recovery`는 부모/실패/대화·범위/검증 근거와 상담의 Task/시각을 확인해 지시를
저장하고 재생/검증 전용 결과 DTO를 반환한다. Pipeline의 기존 run/chat/revision 잠금과 실행
session, timeout 보완·실행 루프를 그대로 사용하며 저장 실패/재전달이 실행을 새로 시작하지 않는다.
`integration.recovery_apply`는 복구 요청 claim·통합 결과/후속 기획·부분 실패 operation 기록을
조합한다. 명시적 승인과 run/chat 잠금, 실제 Git 통합과 기획 effort scope는 Pipeline에 남긴다.
통합 후 기획 실패에서는 commit과 적용 대기 요청을 보존하고 재시도는 기존 복구 검증을 거쳐 기획만 수행한다.

`execution.scope_approval`는 기존 run/chat 잠금 아래에서 현재 부모/승인·범위/미리보기/정책을
검증하고 일회성 요청 claim·계획 적용 callback과 결과 기록을 조합한다. 요청 제어 잠금 API만
제공받으며 실제 선택 Task 재시도·실행 session과 반영 후 부모 취소 확인은 Pipeline이 유지한다.
`integration.archive_workflow`는 Git adapter와 좁은 기록/보호/정리 callback으로 원본 snapshot·
manifest·operation을 먼저 보존하고 정리를 시작한다. Pipeline은 승인/입력·Git 준비와 기존
project/run/chat 잠금을 유지한다. 같은 모듈의 `ArchiveCleanupWorkflow`는 좁은 조회/claim/저장과
기존 정리 callback으로 재시도/재전달·대상별 오류/부분 결과를 기록한다. 승인/request ID·잠금과
보관 존재 확인/SDK idle client 정리는 Pipeline에 남기고 새로운 Git/삭제 권한은 받지 않는다.
`integration.deletion`은 Git adapter와 기존 소유 경계/대상
callback으로 작업공간/branch를 정리하고 결과 DTO만 반환한다. 공유 시간 예산·승인/실행 잠금과
SDK client 정리·최종 기록 삭제/대화 종료의 순서는 Pipeline에 남긴다. 경로 보호 규칙을 완화하지 않는다.

`execution.startup`은 누락된 실행 파일과 명시적 override를 준비하고 실패/선택 재시도의 Task를
정리한다. 재시도 결과는 resume 여부와 기록 문구 DTO로 전달하며 Run resume/단계 전이·최종 저장,
준비 step/dispatch는 Pipeline이 유지한다. `execution.policy_snapshot.ExecutionPolicyPreflight`는
현재 모델 목록과 확정 계획/preview/가용성 callback으로 복구 mode·worker/reviewer/기준선을 검증한다.
정책 binding의 기존 검사/해제·snapshot 생성과 prepare/start·RunState 참조 저장은 Pipeline에 남긴다.
`execution.chat_profiles`는 기존 run/chat 잠금 안에서 대상/취소·가용 AI·프로필 저장/재확인을 처리해
명시적인 저장 결과 DTO를 반환한다. 잠금을 해제한 뒤 원래 복구 진입점을 호출하고 실제 결과를 기록한다.
좁은 기록/제어 잠금 API와 callback만 받으며 저장 실패/취소/대상 변경이 복구를 시작하게 하지 않는다.

`orchestration.planning_routing`은 보관/실행 대화와 초기 Task/inline 변경·미리보기/반영 경로를 기존
조회/기록·대화 잠금 factory 및 callback으로 분기한다. inline 지시를 먼저 저장하고 일반 대화는
`PlanningCommands`의 run 잠금/프로필·AI 호출/단계 기록으로 넘긴다. 독립된 잠금을 만들지 않는다.
`planning.preview_apply`는 기존 run/chat 잠금 안에서 저장 후보·현재 상태/보호 Task/차이를 검증하고
`PlanningLifecycle`의 계획 적용 API로 반영한 뒤 요청/방향 변경 결과를 기록한다. 저장 schema/digest와
최종 Run 전이 권한은 유지한다. `execution.run_verification`은 기존 runner 앞뒤의 attempt/log와
경과 시간·진행/성공/실패 기록을 조합한다. 설정/명령/HEAD 검사·취소는 caller의 좁은 API를 사용하며
구체적인 취소 신호 타입은 Generic 계약으로 유지한다. 최종 Run 단계 전이는 소유하지 않는다.
같은 모듈의 명령 선택 함수는 프로젝트 명령 우선·Task 명령 중복 제거와 기존 관리 명령 제외
callback을 사용한다. `VerificationFailureEvidence`는 공통 명령 존재 여부·commit queue/저장 callback으로
환경/파일 잠금과 소스 실패의 관련 후보를 기록한다. 단일 원인을 확정하지 않고 기존 조회/저장 순서를 유지한다.
`execution.results.record_group_result`는 검증 attempt의 중복 기록 방지와 commit 파일 근거/시각을
기록한다. 실제 commit 조회·검증 성공 시점의 호출/저장은 Pipeline에 남기며 최종 Run 전이를 소유하지 않는다.
`integration.operations`는 기존 operation 조회/claim/저장 API로 Main 요청의 UUID·대상 digest·검토 ID와
완료 재생·실패 기록을 처리한다. Git 실행이나 Run 단계 전이를 소유하지 않는다.
`integration.main_preflight`는 Pipeline의 project/run 잠금 안에서 공유·분리 작업의 Task/Main/통합 commit 근거를 확인하고,
검증 무효화와 Main 준비 확인은 기존 owner callback으로 수행한다. 승인·공유 작업공간 분기·operation
claim과 실제 Main 반영은 Pipeline에 남긴다. `integration.conflict_verification`은 최초 후보 적용의
run 잠금이 해제된 뒤 후보 정리·후속 검증·새 attempt 연결과 operation 결과를 기록한다. 기록용 잠금은
기존 factory, 실제 검증과 최종 Run 전이는 Pipeline API를 사용한다. 전체 Store/Config/Pipeline을 받지 않는다.
`integration.publishing`은 공유·분리 Push 사전 검사와 원격 HEAD 일치·중복 receipt/operation 근거를
처리한다. 원격 값은 기존 저장 뒤에 조회하며 실제 Push·승인/잠금·최종 Run 전이는 Pipeline에 남긴다.
`integration.verification_repair`는 검증 수정 후보의 작업공간·범위 검사·commit/통합 branch 갱신과
근거/정리를 조합한다. Agent 선택과 SDK/취소 수명은 기존 runner 소유자가 유지하고 제안 callback만
전달한다. 기존 proposal DTO는 타입 참조로 재사용하며 최종 Run 전이를 소유하지 않는다.
`planning.plan_application`은 계획 교체의 Task 프로필 출처/리뷰 근거·기술 결정/기본 구조 구성,
대화 문맥과 확정 구성 검사·적용 성공 지표, 검증한 기본 구조 이후 기능 계획의 내용/출력 구성을
담는다. 각 서비스에 필요한 snapshot/구성/계획 적용·출력/기록 callback만 전달한다. 실제 AI 호출과
SDK 수명, 최초/실패 단계 기록·최종 Run 전이와 오류 복구는 Pipeline에 유지한다.
`execution.manual_tasks`는 수동 작업공간의 소유권/Git 등록·청결/HEAD 검사, 보류/재개의 실행 점유와
기준 commit·의존성 확인, 검증 뒤 완료 commit/result 기록을 담당한다. 명시적 Git adapter와 좁은
검사/기록·기존 다음 작업 준비 callback만 받는다. run/chat 잠금·리뷰/실패 Run 단계 기록과 다음
작업 활성화 실패 처리·최종 그룹 전이는 Pipeline에 남긴다.
`planning.control_decisions`는 프로젝트 판단 문맥과 읽기 전용/승인 거부 profile의 prompt/log·기록,
기존 effort scope/AI 호출·응답 파싱을 조합한다. 문맥은 명시적 조회 callback을 사용하고 chat 잠금,
SDK/정책 수명과 실제 실행 권한은 Pipeline에 유지한다. `execution.scope_consent`는 기존 요청 제어
잠금 안에서 최신 요청/대상·제안과 판단 결과를 재검증해 기록한다. 잠금 해제 뒤 승인 준비/대화 기록과
실제 scope 적용은 Pipeline에 남긴다. 새 모듈이 전체 소유 객체나 독자적 승인/Run 전이를 받지 않는다.
`planning.initialization`은 외부 기획 입력의 정규화/검증·digest와 초기 상태 구성을 담당한다.
저장소 문맥은 명시적 경로와 성숙도/스타일 callback으로 구성하며 main branch·작업공간과 스타일
설정은 기존 시점에 조회한다. 같은 ID 재생/충돌·chat 잠금·기준 commit 재확인과 실제 Task 검증,
상태/문서 저장·effort 초기화·최종 Run 전이는 Pipeline에 유지한다.
`execution.task_invocation`은 시작된 정책/binding·snapshot/Agent/runtime 근거와 Task 호출 문맥을
확인한다. command/model/reasoning·usage/시도·진행/profile과 Generic 취소 신호를 기존 provider
호출 API에 전달하며 정책 binding과 SDK/credential 수명은 소유하지 않는다. `execution.effort_plan`의
반영 서비스는 기존 잠금 안에서 revision/단계·preview/변경/출력·상태/대화 기록을 조합한다.
실제 변경 준비 callback을 원래 시점에 실행하며 전체 소유 객체나 최종 Run 전이 권한을 받지 않는다.
`planning.plan_review`는 계획 확정 전 revision/기본 구조·강도/Task 후보 확인과 Task 제외의
의존성/사용자 확인·출력/기록을 담당한다. 실제 계획 승인과 run 잠금/허용 단계는 Pipeline에 유지한다.
`execution.user_checks`는 revision/확인/기준 commit·중복/통과 확정 조건을 검사해 확인 결과를
기록한다. commit 실재 확인은 기존 읽기 전용 callback을 사용하고 입력/enum·확정 계획 요구,
잠금·최종 그룹 전이/저장은 Pipeline에 남긴다. 동일 결과 재전달 외의 실패를 성공으로 바꾸지 않는다.
`queries.scope_approval`는 좁은 조회 API로 승인 결과와 현재 제안/과거 안내 근거를 읽는다. 저장이나
승인을 수행하지 않으며 공용 제안 ID/승인 문구 판정 규칙을 재사용한다. `execution.chat_profiles`의
변경 준비 서비스는 기존 요청 제어 잠금 안에서 단일 Task/실행/시도·profile 근거를 기록한다.
`execution.chat_recovery`의 자식 기록 scope는 전달받은 기존 요청 잠금과 검증/기록 API로 부모/
자식과 yield·성공/오류 기록을 관리한다. 부모 없음/프로젝트 부모의 진입 경로, 실제 변경/복구·
run/chat 잠금과 최종 Run 전이는 Pipeline에 유지한다.
`planning.direction_changes`는 같은 방향 수정의 재전달·남은 Task/진행 작업과 기존 preview를
확인하고 대화/후속 지시를 기록한다. `planning.result_revisions`의 제안 준비는 읽기 전용 Agent/
근거·prompt/산출물·대화 ID를 DTO로 구성한다. 실제 provider 호출·응답 검증·SDK 정리는 Pipeline에
남긴다. `planning.request_records`는 시작/재분류·소유 조회·완료 operation을 처리하며 요청 잠금,
실행 종료 확인과 기획 중단/Run 전이·대화/SDK 정리는 기존 Pipeline이 유지한다.
`execution.provider_commands`는 작업/리뷰 명령 선택과 모델/추론 강도·Claude 세션 인자를 구성한다.
상태·실행·세션 수명을 소유하지 않으며 강도 검증은 기존 Pipeline classmethod callback을 사용한다.
`execution.provider_choices.ProviderAvailability`는 Agent 조회·SDK/키 준비 여부 bool과 명령/실행 파일
callback으로 가용성과 필수 Agent 조건을 검사한다. 실제 SDK/인증키·환경 조회와 선택 제외 정책,
실행/승인·잠금·Run 전이는 Pipeline과 기존 실행 소유자에 유지한다.
`planning.profiles`는 기획 Agent/모델/강도의 명시적 설정과 출처·기준값/Claude 대화 ID 메타데이터,
자동 모드의 기획 프로필 적용을 담당한다. 기본 Agent/가용성·정규화/검증과 선택 모드 조회 callback만
받으며 전체 Config/Store/Pipeline·SDK나 정책 저장/실행·최종 Run 전이 권한을 받지 않는다.
`planning.bootstrap.replace_tech_stack_decision`은 기존 결정 대체와 revision/사용자 답변·출처/후보 사본을
기록한다. 실제 구성 확정/계획 승인과 기존 run/chat 잠금은 Pipeline에 유지한다.
기능 모듈 분리 결과는 [기존 계획](../DevDocument/Plan/2026-11-13-python-module-refactoring.md),
최근 흐름 단위 작업은 [33~42단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch33-42.md)에 기록한다.
대화·Task 재시도·검증 복구의 후속 경계는 [43~52단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch43-52.md)을 따른다.
결과 수정/프로젝트 채팅의 기록과 runtime 경계는 [53~62단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch53-62.md)에 기록한다.
AI 호출/실행 목록 조회의 후속 경계는 [63~72단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch63-72.md)에 기록한다.
기획 준비/기능 계획/Task 변경의 후속 경계는 [73~82단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch73-82.md)에 기록한다.
보관 기록/기획 반영/채팅 후속 판단은 [83~92단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch83-92.md)에 기록한다.
실행 파일 준비/채팅 복구/통합 후 재계획은 [93~102단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch93-102.md)에 기록한다.
경로 승인 반영/보관/삭제 수명은 [103~112단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch103-112.md)에 기록한다.
실행 준비/정책 사전 검증/채팅 실행 AI 변경은 [113~122단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch113-122.md)에 기록한다.
기획 메시지/미리보기 적용/통합 검증 기록은 [123~132단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch123-132.md)에 기록한다.
Main 요청 기록/반영 전 검사/충돌 후속 검증은 [133~142단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch133-142.md)에 기록한다.
공유 Main 검사/Push 근거/검증 수정 작업공간은 [143~152단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch143-152.md)에 기록한다.
계획 내용/대화 적용 기록/기능 계획 구성은 [153~162단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch153-162.md)에 기록한다.
수동 작업공간/보류·재개/완료 근거는 [163~172단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch163-172.md)에 기록한다.
프로젝트 채팅 문맥/판단 호출/경로 승인 기록은 [173~182단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch173-182.md)에 기록한다.
외부 기획 입력/초기 상태/저장소 기획 문맥은 [183~192단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch183-192.md)에 기록한다.
작업 호출 정책/호출 문맥/강도 계획 반영은 [193~202단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch193-202.md)에 기록한다.
계획 확정 준비/Task 제외/사용자 확인 기록은 [203~212단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch203-212.md)에 기록한다.
경로 승인 조회/실행 AI 변경 준비/복구 자식 기록은 [213~222단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch213-222.md)에 기록한다.
방향 수정 접수/결과 제안 준비/기획 요청 기록은 [223~232단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch223-232.md)에 기록한다.
공급자 명령 구성/가용성 판정은 [233~242단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch233-242.md)에 기록한다.
통합 검증 명령/실패 후보/결과 기록은 [243~252단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch243-252.md)에 기록한다.
기획 프로필/자동 강도/기술 구성 이력은 [253~262단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch253-262.md)에 기록한다.
보관 정리 재시도/결과/commit 참조는 [263~272단계 계획](../DevDocument/Plan/2026-11-14-pipeline-workflow-batch263-272.md)에 기록한다.
기획 색인 갱신/재사용/복원은 [273~282단계 계획](../DevDocument/Plan/2026-11-15-pipeline-workflow-batch273-282.md)에 기록한다.
작업 로그/작업공간 상태 조회는 [283~292단계 계획](../DevDocument/Plan/2026-11-15-pipeline-workflow-batch283-292.md)에 기록한다.
최종 계약/종료 기록은 [293~302단계 최종 정리](../DevDocument/Plan/2026-11-15-pipeline-workflow-batch293-302.md)에 기록한다.

**기능별 규칙 분리는 302단계에서 종료했다.** 사용자의 추가 요청에 따른 Pipeline 자체의 축소는
[진입점/실행 호출 경계 축소](../DevDocument/Plan/2026-11-15-pipeline-facade-reduction.md)로 별도 진행한다.
후속 목표 구조는 [Pipeline 재설계안](../DevDocument/Design/Technical/2026-11-15-pipeline-orchestration-redesign.md)과
[5단계 이행 계획](../DevDocument/Plan/2026-11-15-pipeline-orchestration-redesign.md)에 정리했다.
현재 **P1~P5를 완료했다. 공개 API 112/112개가 명령/조회 owner로 연결되고 facade는 977줄**이다.
[private 소유권·자원/잠금 경계](../DevDocument/Design/Technical/2026-11-15-pipeline-private-ownership.md)에
299개 정의·75개 별칭·2개 endpoint와 기존 테스트 hook의 이전 대상을 기록했다.
`pipeline_bootstrap`이 Pipeline별 자원과 공통 실행 제어·단계/기획 scope를 구성하고,
Pipeline은 기존 공개 signature와 명시적 delegation·호환 자원 속성만 유지한다.
승인·잠금·최종 상태 조정은 실제 명령/phase owner가 담당한다.
줄 수를 맞추거나 선택적 이동 후보를 소진하기 위해
단계를 자동 추가하지 않는다. 기능 변경이나 새 결함은 별도 작업 범위로 다룬다.

P1의 `PipelineResources`는 bootstrap/facade 내부의 구체적인 자원 holder다. 기능 객체에는
전체 holder 대신 제한된 기록·설정·Git callable만 전달한다. facade의 기존 자원 속성은
명시적 property로 연결하며 store/config/git/agents/SDK 교체를 공통 scope의 port가 호출 시 반영한다.
Config만 바꿨을 때 다른 자원을 자동 재구성하지 않는다. SDK 종료는 기존 호스트가 소유한다.
`RunStepLifecycle`은 기존 step 전이·attempt·중단/실패/stale·결과 기록 순서를 소유하고,
`PlanningPolicyScope`는 같은 Run의 중첩 정책 재사용과 prepare/finish·ContextVar 복원을 맡는다.
`StoredStopSignal`은 생성 당시 store의 control loader만 유지한다. 기존 제어 모듈의 잠금과
request/execution/task/attempt/invocation 판정은 유지한다. P5에서 남은 명령과 factory를 이전했고
공통 scope/조회/기획 기능의 임시 facade 연결도 제거했다.

P2의 `orchestration.queries.RunQueries`, `providers.ProviderQueries`, `effort.EffortCommands`는
상태 조회 16개·provider 5개·강도 6개 API의 실제 흐름을 소유한다. facade는 동일 signature로
명시적으로 위임한다. static 계정/연결 조회는 Pipeline/SDK/runtime 구성 없이 호출할 수 있다.
`queries.control`이 lock 전후 snapshot과 실행/통합 제어 조회를, `queries.scope_proposals`가
범위 제안·채팅 fingerprint를 소유한다. `persistence.run_lookup`과 `planning.plan_files`는
제한된 조회/계획 파일 port만 받는다. 기획·실행의 기존 소비자는 이 owner를 공유한다.
`execution.effort_previews`와 `provider_choices.ConnectedProviderQueries`를 기능 사이에서 직접
연결하며 기능에서 facade/명령 객체로 되돌아오는 callback은 넣지 않는다. 계정/가용성·강도 조회의
설정/SDK와 필요한 feature 구성이 호출 시 최신 자원을 반영한다. SDK·credential의 소유권은 유지한다.

P3의 `orchestration.planning.PlanningCommands`는 공개 기획 API 26개의 입력 검증·잠금·요청 순서를
소유한다. `PlanningIntake`는 준비된 Run 접수를, `PlanningAI`는 공통 정책 scope 안의 생성·대화·호출을,
`PlanningLifecycle`은 잠금 아래 계획/기능 적용·실패 복원·단계/저장 기록을 소유한다.
`PlanningMessages`는 대화 파일·메시지와 채널 판정을, `ResultRevisionAI`는 결과 수정 제안과 대화 정리를 맡는다.
각 기능은 좁은 기록/설정/기능 port만 받는다. 메시지 라우팅은 명령 계층에 있으며 기능에서 facade나
명령 객체로 되돌아오는 callback은 없다. 색인의 갱신은 `PlanningSourceIndexes` 안에서 직접 호출한다.

`pipeline_planning_bootstrap`과 `pipeline_provider_bootstrap`은 최상위 bootstrap의 구성 하위 모듈이다.
전체 자원 holder는 이 구성 함수들 안에서만 사용하며 기능 생성자에는 전달하지 않는다.
구성 과정에서 Run/Git/AI 작업을 실행하지 않는다. provider runtime은 같은 요청별 자원으로 만들고
기존 실행·기획에서 공유한다. 기획에서 먼저 쓰는 Task 준비도 기존 실행 기능 API로 직접 구성한다.
P3 당시 legacy 기획 연결과 provider endpoint는 P4~P5에서 소비자를 직접 owner에 연결하며 제거했다.

P4의 `orchestration.execution.ExecutionCommands`와 `control.RunControlCommands`는 공개 API 32개의
입력/승인·잠금·세션·child 요청/실패 기록을 소유한다. 경로 승인 조정은 `ScopeApprovalActions`,
관제 판단/실행/영수증 workflow는 같은 명령 계층의 `chat_workflows`에서 처리한다.
`execution.project_chat`에는 기능 간 전달하는 records/DTO만 남긴다.

`ExecutionFlow`는 실행/재개와 dispatch를, `ExecutionPolicyLifecycle`은 승인된 실행 정책의
prepare/save/start·snapshot 복원/finish를, `ExecutionProfiles`는 프로필 예약과 quota 대체를 맡는다.
`TaskWorkflows`는 기존 Task action·시도·검증·리뷰·수동 완료 기능을 조합한다.
관제에서 처음 소비하는 `VerificationFlow`·`RecoveryFlow`와 `VerificationCommands`도 함께 이전했다.
`WorkspaceAccess`는 공유 workspace 설정과 Git 접근을 묶는다.

`pipeline_execution_bootstrap`은 제한된 persistence callable·설정 getter와 구체적인 객체를 구성한다.
`ExecutionRuntime`은 이 객체들의 구성 결과만 담으며 feature에 전체 묶음을 주입하지 않는다.
`ExecutionControlService.owned_session`은 동일 owner의 생성/종료 수명을 연결하고, state lock과
기존 SDK/provider를 공유한다. feature에서 facade/명령 계층을 역참조하지 않는다.
P4 당시 facade의 phase 연결 19개는 P5에서 제거했다.

P5의 `IntegrationCommands`와 `LifecycleCommands`는 남은 공개 통합 21개·수명 6개의
승인·잠금·세션·작업 순서를 소유한다. `MainApplyFlow`가 Main 반영/Push 완료·operation·배포 phase를,
`ConflictFlow`가 후보/프로필/명령·조회 조합을, `WorkspaceFlows`와 `ArchiveFlow`가 workspace·보관
수명과 부분 실패를 맡는다. 기능은 확보된 잠금 안에서 기존 기능 API를 직접 호출한다.
`pipeline_integration_bootstrap`은 제한된 persistence port·설정/getter와 구체적인 객체만 구성한다.

facade의 비-property 정의는 생성자 1개·공개 API 112개뿐이다. private helper/class 별칭·동적 forwarding과
명령의 facade 역호출을 제거했으며 알려진 모듈 import와 자원 property는 보존한다.
`RunLookup.require_known`이 원래 존재 확인/오류를 공유하고 삭제 한도 상수는 삭제 모듈이 소유한다.
SDK의 실제 생성/종료는 기존 host에 유지하며 테스트/빌드/실환경 증거는 이행 계획에서 구분한다.

실행/기획 package의 공개 export는 Git adapter나 문서 색인을 로드하지 않는다.
Git의 순수 오류/한도는 `git_contracts`로 공유하고 annotation 전용 adapter/색인 import는
TYPE_CHECKING 아래에 둔다. 기존 `git.GitError` import와 예외 계층/동일 객체는 유지한다.

## 모듈 책임

| 모듈 | 책임 | 포함하지 않는 것 |
|---|---|---|
| `cli` | 인자 파싱, 명령 라우팅, 출력, 종료 코드 | 상태 전이 규칙, Git 명령 구성 |
| `pipeline` | 112개 공개 signature·명시적 delegation, 기존 생성자와 호환 자원 속성 | 업무 private helper·승인/잠금/상태 전이 구현, 동적 forwarding·숨은 전체 context |
| `pipeline_bootstrap` | Pipeline별 자원·SDK 참조·credential snapshot·공통 실행/기획 scope와 제한된 port 구성 | Run 쓰기·실행·Git 부작용, SDK 생성/종료, feature에 전체 자원 holder 주입 |
| `orchestration` | 상태/provider 조회·강도·기획·실행/관제·통합/수명의 승인/잠금/요청 순서·메시지 라우팅. 기존 기능 API를 직접 조합 | facade/전체 자원 holder 역참조, 새 transport·저장 형식·SDK 수명 소유 |
| `application` | UI 독립 공개 기능 조합, 프로젝트 등록 snapshot 검증, SDK 수명과 공통 Pipeline 구성·조회 모델 | RPC frame·입력 parsing, 화면, 상태 전이 우회 |
| `rpc` | 메서드 allowlist·요청 범위, 기능별 handler·필드/승인 검증, 요청·성공/실패 frame 타입 | SDK 소유, 상태 전이, stdio/executor 수명 |
| `run_queries` | 실행 상태·사용자 확인·주의 항목·그룹 표시 판정 | Pipeline·Store·Git 객체 접근, 상태 쓰기·실행 권한 부여 |
| `queries` | callback 기반 실행 목록·주의/활동 그룹·사용자 확인 목록과 근거 기반 다음 단계 안내 | Store/Pipeline/Config/Git 객체 접근, 상태 쓰기·잠금 소유·실행 권한 부여 |
| `execution` | AI 호출·리뷰/검증·복구 규칙, 실행 제어/활동 기록과 Run step 수명, Task action/시도/재개·scope/검증/완료 근거·배정/묶음 결과·작업 순서/선행 Git 준비 | Pipeline/Store/전체 Config 역참조, 독자적 승인·새 공개 run lock 진입 |
| `project_chat` | 프로젝트 채팅의 허용 행동·구조화 AI 응답 계약 | 파일 I/O, 실행 권한 부여, 상태 저장 |
| `document_index` | 기획 문서 후보 필터링, 메타데이터 추출, 프로젝트 로컬 색인의 원자적 저장·재사용 | Planning AI 실행, run 상태 전이, Git 명령 실행 |
| `codex_sdk` | 공식 Python Codex SDK client pool, 비밀값 없는 인증 상태 조회, 실제 실행 model profile 해석·보고, thread·turn 결과·timeout·interrupt | Pipeline 상태 전이, SDK 내부 JSON-RPC 구현, 프로젝트 registry 접근 |
| `worker_mcp` | 프로젝트 외부 도구 연결 정의·검증, Codex/Claude 설정 변환, 초기 연결 확인·연결 점유 잠금과 출력 마스킹 | 외부 대화 앱 설정 수정, MCP 서버 설치, Pipeline 상태 전이 |
| `app_paths` | OS별 앱 사용자 설정 root의 경로 계산 | 디렉터리 생성, 인증·registry 내용 조회, 전역 환경 변경 |
| `nvidia_agent` | 수동 NVIDIA 코딩 프로필, OpenCode argv·도구 권한, 완료 응답·사용량 해석과 키 마스킹 | Pipeline 상태 전이, Git 실행, 프로젝트 설정·키 저장 |
| `provider_executable` | 외부 provider 실행 파일의 명시 경로·`PATH`·Claude 사용자 설치 경로 탐색 | 인증 정보 조회, provider 실행, 상태 전이 |
| `account_usage` | 공급자 계정 한도 요약·소진 판정과 요청별 짧은 조회 캐시 | 작업 token 집계, 인증 변경, Task 배정·상태 전이 |
| `planning` | 계획/요청/응답·검증·배정, 정책 scope·접수/대화/기획 호출, 잠금 아래 계획 적용·실패 복원·Run 기록, 결과 검증/캐시 identity, 기본 구조 명세·경로 보호 | Pipeline/Store/전체 Config 역참조, 독자적 실행 승인·새 잠금/SDK·프로세스 소유 |
| `planner` | 기존 기획 API 호환, 문서 I/O·Markdown 작업 분해·capability 추론 | 외부 AI 프로세스 실행, worktree 생성, 상태 파일 쓰기 |
| `git` | Git·외부 명령 실행과 오류 변환. GitError/로컬 한도는 기존 import로 재노출 | 실행 단계 결정, 사용자 승인 판단 |
| `git_contracts` | adapter를 불러오지 않는 GitError와 로컬 명령 한도 계약 | Git 실행·filesystem/프로세스 I/O |
| `integration` | 작업공간 layout/소유권·청결/상태·보관/삭제 수명, Main 변경 snapshot/선택·통합/복구/충돌·후보/요청/반영 기록, 확보된 잠금 안의 Main/Push·workspace/보관 phase | Pipeline/Store 역참조, 독자적 공개 run/프로젝트 잠금·승인, SDK/프로세스 수명 |
| `errors` | 공유 PipelineError·ApprovalRequired·검증 입력 변경·provider 입력/timeout/capacity/request-limit 계약과 기존 pipeline import의 동일 오류 객체 | 실행 규칙, 상태·I/O 처리 |
| `store` | 상태 파일·sidecar 조합, run/기획/사용량/정책 잠금과 저장 API 호환, run 존재 확인 | 상태 전이 정책, Git 접근 |
| `persistence` | 원자적 파일 교체, 사용량 ledger, 기획 결과 cache·대화 sidecar 복원, 알림 사건 파일 검증·저장, 공유 저장/잠금 오류 계약 | Store/Pipeline 역참조, 잠금 구현·승인·상태 전이 |
| `state` | 공통 값·작업/실행·기획·통합·강도·Run 모델과 JSON 복원, 모델의 상태/readiness 규칙 | 파일 I/O, 프로세스·Store/Pipeline 접근 |
| `models` | 기존 상태 모델 import와 동일 클래스·상수의 호환 재노출 | 모델 구현, 파일 I/O, 프로세스 실행 |
| `notifications` | Run·Task 상태의 안정적인 알림 사건·이동 대상 파생·동기화, callback 기반 읽기 전용 목록·pagination | 파일 I/O, OS 알림 전달, 읽음 상태, Pipeline 상태 전이 |
| `config` | TOML 로드·생성, 기본값과 유효성 검증 | 실행 흐름, 런타임 상태 저장 |
| `registry` | 대상 프로젝트·설정·기획 디렉터리 경로의 원자적 저장·조회 | project 설정 해석, run 상태 접근 |
| `desktop_rpc` | JSON Lines 입출력·결과 직렬화, 요청 credential 범위·마스킹, executor·backend 수명과 호환 진입점 | 기능 처리·필드 검증 규칙, 화면 렌더링, 상태 전이, 네트워크 서버 |
| `desktop/main` | Electron lifecycle, 보안 BrowserWindow, 앱 credential 보안 저장, 역할별 Python process와 typed IPC 중계 | Pipeline 규칙, renderer 화면 상태, shell command 조립 |
| `desktop/renderer` | React 화면, 접근 가능한 사용자 상호작용과 로컬 view state | Node·파일 시스템 접근, Git·Pipeline 상태 전이 |
| `desktop_entry` | 개발 checkout의 Electron 빌드·실행 진입점 | UI 구현, Pipeline 호출, installer 패키징 |

## 의존 방향

```text
cli ─────> application.runtime ──> pipeline
 ├───────> registry ──────────> app_paths
 ├───────> desktop_entry ─────> Electron main
 └───────> mcp_server

pipeline ────────────────────> config
             ├──> execution ──> codex_sdk, nvidia_agent, worker_mcp, provider_executable, git, models, persistence.errors
             │                  ├──> code_style, task_scope_review, account_usage
             │                  └──> effort_policy (미리보기/순수 판단), planning (순수 경로/배정 규칙)
             ├──> execution.manual_tasks ──> git, models, errors
             ├──> execution.scope_consent ──> models, errors, scope_consent
             ├──> execution.task_invocation ──> codex_sdk (DTO), config, models, usage, execution_control, errors
             ├──> execution.effort_plan ──> config, effort_policy, models, planning.contracts/validation, errors
             ├──> execution.user_checks ──> models, errors
             ├──> execution.provider_commands ──> config, nvidia_agent, errors
             ├──> execution.provider_choices ──> account_usage, config, models, nvidia_agent, planning, errors
             ├──> execution.run_verification ──> models, errors, execution_control, git, execution.verification_runner
             ├──> execution.results ──> models, git
             ├──> execution.task_logs ──> models
             ├──> execution.provider_runtime ──> execution.invocation/provider_runner, codex_sdk (진행 DTO), config, usage, errors
             ├──> execution.chat_profiles/chat_recovery ──> config, models, errors, planning, project_chat, task_scope_review
             ├──> codex_sdk ──> app_paths
             ├──> nvidia_agent ──> config, usage
             ├──> document_index
             ├──> planner ──> planning (순수 계약/규칙), config
             ├──> planning (계약/규칙) ──> config, models, model_selection, errors
             ├──> planning.runner/documents/output ──> planner, codex_sdk, git, errors
             ├──> planning.invocation ──> config, models, effort_policy, codex_sdk (진행 DTO), usage, errors
             ├──> planning.preparation ──> planner, document_index, config, models, errors
             ├──> planning.source_indexes ──> document_index, git (준비 상태 DTO), models, errors
             ├──> planning.features ──> models, planning.contracts/validation, errors
             ├──> planning.task_apply ──> document_index, models, planning.changes/contracts, errors
             ├──> planning.plan_application ──> document_index (DTO), models, planning.contracts/features/task_apply, errors
             ├──> planning.control_decisions ──> config, models, project_chat, scope_consent, planning.apply_requests
             ├──> planning.initialization ──> code_style (DTO), models, errors
             ├──> planning.plan_review ──> effort_policy, models, planning.contracts/validation, errors
             ├──> planning.direction_changes/request_records ──> models, errors
             ├──> planning.result_revisions ──> config, models, errors
             ├──> planning.profiles ──> config, effort_policy, model_selection, models, errors
             ├──> planning.apply_requests ──> config, models, errors
             ├──> planning.bootstrap ──> models, greenfield_instructions, planning.contracts/validation, errors
             ├──> planning.preview ──> models, document_index (DTO), planning 계약/대화/검증, errors
             ├──> run_queries ──> models
             ├──> queries ──> models, notifications, git (오류 계약)
             ├──> queries.scope_approval ──> models, scope_consent, task_scope_review (순수 승인 문구 규칙)
             ├──> integration.archive_views ──> models, errors
             ├──> integration.workspaces ──> models, git, errors, integration.layout
             ├──> integration.recovery_apply ──> config, models, git (오류 계약), errors
             ├──> integration.archive_workflow/deletion ──> models, git, errors
             ├──> integration.operations ──> models, errors
             ├──> integration.main_preflight/conflict_verification ──> models, git, errors
             ├──> integration.publishing ──> models, git, errors
             ├──> integration.verification_repair ──> config, models, git, errors
             ├──> integration ──> git, config, models, errors, codex_sdk (진행 DTO), progress, usage
             ├──> notifications ──> models, errors
             ├──> git
             ├──> store ────> persistence, models
             └───────────────> models ──> state

persistence ──> models, usage
state.run ────> state.codec ──> state.common, execution, planning, integration
state.effort ──> state.common

mcp_server ──> mcp_operations ──> application ──> pipeline, registry, codex_sdk
desktop_rpc ──> rpc ────────────> application
application.views ──> run_queries, models, config
application.summaries ──> models
application.planning_indexes ──> document_index
application.project_settings ──> registry (DTO/오류), config, worker_mcp, code_style, repository_maturity

renderer ──typed preload API──> Electron main
                                  ├──JSON Lines──> desktop_rpc (control)
                                  ├──JSON Lines──> desktop_rpc (planning)
                                  └──JSON Lines──> desktop_rpc (work)
```

- `cli`는 자동화 진입점이며 `application`, `registry`, `desktop_entry`, `mcp_server`의
  공개 진입점을 호출한다.
- 옵트인 `mcp` 진입점은 Codex의 stdio 연결에서 기능별 도구를 제공한다. 작업 PC에서
  직접 또는 SSH로 실행하며 같은 `OrchestratorApplication`과 프로젝트 등록 정보를 사용한다.
  MCP의 실행 권한과 요청 기록은 `mcp_operations`에서 관리하고, 작업 상태 전이와 잠금은
  `Pipeline`이 처리한다. 앱과 MCP는 등록 정보의 쓰기 잠금을 공유한다.
- `--allow-planning` 연결은 `get_planning_context`의 기준 커밋에 맞춰 외부 작성 계획을
  `submit_plan`으로 제출한다. Python은 기존 Task 계약 검증과 실행 배정을 재사용해 계획 검토 상태를
  저장한다. 기획 모델 호출 없이 작성한 초안도 기존 앱의 계획 revision 승인과 실행 경계를 거친다.
- 계획의 사용자 확인은 기준 Task 결과나 계획 기준 커밋에 연결한다. `planning.validation`이 Task와 확인의
  의존성을 검증하고, `Pipeline`이 확인 결과를 기록하며 대기할 Task와 통합 가능 여부를 결정한다.
  데스크톱은 확인 결과를 기록하고 MCP는 기준 커밋과 확인 상태를 조회한다.
- registry 명령은 프로젝트 설정이 선택되기 전에 `registry` 공개 API를 호출한다.
- 작업 AI의 외부 MCP는 `worker_mcp`의 stdio·Streamable HTTP 연결 정의를 사용한다.
  `config`와 `registry`가 정의를 읽고 `desktop_rpc`가 revision·native 확인을 거쳐 저장한다.
  registry schema 4는 1~3을 호환해서 읽는다. 미설정은 TOML을, 명시적인 빈 목록은 연결 해제를 뜻한다.
  `Pipeline`은 생성 시 설정을 고정하고 실행·수정 요청에만 전달한다. `codex_sdk`는 해당 thread에
  필수 연결을 넣고 MCP를 쓴 client는 닫으며, Claude는 strict 설정과 명시적인 도구 권한을 받는다.
  다른 공급자에 연결을 전달할 수 없으면 명시적으로 실패한다. 저장과 연결 확인은 구분하며,
  연결 확인은 initialize·tools/list만 수행한다. 인증 값은 도구 전용 환경변수 이름으로 참조하고
  실제 값은 반환·로그에서 가린다. OAuth 대행·SSE·서버 자동 설치는 지원하지 않는다.
  표준 `mcpServers` JSON 또는 TOML의 `[mcp_servers.연결이름]`으로 설정한다. stdio의
  `env = { TOOL_TOKEN = "${MY_TOOL_TOKEN}" }`, HTTP의 `bearer_token_env_var = "MY_TOOL_TOKEN"`은
  도구 전용 환경변수 이름을 참조한다. stdio 인자에는 `{worktree}`·`{project_root}`를 사용할 수 있다.
  개별 `enabled_tools` 허용 목록은 Codex만 지원하며 Claude에 지정하면 권한을 넓히지 않고 실패한다.
  CLI에서 앱의 연결 설정을 사용하려면 같은 `--registry`를 명시한다.
  같은 연결의 오케스트레이터 요청은 OS 잠금으로 직렬화하며 대기 원인을 표시하고 중지 요청을 받는다.
  사용 중인 연결의 수동 검사는 기다리지 않고 점유 상태를 알린다.
  외부 앱의 별도 연결이나 다른 주소로 등록한 동일 서버까지 잠그지는 않는다. 실제 에디터의 대상
  경로 확인은 작업 지침으로 전달하며 범용 MCP로 대상 경로를 강제하지 않는다.
- React renderer는 화면에 필요한 의미 단위의 typed method만 호출한다. Electron main은
  renderer payload를 shell command나 파일 접근으로 해석하지 않고 Python RPC로 중계한다.
- `desktop_rpc`는 method allowlist와 입력 schema를 검증하고 선택된 registry 항목의
  `Pipeline` 공개 API만 호출한다. 임의 Python attribute 호출은 허용하지 않는다.
- Electron main은 요청 id, timeout, backend 종료를 관리한다. 장시간 동작은 renderer
  thread를 막지 않지만 Python의 기존 run lock 경계를 그대로 유지한다.
- Electron main은 상태 조회·UI 제어 요청을 control backend로, Planning 색인·생성·대화
  요청을 planning backend로, Task 실행 요청을 work backend로 라우팅한다. Task 실행 중에도
  Planning 대화가 별도 프로세스에서 진행되며 각 backend 내부에서도 역할별 executor를 사용한다.
- Task 작업공간 목록은 read-only Git 상태를 제한 시간 안에서 병렬 조회하고, Electron은
  일반 상태 조회보다 긴 bounded timeout을 적용한다. Git 조회가 정체되면 Python이 먼저
  구체적인 작업공간 조회 실패를 반환한다.
- 데스크톱 작업 그룹 목록은 카드 표시에 필요한 요약만 반환하고, Task·이벤트·Planning
  대화가 포함된 전체 상태는 사용자가 선택한 작업 그룹 하나를 별도로 조회한다.
- Electron main은 사용자가 명시적으로 재시작을 선택한 경우 세 Python backend와 그
  자식 프로세스 트리를 종료한 뒤 새 backend들을 시작한다.
- 진행 중인 Planning을 사용자가 명시적으로 중단하면 Electron main은 planning backend와
  그 자식 프로세스 트리만 재시작한다. control backend는 종료된 소유자의 stale run
  lock만 확인 후 제거하고 해당 run을 Planning 실패 상태로 기록한다. 실행 중 자유 대화만
  중단한 경우 Task 실행과 run 상태는 유지하고, 다음 대화 요청에서 안전한 stale sidecar
  lock만 자동 복구한다. 프로젝트 소스와 Git 상태는 변경하지 않는다.
- `pipeline`은 유스케이스 조정자이며 `document_index`, `planner`, `git`, `store`를
  조합한다. 실제 AI 전송은 `execution`의 공개 `ProviderRunner` API에 위임하고,
  CLI 또는 데스크톱 backend가 주입한 SDK를 전달한다. SDK 대화 수명과 상태 판정은 기존
  조정자에 남긴다. 실행기는 호출자 소유 SDK를 새로 만들거나 닫지 않는다.
- `execution`은 Pipeline 객체나 저장 객체를 받지 않는다. 저장소 경로·기본 timeout·MCP
  연결을 담은 불변 `ProviderRuntimeOptions`, credential snapshot과
  명시적인 실행 파일 해석/프로세스 종료 callback을 받아 SDK 또는 command를 실행한다.
  실행기 고유 오류는 Pipeline의 호환 계층에서 기존 예외·메시지와 SDK 원인으로 변환한다.
  사용량 저장·공유 MCP lease·사전 연결 확인·승인과 상태 전이는 기존 소유자가 처리한다.
  통합 검증은 `VerificationRunner`가 명령·NPM 복원·공유 deadline·출력과 .NET 실패 분류를
  처리한다. `VerificationRuntimeOptions`의 경로·시간 값과 명시적 명령 실행·진단·중지·HEAD
  확인 callback만 받는다. 진행·통과 기록 callback과 실패 정보에 따른 상태 저장·원인 후보
  기록은 Pipeline이 소유하며 기존 Git 어댑터의 원인 예외도 유지한다.
  작업별 명령 검증은 `TaskVerificationRunner`로 실행하며, 준비/명령 완료 후의 전체 시간 확인과
  시도별 실패 로그를 유지한다. 문맥 digest·반복 timeout·progress·코드 스타일·scope/HEAD 확인은
  `TaskVerificationService`가 기존 callback과 runner로 조합한다. action context·취소 신호 생성·
  SDK/정책 binding과 최종 상태 전이/저장 권한은 기존 진입점이 유지한다.
  `execution.review`는 불변 `ReviewRequest`의 값으로 리뷰/수정 프롬프트를 구성하고 구조화
  응답을 검증하는 순수 API다. 리뷰 반복은 TaskReviewCycles, action/리뷰어 Git 변경 차단은
  TaskActionRunner가 기존 진입 callback으로 조합한다. 모델/사용량·SDK와 action 등록/종료는
  기존 Pipeline이 소유하며 응답 오류는 기존 PipelineError와 JSON 원인으로 변환한다.
  `execution.recovery`는 실패 분류·실패 fingerprint·복구 한도와 재시도 조건을 값으로 판정한다.
  파일 잠금/환경 오류/복구 한도/반복 실패의 우선순위와 기존 응답·해시를 유지한다. 실패 이력
  선택·scope 확인·HEAD 조회·상태 저장·모델 변경·실제 재실행·승인은 Pipeline이 소유한다.
  `execution.task_prompts`는 불변 작업/부트스트랩 snapshot으로 작업 요청을 구성하고 자동 수정·
  재시도/중단 후 이어하기·실행 지침을 렌더링한다. 기존 텍스트와 작업공간 계약을 보존하며,
  파일 조회·재시도 지시의 유효성 확인·파일 저장·실제 실행과 상태 전이는 Pipeline에 남긴다.
  `execution.dispatch.TaskDispatcher`는 Pipeline의 승인·정책 고정·초기 Task 준비와 EXECUTING 전이 뒤에만
  준비된 Task를 수동 인계하거나 실행 묶음으로 배정한다. 현재 agent map과 준비/실행·대화/모델·quota·
  방향 변경 callback, 상태 읽기/쓰기·대화 lock callback만 받는다. 준비 단계의 상태 표시, user check·
  deferred/선택 실행, 방향 변경 경계와 planning lock 실패·중지/실패 결과의 저장 순서를 유지한다.
  `execution.batch.TaskBatchExecutor`는 기존 ThreadPool과 state lock 안에서 완료·dispatch 일시 중단·
  소유 작업 중지·독립 실패를 기록한다. shared는 한 작업, isolated는 기존 max_parallel을 사용하며
  실제 Task 실행·정책 binding·취소 신호·중지 확인은 Pipeline callback이 소유한다.
  `execution.scheduling`은 의존/위험도/계획 순서·deferred 전파·사용자 확인 대기 규칙을,
  `TaskWorkspacePreparation`은 기존 Git 어댑터로 선행 branch 병합과 보존된 scope baseline/조상 검증을 처리한다.
  `READY_TO_MERGE` 전이는 기존 Pipeline callback에 둔다. run/정책 승인과 SDK 수명·최종 저장 권한은
  기존 진입점이 유지하며 기능 모듈은 Pipeline/Store 전체를 받지 않는다. 공유 `RunLockedError`는
  persistence.errors에 정의하고 store/pipeline의 기존 import와 같은 객체를 노출한다.
  `execution.task_runner.TaskRecoveryRunner`는 기존 검증 실패의 반복/환경 판정·자동 수정 한도·
  검증 전용 재시도와 증거 저장을 조합한다. scope 최초 검토·중지 신호 생성·HEAD/scope/청결 검증과
  고정 정책의 모델 승격은 Pipeline callback이 처리하고 기존 state lock을 재사용한다.
  `TaskAttemptRunner`는 EXECUTE/REVIEW/REVISE/VERIFY 재개, 수정 prompt/이전 로그 보존과 결과 기록을,
  `TaskReviewCycles`는 제한된 리뷰/수정 반복을 조합한다. 실제 action/검증·중지·SDK 호출·정책 binding은
  기존 Pipeline 진입점에 남는다. TaskVerificationFailure/Timeout은 execution.errors에서 정의하며
  기존 pipeline import와 같은 클래스다. timeout/provider/stop은 일반 검증 실패 자동 수정과 구분한다.
  `execution.results`는 commit 파일 비교 근거와 중복 없는 Task 완료 기록을 소유한다. 미확인과 파일 변경
  없음, 수동 확인 메모·검증 성공 기록·self-report 길이와 UTC 시각을 유지하고 그룹 기록/최종 저장은 Pipeline에 둔다.
  `execution.task_actions.TaskActionRunner`는 기존 `_task_action` context 안에서 실행/리뷰/검증의
  baseline·결과 HEAD/변경 파일·scope/청결·commit/no-commit와 리뷰 결과 JSON을 조합한다. 실제 agent 호출과
  attempt/invocation·중단 checkpoint의 소유자는 기존 Pipeline callback이며 처음 캡처한 중지 check를 재사용한다.
  `execution.task_evidence.TaskScopeInspector`는 다른 완료 Task의 증명된 action commit만 제외하고 Task 소유
  변경을 우선 확인한다. 범위 위반/Git 조회 실패의 JSONL·경로 규칙·계약 digest·저장된 scope 검토와
  기존 구현/코드 스타일 근거를 처리한다. Store/Pipeline을 참조하지 않고 기존 DTO와 Git·경로만 받는다.
  `execution.verification_evidence`의 TaskCancellation은 원래 CancellationSignal 객체와 소유자의 check
  closure를 함께 전달한다. 모든 command와 중지 확인이 같은 신호를 사용하며 timeout 기본값/tool은
  기존 시점에 읽는다. 검증 문맥/제한·반복 timeout·예외 원인·부분 기록과 최종 scope/청결 확인 순서를 유지한다.
  `execution.lifecycle.ExecutionControlService`는 좁은 잠금·기록 callback으로 session/종료·활성 대상·
  중지 claim/판정/확인·checkpoint를 기록한다. 이전 session의 execution ID와 다른 owner PID/attempt의
  늦은 정리를 차단한다. UUID/범위/메시지 검증·중복 요청의 채팅 제외·기존 중지 신호 생성은 Pipeline에 남는다.
  `execution.task_activity.TaskActivityRecorder`는 기존 state lock과 callback으로 action의 시작/성공/실패/
  중지·finally 정리, progress/유효 모델과 중단 수집을 기록한다. Pipeline 진입점·예외/저장 순서와
  기존 활동 수신 조건을 유지하며 추가 event ID 필터·독자적 정책 binding·run 잠금은 만들지 않는다.
  `execution.profiles.TaskProfileValidator`는 agent 목록과 가용성/리뷰 호환성 callback으로 실행 프로필의
  역량·모델·추론 강도를 검증한다. 공유 정규화/강도·snapshot/수동 배정·pending 대상 함수도 이 모듈에
  두며 기존 Pipeline static 진입점은 같은 함수를 재노출한다. credential 값·전체 Config는 받지 않는다.
  `execution.profile_requests.TaskProfileService`는 좁은 기록·검증/조회/계획 callback으로 다음 설정의 저장·
  조회·대기 저장/dispatch 적용을 조합한다. 조회는 원래 상태를 바꾸지 않고 현재 snapshot/revision·
  활성 작업/예약·정책 receipt를 검사한다. receipt 선저장·계획/상태 저장·대기 소비 순서와 실패/재개를
  유지하며 update/queue 잠금·재조회·stage 확인, 승인·정책 binding·실제 실행은 Pipeline에 남는다.
  `execution.quota.QuotaFallbackService`는 기존 TaskProfileRecords·agent/routing과 사용량/연결/리뷰·
  작업공간/계획 callback으로 미시작 자동 Task의 한도 전환·중단 기록 재적용을 조합한다. 수동/고정 rule·
  기존 시도 보호, 한도 불명 유지·호환/병렬 제한과 receipt/상태/계획 저장 순서를 보존한다.
  receipt의 policy/revision/baseline/source와 실제 선택/기존 승격 증거도 순수 함수로 검사한다.
  기존 Pipeline 진입점·dispatch 잠금/시작·승인/정책 binding·계정별 한도 조회/캐시는 유지한다.
  기존 planning 공개 순수 배정을 재사용하고 전체 Pipeline/Store/Config·새 cache/lock/client는 받지 않는다.
  `execution.model_escalation.AutomaticModelEscalation`은 정책/프로필 조회·quota 일치·상태 저장 callback과
  기존 state lock으로 코드 실패 근거에 따른 1회 승격을 기록한다. 순수 증거 판정은 기존 Pipeline static
  진입점과 같은 함수다. started binding·원래/quota 프로필 확인·환경/수동 제외와 잠금 안의 근거 불일치
  복원/이벤트/저장 순서를 유지한다. 복구 루프·정책 검증 호출 위치·실제 SDK 호출과 승인/정책 고정은 Pipeline에 남는다.
  `execution.policy_snapshot.ExecutionPolicyValidator`는 현재 agent mapping·프로필 기록 조회와 승격/quota
  일치 callback으로 승인/revision·작업/리뷰 집합·프로필/실행 AI 설정을 읽기 전용으로 대조한다.
  수동 receipt의 policy/revision/baseline/selection/source, 버전별 리뷰 검사와 예외 인정/오류 순서를
  유지한다. started binding 재개와 AI 호출 직전의 기존 Pipeline 진입점에서 호출하며 승인/잠금·정책
  선택/예약/binding 수명·호출별 추가 검사·실제 SDK는 옮기지 않는다. 상태 쓰기나 새 검증 기준은 추가하지 않는다.
  같은 모듈의 `build_execution_policy_snapshot`은 RunState/미리보기·agent mapping과 기본 Planning agent ID로
  기존 Planning/Task/리뷰 snapshot·수동 예외/미지원 항목을 조립한다. Task 순서·리뷰 대체 조건과 UUID/
  버전 3/execution scope/revision/UTC 시각 생성 순서를 유지한다. Pipeline의 기존 생성 진입점과
  정책 선택/검토·예약/저장/started binding 순서가 그대로이며 Store/전체 Config·SDK·잠금은 받지 않는다.
  `execution.effort_preview.EffortPreviewBuilder`는 현재 agent mapping/설정 tuple·기본 Planning agent·
  필수 리뷰 여부와 리뷰 호환성/선택 가능/가용성 callback으로 모델·추론/리뷰 미리보기를 조합한다.
  기존 effort_policy의 DTO/판단을 쓰며 수동/legacy·시작된 작업 보호, 저장 프로필 보존·runtime 제외,
  리뷰 추가/제거·미지원/재검토 표시와 lazy 조회 순서를 유지한다. public preview의 mode/revision 검증·
  상태/정책 조회·설정 저장/계획 반영/승인·실행 예약과 실제 AI는 기존 Pipeline 진입점에 남는다.
  미리보기는 상태를 저장하지 않으며 전체 Pipeline/Store/Config·SDK·새 client/lock은 받지 않는다.
  `execution.effort_plan.EffortPlanApplicator`는 agent mapping/기본 Planning agent와 기존 가용성/
  리뷰 호환성/선택 가능 callback으로 리뷰 명시 선택을 검사하고 원본 사본의 프로필·리뷰 변경안을 만든다.
  EffortPlanChange는 사본과 전체/Planning 변경 여부를 전달한다. baseline·리뷰 추가/제거·오류/조회
  순서를 보존하며 직접 저장하지 않는다. mode/revision·잠금·stage 확인과 반환 뒤 그래프/readiness·
  계획 revision/재승인·파일/상태/기존 Planning 채팅 저장은 Pipeline이 같은 순서로 처리한다.
  `execution.effort_queries.EffortQueries`는 좁은 EffortQueryRecords와 미리보기/agent 목록·선택 가능/
  연결/리뷰 호환 callback으로 강도 상태·desktop 미리보기 응답을 조합한다. 상태 재조회/expected
  snapshot 비교·잠금/보관 이력과 후보 lazy 조회, 응답 field/enum/null·변경 가능 표시를 보존한다.
  상태 비교 key/예약 가능 판정은 기존 Pipeline static 진입점과 같은 함수다. 경로/존재 확인은
  Pipeline이 연결한 Store callback이 처리하며 새 저장/refresh/client/lock은 없다. public 진입점과
  application/RPC/renderer 응답 계약·실제 쓰기/승인/revision 검증은 그대로 유지한다.
  `execution.provider_choices.ProviderChoiceQueries`는 agent 목록/균형 설정·가용성/선택 가능·연결/
  사용량 callback으로 실행/기획 목록과 기획 실행 후보를 조합한다. 역량·기본 프로필·정렬·기획용
  NVIDIA 제외, 균형 옵션의 연결/한도와 commandless custom legacy 후보를 보존한다.
  connected_provider_ids는 기존 공급자 상태 callback으로 Codex/Claude의 인증 true·NVIDIA 가용성과
  다른 공급자의 기존 허용 조건을 같은 순서로 판정한다. 기존 순수 선택 함수/응답 DTO와 private/public
  진입점은 유지하며 실제 status/SDK/credential·실행 파일·사용량 캐시·배정/실행·설정 쓰기는 옮기지 않는다.
  `execution.provider_status.ProviderStatusQueries`는 agent 목록과 account_status callback/SDK 없음,
  실행 파일 probe·NVIDIA 키 존재/등록 방식 bool·Claude 인증 callback으로 기존 상태 응답을 조합한다.
  SDK 인스턴스 수명·명령 구성/리뷰 명령 대체·실행 파일 해석·실제 키/인증 확인은 Pipeline이 소유한다.
  공급자/agent 순서·오류/로그아웃/미확인·SDK/CLI 없음과 안내 우선순위를 보존하며 키 값이나 계정
  세부를 새 응답에 추가하지 않는다. 기존 public 진입점과 선택/연결·application/RPC 계약도 유지한다.
  `execution.claude_connection`은 JSON payload·종료 코드·앱 키 사용 여부 bool로 인증 응답을 해석한다.
  CLI/환경·실제 키·timeout/JSON 오류 처리는 Pipeline에 두고 구독/API/외부 인증·미확인과 계정 필터를 유지한다.
  `execution.verification_repair.VerificationRepairRunner`는 가용 Agent 선택·실패 로그/prompt·호출 준비와
  중지/진행 기록을 조합하고 범위 검사할 Task와 원래 검증 시도를 반환한다. 실제 provider 호출은 기존
  callback을 사용하며 Pipeline/Store/전체 Config·Git 객체를 받지 않는다. Pipeline이 작업공간·청결/HEAD·
  변경 범위·commit/branch 갱신·최종 복구 근거 저장과 격리 작업공간 정리를 소유한다.
  같은 모듈의 `VerificationRepairWorkflow`는 명시적 기록/정책/verify/repair callback으로 요청 claim·
  검증/수정 반복·저장 한도와 receipt를 조합한다. Pipeline은 parent 검증·run lock/실행 session,
  중지 시 Run 복원/checkpoint/확인과 후속 기능 기획의 chat lock·최종 전이를 유지한다.
  완료 callback에는 요청 run ID를 명시적으로 전달한다. 새 SDK/Git/저장 객체나 실행 권한은 만들지 않는다.
  `execution.retry_guidance.TaskRetryGuidance`는 수정 지시·진단/현재 실패 근거·scope/timeout 복구 가능성을
  기존 기록/Task/scope/HEAD/알림 callback으로 조합한다. 이전 시도의 응답을 현재 실패로 표시하지 않고
  계약/fingerprint·중복 요청/오래된 실패와 저장 뒤 알림 순서를 유지한다. 입력 검증·run/대화/요청 잠금,
  실제 재시도/최종 실행 상태는 Pipeline에 남긴다.
  기능별 패키지 전환은 [Python 모듈 리팩터링 계획](../DevDocument/Plan/2026-11-13-python-module-refactoring.md)에
  따라 실제 코드가 이동하는 영역부터 진행한다.
- `codex_sdk`는 SDK client pool과 Codex thread·turn 생명주기만 소유한다. Planning,
  Task 실행·Review 조정과 그룹 상태 전이는 `Pipeline`에 남긴다. Codex 요청은 SDK turn으로만
  전달하고 SDK가 없거나 시작에 실패하면 명시적으로 실패한다. Claude와 custom provider는
  외부 command 경계를 유지한다. NVIDIA 코딩 시험 프로필도 이 경계에서 OpenCode
  1.19.3의 비대화형 `run --format json`을 실행한다. 기존 프로젝트 설정을 쓰지 않고
  수동 선택 전용 프로필을 보완하며 기본 자동 배정·Planning 후보·자동 리뷰에서는
  제외한다. `nvidia_agent`는 비밀값 없는 준비 상태, 외부 CLI argv·도구 권한과
  응답·사용량 해석을 담당한다. Pipeline은 중단·제한시간·검증·Git 부작용을 계속
  소유한다. 별도 HTTP 서비스는 추가하지 않는다.
  NVIDIA 앱 등록 키는 Electron main의 `NvidiaCredentialStore`가 `safeStorage`로
  암호화해 userData에 원자적으로 저장한다. 보안 저장소 미지원·Linux `basic_text`는
  평문으로 대체하지 않는다. 이름·ID·기본 키·모델 연결을 포함한 버전 1 vault를 통째로
  암호화하며 기존 단일 키 암호문은 기본 키로 호환한다. renderer는 고정 preload API로
  비밀값 없는 목록·저장·삭제·키 연결만 요청하며 키를 읽어오는 API는 없다. 모델에
  직접 연결된 키와 대체 기본 키를 지정하지 않은 기존 기본 키는 삭제를 막는다.
  기본 키 사용으로 전환해도 모델 등록은 유지하고 기본 키 변경을 따른다. 등록 모델이
  남아 있으면 마지막 앱 키를 삭제하지 않는다.
  main은 기본 키와 모델별 키를 공개 RPC params와 분리된 내부 JSON Lines 필드로
  전달한다. `desktop_rpc`의 요청별 credential scope에서 만들어진 Pipeline이 snapshot을
  고정하고 요청 모델에 해당하는 키만 NVIDIA subprocess 환경에 주입한다. 다른 AI 환경이나
  OS 환경 변수는 바꾸지 않는다. 저장·삭제 후 다음 요청부터 반영하며 실행 중 작업과
  backend 프로세스를 재시작하지 않는다. 앱 키가 없으면 OS 환경 변수 설정을 사용한다.
  Claude 앱 키도 main의 `ClaudeCredentialStore`가 safeStorage로 암호화해 userData에
  저장한다. 고정 preload API는 키 없는 상태와 저장·삭제만 제공한다. 내부 JSON Lines의
  `claude_api_key`와 요청별 credential scope를 통해 Pipeline 생성 당시 값을 유지하고,
  Claude 인증 조회·작업 자식 환경에만 주입한다. 앱 키를 사용할 때 상속한 외부 인증·
  endpoint·cloud provider 환경 변수는 이 자식에서만 제거한다. CLI의 관리 정책은
  변경하지 않는다. 원문 출력·RPC 오류에서 키를 마스킹하고, 저장 상태와 실제 API 검증은
  구분한다. 삭제하면 기존 CLI·환경 인증을 따르며 실행 중 작업은 재시작하지 않는다.
  모델 연결의 모델 ID는 수동 프로필 목록·계획 검증·실행 모델 검증에 포함한다. planner에는
  추가 모델 ID만 명시적으로 전달하며 비밀값·credential scope 접근은 추가하지 않는다.
  공통 AI 연결 dialog는 Codex 로그인·Claude 로그인/API 키·NVIDIA 키를 독립적으로 관리하며, 화면의 제공자
  선택으로 연결 해제·기본 실행 AI 변경·키 자동 순환을 수행하지 않는다.
  Claude Planning 채팅만 `Pipeline`이 소유한 session
  ID를 `--session-id`·`--resume`으로 전달한다. Claude의 Task·Review와 custom command는
  단발 실행이다.
- `document_index`는 전달받은 파일 후보나 제한된 파일 시스템 탐색 결과로 로컬 색인을
  만들며 Git 명령과 Planning AI 실행을 직접 소유하지 않는다.
- `planner`는 설정과 모델을 사용할 수 있지만 `pipeline`을 참조하지 않는다.
- `planning`의 기본 import는 기존 Plan/PlanningError 계약과 요청문·schema·Task/사용자 확인/
  기획 단계 검증, 공급자·실행 AI/리뷰어 배정과 명시적 callback 기반 계획 변경 API를 노출한다. 기존 `planner` import는
  같은 계약을 노출하며 기본 import는 planner·Pipeline·Store·Git을 로드하지 않는다.
- 명시적으로 가져오는 `planning.runner`는 계획 생성 시도·SDK/Claude 세션 연속성·timeout·
  캐시 재검증·시도/preview 진행 기록을 조합한다. repository·PlanningConfig/RoutingConfig 값·SDK와
  agent/실행 프로필 조회·기존 Git 조회·검증·provider 호출·저장 callback만 받고 Pipeline/Store/Config
  전체를 받지 않는다. `PlanningPersistence`는 기존 run 경로·상태/preview/결과 cache API만 연결한다.
  시도 증거만 갱신하며 승인·run/대화 잠금·강도 scope·최종 계획 적용/상태 전이·SDK 수명은 기존 소유자에 둔다.
- 명시적으로 가져오는 `planning.chat.PlanningChatRunner`는 repo/timeout 조회·기존 SDK와 좁은
  profile/문맥/prompt/기록/호출 callback으로 대화 세션·근거 문맥·시도/오류를 조합한다. SDK 전체 수명을
  소유하지 않고 기존 thread/session 재개·초기 Claude 세션 확정 위치를 유지한다. Pipeline은 정책 scope와
  대화 잠금·메시지/계획 최종 반영을 소유한다. 기본 planning import에는 이 runtime을 추가하지 않는다.
- `planning.output`은 응답의 문서/단계 근거 검증·이전 수동 프로필 보존·모델 배정과 캐시 identity를,
  `planning.documents`는 선택 문서 복사·digest·manifest를 소유한다. `planning.conversation`은 명시적
  반영 제어 문장과 구체적 요구의 구분, 기존 저장 문맥 복원과 응답/태스크 초안 표현을 소유한다.
  기존 Pipeline 메서드는 같은 함수 별칭이나 좁은 위임이며 runtime 모듈은 Pipeline/Store를 역참조하지 않는다.
- `planning.changes`는 계획 초안 검증·수동/legacy 프로필과 리뷰 보존, 같은 그룹 Task 병합/보호와
  반영 요청 revision/중복 처리, 결과 수정 제안 검증을 소유한다. 필요한 설정 조회·문맥/메시지·
  Task 편집/근거 경로 callback만 받고 전체 Pipeline/Store/Config나 실행 모듈에 의존하지 않는다.
  병합 결과는 Task 목록과 준비할 ID이며, 잠금·AI/작업 준비·최종 전이/저장·실패 복원은 Pipeline에 남는다.
- `planning.result_revisions.ResultRevisionWorkflow`는 원래 결과 evidence/경로·문맥과 제안/요청 조회·
  재사용·대상 검증·같은 그룹/연결 그룹 선택을 조합한다. 명시적 기록/재시도 잠금·기획/근거/알림 callback만
  사용하며 제안 AI와 연결 그룹 준비·바깥 proposal/request 잠금·입력 검증은 Pipeline이 소유한다.
  기존 fingerprint/receipt·저장 실패 뒤 child 재사용과 저장 뒤 재시도 대기 알림 순서를 유지한다.
- `execution.project_chat`는 순수 문법/행동 계약인 최상위 `project_chat`를 재사용한다.
  `ProjectChatDecisions`는 결정 claim/한도·응답/취소/대상/범위 재검증과 기록을, `ProjectChatActions`는
  행동 claim/중복 거부·실제 결과/중지와 후속 기록을 소유한다. `ProjectChatRecords`로 요청 제어 잠금과
  기록 API만 받으며 실제 판단/프로필/동의 fast path와 실제 행동/run lock/session은 Pipeline callback이다.
  명시적 handled/payload 결과와 준비된 행동 DTO만 교환하며, 실행 callback은 갱신된 operation을 반환해
  범위 승인 후 reload/expected/history 순서를 보존한다. 전체 Pipeline/Store/Config나 임의 context는 받지 않는다.
- `planning.preview.PlanningPreviewWorkflow`는 fingerprint/Task 차이·후보 digest 검증·공개 후보와
  활동 상태 조회·후보 생성을 조합한다. `PlanningPreviewRecords`의 기존 run/candidate/progress/chat·
  잠금 조회 callback과 계획 생성·문맥/색인·파일 digest·요청 ID callback만 받는다. 진행 표시 파생 함수는
  I/O 없이 DTO를 사용하며 workflow는 기존 명세 파일 읽기와 명시적 기록 callback을 사용한다.
  SDK/Git 오류 tuple은 호출자가 전달하므로 planning 기본 import에 실제 runtime 의존성을 추가하지 않는다.
  Pipeline은 run/chat 잠금·preview 생성의 실패 표시와 승인된 후보 적용/최종 상태 전이를 소유한다.
- `planning.bootstrap.BootstrapPlanner`는 repository 경로와 기존 Run/Task/BootstrapSpec DTO만 받아
  확정 기술 결정의 기본 구조 명세·AGENTS.md 미리보기, 생성/제외 선택의 명세 갱신과 실행 직전
  경로 변경 재검증을 처리한다. 원본 AGENTS.md는 보존하고 자동 주입한 경로/완료 기준만 제외·복원한다.
  경로 snapshot은 파일 digest·디렉터리·symlink/junction을 기록하며 링크를 따라가지 않고 기존 제외
  디렉터리와 최대 10,000개 제한을 유지한다. 명세 생성/재검증은 프로젝트 파일을 쓰지 않는다.
  Pipeline은 기존 설정 요청의 잠금·stage/revision/digest 검증·계획 revision/이벤트·최종 저장을 소유하고,
  실행 전 계획 확인 다음·작업공간 생성 전에 경로를 재검증한다. 기존 helper·상수 import와 저장 형식은 유지한다.
- `models`의 기존 클래스·enum·상수 import는 `state`의 같은 객체를 가리킨다.
  `state` 안에서 공통 값/시간·강도·기획·작업/실행·통합·Run 책임을 나누고 실제 상태 전이와
  readiness 규칙은 RunState에 둔다. `state.codec`은 하위 모델의 필드만 복원하며 RunState나
  models facade를 역참조하지 않는다. RunState는 복원된 필드로 자신을 생성한 뒤 readiness를
  갱신한다. RunSummary는 전체 Task 모델을 만들지 않고 기존 요약 필드만 복원한다.
- `store`는 모델을 저장하지만 상태 전이를 스스로 결정하지 않는다. 상태/sidecar의 조합·
  run 존재 확인과 잠금은 기존 StateStore가 소유한다. `persistence.usage.UsageLedger`는
  경로·상태 읽기·잠금·쓰기 callback만 받고, 기록 중복/역행·집계·pagination을 처리한다.
  `persistence.planning`은 기획 결과 cache와 대화 payload/revision 복원을 소유한다.
- `integration`은 ProjectConfig/RunState DTO·GitWorkspace 공개 API와 필요한 좁은 callback으로
  협력한다. workspace layout/조회/수명·Main 변경·통합 inspector·충돌·반영 검토를 나누고
  Pipeline/Store 전체를 주입하거나 역참조하지 않는다. `MainChangeService`는 승인된 잠금 범위
  안에서 snapshot·선택 파일·현재 HEAD/index/content의 검증과 Git 작업을 조합한다.
  `IntegrationInspector`와 `ConflictInspector`는 조회만 수행하고 query 실패를 실행/반영 가능으로 숨기지 않는다.
  `errors.PipelineError`는 기존 `pipeline.PipelineError`와 같은 객체여서 예외/원인 계약을 유지한다.
- `integration.recovery.RecoveryWorkflow`는 Git adapter·작업공간/청결·초안 callback과 `RecoveryRecords`의
  run/operation/result/잠금 조회로 복구 후보·45초 deadline·claim/재생·중단 복원과 부분 적용 재개를 조합한다.
  원본 receipt와 결과/HEAD 일치를 확인하고, 실제 복구 commit 반영·재계획/정책 scope·승인/run lock과
  최종 Run 전이는 Pipeline이 소유한다. 실패나 불완전한 receipt를 성공/빈 결과로 바꾸지 않는다.
- `integration.verification.CandidateVerification`는 caller lock 안에서 격리/공유 작업공간의 후보 통합·
  검증·충돌 근거/abort·finally 정리·현재 HEAD 재검사를 조합한다. `VerifiedCandidate`에 Main/통합/Task
  commit 근거만 돌려주며, Pipeline이 그 뒤 원래 순서대로 bootstrap 완료·VERIFIED 전이·최종 저장을 한다.
  기존 pinned 검증 callback과 Git adapter를 재사용하고 Main 반영/push 승인을 추가하거나 우회하지 않는다.
  `errors.VerificationInputsChanged`는 기존 pipeline import와 같은 오류 객체다.
- `integration.candidates.ConflictCandidateBuilder`는 고정된 충돌을 detached 후보 worktree에 재현하고,
  기존 provider 호출 callback으로 해결안을 요청한 뒤 허용 경로·충돌 표식·index·commit 부모와 내용
  digest를 검사한다. 진행 이벤트는 기존 state lock으로 attempt/invocation ID와 수신/활동 근거를 검증해
  operation 기록에 저장한다. SDK/프로세스 수명과 실제 호출은 기존 Pipeline 실행 어댑터가 소유한다.
- `integration.resolution.ConflictResolutionService`는 호출자의 run lock 안에서 기존 DTO·GitWorkspace와
  조회/저장·작업공간/정리·프로필 선택 callback을 조합한다. request claim·중복/오래된 후보 차단과
  conflict/candidate 상태·부분 실패·증거 저장을 처리하며 Store/Pipeline 전체를 받지 않는다.
  Pipeline은 명시적 승인·UUID/현재 충돌 검증·run lock을 소유하고 반영 뒤 정리 잠금·verify 호출과
  검증 결과의 복구 연결을 유지한다. 성공 후 최종 조회 실패도 기존 후보 실패/정리 경로를 거친다.
- `persistence.atomic`은 기존 파일을 원자적으로 교체하고 일시 Windows 오류를 같은 횟수로
  재시도한다. 최종 실패 시 기존 파일과 복구용 임시 payload를 보존한다. 기획 결과 cache의
  별도 임시 파일 정리 규칙은 유지하며 실제 사용자 데이터를 자동 변환하지 않는다.
- `git`, `state`, `models`, `config`는 상위 흐름 모듈을 참조하지 않는다.
- 어떤 모듈도 순환 의존성을 만들지 않는다.

## 모듈 협력 규칙

- 다른 모듈의 공개 클래스와 함수로 협력한다.
- 다른 모듈이 소유한 상태 파일이나 Git 프로세스를 우회해서 직접 조작하지 않는다.
- 단순한 Python 모듈 협력을 위해 이벤트 버스, 서비스 컨테이너 또는 네트워크 API를
  추가하지 않는다. Electron 경계는 versioned JSON Lines 계약만 사용한다.
- 두 모듈에 동시에 필요한 값은 안정적인 개념일 때만 `models` 또는 `config`의 명시적 타입으로 승격한다.
- 공통 책임이 불분명한 `utils.py`, `common.py`, `helpers.py`에 기능을 모으지 않는다.

## 상태와 부작용 소유권

- 데스크톱의 `PlanningMessageQueue`는 기존 대화의 미전송 메시지를 main 수명에서 순서대로
  전달하는 로컬 outbox다. project/run·본문·AI 프로필을 예약 시 고정하고 고정 preload API로만
  추가·취소·재개한다. 수정은 미전송 예약을 취소해 원래 대화 입력창으로 가져온 뒤 다시 예약한다.
  `PlanningRequests`의 단일 슬롯과 기존 Python RPC를 그대로 사용하며 Pipeline의 대화 잠금이나
  실행·승인 판정을 대체하지 않는다. 실행 제어 의도는 예약한 Task/attempt와 최신 상태를 대조한다.
  사용자 데이터의 버전 1 JSON을 원자적으로 교체하며 앱 재시작 시 대기는 일시 정지, 전송 중이던
  메시지는 결과 확인 필요로 복원해 자동 재전송하지 않는다. backend Run 저장 형식은 바꾸지 않는다.

- `Pipeline`이 허용된 상태 전이와 실행·교차 리뷰·수정 순서를 소유한다.
- `Pipeline`이 Planning AI 프로세스와 재시도, provider 대화 식별자, 사용자 대화 메시지
  스냅샷 및 실행 전 재계획 경계를 조정하고, `planning`이 해당 출력의 schema와 task DAG를
  검증한다. Claude Planning session ID는 인증 정보가 아닌 로컬 CLI 대화 식별자로
  `RunState`에 저장하며 provider·model 변경 시 무효화한다.
- Planning 제한시간은 schema 보정 재시도마다 초기화하지 않고 하나의 `_build_plan`
  실행 전체가 공유한다. provider timeout 뒤 프로세스 트리 종료와 출력 회수도 유한한
  제한 안에서 끝내고 run을 Planning 실패 상태로 저장한다.
- `Pipeline`은 clean 저장소에서 기준 commit, Planning 실행 profile과 최종 prompt가
  정확히 같은 경우에만 `StateStore`의 Planning 결과 캐시를 조회한다. 캐시 결과도
  현재 schema, source·instruction 경로와 실행 agent 배정을 다시 검증한 뒤 적용한다.
- clarification 재계획에는 최신 구조화 계획과 최신 사용자 메시지만 전달하고 전체
  대화 이력은 `RunState`에 보존한다.
- 채팅의 기존 논의 반영 명령과 새 요구가 포함된 계획 변경 요청은 구분한다.
  `코덱스만 쓰는 걸로 테스크를 변경해줘` 같은 요청은 사용자 대화 revision에 먼저 저장하고
  변경 미리보기를 생성한다. 재계획·실행 후속 문맥에서는 단순 제어 문장만 제외하며
  구체적인 요구는 전달한다. Task 변경은 기존 미리보기 확인 절차를 따르고 실패해도 요구를 보존한다.
- Planning 대화는 `needs_clarification`, `planned` 또는 Planning 실패 상태에서 같은
  run을 다시 계획한다. Task 실행이 시작된 상태에서는 기존 작업공간과 구현 결과를
  무효화하지 않도록 메시지 전송을 거부한다.
- `document_index`가 선택 기획 디렉터리별 색인을 설정된 `state_dir` 아래에 원자적으로
  저장하고 동일 파일의 메타데이터를 재사용한다. `Pipeline`은 Git에 보이는 파일 후보와
  기준 commit을 전달하고 Planning 시작 시점의 색인을 run에 스냅샷한다. Planning AI의
  초기 입력에는 전체 문서 메타데이터 대신 크기가 제한된 디렉터리·대표 문서 요약과
  전체 JSON 색인 경로만 전달하며, agent는 해당 색인을 좁은 검색으로 조회한다.
- 색인은 이전 기준 commit과 현재 색인의 SHA-256을 비교해 추가·수정·삭제 문서를
  기록한다. 변경 문서는 제한된 본문 발췌를, 관련 현재 문서는 메타데이터만 Planning
  입력에 추가한다. 같은 기준 commit의 변경 묶음은 안정적으로 유지해 동일 prompt의
  Planning 결과 cache가 모델 중복 실행을 막는다. 다음 기준 commit에서는 직전 색인을
  새 비교 기준으로 사용한다.
- 최초 directed 디렉터리 Planning에서 `document_index`는 요청과 색인 메타데이터를
  비교해 최대 5개 문서의 제한된 본문 발췌와 출처를 구성한다. `Pipeline`은 이 문맥을
  기존 prompt 기록과 캐시 key에 포함한다. 문서별 읽기·발췌 상한을 적용하고 경계 이탈,
  읽기 실패와 확인 가능한 색인 이후 변경을 Planning 오류로 변환한다. 후보는 AI의
  최종 source_paths가 아니며 auto와 대화 재개는 기존 탐색·스냅샷 경로를 유지한다.
- 디렉터리 Planning은 같은 저장 기획문서와 색인을 사용하는 `directed`와 `auto`
  범위를 가진다. 기본 데스크톱 `directed` 범위는 사용자 요청을 run에 저장하고 관련
  문서와 직접 의존성·충돌·검증 자료만 탐색한다. `auto` 범위만 기획문서의 미완료
  backlog를 발굴한다. 기획문서 경로가 없는 `directed` 실행은 문서 색인을 만들지 않고
  사용자 요청과 필요한 저장소 코드만 읽기 전용으로 조사하며, `auto` 실행은 기획문서
  파일 또는 디렉터리를 필수로 요구한다. 기존 run과 범위를 지정하지 않은 CLI 호출은
  `auto`로 해석한다.
- `planning`은 task 완료 조건, dependency, 예상·금지 변경 경로, argv 검증 명령,
  위험도와 Planning AI의 실행 provider·모델·추론 강도 추천 계약을 검증한다.
  추천이 없는 Markdown fallback과 이전 구조화 결과는 routing 정책으로 변환한다.
  기본 `balance_providers=true`에서는 연결된 실행 후보의 역량·용량을 확인하고 계획 안에서
  공급자별 실행 배정량이 적은 쪽에 나눈다. 같은 배정량이면 역량 일치도·기본 공급자·ID로 결정한다.
  수동 전용 공급자는 자동 분배에서 제외하고, 구체적인 AI 추천과 capability 규칙은 유지한다.
  `balance_providers=false`는 기존 기본 공급자 고정 배정과 호환한다. 기획 후보 수집에서
  Codex·Claude의 인증 상태를 확인하며, 이미 저장된 Task를 연결만으로 재배정하지 않는다.
  같은 Task를 재계획할 때는 현재 상태에 저장된 수동 실행 agent/provider/model/추론 강도를
  AI 추천보다 우선한다. 일반 응답과 캐시 모두 배정 전에 복원하고 정확한 agent의 가용성·역량·
  모델·용량을 검증한다. 사용할 수 없는 수동 선택은 다른 AI로 대체하지 않고 실패시킨다.
  새 Task에는 기존 수동 선택을 전파하지 않으며 Task 설정의 명시적 변경은 그대로 허용한다.
- CLI·desktop/MCP 호스트는 읽기 전용 계정 한도 reader를 Pipeline에 주입하고 Claude 인증을
  요청 시점에 고정한다. 캐시는 Pipeline 인스턴스 안에서 최대 30초, 숫자 reset 시각까지다.
  확인된 5시간·주간 한도 소진만 신규 자동 후보에서 제외하며 조회 실패·미제공·API 키는
  소진으로 취급하지 않는다. dispatch 직전 미시작 자동 작업만 연결된 대안으로 전환한다.
  수동·legacy·명시적 routing rule과 시작한 작업·리뷰 계약은 보존한다. 대안이 없으면 명시적으로
  실패한다. 전환 snapshot과 원래 정책 근거를 기존 execution profile sidecar에 먼저 저장하고,
  started 정책 검증은 그 기록과 일치하는 전환만 허용한다. 인증 방식을 자동 변경하지 않는다.
- `model_selection`은 Codex·Claude 자동 모델의 닫힌 허용 목록과 위험/역량/범위/작업 내용에 따른
  순수 선택 규칙을 소유하며 `models`에만 의존한다. `planning.assignment`와 `effort_policy`가 같은 규칙으로
  계획·미리보기·기획 호출을 해석한다. 수동·레거시 출처는 보존한다. 자동 기획/원인 판단/충돌
  해결은 Sol, 절약의 명확한 낮은 위험 작은 수정은 Luna, 나머지는 Sol을 사용한다. SDK의
  빈 모델도 Sol로 해석하며 5.6 또는 새로운 SDK 기본 모델로 조용히 대체하지 않는다.
  새 고정 정책 버전 3은 Luna의 실제 코드 검증 실패에 한해 Sol/high 승격을 한 번 허용한다.
  Task의 선택 이유와 정책 ID·실패 action 인덱스를 저장하고 재시작/호출 전 원래 고정 프로필과
  실패 근거를 대조한다. 원래 정책과 이전 사용량은 수정하지 않으며 v1/v2 정책은 그대로 해석한다.
  SDK·권한·파일 잠금·시간 초과·사용자 중지·범위 실패는 모델 승격으로 우회하지 않는다.
  Claude 자동 선택은 일반 구현에 Sonnet, 높은 위험·민감 계약·설계·동시성·선행 필수 작업·
  충돌·넓거나 불명확한 범위에 Opus를 사용한다. 집중과 내부 기획·원인 판단도 Opus다.
  명시적인 버전 ID와 수동·레거시 프로필은 유지하고, 배정·미리보기·호출이 같은 규칙을 따른다.
  실행 전에는 선택 이유를 기존 필드에 기록하고, 시작된 정책은 snapshot을 재사용한다.
  Claude 실패 후의 새 자동 승격·재시도는 추가하지 않는다.
- `RunState`는 task lifecycle과 dependency 상태에서 readiness와 차단 dependency를
  계산하고, `Pipeline`은 이 계산 결과로 실행 가능한 task를 선택한다.
- `planning.validation`은 예상 경로의 잠재 교집합으로 충돌 그룹과 자동 선행 관계를 계산한다.
  명시 dependency를 유지하면서 `is_prerequisite` 작업을 겹치는 일반 작업보다 먼저
  배치하고, 모순된 순환 관계는 거부한다. 자동 관계는 계획 변경 시 재계산하며
  `RunState`의 readiness와 `Pipeline`의 의존성 통합은 명시·자동 관계를 함께 사용한다.
  renderer는 저장된 분석 결과를 표시한다. schema 20 이전 상태는 새 필드를 기본값으로
  읽으며, 실행 중인 기존 Run의 순서를 로딩 시 재계산하지 않는다.
- 새 Planning 결과와 planned 상태의 Task 편집·제외는 `plan_revision`을 올리고 기존
  확정을 무효화한다. `Pipeline`은 전체 Task Graph와 실행 profile을 다시 검증한 뒤
  현재 revision만 확정하며, 확정되지 않은 revision의 그룹·개별 Task 실행을 거부한다.
  Task 실행이 시작되면 계획 편집 UI는 잠기지만 Planning 자유 대화는 유지한다.
  명시적인 Task 반영 요청은 같은 그룹의 미실행·실패 Task 계획 필드만 갱신한다.
  완료·수동 확인 결과와 Task ID·worktree·commit·실행 이력은 보존한다.
  실행 중 요청은 현재 batch가 끝난 경계에서 반영하고 다음 실행은 사용자 확인까지 멈춘다.
  실행 후 명시적 반영은 기존 실행 승인을 유지하고 자동 재실행하지 않는다. 실행 전
  반영만 새 revision을 만들어 다시 사람 확인을 요구한다. revision 필드가 없는 기존 상태
  파일은 호환을 위해 기존 확정 계획으로 취급한다.
  실행 후 재계획으로 추가·변경된 미실행 Task는 기존 작업공간 경계를 검증한 뒤 prompt와
  log 경로를 즉시 준비한다. 이전 버전에서 이 실행 파일이 누락된 Task는 다음 실행·재개
  진입 시 같은 경계에서 복원하며, 빈 경로를 현재 디렉터리의 파일로 해석하지 않는다.
- task 공급자 호출은 `execute`, `review`, `revise` action과 시도 정보를 상태에 먼저
  저장하며, 구현·수정 실행에는 Task에 저장된 모델과 추론 강도를 provider 명령에
  적용한다. Task 검증은 별도 `verify` action으로 기록하고 resume은 마지막 실패
  action부터 이어가므로 검증 실패가 구현 agent를 다시 실행하지 않는다.
- Task의 현재 작업과 마지막 활동은 기존 progress 필드에 기록한다. SDK 동일 단계 알림은
  5초 간격으로 다시 보고할 수 있으며, 기록 시각은 실제 알림을 받았을 때만 갱신한다.
  renderer는 action_results의 실제 성공/실패 및 통과 명령 수를 표시하며 SDK 계획 진행과
  오케스트레이터의 단계 완료를 별도로 표시한다. 로그 조회는 겹치지 않게 주기 실행하고
  Task 선택 변경 후 도착한 이전 로그 응답은 무시한다.
- Task action은 고유 attempt ID를 Task의 현재 시도, action 결과와 provider 진행 관측에 함께
  기록한다. renderer는 동일 ID의 실패 응답만 현재 실패 근거로 사용하고, 구형 기록은 action과
  비교 가능한 시각이 일치할 때만 연결한다.
- 데스크톱 .NET 경로는 `RegisteredProject.dotnet_executable` 선택 필드로 로컬 registry에
  저장한다. 기존 항목의 누락/빈 값은 PATH 탐색이다. `desktop_rpc`는 매 요청의 최신 설정을
  `Pipeline`에 전달하고, SDK 진단과 Task/통합 검증이 같은 실행 파일을 사용한다. dotnet
  SDK 명령이 있는 Task에는 실행 직전 해당 절대 경로와 치환된 검증 argv를 추가해 Codex가
  실행하는 focused .NET 명령도 같은 파일을 사용하게 한다.
  실행 전 SDK 검사는 Task 작업 디렉터리에서 수행하며 실패 action과 로그를 보존한다.
  SDK 확인 RPC는 임의 명령을 받지 않고 `git.diagnose_dotnet`의 고정 진단만 수행한다.
- planned 상태의 실행 profile 변경은 Task 계획 편집에 포함되며 저장 후 다시 확정해야
  한다. 실행 요청에 끼워 넣는 profile override는 확정 뒤 또는 일부 Task 실행 뒤에 허용하지 않는다.
  사용자가 명시적으로 선택하는 `tasks.updateExecutionProfile`은 별도 저장 경로다. 멈춘 실행 그룹이나
  Agent 실행 실패 그룹의 미실행·실패 Task에 다음 실행 모델을 저장한다. 이 직접 저장은 실행/기획 lock·
  활성 Task·미완료 작업 강도 binding이 있으면 거부한다. 실행 중인 그룹의 `pending` Task는 별도
  `task-execution-profiles.json`에 저장하고, 실행 소유자가 batch 사이 dispatch 경계에서만 반영한다.
  저장과 실행 시작이 같은 Planning 대화 lock 아래 profile·attempt·status·계획 revision을 재검증하며,
  조회는 저장된 다음 모델을 보여준다. 다른 RPC가 실행 소유자의 RunState를 덮어쓰지 않는다.
  작업 강도 snapshot·binding과 다음 실행 강도 예약을 보존하고, 해당 policy ID·원래 프로필·계획 revision에
  결합한 별도 수동 반영 기록으로 이후 호출의 변경 프로필을 검증한다. 실행 중인 Task는 변경하지 않는다.
  수동 출처로 저장하고 작업 내용·승인·실패·완료 결과와 과거 실행 모델 기록은 유지한다.
  모델이 바뀐 실패 Task의 다음 재시도는 구현부터 시작한다. 저장만으로 실행·중지·재개하지 않는다.
  채팅 복구·개별 재시도는 저장된 Task 프로필과 같은 계획의 마지막 적용 강도(없으면 기존 선택 강도)로 실행하며
  다음 강도 예약을 소비하지 않는다.
  초기 실행·일반 재개에는 예약 강도의 계획 일치 검사를 유지하고, 기존 started binding은 같은 snapshot으로 복구한다.
- `StateStore`가 `state.json`, schema-versioned Planning 결과 캐시와 실행 중 Planning
  대화·다음 실행 모델 sidecar의 원자적 교체, token 기반 run lock과 별도 Planning 대화 lock을 소유한다.
  실행 상태와 Planning 대화 저장은 고유 임시 파일을 사용하고 Windows 교체 오류
  5/32/33을 최대 6회(총 대기 1.55초) 시도한다. 계속 실패하면 기존 대상 파일과 완성된
  임시 payload를 보존하고 원인과 경로를 포함한 오류를 반환한다. 대상 파일을 먼저
  삭제하거나 실패를 성공으로 처리하지 않는다.
- `notifications.events`는 저장되는 Run 상태에서 완료·최종 실패·사용자 확인 대기의 source key와
  이동 대상을 파생해 기존 `notification_events`에 누적한다. `NotificationCollector`는 Run과 별도
  사건 조회 callback으로 중복 병합·정렬·cursor pagination을 수행한다. 조회는 작업 상태를 바꾸거나
  읽음 처리하지 않으며 원본 오류·prompt를 복제하지 않는다. `persistence.notifications`가 별도 사건
  파일의 ID·경로·metadata를 검증하고, StateStore가 기존 validator·run 경로·원자적 쓰기를 연결한다.
  Run 저장과 사건 동기화 시점은 기존 StateStore/Pipeline이 소유한다.
- Electron main의 `workNotifications` center는 선택된 화면과 독립적인 polling·상태 commit과
  기존 IPC 진입점을 유지한다. `notifications/`의 contracts/records/codec/storage/refresh/delivery가
  내부 계약·읽음/숨김 기록·형식 복원·파일 저장·조회 진단·OS 전달을 나눈다. 사용자 데이터의
  cursor·읽음·숨김·전달 시도·설정은 기존 schema 4로 원자 저장하고 1~3 복원·backup/future 보호를 유지한다.
  최초 조회와 재시작 catch-up은 앱 알림함에만 넣고 새 사건만 앱이 비활성일 때 OS 알림으로 보낸다.
  전달기는 queue·묶음 timer·취소 수명을 소유하고 현재 기록·대기 근거 조회와 저장 callback만 받는다.
  await 뒤 현재 읽음/숨김·설정·취소를 확인하고 전달 시도를 저장한 뒤 OS에 표시한다.
  알림 선택은 기존 창을 복원해 저장된 대상으로 이동할 뿐 실행·승인·Git 요청을 만들지 않는다.
  앱 종료는 center의 polling과 전달기의 timer·진행 중 전달을 함께 무효화한다.
- 작업 그룹 삭제는 `Pipeline`의 별도 승인·잠금 경계에서 `integration.WorkspaceLifecycle`이
  deterministic Run worktree와 branch 소유권을 전부 검증한 뒤 `GitWorkspace`로 로컬 작업공간을 제거하고,
  `StateStore`가 마지막에 정확한 run 디렉터리만 삭제한다. Windows의 worktree 제거는
  명령 범위의 `core.longpaths=true`를 사용해 긴 내부 경로도 Git 등록과 함께 제거하며,
  저장소·사용자 Git 설정은 변경하지 않는다. 이전 제거가 긴 경로 오류로 부분 실패한
  경우에는 run 이벤트의 정확한 대상 경로, 결정적 run 경계와 사라진 `.git` 표식을 모두
  확인한 잔여 디렉터리만 Windows 확장 길이 경로로 삭제한다. 증거가 없는 미등록 경로와
  link·junction은 계속 거부한다.
- `ProjectRegistry`가 사용자 설정 디렉터리의 `projects.json` 원자적 교체,
  프로젝트 name/repository 중복 검사, 관리 설정 경로 결정과 프로젝트별 기획
  디렉터리 저장을 소유한다. `config`는 요청받은 관리 경로에 기본 TOML을 원자적으로
  생성하되 기존 파일을 덮어쓰지 않는다.
- `StateStore`는 같은 host의 소유 PID가 종료된 lock만 `stale`로 판정하며, 다른
  host나 손상된 메타데이터를 임의로 정리하지 않는다.
- `Pipeline`의 상태 변경 명령은 run별 lock 안에서 실행한다.
- stale lock 삭제는 `Pipeline`의 독립적인 승인 경계를 통과해야 한다.
- `integration.WorkspaceLayout`은 고정/legacy root와 Run 공유/격리 workspace의 deterministic
  경계를 해석한다. `WorkspaceInspector`는 제한 시간 안에서 경계·청결·잠금·통합 상태를 조회하고,
  `WorkspaceLifecycle`은 기존 소유권/HEAD/branch/사용자·ignored 파일 검사를 거쳐 보관/삭제
  대상을 판정·정리한다. Pipeline은 실행 승인·잠금·SDK 수명·실패 사건과 최종 Run 저장을 소유한다.
  shared 정리의 SDK client 해제와 부분 실패 저장은 같은 위치의 좁은 callback으로 연결한다.
  보관 target metadata는 수명 관리 API가 갱신하고 실제 Run 저장은 Pipeline이 수행한다.
  `GitWorkspace`는 Git 등록 조회와 local worktree·branch 제거, 원자적 Main 갱신을 수행한다.
- workspace 정리는 Main 반영·Push가 끝난 clean Run과 unlocked run만 대상으로 한다.
  공유 workspace는 Main Push 성공 뒤 자동 정리하고, 수동 정리는 별도 승인을 요구한다.
  상태, prompt와 log는 정리 대상이 아니다.
- resume은 검증 가능한 이전 단계만 복원하고 부분 merge나 task 준비 실패를 임의로
  진행하지 않는다. push와 deploy의 기존 승인 경계도 유지한다.
- 공급자 timeout과 운영체제별 프로세스 트리 종료는 `Pipeline`의 실행 경계에서
  처리하고 기존 run log와 실패 단계에 결과를 기록한다. 모든 Codex Planning·Task·Review는
  진입점이 소유한 Codex SDK client의 설정된 sandbox·approval profile로 실행한다.
  `Pipeline`은 새 Planning 준비 전에 Codex SDK 계정 또는 Claude CLI의 읽기 전용 인증
  상태를 재검증한다. provider 판정에서는 로그인 여부와 허용한 인증 분류만 사용하고
  이메일·조직·token은 실행 상태나 log로 전달하지 않는다. Claude command가 OAuth 만료·인증
  실패로 종료되면 provider 원문을 log에 보존하고 비밀값을 복사하지 않은 재로그인
  안내를 사용자 오류로 반환한다.
  전역 `auth.claude.status` 조회도 같은 인증 판정을 사용하며 설치 여부·로그인 여부·허용된 분류와
  안내와 연결 화면 전용 `account_email`, `plan_type`을 반환한다. 정상 구독 인증의 공개 CLI 응답에서
  허용한 이메일·구독 유형만 사용하며 누락·실패·API/외부 인증은 빈 값이다. 원문·조직·비밀값은
  전달·저장하지 않는다. Electron의 고정된 `orchestrator:claude-login`은 사용자 클릭으로 공식 CLI 로그인
  터미널을 열며 renderer에서 명령·인자·경로를 받지 않는다.
  SDK adapter가 해당 turn의 timeout·interrupt와 구조화 로그를 기존 Pipeline 오류
  계약으로 변환한다.
- 통합 검증은 최신 Main 확인·동기화, 검증 명령과 결과 저장 단계를 현재 항목과
  전체 개수, 시작 시각과 함께 `RunState`에 저장한다. renderer는 장기 `runs.verify`
  요청과 병행하는 기존 상태 polling으로 현재 단계와 경과 시간을 표시하며, 검증 중인
  run의 후속 작업 Branch Push 동작을 활성화하지 않는다. 저장된 `active_step=verify`와 실제
  active verify lock이 함께 있을 때만 실행 중으로 판정하고, lock이 없거나 stale이면
  중단·재시도 상태로 표시한다. Main·공유 작업 branch 조회와 동기화에 사용하는 Git
  명령은 모두 비대화형으로 실행하고 로컬 Git 제한시간을
  적용해 응답하지 않는 자식 프로세스가 검증 lock을 무기한 점유하지 않게 한다.
  프로젝트·Task 검증 명령도 비대화형으로 실행하며 Git 명령은 로컬 Git 제한시간,
  일반 빌드·테스트 명령은 명령당 10분 제한시간을 적용한다. `git worktree` 명령은
  Pipeline 소유 작업공간을 조회·변경하는 명령이므로 통합 검증에서 제외하고 run
  이벤트에 사유를 남긴다. npm script 검증 명령의 대상 디렉터리에
  `package-lock.json`은 있지만 `node_modules`가 없으면 Pipeline이 같은 검증
  작업공간에서 `npm ci`를 한 번 선행한다. 명시적인 `npm ci`/`npm install` 명령이나
  이미 설치된 의존성은 중복 처리하지 않으며 복원 진행과 실패도 검증 상태·log에 남긴다.
- 기존 격리 Run의 승인된 Main 반영은 Task branch, Main과 보존된 integration branch를
  확인하는 사전 조회부터 fast-forward와 integration branch 정리까지 모든 로컬 Git
  호출을 비대화형·30초 제한으로 실행한다. renderer는 승인 요청 직후 Main 반영 진행과
  경과 시간을 표시하고, 이전 backend 종료로 stale lock이 남았다면 기존 승인 경계에서
  잠금을 정리한 뒤 Main 반영 요청을 다시 보낸다.
- Codex SDK Planning의 turn·item·plan event는 원문 추론과 command 내용을 노출하지
  않는 제한된 진행 단계로 변환해 `RunState.events`에 저장한다. renderer는 기존 status
  polling으로 최신 진행 상태를 표시하며 빈번한 delta event는 저장하지 않는다. run이
  만들어지기 전의 기획문서 경로 저장·색인·실행 요청은 renderer의 일시적인 준비 상태로
  표시하고, run 생성 뒤에는 저장된 event와 질문·답변을 같은 Planning 대화 영역에서
  이어서 표시한다. 데스크톱 시작 흐름은 색인 token을 전달하는 짧은 run 준비 RPC와
  장기 Planning RPC를 분리해 renderer가 Planning 실행 전에 run ID를 확보한다. CLI의
  동기식 시작 계약은 같은 두 Pipeline 단계를 연속 호출해 유지한다. planning backend는
  직전에 갱신한 색인 객체를 token과 함께 한 번만 소비하며, 해당 준비 요청에서는
  저장소 확인과 Git 변경 검사를 반복하지 않는다. 기존 Planning 대화에서 사용자가
  메시지를 전송하면 renderer는 사용자 메시지를 즉시 대화에 표시하고 입력값을 비운 뒤,
  장기 `runs.sendPlanningMessage` 요청과 병행해 control backend의 `runs.get`을 polling한다.
  저장된 SDK 진행 이벤트는 같은 대화의 현재 작업 항목으로 갱신한다. 기본
  `runs.sendPlanningMessage`는 기본적으로 같은 provider 대화(Codex SDK thread 또는
  Claude CLI session)에서 자유 형식 답변만 생성하며
  기존 구조화 계획, Task와 run stage를 변경하지 않는다. 사용자가 계획·Task의 반영·적용·
  생성·갱신을 명시적으로 요청한 문장만 Pipeline이 승인된 반영 의도로 판정하고, 같은
  provider 대화에 `AI_PLAN_RESULT` materialization을 요청한 뒤 기존 검증과
  `_apply_plan` 경계를 통과시킨다. 질문형·예시형 문장은 일반 대화로 유지하며 intent
  분류를 위한 별도 모델 turn은 추가하지 않는다. provider 대화가 유실된 경우에는 저장된
  대화와 계획을 이용해 새 provider session으로 복원한다. Task 실행 중 대화는 장기 run
  lock과 분리된 sidecar에 저장해 실행 상태 저장과 서로 덮어쓰지 않는다. 이 단계의 반영
  요청은 기존 sidecar 목록에 적용 대기로 보관한다. 적용 시 run lock 뒤 chat lock을 잡고
  최신 상태로 재계획한다. 실패 시 기존 Task와 요청을 보존하고 오류를 기록한다.
  Planning 대화 기록과 직전
  구조화 계획을 제한된 크기로 복원 prompt에 포함한다. 영구 상태의
  `planning_attempts`는 작업 그룹 전체의 provider 호출 누적값이며, renderer의 현재 요청
  시도 표시는 마지막 `planning document reviewed`, `planning chat message received` 또는
  `planning apply requested from chat` 이후의 attempt 시작 이벤트만 계산한다. 최초 디렉터리
  Planning은 질문과 함께 best-effort
  Task 초안을 요구하지만, 기존 계획의 후속 대화는 Task 없는 확인 질문도 허용한다.
  renderer는 Pipeline 검증 오류를 Backend 장애로 표시하지 않으며, Backend 프로세스
  종료·조회 timeout처럼 복구가 필요한 경우에만 재시작 동작을 노출한다. 하나의
  `_build_plan` 안에서 응답 구조
  검증이 실패하면 같은 ephemeral SDK thread에 검증 오류와 수정 지시만 후속 turn으로
  전달한다. 전체 기획 prompt와 문서 탐색 지시는 반복하지 않는다. 동일 작업 그룹의
  후속 Planning 메시지도 provider·model과 실행 설정이 같으면 해당 대화를 이어서 최신
  사용자 메시지만 전달한다. Codex SDK thread가 유실됐거나 기존 Claude run에 session
  ID가 없으면 저장된 문서·직전 계획·대화 기록을 복구 prompt로 보내 새 대화를 만든다.
  Claude session ID는 최초 응답이 성공한 뒤에만 저장하며 provider·model 변경 시
  초기화한다. Codex conversation은 작업 그룹 삭제·사용자 중단·Backend 종료에서
  정리하고 Claude CLI 전역 session 파일은 오케스트레이터가 직접 삭제하지 않는다.
- Codex SDK turn의 Planning 제한시간은 전체 wall-clock 시간이 아니라 SDK notification이
  연속으로 없는 비활성 시간에 적용한다. UI에 저장하지 않는 delta도 activity로 인정해
  active한 문서 탐색을 중단하지 않으며, 비활성 제한을 넘기면 turn을 interrupt하고 해당
  SDK client를 폐기한다. 외부 provider의 Planning 전체 시간 예산은 유지한다.
- `GitWorkspace`가 branch, worktree, commit, merge, push 조작을 소유한다.
- 승인된 작업 그룹 폐기에서는 그룹 소유의 dirty·미병합 공유 worktree와 branch를 force
  제거할 수 있지만 Main branch와 remote는 대상에 포함하지 않는다.
- 새 Run의 Task는 하나의 공유 worktree에서 dependency와 계획 순서에 따라 직렬로
  실행하며 Task마다 독립 commit을 만든다. Main branch는 Main 반영 승인 전까지
  변경하지 않는다. 기존 Task별 worktree Run은 호환 경로로 유지한다.
- 공유 순차 Run의 계획 생성·편집·확정·프로필 변경은 에이전트를 재사용하며 `max_tasks`를
  총 Task 수 제한으로 적용하지 않는다. 격리 Run은 기존 배정 한도를 유지한다.
  capability·모델·독립 Reviewer 검증은 두 모드에서 동일하게 적용한다.
- 실행 카탈로그는 command 없는 Codex SDK 프로필도 포함하고 Pipeline이 실제 사용
  가능 여부를 판정한다. Planning 대화·Task 반영·재시도마다 최신 카탈로그를 전달하며
  Planning 제공자와 실행 제공자를 구분한다. renderer의 일괄 변경은 기존 Task 편집·저장
  및 계획 재확정 계약을 사용하고 프로젝트 에이전트 설정을 자동 생성하지 않는다.
- 계획 뒤 Main이 이동해도 공유 worktree는 계획 당시 base commit을 유지한다. 전체
  검증은 실행 시점의 최신 로컬 Main을 공유 작업 branch에 통합한 뒤 같은 worktree에서
  수행한다. 프로젝트 공통 `execution.verify_commands`가 있으면 이를
  사용하고, 없으면 계획에 저장된 Task별 검증 명령을 중복 제거해 통합 검증 명령으로
  사용한다.
- 전체 검증을 통과한 commit은 먼저 승인 후 Run 작업 branch로 Push한다. 검증한 Main과
  작업 branch HEAD가 유지된 경우에만 별도 승인 후 동일 commit을 Main에
  fast-forward하고 Main을 Push한다. 성공 뒤 local 공유 worktree와 branch를 정리한다.
  공유 Run에서는 원본 Main의 미커밋 경로가 검증 commit 변경 경로와 겹치지 않고
  index·작업 폴더 변경 보존을 확인한 경우에만 dirty Main에도 반영한다. 겹침이나
  보존 확인 실패는 Push·성공 전이를 중단하며 기존 격리 Run은 clean Main을 요구한다.
- Commit Queue는 dependency를 먼저 만족시키고, 같은 ready 집합에서는 `high`, `medium`,
  `low` 위험도와 사용자가 확인한 계획 순서로 Task를 정렬한다. 격리 실행의 통합 merge와
  공유 작업공간의 다음 Task 선택이 같은 순서를 사용하며 검증 시도에 실제 queue를 저장한다.
- `Pipeline`은 Task action별 결과와 통합 검증 시도별 증거를 schema 32 상태에 보존한다.
  Worker 응답과 실제 Git·명령 검증 증거는 별도 필드로 저장한다. Reviewer 판정은
  action 기록과 기존 review 계약에 남기며 자유 형식 Worker 응답을 완료 승인으로 쓰지 않는다.
  검증 명령마다 시작 HEAD를 유지하는지 확인하고 종료 시 clean 작업공간을 요구한다.
  실패·중단 이력과 시도별 통합 로그는 재시도에 덮어쓰지 않는다. 재시도는 전체 검증을
  다시 수행한다. merge 실패는 직접 실패 Task로 기록하고 검증 명령 실패는 명령 출처에
  따른 관련 Task 후보와 귀속 근거를 기록한다. 전체 테스트 실패의 단일 원인은 추정하지 않는다.
- task 범위·검증 명령·위험도는 Worker와 Reviewer prompt에 전달한다. Task 명령은
  자동·수동 Task 완료 직전에 해당 worktree에서 Pipeline이 독립 실행한다. `git`은
  Task 시작 commit 이후 이력과 stage·작업 트리·비추적 변경 경로를 NUL 구분으로 조회하고,
  `Pipeline`이 expected/forbidden 경로와 대조해 commit·완료를 차단한다. 이름 변경은
  양쪽 경로를 검사하며 forbidden이 우선한다. glob은 루트 기준·대소문자 구분이며
  `*`, `?`, `[]`는 한 구성 요소, `**`는 0개 이상의 구성 요소와 일치한다.
- 자동 Task의 독립 검증 명령 비정상 종료는 `Pipeline`이 같은 Task의 수정 지시로
  보완하고 코드 수정 또는 검증 재개를 합쳐 총 3회까지 자동 복구한다(최초 실행 포함 최대 4번).
  실패 action과 검증 로그, 자동 수정 prompt·로그·이벤트를 보존한다. 같은 오류라도 새 수정 commit이
  있으면 한도 안에서 계속하지만, 코드 변경 없이 같은 commit에서 동일 진단 반복·미증명 구현 commit,
  출력 파일 잠금·범위 위반·검증 HEAD 변경은 중단하고 승인된 Task 계약을 바꾸지 않는다.
  공급자/환경 조회 실패와 사용자 중지는 자동 코딩으로 넘기지 않는다. 수동 완료에는
  Agent를 추가 호출하지 않으며 새 공개 상태/설정과 Main·Push 부작용을 도입하지 않는다.
  MSB4018/MSB3101과 obj/bin 경로 쓰기 접근 거부가 같은 진단에 있으면 환경 실패로
  분류해 구현 commit을 보존하고 서버/노드 재사용을 끈 .NET 자식 환경에서 같은 검증을
  한 번 재시도한다. 변경한 환경에서도 같은 접근 오류가 남으면 동일 환경의 검증을 반복하지 않는다.
  부모 환경·argv·권한은 불변이며 실패 이력은 보존한다. 동일 실행의 성공
  execute/revise commit이 HEAD 조상으로 증명되면 새 commit 없이 리뷰·검증을 이어간다.
  현재 계약의 새 EXECUTE는 그 호출 이후 이력만 인정한다. 통합 검증은 command_environment로
  기록하며 코드 수정 Agent를 호출하거나 특정 Task의 코드 결함으로 귀속하지 않는다.
- Task 검증 기본 제한은 명령당 900초·전체 1800초이며 기존 Run의 저장 정책을 자동으로 덮어쓰지 않는다.
  명시적인 시간 초과 복구 요청은 run/대화 잠금과 최신 실패 검사를 거쳐 기존 한도를 최소
  900/1800초로 보완하고 VERIFY부터 재개한다. 실행 중인 명령과 더 긴 저장 한도는 유지한다.
  Task action의 선택적 `verification_context_digest`·`verification_failure_kind`로 검증 조건과
  timeout/실제 비정상 종료를 구분한다. 같은 commit·명령·설정 한도·실제 명령·자식 환경의
  시간 초과 재실행을 막고 조건이 바뀐 경우에만 명령을 실행한다. 기존 기록의 누락 값은 빈 값으로
  읽으며 반복을 추정하지 않는다. 일반 오류 비교에서는 알려진 runner의 시각·소요 시간만 정규화한다.
- 공유·격리 Task 모두 dependency 통합과 앞선 공유 Task 완료 뒤 실제 실행 직전
  `started_commit`을 기록한다. 복구에서 미리 저장된 기준은 해당 Task가 만든 HEAD 변경
  이력이 없을 때만 현재 HEAD로 갱신하며, Task가 만든 commit이 있거나 verify를 재개하면
  기존 기준을 유지한다. 범위가 있는 이전 Task에 기준이 없으면 추측하지 않고
  차단한다. 자동 execute/revise commit 전후, review 재개와 Task verify 전후에 검사하고
  수동 사전 검사 실패는 진단과 WAITING을 보존한다. 실패 파일·commit은 자동 복원하지 않는다.
  공유 재시도는 원래 기준 이후 같은 Run·작업공간의 다른 완료 Task가 성공 action의
  기준·결과로 증명한 commit만 제외한다. 현재 Task의 execute/revise commit은 우선
  포함하고, 귀속 불명 commit과 stage·작업 트리·새 파일은 제외하지 않는다. `git`은
  선택 commit의 개별 변경 경로를 조회하므로 같은 파일의 현재 Task 변경과 되돌린
  위반 이력도 남는다. `Pipeline`은 실제 expected/forbidden, 기준·HEAD, 제외 commit의
  소유 Task와 판정 경로를 Run의 Task scope JSONL에 기록한다.
  명시 경로가 없는 Markdown Task와 Git이 ignore하는 비추적 생성물은 기존 호환 범위다.
- `planner`는 명세를 읽고 `planning.assignment`에 배정을 위임한다. 배정기는 capability 라우팅
  정책으로 실행 공급자와 다른 공급자의 리뷰어를 고르며 Git 또는 실행 상태를 변경하지 않는다.
- 집중 모드의 추가 리뷰는 사용자가 명시적으로 선택한 같은 Codex 프로필도 허용한다.
  `Pipeline`이 후보·계획 반영·실행 정책의 호환성을 검사하며 SDK의 별도 대화와
  리뷰 프로필 권한으로 호출한다. 모드 저장만으로 리뷰를 자동 배정하지 않는다.
- 작업 branch push, Main 반영·Main push, deploy는 호출자가 각각 명시적으로 승인한
  경우에만 실행한다.
- Electron renderer가 직접 승인 여부를 결정하지 않는다. Electron main의 native
  dialog에서 받은 명시적 승인과 RPC의 `approved: true`를 `desktop_rpc`가 재검증한
  후에만 작업 branch push, Main 반영·push, deploy, workspace 정리와 작업 그룹
  삭제의 Pipeline 승인
  인자를 전달한다.
- 실패는 예외와 `failed` 상태로 드러내며 성공 상태로 보정하지 않는다.

## 변경 배치 기준

### 외부 AI와 결과 실행

기본 renderer `MakerApp`은 실제 registry와 Run의 조회·계획 확인·사용자 확인·결과 실행을 제공한다.
새 채팅은 외부 앱 선택 없이 MCP 설치·연결 프롬프트를 복사한다. `connections.externalGuide`의
실제 서버 명령과 `mcp-register` 등록 도우미를 전달하며, 복사 동작에서 설정을 쓰지 않는다.
등록 도우미는 현재 대화 앱에 해당하는 연결만 갱신하고 작업 AI 공급자·모델 설정을 유지한다.
외부 계획 제출 후 태스크 생성·모델 배정이 완료된 계획 승인 알림을 제작 준비 알림으로 표시한다.
대화는 Codex/Claude 앱이 담당한다. 작업 AI 연결·프로젝트 관리·알림·태스크 상세·실행과 마무리는
`MakerWorkers`, `MakerProjects`, `MakerNotifications`, `MakerTaskDetails`, `MakerRunControls`로
분리하고 같은 제작 화면 안에서 제공한다. 옛 `App`, 기획 채팅·사이드바·작업 화면과 전용 스타일·
표현 helper는 삭제했다. 실행 프로필 선택 타입은 `types.ts`, 완료 결과 선택은 `taskResults.ts`에
유지한다. 공통 인증·복구·승인 컴포넌트는 새 테마로 재사용하며 고정 preload RPC만 호출한다.
공통 대화창은 Maker 화면의 modal과 portal만 제공하며 삭제한 기획 사이드바의 생명주기를 제어하지 않는다.
계획 모델 수정은 기존 `runs.updatePlan`의 선택적 `expectedRevision`을 코어로 전달한다.

`mcp --allow-control`은 외부 계획 제출과 검토·수정·확정, 실행·재개·중지·검증을 제공한다.
관제 AI는 제어 요청의 접수 결과를 알린 뒤 답변을 끝낸다. 지속적인 진행 확인·완료·실패·
사용자 확인은 데스크톱 UI와 알림이 담당하며, 관제 AI는 사용자의 질문이나 요청한 후속 행동에
필요한 경우에만 상태를 조회한다. 접수를 실행·완료로 표현하거나 완료까지 자동 반복 조회하지 않는다.
관제 답변 종료는 MCP 프로세스 종료나 연결 해제를 뜻하지 않는다.
제작 화면은 현재 실행 제어와 현재 Task 시도·호출에 맞는 관측으로 최근 활동·경과·대기를 표시한다.
상태 조회 성공이나 새 신호만으로 작업 진행을 주장하지 않으며 오래된 관측·조회 지연과 실제 중지를
구분한다. 앱의 시작 확인은 당시 계획에 고정하고 최신 상태를 재검사한다. 모델·강도는 관제에서
시작 전에 확인하고 상시 설정 메뉴를 표시하지 않는다. 긴 실행 RPC 중에도 상태 조회·중지는
독립적으로 처리하며 접수 뒤 확인 전에는 중지 완료로 표시하지 않는다.
기존 `draft_tasks` 기획 AI 도구는 이 역할에서 등록하지 않는다. 계획 확인은 review digest와
revision으로 고정하고, 실행 요청은 UUID receipt로 중복 실행을 방지한다. MCP 프로세스 안의 로컬
작업자가 접수한 제어를 수행하며 `get_control_request`가 접수·시작·완료·실패 기록과 실제 Run을
반환한다. 접수·시작 기록만으로 현재 작업자 생존을 주장하지 않는다. Main·push·배포 승인
경계는 기존 계약을 유지한다. 빈 프로젝트의 외부 계획에도 같은 Task 검증·배정 규칙을 적용한다.

`Pipeline`이 개별 Task 또는 통합 검증을 마친 clean 공유 작업공간과 HEAD를 확인한 뒤 `result_artifacts`에 파일 경계·digest·
실행 환경 검사를 위임한다. `StateStore`는 Run 디렉터리의 `result-artifact.json`을 원자적으로
저장한다. 등록 파일 또는 Mac 앱 디렉터리의 내용이 바뀌면 실행을 거절한다. 개발 서버·임의 명령
실행은 받지 않는다. Android는 명시적으로 선택한 기기에 APK를 설치하고 시작 요청을 보낸다.
실행 요청·프로세스 시작과 실제 UI·기능 검증 결과는 구분한다.

`mcp_bundle`의 연결 등록은 앱이 사용하는 registry와 제작 제어 역할을 전달한다. Windows 패키지는
기존 안정 launcher와 동봉 runtime 갱신을 재사용하며, Claude Desktop은 자신의 stdio 설정을,
Claude Code와 Codex는 각각의 CLI 등록 명령을 사용한다. 설정 저장을 실제 연결 성공으로 표시하지 않는다.

- 새 CLI 옵션이나 표시 형식은 `cli.py`에 둔다.
- 기획 문서 후보 수집, 메타데이터 추출과 색인 저장은 `document_index.py`에 둔다.
- 프로젝트 등록 계약과 저장은 `registry.py`에 둔다. Electron lifecycle과 IPC는
  `desktop/main`, 화면과 view state는 `desktop/renderer`, Python RPC adapter는
  `desktop_rpc.py`에 둔다. 개발 checkout의 Electron 실행은 `desktop_entry.py`에 둔다.
- 새 실행 단계나 승인 규칙은 `pipeline.py`와 `models.py`에 둔다.
- 새 기획 요청·응답 계약과 검증·공급자/리뷰어 배정은 `planning`에 둔다. 문서 I/O·Markdown
  fallback·capability 추론과 기존 공개 API 호환은 `planner.py`에 유지한다.
- 새 Git 동작은 `GitWorkspace`에 둔다.
- 새 Codex SDK client 생명주기, profile 적용 또는 timeout 동작은
  `codex_sdk.py`에 둔다. SDK 내부 App Server protocol을 다시 구현하지 않는다.
- 상태 저장 형식 변경은 `models.py`와 `store.py`를 함께 검토한다.
- 새 책임이 기존 경계에 맞지 않을 때만 이름과 공개 계약이 명확한 모듈을 추가한다.

## 분리 재검토 조건

Electron UI와 Python backend의 로컬 자식 프로세스 경계를 넘어서 특정 모듈에 독립
배포, 독립 확장 또는 네트워크 격리가 실제로 필요해질 때만 서비스 분리를 검토한다.
그 전에는 Python 모듈 경계와 versioned IPC 계약을 테스트로 강화하고 하나의 로컬
제품 경계를 유지한다.


### 검토 가능한 실패 그룹 복구

`runs.recoveryPlan`은 Pipeline 잠금 아래 공유 실패 그룹의 Git 기준선, 실패 응답,
같은 프로젝트의 완료 commit 후보를 읽어 fingerprint와 함께 반환한다.
`runs.applyRecovery`는 Electron native 승인과 Python 승인·fingerprint 재검증을 거친다.
GitWorkspace가 임시 detached worktree에서 선택한 commit을 통합하고 성공한 경우에만
현재 작업 branch를 fast-forward한다. Pipeline은 미완료 Task의 scope 기준선을 갱신하고
같은 그룹 재계획을 수행한다. 통합 완료 후 재계획 실패는 통합 취소로 표현하지 않으며
기준선과 대기 요청을 저장한다. renderer는 후보 선택과 결과 표시만 담당한다.
