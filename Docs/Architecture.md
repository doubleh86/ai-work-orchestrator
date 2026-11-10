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

## 모듈 책임

| 모듈 | 책임 | 포함하지 않는 것 |
|---|---|---|
| `cli` | 인자 파싱, 명령 라우팅, 출력, 종료 코드 | 상태 전이 규칙, Git 명령 구성 |
| `pipeline` | 단계 전이, 승인 경계, 작업 실행·교차 리뷰 조정 | TOML 파싱, Git 세부 구현 |
| `project_chat` | 프로젝트 채팅의 허용 행동·구조화 AI 응답 계약 | 파일 I/O, 실행 권한 부여, 상태 저장 |
| `document_index` | 기획 문서 후보 필터링, 메타데이터 추출, 프로젝트 로컬 색인의 원자적 저장·재사용 | Planning AI 실행, run 상태 전이, Git 명령 실행 |
| `codex_sdk` | 공식 Python Codex SDK client pool, 비밀값 없는 인증 상태 조회, 실제 실행 model profile 해석·보고, thread·turn 결과·timeout·interrupt | Pipeline 상태 전이, SDK 내부 JSON-RPC 구현, 프로젝트 registry 접근 |
| `app_paths` | OS별 앱 사용자 설정 root의 경로 계산 | 디렉터리 생성, 인증·registry 내용 조회, 전역 환경 변경 |
| `nvidia_agent` | 수동 NVIDIA 코딩 프로필, OpenCode argv·도구 권한, 완료 응답·사용량 해석과 키 마스킹 | Pipeline 상태 전이, Git 실행, 프로젝트 설정·키 저장 |
| `provider_executable` | 외부 provider 실행 파일의 명시 경로·`PATH`·Claude 사용자 설치 경로 탐색 | 인증 정보 조회, provider 실행, 상태 전이 |
| `account_usage` | 공급자 계정 한도 요약·소진 판정과 요청별 짧은 조회 캐시 | 작업 token 집계, 인증 변경, Task 배정·상태 전이 |
| `planner` | 문서 형식 확인, 구조화 계획 검증, 작업 분해, 공급자 라우팅과 에이전트·리뷰어 배정 | 외부 AI 프로세스 실행, worktree 생성, 상태 파일 쓰기 |
| `git` | Git·외부 명령 실행과 오류 변환 | 실행 단계 결정, 사용자 승인 판단 |
| `store` | `RunState`와 Planning 결과 캐시의 원자적 저장·조회, run lock | 상태 전이 정책, Git 접근 |
| `models` | 단계, 작업, 이벤트 데이터 모델 | 파일 I/O, 프로세스 실행 |
| `notifications` | Run·Task 상태에서 안정적인 사용자 알림 사건과 이동 대상을 파생 | OS 알림 전달, 읽음 상태, Pipeline 상태 전이 |
| `config` | TOML 로드·생성, 기본값과 유효성 검증 | 실행 흐름, 런타임 상태 저장 |
| `registry` | 대상 프로젝트·설정·기획 디렉터리 경로의 원자적 저장·조회 | project 설정 해석, run 상태 접근 |
| `desktop_rpc` | Electron이 호출할 RPC allowlist, 입력 검증, 결과 직렬화, 승인 재검증 | 화면 렌더링, 상태 전이 규칙, 네트워크 서버 |
| `desktop/main` | Electron lifecycle, 보안 BrowserWindow, 앱 credential 보안 저장, 역할별 Python process와 typed IPC 중계 | Pipeline 규칙, renderer 화면 상태, shell command 조립 |
| `desktop/renderer` | React 화면, 접근 가능한 사용자 상호작용과 로컬 view state | Node·파일 시스템 접근, Git·Pipeline 상태 전이 |
| `desktop_entry` | 개발 checkout의 Electron 빌드·실행 진입점 | UI 구현, Pipeline 호출, installer 패키징 |

## 의존 방향

```text
cli ─────> registry ──────────> app_paths
 │
 ├───────> desktop_entry ─────> Electron main
 └───────> pipeline ──────────> config
             ├──> codex_sdk ──> app_paths
             ├──> nvidia_agent ──> config, usage
             ├──> document_index
             ├──> planner ──> config
             ├──> git
             ├──> store ────> models
             └───────────────> models

renderer ──typed preload API──> Electron main
                                  ├──JSON Lines──> desktop_rpc (control)
                                  ├──JSON Lines──> desktop_rpc (planning)
                                  └──JSON Lines──> desktop_rpc (work)
                                                    ├────────> registry
                                                    └────────> pipeline
```

- `cli`는 자동화 진입점이며 `pipeline`, `registry`, `desktop_entry`, `mcp_server`의
  공개 진입점을 호출한다.
- 옵트인 `mcp` 진입점은 Codex의 stdio 연결에서 기능별 도구를 제공한다. 작업 PC에서
  직접 또는 SSH로 실행하며 같은 `DesktopApplication`과 프로젝트 등록 정보를 사용한다.
  MCP의 실행 권한과 요청 기록은 `mcp_operations`에서 관리하고, 작업 상태 전이와 잠금은
  `Pipeline`이 처리한다. 앱과 MCP는 등록 정보의 쓰기 잠금을 공유한다.
- `--allow-planning` 연결은 `get_planning_context`의 기준 커밋에 맞춰 외부 작성 계획을
  `submit_plan`으로 제출한다. Python은 기존 Task 계약 검증과 실행 배정을 재사용해 계획 검토 상태를
  저장한다. 기획 모델 호출 없이 작성한 초안도 기존 앱의 계획 revision 승인과 실행 경계를 거친다.
- 계획의 사용자 확인은 기준 Task 결과나 계획 기준 커밋에 연결한다. `planner`가 Task와 확인의
  의존성을 검증하고, `Pipeline`이 확인 결과를 기록하며 대기할 Task와 통합 가능 여부를 결정한다.
  데스크톱은 확인 결과를 기록하고 MCP는 기준 커밋과 확인 상태를 조회한다.
- registry 명령은 프로젝트 설정이 선택되기 전에 `registry` 공개 API를 호출한다.
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
  조합하고 CLI 또는 데스크톱 backend가 주입한 `codex_sdk` 전송 계층을 사용한다.
- `codex_sdk`는 SDK client pool과 Codex thread·turn 생명주기만 소유한다. Planning,
  Task 실행과 Review 상태 전이는 `Pipeline`에 남긴다. Codex 요청은 SDK turn으로만
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
- `store`는 모델을 저장하지만 상태 전이를 스스로 결정하지 않는다.
- `git`, `models`, `config`는 상위 흐름 모듈을 참조하지 않는다.
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
  스냅샷 및 실행 전 재계획 경계를 조정하고, `planner`가 해당 출력의 schema와 task DAG를
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
- `planner`는 task 완료 조건, dependency, 예상·금지 변경 경로, argv 검증 명령,
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
  순수 선택 규칙을 소유하며 `models`에만 의존한다. `planner`와 `effort_policy`가 같은 규칙으로
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
- `planner`는 예상 경로의 잠재 교집합으로 충돌 그룹과 자동 선행 관계를 계산한다.
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
- `notifications`는 저장되는 Run 상태에서 완료·최종 실패·사용자 확인 대기의 source key와
  이동 대상을 파생해 schema 22 `notification_events`에 누적한다. `desktop_rpc`의 조회는
  작업 상태를 바꾸지 않으며 원본 오류·prompt를 복제하지 않는다. Electron main은 선택된
  화면과 독립적으로 사건을 조회하고 사용자 데이터 디렉터리에 cursor·읽음·전달 시도·설정을
  원자 저장한다. 최초 조회와 재시작 catch-up은 앱 알림함에만 넣고 새 사건만 앱이 비활성일
  때 OS 알림으로 보낸다. 알림 선택은 기존 창을 복원해 저장된 대상으로 이동할 뿐 실행·승인·Git
  요청을 만들지 않으며, 앱 종료 시 polling도 함께 종료한다.
- 작업 그룹 삭제는 `Pipeline`의 별도 승인 경계에서 deterministic Run 공유 worktree와
  branch 소유권을 전부 검증한 뒤 `GitWorkspace`로 로컬 작업공간을 제거하고,
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
- `Pipeline`은 Run 공유 workspace와 기존 task workspace의 deterministic 경계 및 정리
  가능 상태를 판정하고,
  `GitWorkspace`는 Git 등록 조회와 local worktree·branch 제거를 수행한다.
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
- `planner`는 명세를 읽고 capability 라우팅 정책으로 실행 공급자와 다른 공급자의
  리뷰어를 배정하지만 Git 또는 실행 상태를 변경하지 않는다.
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
- 새 명세 문법, capability 추론이나 공급자·리뷰어 배정 정책은 `planner.py`에 둔다.
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
