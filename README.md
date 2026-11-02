# AI Work Orchestrator

AI 코딩 작업을 Run 전용 로컬 Git worktree에서 순차 실행하고, 작업 특성에 따라
Codex와 Claude를 자동 배정해 교차 리뷰한 뒤 검증·작업 branch push·Main 반영과
push·배포까지 단계적으로 진행하는
로컬 데스크톱 앱과 CLI다. 작업 branch push, Main 반영·push, deploy 같은 외부
부작용은 명시적인 승인을
요구한다.

## 채팅으로 작업 이어가기

계획이 있는 작업 그룹에서는 채팅으로 “잠금해제 하고 계속 진행해줘”, “막힌 거 고치고 이어가”처럼
요청할 수 있다. AI가 현재 상태를 조사하고 기존 목표 안에서 작업·수정·검증과 다음 Task 진행을
연결한다. 질문만 하면 작업을 바꾸지 않으며, 실패 수정은 한 요청에서 최대 3회다.
요구사항·완료 조건 변경과 merge·push·배포는 별도 확인 흐름을 유지한다.

## 아키텍처

이 프로젝트는 **모듈러 모놀리스 코어 + 로컬 데스크톱 셸** 방식으로 개발한다.
계획 수립, 실행 조정, Git 연동과 상태 저장은 Python 코어에 유지하고, 데스크톱
화면은 Electron main과 React/TypeScript renderer로 분리한다.

- 배포 단위: CLI Python 패키지 또는 Electron 데스크톱 설치 앱
- 실행 단위: CLI 단일 프로세스 또는 Electron main/renderer + 역할별 Python backend
- 통신: Python 내부 호출, 데스크톱 경계의 stdio JSON Lines RPC
- 상태 저장: 대상 저장소의 `.ai-orchestrator/`
- 작업 격리: 대상 저장소의 `.ai_auto_work/worktree/`

세부 의존 방향과 변경 배치 기준은 `Docs/Architecture.md`를 따른다.

## 프로젝트 구조

```text
ai_work/
  AGENTS.md
  Docs/
  DevDocument/Plan/
  desktop/
    main/
    renderer/
    shared/
  src/ai_orchestrator/
    cli.py
    config.py
    desktop_entry.py
    desktop_rpc.py
    git.py
    models.py
    pipeline.py
    planner.py
    registry.py
    store.py
  pyproject.toml
  package.json
  design.md
```

## 요구 사항과 설치

- Python 3.11 이상
- Node.js 22 이상과 npm
- Git
- 오케스트레이션 대상 Git 저장소
- 사용할 AI 공급자의 CLI와 해당 CLI의 인증

macOS 또는 Linux:

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools
python -m pip install -e .
```

`python3 --version`은 3.11 이상이어야 한다. 오래된 가상환경의 editable install이
실패하면 가상환경을 지원 버전 Python으로 다시 만든다.

## Electron 데스크톱 앱

작업 공간은 AI 채팅을 중심으로 구성한다. 프로젝트의 대화에서 요청·진행·오류·복구안을 확인하고,
`작업 보기`에서 계획·Task 모델·결과·프로젝트 반영을 연다. 대화나 상세를 닫아도 실행은 계속된다.
계획 반영, 작업 재실행, 프로젝트 반영·Push는 각각 기존의 별도 행동과 승인을 유지한다.

AI 답변 중에는 다음 메시지를 입력하고 `예약` 또는 `Ctrl/Cmd+Enter`로 전송을 대기시킬 수 있다.
답변이 끝나면 원래 대화·AI 설정으로 순서대로 보낸다. 예약 목록의 수정은 입력창으로 가져오고,
취소는 미전송 예약만 제거한다. 답변이 실패·중단되거나 앱을 다시 열면 예약은 일시 정지하며,
전송 도중 앱이 종료된 항목은 결과 확인 후 다시 입력한다.

`설정 → AI 연결 관리 → Codex`에서는 ChatGPT 구독 로그인과 OpenAI API 키 연결을
선택할 수 있다. 연결 화면의 `OpenAI API 키로 연결` 입력란은 항상 표시한다.
브라우저 로그인 대기 중에는 같은 영역의 `로그인 취소` 후 API 키를 입력할 수 있다.
연결된 상태에서도 `API 키로 전환 · 키 교체`에서 입력할 수 있고,
API 키 연결 뒤에는 `ChatGPT로 전환`으로 돌아갈 수 있다. API 키 사용은 ChatGPT 구독과
별도로 과금된다. 키는 공식 SDK가 이 앱 전용 Codex 저장소에서 관리하며 앱 설정·대화·로그에는
저장하지 않는다. 키 등록 상태와 실제 작업 호출의 인증·모델 접근 성공은 구분한다.

Codex 앱·CLI와 로그인 정보를 공유하지 않는다. 앱 사용자 설정 폴더 아래 `codex`를 전용
`CODEX_HOME`으로 사용하며 기획·대화·작업·리뷰와 연결 화면이 모두 이 저장소를 사용한다.
공용 인증 파일을 자동 복사하지 않으므로 분리 후에는 AI 연결에서 한 번 다시 로그인하거나
API 키를 등록해야 한다. 이전 연결로 Codex 앱도 API 방식이 됐다면 Codex 앱에서 ChatGPT로
다시 로그인한다. 이후 오케스트레이터의 연결 변경은 Codex 앱·CLI에 적용되지 않는다.

SDK와 내장 런타임은 `0.163.0`으로 고정한다. Windows에서는 앱 전용 환경에도
`features.prefer_mxc=true`를 적용해 지원되는 장치의 native sandbox를 우선 사용한다.
기획의 읽기 전용·승인 거부 정책은 유지하며 관리자 정책을 우회하지 않는다.
SDK 교체 전부터 실행 중인 앱은 다음 시작부터 새 SDK와 설정을 사용한다.

`설정 → AI 연결 관리 → Claude`에서 Claude Code CLI의 설치·로그인 상태를 확인할 수 있다.
`Claude 로그인`은 공식 `claude auth login`을 실행하는 터미널을 연다. 로그인 후 `연결 다시 확인`을
누르면 기획·대화·Task·리뷰에서 구성된 Claude 모델을 선택할 수 있다. 앱은 CLI 인증 정보를 저장하지 않는다.
모델 선택 목록에는 로그인·인증이 확인된 Codex·Claude만 표시한다. NVIDIA는 API 키와 실행 CLI가
준비됐을 때 표시하며 실제 API 인증은 실행 시 확인한다. 미연결 AI도 AI 연결 관리 화면에는 남아 있다.
연결을 다시 확인하면 모델 목록도 갱신한다. 인증 조회가 실패하면 오래된 후보를 유지하지 않는다.
Codex 자동 모델 선택은 `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-luna` 안에서 확정한다.
기획·원인 판단과 중요하거나 불확실한 작업은 Sol을 사용한다. 낮은 위험·명확한 범위의
작은 문구/문서/UI 수정은 균형 모드에서 Terra, 절약 모드에서 Luna를 사용한다.
집중은 Sol의 추론과 기존 리뷰 정책을 강화한다. 모델과 선택 이유는 실행 전에
확정한다. 수동 선택과 이미 시작한 실행의 정책은 보존한다. 자동 Terra/Luna 작업의 실제 코드
검증 실패는 기존 자동 수정 과정에서 Sol로 한 번 승격할 수 있지만 SDK·잠금·시간 초과에서는
승격하지 않는다. SDK 기본 모델이 다른 모델을 가리켜도 빈 자동 선택은 Sol로 해석한다.
자동 배정은 위의 Sol/Terra/Luna 정책과 저장된 실행 계약을 따른다.
Opus 5.5의 명시적인 모델 ID는 `claude-opus-5-5`이며 Claude Code `2.1.280` 이상이 필요하다.
`claude --version`으로 버전을 확인하고 `claude update`로 업데이트할 수 있다.

새 데스크톱 앱은 Electron과 React/TypeScript로 실행된다. Electron main이 Python
제어용·장기 작업용 backend를 로컬 자식 프로세스로 실행하고 각각 표준 입출력 JSON
Lines RPC로 기존
`Pipeline`을 호출한다. localhost 서버나 임의 포트를 열지 않으며 renderer에는
Node.js 권한을 제공하지 않는다.

Electron 앱은 프로젝트 등록·제외, 작업 그룹과 Task 조회, Planning AI 대화,
provider·모델·추론 강도 편집, 실행·재개·재시도, 통합 검증, 작업 Branch Push,
Main 반영·Main Push, 배포와
작업공간·작업 그룹 정리를 지원한다. Git 부작용과 삭제는 Electron native 확인창과
Python 승인 검사를 모두 통과해야 한다.

```bash
ai-orchestrator project add /path/to/project --name my-project
ai-orchestrator project list
```

프로젝트 root에 `orchestrator.toml`이 있으면 기존 설정을 그대로 사용한다. 파일이
없으면 대상 저장소에는 파일을 만들지 않고 registry와 같은 사용자 설정 root의
`project-configs/<저장소 식별자>/orchestrator.toml`에 기본 설정을 자동 생성한다.
자동 설정에는 Codex·Claude 프로필이 포함된다. CLI와 Electron 데스크톱의 Codex
프로필은 Python 패키지에 포함된 공식 `openai-codex` SDK와 고정 런타임만 사용하므로
별도 `codex` CLI 설치가 필요하지 않다. 외부 Codex CLI와 시스템 실행 파일 override,
직접 OpenAI HTTP 요청으로 우회하지 않으며 SDK를 시작할 수 없으면 해당 실행을
명시적으로 실패로 기록한다. Claude와 custom provider는 설정한 외부 실행 파일이
필요하다.
프로젝트별 공통 검증·배포 명령은 추측하지 않으므로 `verify_commands`와
`deploy_command`는 비어 있다. 통합 검증은 공통 `verify_commands`가 없으면 Planning이
만든 Task별 검증 명령을 중복 제거해 사용한다. 전체 프로젝트 전용 검증이나 배포가
필요하면 실제 프로젝트에 맞게 관리 설정 파일을 수정해야 한다. 데스크톱의 배포 단계와
버튼은 `deploy_command`가 설정된 프로젝트에서만 표시된다.

다른 이름이나 이미 준비한 설정 파일은 프로젝트 root 기준 상대 경로 또는 절대 경로로
지정할 수 있다. 명시한 설정 경로가 없으면 해당 위치에 파일을 자동 생성하지 않고
등록을 실패시킨다. 설정의 `project.repo`는 등록 경로와 일치해야 한다.

```bash
ai-orchestrator project add /path/to/project \
  --name my-project \
  --project-config config/orchestrator.toml
```

기획 문서 디렉터리도 프로젝트 등록과 함께 저장할 수 있다. 상대 경로는 프로젝트
root를 기준으로 해석한다.

```bash
ai-orchestrator project add /path/to/project \
  --name my-project \
  --planning-source Planning
```

registry의 기본 위치는 다음 운영체제 규칙을 따른다.

- macOS: `~/Library/Application Support/ai-work-orchestrator/projects.json`
- Windows: `%APPDATA%\ai-work-orchestrator\projects.json`
- Linux: `$XDG_CONFIG_HOME/ai-work-orchestrator/projects.json` 또는
  `~/.config/ai-work-orchestrator/projects.json`

registry에는 프로젝트 이름, 로컬 경로, 설정 경로와 선택한 기획 문서 디렉터리를
저장하며 token이나 AI 인증 정보는 저장하지 않는다. 이전 schema의 registry는 기획
디렉터리가 없는 상태로 호환해서 읽는다. 테스트나 별도 registry가 필요하면 전역
`--registry` 옵션으로 JSON 경로를 지정한다.

```bash
npm install
npm run start

# Python backend만 진단
ai-orchestrator-backend

ai-orchestrator-desktop
ai-orchestrator desktop
ai-orchestrator --registry /path/to/projects.json desktop
```

현재 Electron 데스크톱 기능은 다음과 같다.

- 프로젝트 등록·삭제와 run 선택
- 확인 후 등록 프로젝트 main을 `git pull --ff-only`로 최신화
- 운영체제 디렉터리 선택창에서 기획문서 묶음 선택
- 기획 문서 로컬 색인 수동 갱신과 갱신 결과 확인
- 새 계획에서 기본 `지정 작업` 또는 `풀 오토 탐색` 범위 선택
- Planning run별 provider·모델 선택 또는 프로젝트 기본값 사용
- Planning AI가 추천한 Task별 실행 모델·추론 강도 확인과 최초 실행 전 변경
- Planning 결과의 Task 내용·의존성·경로·검증 명령 편집, Task 추가·제외와 계획 확정
- 계획 수정이나 Planning 대화의 Task 반영 뒤 확정 자동 해제 및 미확정 Task 실행 차단
- 화면의 Planning AI 대화 영역에서 질문 답변과 자유 형식 계획 보완 메시지 전송
- Planning 대화의 `반영` 짧은 요청이나 `Task에 반영` 버튼으로 현재 그룹 Task 갱신,
  실행 중이면 요청 당시 대화를 예약하고 다음 Task 전에 반영
- 진행 중이거나 앱 재시작 뒤 고아 상태가 된 Planning 작업을 확인 후 중단하고 실패
  상태로 복구
- task 상태·의존성과 event·agent log 확인
- 전체 ready Task 실행, 행별 ready Task 단독 실행, 실패 Task 재시도, resume,
  manual complete, verify
- 통합 검증 중 최신 Main 동기화, 현재 검증 명령과 진행 개수·경과 시간 확인
- Planning run을 하나의 작업 그룹으로 표시하고 확인 후 그룹 전체 삭제
- native 확인 dialog를 통한 작업 Branch Push, Main 반영·Push, deploy 개별 승인

Electron 작업 영역은 `Tasks`, `Planning AI`, `통합·정리`, `상세·로그`로 나뉜다. `Tasks`
목록은 기능명, 진행 상태, 위험도, 실행 프로필, 계획 검토 상태와 행별 동작을 표시한다.
실행 전에는 우측 상세 패널에서 Task ID, 설명, 완료 조건, 의존성, 예상·금지 경로와
검증 명령을 편집하고 계획을 확정한다. 확정 전에는 실행 버튼이 잠긴다. 실행 후 내부
agent ID는 tooltip과 상세 탭에서 확인한다. 실행 프로필은 사용자 기준의
`gpt-6.1-sol · codex`와 `high`처럼 표시한다.

Electron renderer의 비동기 요청은 화면 thread를 막지 않으며 Python의 기존 run lock,
worktree와 상태 저장 규칙을 그대로 사용한다. 앱에서 프로젝트를 제거해도 Git
저장소와 run 상태는 삭제하지 않는다. CLI에서 registry 항목만 제거하려면 다음 명령을
사용한다.

Planning이 응답하지 않으면 Planning 화면의 `Planning 중단`을 사용할 수 있다. native
확인창에서 승인하면 장기 작업용 Python backend와 그 자식 agent 프로세스만 종료하고
다시 시작한다. 상태 조회용 backend는 유지되며, 종료된 프로세스가 남긴 stale run
lock을 확인한 뒤 해당 작업 그룹만 Planning 실패 상태로 기록한다. 대상 프로젝트의
소스와 Git 상태는 변경하지 않는다.

하나의 Planning run은 하나의 `작업 그룹`으로 표시되고, Planning AI가 분해한 Task는
그룹 안의 표로 표시된다. `작업 그룹 삭제`는 확인 dialog를 거쳐 해당 run의 상태,
계획, prompt, log와 그룹 소유의 local worktree·`ai/<run-id>` branch를
삭제한다. dirty worktree와 Main에 병합하지 않은 local commit도 함께 삭제될 수 있으므로
앱에서 되돌릴 수 없다. 기존 Run의 `ai/<run-id>/<task-id>` 작업공간도 호환 정리한다.
Main branch와 remote는 변경하지 않으며, run lock이 있거나
worktree 경계·Git 소유권이 예상과 다르면 삭제를 거부한다. Windows에서는 worktree
제거 명령에만 긴 경로 지원을 적용하므로 깊은 `node_modules`가 있어도 정리할 수 있다.
이전 긴 경로 오류로 Git 등록만 제거된 경우에는 해당 실패가 run에 기록된 정확한
worktree 잔여물만 다음 삭제 시도에서 복구한다.

```bash
ai-orchestrator project remove my-project
```

## 앱 패키징

Electron renderer와 main/preload의 production build는 다음 명령으로 검증한다.

```bash
npm run typecheck
npm run build
```

### Windows x64 portable ZIP

이 공개 저장소는 소스부터 제공한다. 이전 비공개 배포 파일은 포함하지 않는다.
검증된 바이너리를 발행하면 이 저장소의 Releases에서 제공한다.

제품 v0.3.0부터 Windows x64의 무설치 실행 ZIP을 로컬에서 만들 수 있다.
Windows x64 Node.js와 Python 3.11+ 환경에서 의존성을 준비한 뒤 실행한다.
제품 소스의 미커밋 변경이 있으면 먼저 검토·커밋해야 빌드 기준 commit을 정확히 기록할 수 있다.

```powershell
npm ci
.venv/Scripts/python.exe -m pip install -e ".[windows-build]"
npm run package:win-x64
```

결과는 `build/windows-x64/0.4.0/ai-work-orchestrator-v0.4.0-win-x64.zip`과 같은 이름의
`.zip.sha256`이다. ZIP 전체를 새 로컬 폴더에 압축 해제하고 `AI Work Orchestrator.exe`를
실행한다. Electron·Python backend·고정 Codex SDK/runtime을 포함하므로 Python·Node.js·
외부 Codex CLI를 사용자가 설치할 필요는 없다. `resources` 폴더도 함께 유지해야 한다.
기존 빌드나 실패한 빌드 디렉터리가 있으면 덮어쓰지 않고 멈춘다.

Git for Windows 및 대상 프로젝트의 .NET 등 빌드 도구는 별도 설치하고 PATH/앱 설정을
확인한다. Codex 로그인은 사용자가 앱의 AI 연결에서 진행한다. 사용자 설정·프로젝트 목록·
인증은 기존 사용자 설정 위치에 유지되므로 portable은 무설치 실행을 뜻한다.
ZIP 안에는 registry·작업 기록·사용자 인증을 넣지 않는다. 이 빌드는 서명되지 않았으며
Windows에서 실행 안내가 표시될 수 있다. installer·코드 서명·자동 업데이트는 후속이다.

### Apple Silicon macOS 로컬 앱

Apple Silicon macOS에서는 Electron뿐 아니라 Python backend와 Codex SDK의 고정 실행
파일도 arm64여야 한다. `npm start`는 실행 전 두 아키텍처를 검사하며, 기존 x86_64
`.venv`가 있으면 오류를 내고 앱을 시작하지 않는다. x64 Node.js도 같은 검사에서
거부한다. arm64 Node.js로 `npm install`을
실행하고 arm64 Python 3.11+로 별도 가상환경을 만든다. 예를 들어 native Python의
절대 경로를 확인한 뒤 다음처럼 설치한다.

```bash
/path/to/arm64/python3 -m venv .venv-arm64
.venv-arm64/bin/python -m pip install -e . pyinstaller
AI_ORCHESTRATOR_PYTHON="$PWD/.venv-arm64/bin/python" npm start
```

macOS용 로컬 `.app`은 같은 arm64 Node.js 환경에서 다음 명령으로 만든다. 빌드 전에
`npm install`이 끝나 있어야 한다.

```bash
AI_ORCHESTRATOR_PYTHON="$PWD/.venv-arm64/bin/python" npm run package:mac-arm64
```

결과는 `build/macos-arm64/AI Work Orchestrator.app`이다. 명령은 Electron·Python
backend를 arm64로 검사하고 Python·Codex 고정 런타임을 앱 안에 넣은 뒤 로컬 임시
서명과 검증을 수행한다. 기존 빌드가 있으면 덮어쓰지 않고 멈춘다. 이전 Qt/PyInstaller
`AI Work Orchestrator.app`은 자동으로 찾아 교체하거나 삭제하지 않는다. 새 앱의 실행을
확인한 뒤 사용자가 기존 설치본을 구분해 정리해야 한다.

이 로컬 `.app`은 공증된 배포본이나 installer가 아니다. 배포용 macOS 서명·공증,
Windows installer/signing과 자동 업데이트는 후속이다. `ai-orchestrator desktop`은
여전히 저장소 checkout의 `npm start`를 호출하므로 `npm install`이 필요하다.

## 설정

직접 실행하는 CLI 명령의 기본 설정 파일은 현재 디렉터리의 `orchestrator.toml`이다.
다른 파일을 사용하려면 `--config`로 지정한다. 프로젝트 registry를 사용하는
데스크톱 앱은 각 등록 항목에 저장된 설정 경로를 사용한다.

```toml
[project]
repo = "."
main_branch = "main"
remote = "origin"

[execution]
max_parallel = 3
auto_commit = true
agent_timeout_seconds = 1800
verify_commands = [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]]
deploy_command = []

[planning]
agent = "codex-general"
max_attempts = 2
reuse_results = true
timeout_seconds = 600

[routing]
default_provider = "codex"
balance_providers = true
review_required = true
max_review_cycles = 2

[[routing.rules]]
capabilities = ["planning", "architecture", "docs", "security", "review"]
provider = "claude"

[[agents]]
id = "codex-general"
provider = "codex"
capabilities = ["general", "backend", "qa"]
sandbox_mode = "workspace-write"
approval_mode = "auto-review"
review_sandbox_mode = "read-only"
review_approval_mode = "deny-all"

[[agents]]
id = "claude-general"
provider = "claude"
model = "sonnet"
capabilities = ["general", "planning", "architecture", "docs", "security", "review"]
command = ["claude", "-p", "Follow the task instructions from standard input."]
review_command = ["claude", "-p", "Follow the review instructions from standard input."]
```

`balance_providers`는 기본 true다. 수동 선택·기획 AI의 구체적인 추천·capability 규칙이
없는 Task는 연결되어 있고 역량·용량을 충족하는 공급자 중 현재 계획의 실행 배정이 적은
쪽에 나눈다. 배정량이 같으면 역량 일치도, `default_provider` 순으로 우선한다.
예를 들어 Codex와 Claude가 동등하게 적합한 네 Task는 둘씩 배정할 수 있다.
기획 AI에도 동등한 후보는 빈 프로필로 반환해 이 자동 분배를 사용하도록 안내한다.
구체적인 AI 추천과 사용자가 직접 고른 프로필은 그대로 유지한다. 기존 저장된 Task는
연결만으로 재배정하지 않으며, 새 계획·재계획 후보에 적용한다.
`balance_providers = false`이면 규칙이 없는 Task를 기존처럼 `default_provider`에 고정한다.
명시적 규칙이나 선택을 사용할 수 없을 때 다른 공급자로 조용히 바꾸지 않는다.
규칙의 capability가 작업과 일치하면 해당 공급자를 사용하고, 자동 배정 리뷰는 다른 공급자의
에이전트가 담당한다. 집중 모드에서 사용자가 명시적으로 추가하는 리뷰는 같은 Codex
프로필도 선택할 수 있으며 별도 대화와 리뷰 권한으로 실행한다. 모드 선택만으로 리뷰를
추가하지 않는다. `max_review_cycles`는 최초 리뷰를 포함한 전체 리뷰 횟수다.
새 공유 worktree Run은 commit 순서를 보장하기 위해 `max_parallel` 값과 관계없이
Task를 하나씩 실행한다. 이 값은 저장된 기존 Task 격리 Run의 호환 실행에만 적용된다.

`planning.agent`를 설정하면 `start`가 해당 에이전트로 자유 형식 문서를 구조화된 작업
계획으로 변환한다. Codex는 `review_sandbox_mode`와 `review_approval_mode`의 SDK profile을
사용하고, Claude와 custom provider는 `review_command`를 우선 사용하며 없으면 `command`를
사용한다. Planning AI의 실행 실패나 잘못된 구조화 결과는
`max_attempts`만큼 재시도하며, 실패를 규칙 parser의 성공 결과로 숨기지 않는다.
`planning.timeout_seconds`의 기본값은 600초다. 외부 CLI와 custom provider에서는
schema 보정 재시도를 포함한 Planning 실행 전체 제한시간이며 각 재시도는 남은 시간만
사용한다. Codex SDK provider에서는 SDK notification이 연속으로 오지
않는 비활성 제한시간이다. 문서 탐색 event가 계속 오는 active turn은 600초를 넘어도
이어지며, 각 schema 보정 turn은 같은 비활성 제한시간을 사용한다. 제한시간을 넘기면
provider를 중단하고 timeout 뒤 프로세스 종료와 출력 회수에도 별도 상한을 적용한다.
`planning.agent`가 비어 있는 기존 설정만 아래의 규칙 기반 Markdown parser를
호환 fallback으로 사용한다.

Codex SDK의 최종 503·모델 혼잡 실패는 실제 도구 실행 전이면 `5→15→30→60초`에
`0~5초` 무작위 지연을 더해 최대 4회 추가 재시도한다. SDK가 재접속 중이면 새 turn을
시작하지 않는다. 기록된 대기는 실제 활동 및 비활성 timeout과 구분하고, 대기 중 중지와
별도 기획 채팅을 유지한다. 노출된 Retry-After를 지키되 총 300초 대기 예산을 넘으면
수동 재시도를 안내한다. 이미 명령·파일·도구 실행이 시작됐거나 결과 미확인이면 자동
반복하지 않으며, 실제 호출별 사용량·실패 기록을 보존한다.

`planning.reuse_results = true`이면 clean 저장소에서 완전히 같은 기준 commit,
기획 입력, 저장소 규약, Planning provider·SDK profile 또는 실행 명령·모델·추론 강도와
prompt로 이미
검증된 결과를 `.ai-orchestrator/planning-cache/`에서 재사용한다. cache hit 때는
Planning AI 프로세스를 호출하지 않으며 Planning attempt도 증가하지 않는다. tracked
변경이나 state 디렉터리 밖의 무시되지 않은 untracked 파일이 있으면 캐시를 사용하지
않는다. 캐시가 손상됐거나 현재 schema·문서 경로·agent 배정 검증을 통과하지 못하면
오류를 성공으로 숨기지 않고 이벤트를 남긴 뒤 Planning AI를 정상 호출한다. 재사용을
원하지 않으면 이 값을 `false`로 설정한다.

Claude와 custom provider에서 `command`는 구현·수정용이고 `review_command`는 읽기 전용
검토용이다. 리뷰 명령이 없으면 `command`를 사용하지만 리뷰 전후의 worktree와 HEAD가
달라지면 실패한다. Codex provider는 이 두 command를 실행하지 않고 SDK profile만
사용한다. 외부 command provider의 `command`가 비어 있으면 `execute --manual`로
worktree와 프롬프트만 준비할 수 있다. 실제 비밀번호, token 또는 접속 정보는 설정
파일이나 로그에 저장하지 않는다.

Claude Planning 대화의 `--session-id`·`--resume`은 오케스트레이터가 작업 그룹별로
관리하므로 Claude `review_command`에 `--continue`, `--resume`, `--session-id`,
`--fork-session` 또는 `--no-session-persistence`를 직접 넣지 않는다. 충돌하는 session
flag가 있으면 다른 Claude 대화를 잘못 잇지 않도록 실행 전에 명시적으로 실패한다.

`agent_timeout_seconds`는 Claude·custom 실행자와 리뷰어 명령에는 각각의 최대 실행
시간으로 적용한다. 제한을 넘으면 macOS/Linux에서는 해당 프로세스 그룹을, Windows에서는
프로세스 트리를 종료하고 task log와 run 실패 단계에 timeout을 기록한다. Codex SDK에는
진행 event가 없는 시간의 제한으로 적용하며 event를 받으면 다시 계산한다. Electron bridge는
Task 실행·재개·검증처럼 backend가 자체 제한을 관리하는 장기 요청에 별도의 전체 경과
1800초 제한을 두지 않는다. 조회와 환경 진단 같은 짧은 요청은 method별 응답 제한을 유지한다.

CLI와 Electron 데스크톱의 Codex 프로필은 앱 내부 SDK의 계정 상태까지 확인해
ChatGPT 구독 로그인, API 키 사용량 과금, 로그인 필요 상태를 구분한다. Claude 프로필은
설치된 CLI의 `claude auth status --json` 결과에서 로그인 여부와 구독/API 인증 방식만
해석한다. 선택한 Provider가 인증되지 않았거나 상태를 확인하지 못하면 새 Planning을
시작하지 않으며 실행 프로필의 `인증 새로고침`으로 다시 확인할 수 있다. 인증 비밀값,
계정 이메일과 조직 식별자는 상태 응답이나 로그에 포함하지 않는다. custom provider는
실행 파일 설치 여부만 확인하며, 어느 쪽도 원격 모델 호출 성공까지 보장하지 않는다.

### NVIDIA 코딩 시험

NVIDIA는 작업 상세의 **실행 모델**에서 직접 선택하는 시험용 코딩 담당이다.
기존 프로젝트 설정 파일을 변경하지 않고 `NVIDIA · 시험` 프로필을 제공한다.
기본 AI 배정과 Planning AI는 유지하며, 필수 리뷰어를 자동으로 추가하지 않는다.
기본 모델은 `nvidia/nemotron-3-super-120b-a12b`이다.

1. [OpenCode CLI](https://opencode.ai/docs/)를 설치한다.
   검증한 버전은 `npm install -g opencode-ai@1.19.3`이다.
2. **File → AI 연결…** 또는 **설정 → AI 연결 관리**를 열고 **NVIDIA**를 선택한다.
   키 이름과 발급한 API 키를 입력하고 **키 저장**을 누른다. Codex 로그인과 NVIDIA
   키는 함께 유지되며 이 화면의 제공자 선택은 작업의 실행 AI를 변경하지 않는다.
   OS 보안 저장소로 암호화해 앱 전용 파일에 저장하며, 프로젝트 설정·대화·소스에는 넣지 않는다.
3. 저장한 키는 앱 재시작 없이 다음 요청부터 사용한다. 실행 중인 작업은 현재 키를 유지한다.
   이름을 붙여 키를 여러 개 추가·교체·삭제하고 기본 키를 선택할 수 있다.
   **모델별 사용할 키**에서 Catalog의 모델 ID와 사용할 키를 연결한다. 등록한 모델은
   실행 모델 목록에도 표시된다. 모델에서 **기본 키 사용**을 선택하면 모델 등록을
   유지하면서 기본 키 변경을 따른다. **모델 삭제**는 모델별 설정을 제거한다.
   모델에 직접 지정한 키는 연결을 변경하거나 모델 설정을 제거한 뒤 삭제한다.
   지정하지 않은 모델은 기본 키를 사용하며, 다른 키가 있을 때 기본 키를 삭제하려면
   먼저 기본 키를 변경한다. 마지막 앱 키는 등록 모델 설정을 먼저 삭제한 뒤 제거한다.
   오류나 한도 초과 시 다른 키로 자동 전환하지 않는다.
   앱에 저장한 키가 없으면 기존 `NVIDIA_API_KEY`
   환경 변수를 사용한다. OS 환경 변수를 직접 바꾼 경우에는 앱을 다시 시작한다.
4. 실행 전 **작업 상세 → 실행 AI · 모델 → 실행 모델**에서
   NVIDIA를 선택하고 계획을 저장한 뒤 작업을 시작한다.
   추가 리뷰가 필요하면 별도로 선택한다.

실행을 시작한 그룹이 멈춰 있으면 실패·미실행 Task의 **작업 상세 → 다음 실행 AI · 모델**에서
모델을 다시 선택하고 **모델 변경 저장**을 누른다. 그 다음 재실행·그룹 재개를 별도로 선택한다.
그룹이 실행 중이어도 아직 시작하지 않은 대기 Task는 다음 모델을 저장할 수 있으며 해당 작업이
시작될 때 적용된다. 현재 실행 중인 Task와 완료한 Task는 변경하지 않는다.
저장만으로 작업을 시작하거나 기존 실패·완료 기록을 지우지 않는다.
미저장 모델 변경은 저장하거나 취소한 뒤 별도 실행을 요청할 수 있다.

작업 상세의 **기록 파일 열기**는 현재 로그·작업 내용·모델·시도·이벤트 기록의
텍스트 사본을 기본 편집기로 연다. 원본은 변경하지 않으며 사본은 자동 갱신되지 않는다.
실시간 로그가 필요하면 **앱에서 로그 보기**로 별도 로그 창을 연다.

준비 상태는 CLI 설치와 키 설정 여부만 뜻하며 원격 인증 성공을 보장하지 않는다.
실제 호출은 사용자가 선택한 작업을 실행할 때 발생한다. OpenCode가 도구 호출을
처리하고 Pipeline이 기존 방식으로 변경 검증과 커밋을 수행한다. 외부 경로·비밀 파일·
별도 에이전트와 대화형 질문을 제한하고 Git 쓰기 명령은 허용하지 않는다.
리뷰는 읽기 도구만 허용한다. 이는 OpenCode 도구 권한이며 OS 샌드박스는 아니다.
실행 제한시간·사용자 중단은 기존 외부 프로세스 계약을 따른다. 429·503 오류는
실패로 기록하며 다른 AI로 자동 변경하거나 작업을 새로 실행하지 않는다.

Nemotron 3 Ultra(`nvidia/nemotron-3-ultra-550b-a55b`)와 Super는
[NVIDIA의 코딩 에이전트 안내](https://docs.api.nvidia.com/nim/re/reference/nvidia-nemotron-3-ultra-550b-a55b)에 따라
`chat_template_kwargs.force_nonempty_content: true`를 요청에 포함한다.
다른 모델에는 이 옵션을 임의로 적용하지 않는다. 답변이 여전히 비어 있거나 검증이
실패하면 완료로 처리하지 않으며, 작업을 자동으로 반복하지 않는다.

[NVIDIA 체험 약관](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf)의
평가용·기밀정보 입력 제한을 확인하고 공개 예제부터 시험한다. 실제 프로젝트 사용은
선택한 서비스 계약을 확인해야 하며, 코딩 품질·한국어 품질·한도는 별도 평가가 필요하다.

Codex가 미로그인 상태이면 데스크톱의 `AI 연결 → Codex` 또는 Planning 인증 영역에서
`ChatGPT로 로그인`을 선택한다. 연결 창에서는 NVIDIA 설정도 따로 관리할 수 있다.
앱은 공식 SDK 로그인 시도를 만들고 HTTPS 공식 인증
주소만 기본 브라우저로 연다. 브라우저 로그인과 기기 코드 방식은 같은 화면에서 완료를
확인하거나 취소할 수 있으며, SDK 계정 재조회가 성공해야 Planning을 허용한다. 인증 URL과
기기 코드는 Run·로그·알림에 저장하지 않는다.
Claude CLI가 OAuth token 만료 또는 인증 실패를 반환하면 앱은 일반 종료 코드 대신
`claude auth login` 재로그인 안내를 표시하며 provider 원문은 기존 run log에만 보존한다.

```bash
ai-orchestrator provider list
ai-orchestrator provider doctor
ai-orchestrator provider doctor claude
```

## 작업 명세

Planning AI가 설정된 프로젝트는 UTF-8 `.md`, `.markdown`, `.txt` 문서를 자유 형식으로
작성할 수 있다. `start`에는 단일 문서 또는 기획문서 디렉터리를 전달할 수 있다.
단일 문서는 기존처럼 Planner 입력으로 전달한다. 디렉터리는 전체 문서 내용을
결합하지 않고 오케스트레이터가 먼저 로컬 기획 문서 색인을 생성하며
`planning.agent` 설정이 필요하다.
Planning AI는 등록된 프로젝트 루트에서 실행된다. 데스크톱 새 계획의 기본 범위는
`지정 작업`이며, 사용자가 입력한 요청을 기준으로 기획문서 색인에서 관련 후보를 좁게
검색하고 직접 필요한 원문·의존성·충돌·검증 자료만 확인한다. 관련 없는 backlog를
발굴하거나 Task에 포함하지 않는다. `풀 오토 탐색`을 선택한 경우에만 기획문서에서
실행 가능한 미완료 작업을 발굴한다. 기존 상태 파일과 별도 범위를 전달하지 않는 CLI
호출은 호환을 위해 풀 오토 탐색으로 처리한다.

기획 디렉터리를 사용하는 지정 작업의 최초 Planning에는 요청의 단어 및 명시 경로와
색인의 경로·제목·목차를 비교해 최대 5개 문서의 본문 발췌를 미리 제공한다. 발췌는
문서별 최대 2,000자이며 출처·hash와 생략 여부를 함께 기록한다. 128 Ki 문자를 넘는
문서는 본문을 포함하지 않고 원문 탐색이 필요함을 표시한다. 이는 초기 후보 선정이므로
동의어나 본문에만 있는 관련 내용은 기존 색인 검색으로 추가 확인한다. 후보가 없으면
무관한 대표 문서로 대신하지 않는다. 선택 문서의 읽기 오류나 색인 이후 내용 변경은
Planning 실패로 표시하며, 변경된 경우 색인을 갱신하고 새 계획을 시작해야 한다.
대화 재개는 기존 대화와 선택 문서 스냅샷을 사용한다.

오케스트레이터는 루트의
`AGENTS.md`, `AGENTS.local.md` 중 존재하는 지침 내용을 순서대로 prompt에 포함한다.
Planning AI는 해당 지침의 문서 라우팅과 작업 경로에 적용되는 중첩 `AGENTS.md`를
따라 관련 저장소 문서만 추가로 확인한다. 루트 지침이 없는 프로젝트에는 프로젝트별
규칙을 임의로 만들지 않고 선택한 기획 입력과 코드 분석만 적용한다. Planning AI는
색인의 경로·제목·주요 목차에서 후보를 고른 뒤 필요한 원문만 읽으며 디렉터리를 다시
전체 탐색하지 않는다. 다른 worktree로 전환하거나 기존 worktree를 재사용하지 않는다.

현재 구현은 프로젝트 trust 상태를 별도로 저장하거나 검증하지 않고 위 루트 지침을
직접 prompt에 넣는다. 따라서 Planning은 사용자가 내용을 신뢰한다고 판단한 등록
프로젝트에서만 실행해야 한다. Codex 클라이언트가 untrusted project의 project-level
`AGENTS.md`를 무시하는 동작은 오케스트레이터가 직접 주입한 지침의 신뢰 경계를
대체하지 않는다.

색인은 프로젝트의 설정된
`.ai-orchestrator/planning-indexes/` 아래에 JSON으로 저장되며 대상 기획 문서
디렉터리에는 파일을 추가하지 않는다. 저장소 내부 디렉터리는 Git의 추적 파일과
ignore되지 않은 비추적 파일을 대상으로 하고, 저장소 외부 디렉터리는 `.git`,
`.ai-orchestrator`, `.ai_auto_work`, `.ai-worktrees`, `node_modules`, `bin`, `obj` 등 운영·빌드
디렉터리를 제외하고 수집한다. 경로·크기·수정 시각이 같은 문서 메타데이터는 재사용하고
변경된 UTF-8 Markdown/TXT 문서만 다시 읽는다. 데스크톱의 `문서 색인 갱신`으로
수동 갱신할 수 있으며, `계획 만들기`도 시작 전에 항상 증분 갱신한다.
기준 commit이 바뀌면 직전 색인의 SHA-256과 비교해 추가·수정·삭제 문서를 기록한다.
Planning에는 변경 문서의 제한된 발췌와 관련 문서 메타데이터만 추가하며, 같은 기준
commit의 동일 입력은 Planning 결과 cache를 재사용한다. 데스크톱 색인 결과에는
추가·수정·삭제 문서 수가 표시된다.
데스크톱에서 선택하거나 직접 입력한 유효한 기획 디렉터리는 프로젝트 registry에
저장되며 프로젝트를 다시 선택하거나 앱을 다시 실행할 때 자동 복원된다. 프로젝트
등록 화면에서도 기획 디렉터리를 미리 지정할 수 있다.

지정 작업은 요청문이 없으면 시작하지 않는다. 관련 기획문서만으로 구현 범위를 확정할
수 없으면 무관한 Task를 대신 만들지 않고 확인 질문을 반환할 수 있다. 풀 오토 탐색은
관련 작업 추적·미완료 기획 문서를 확인해 구현 가능한 Task를 best-effort로
리스트업하며, 구체적인 구현 결정이 남아도 이미 확인 가능한 Task 초안을 질문과 함께
반환한다. 선택한 범위와 지정 작업 요청은 run 상태와 Planning 대화 첫 메시지에 저장돼
앱 재시작 뒤에도 확인할 수 있다.

Planner가 실제로 확인한 기획 문서 상대 경로는 `source_paths`, 적용한 저장소 규약
문서의 저장소 상대 경로는 `instruction_paths`로 구분해 반환한다. 오케스트레이터는
두 목록의 저장소·기획 루트 경계, 색인 포함 여부, 지원 형식, 파일 존재 여부를 각각
검증한다. 자동으로 불러온 루트 지침이 `instruction_paths`에서 누락되면 결과를
거부하고 Planning AI에 재시도를 요청한다. `source_paths`의 문서는
`.ai-orchestrator/runs/<run-id>/planning-sources/`에 원래 상대 경로로 복사하고
SHA-256 manifest를 남긴다. 선택되지 않은 기획 문서 내용은 prompt나 snapshot에
포함하지 않는다. 지원 기획 문서가 전혀 없으면 시작 전에 실패한다. 고정 heading,
bullet 목록이나 capability 태그를 요구하지 않으며, 기획서 작성자가 Codex나 Claude를
지정할 필요는 없다.

Planning AI가 생성하는 요약, clarification 질문, 작업 제목·설명과 완료 조건은
한국어로 표시한다. task id, capability, 경로, 검증 명령과 위험도 enum은 실행 및
검증 계약이므로 기존 기계 판독 형식을 유지한다. Planning prompt에는 현재 실행 가능한
provider, capability, 총 Task 용량, 지원 모델과 추론 강도 목록을 함께 제공한다.
Planning AI는 Task의 복잡도와 위험도에 맞는 초기 `provider_id`, `model`,
`reasoning_effort`를 추천하며, 모든 Task에 가장 강한 설정을 일괄 선택하지 않는다.
추천이 없는 이전 결과는 기존 capability와 routing 규칙으로 배정한다.

데스크톱의 `Planning Provider` 선택기는 프로젝트 설정에 등록된 agent 중 Planning
capability와 실행 가능한 provider를 표시한다. Codex 프로필은 공식 Python
SDK 계정 조회 결과를 사용해 `ChatGPT 구독 로그인`, `API 키 · 사용량 과금`,
`로그인 필요`, `인증 확인 실패`를 표시하고, 인증되지 않은 Codex 프로필의 계획 시작을
막는다. Claude와 커스텀 command는 로컬 executable 존재 여부를 확인한다. 현재
프로젝트의 기본 Planning agent가 먼저 선택되며 clarification 재계획 전에 다른
provider로 바꿀 수도 있다. 이 가용성 확인은 원격 API 호출 성공까지 보장하지는 않는다.

Planning 전에 프로젝트 목록의 `최신 받기`를 누르면 native 확인 dialog를 거쳐
설정된 remote와 main branch에 `git pull --ff-only`를 실행한다. main worktree가
clean하고 설정된 main branch가 checkout된 경우에만 진행하며, fast-forward할 수
없거나 Git/network 명령이 실패하면 변경을 숨기지 않고 중단한다. 최신화 전에 만든
Planning run은 기준 commit이 달라질 수 있으므로 새 run을 만들어야 한다.

`모델` 선택기에서는 선택한 provider의 설정값을 그대로 사용하거나 Codex의
`gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-luna`, 설정에 등록된 provider 모델 또는
Claude의 최신 별칭 `fable`, `opus`, `sonnet`과 5세대 전체 모델 ID
`claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`, 또는 직접 입력한 model id를
사용할 수 있다. 선택값은 run에 저장되어 Planning schema 재시도와 clarification
재계획에도 유지된다. Codex는 SDK turn의 model로, 외부 command provider는 실행별
model override로 전달된다.

`추론 강도`는 모델과 별도로 선택한다. `provider 설정 사용`을 선택하면 provider
런타임의 기존 설정을 유지한다. GPT-6.1 Sol은 `low`,
`medium`, `high`, `xhigh`, `max`를 표시한다. Claude는
`low`, `medium`, `high`, `xhigh`, `max`를 표시한다. Planning 선택값은 run에,
Task 선택값은 각 task에 저장된다. Codex 선택값은 SDK turn의 model·effort로,
Claude 선택값은 `--model`·`--effort` 실행 override로 전달된다.

이미 실행을 시작한 그룹의 `재개`와 채팅의 `계속 진행`은 저장된 Task 모델·추론·리뷰와
같은 계획에서 마지막으로 적용한 작업 강도를 유지한다. 다음 실행용 강도 예약은 보존하며
재개에 적용하지 않는다. 실행 전 계획의 첫 실행과 실제 변경 계획의 승인 검사는 유지한다.

`openai-codex==0.159.2`의 고정 실행기 모델 목록에서 `gpt-6.1-sol`을 확인했다.
2026-09-30 현재 계정에서 짧은 read-only turn도 성공해 Planning·Task 선택과 추천
목록에 추가했다. 기존 작업의 저장 모델과 기존 프로젝트 설정에 명시된 모델은
보존한다. 새 프로젝트의 Codex 기본 모델과 신규 기본 선택 목록은 `gpt-6.1-sol`로
설정한다. 기존 GPT-6 Sol 모델은 신규 프리셋에서 제외한다. 시스템 Codex CLI로 우회하지 않는다.

2026-10-27부터 `gpt-6.1-terra`를 기획·채팅·작업 실행의 수동 선택 목록에 제공한다.
도입 당시 SDK/런타임 0.159.2의 모델 목록과 짧은 read-only 응답을 확인했으며,
추론 강도는 Codex 카탈로그의 `low`, `medium`, `high`, `xhigh`, `max`, `ultra`를 사용한다.
기본 모델은 Sol이며, 자동 배정은 위의 Sol/Terra/Luna 정책을 따른다.

계획이 완료되면 각 Task 행의 `실행 프로필` 선택기에 해당 Task capability와 호환되고
SDK 또는 로컬 command 가용성이 확인된 provider의 지원 모델이 표시된다. 아직 실행하지 않은 `pending`
Task는 run이 `planned` 또는 `executing`인 동안 provider·모델·추론 강도를 바꿀 수
있으며, 내부 agent는 선택한 provider와 capability 및 남은 용량에 맞춰 배정된다.
이미 실행 중이거나 완료·수동 인계된 Task의 profile과 reviewer 배정은 변경하지 않는다.
교차 provider review가 켜진 프로젝트는 변경한 Task의 Reviewer도 실행 provider와 다른
provider로 다시 배정한다. Planning 추천이 없고 별도 선택도 하지 않으면 기존
capability routing 결과를 그대로 사용한다. Agent 호출이 진행되는 동안에는 run lock과
화면 갱신 충돌을 막기 위해 선택기가 잠시 비활성화되고 호출 완료 후 다시 활성화된다.

구현 방향을 바꿀 수 있는 결정이 누락되면 run은 `needs_clarification`에서 멈추고
질문을 출력한다. 문서에 독립적인 기능이 여러 개 있으면 하나를 고르라고 묻지 않고
복수의 시작 Task로 만든다. 구체적인 구현 결정을 사용자에게 확인해야 하는 경우에도
이미 식별 가능한 Task 초안을 질문과 함께 제공한다. 데스크톱에서는 Planning AI 대화
영역에 질문 답변뿐 아니라 추가 요구사항이나 계획 수정 방향을 자유롭게 입력해 같은
run을 다시 계획할 수 있다. 이 대화는 `needs_clarification`, `planned`와 Planning
실패 상태에서 사용할 수 있으며 Task 실행이 시작된 뒤에는 기존 구현 결과를 보호하기
위해 입력할 수 없다. 입력 메시지는 run의 `clarifications/` 아래에 UTF-8 Markdown으로
보존되고 사용자와 Planning AI의 대화 이력도 run 상태에 저장된다. CLI는 기존처럼
메시지를 Markdown/TXT 파일로 전달한다.

Planning 채팅은 Codex에서는 같은 SDK thread를, Claude에서는 같은 Claude CLI session을
이어 사용한다. Claude session ID가 없는 기존 작업 그룹은 저장된 기획문서·직전 계획·
대화를 첫 메시지에서 한 번 복원하고, 응답이 성공하면 session ID를 run 상태에 저장해
이후에는 최신 메시지만 `--resume`으로 전달한다. Planning provider 또는 model을 바꾸면
이전 Claude session은 재사용하지 않는다. session ID는 인증 token이나 계정 정보가 아니다.

재계획 입력에는 누적 대화 전체 대신 직전 `plan.json`과 최신 사용자 메시지만 넣어
이전 결정은 유지하면서 반복 token 사용을 줄인다. 전체 대화 이력과 사용자 입력 원문은
run 상태와 `clarifications/`에 계속 보존된다. 상세·로그에는 실제 provider 호출 직전
Planning prompt 문자 수와 캐시 hit·miss·우회 여부가 한국어로 표시된다.

```bash
ai-orchestrator clarify <run-id> answers.md
```

AI가 구조화한 계획은
`.ai-orchestrator/runs/<run-id>/plan.json`에, 원본 응답과 prompt는 같은 run의
`logs/`, `prompts/`에 저장한다. Codex SDK 실행은 요청 메타데이터, turn 결과와 최종
응답을 JSON Lines `.log`에 보존한다. Claude와 custom provider의 stdout도 기존 `.log`에
보존한다. 새 Run은 하나의 `ai/<run-id>` branch와 공유 worktree를 사용한다. Task는
계획 순서대로 하나씩 실행되며 각 결과는 별도 commit으로 남는다. 의존성이 있는 작업은
선행 작업 완료 전에 실행하지 않는다. 저장된 기존 Run은 Task별 branch/worktree
호환 모드로 계속 처리한다.

공유 순차 Run에서는 에이전트의 `max_tasks`를 계획 전체 작업 수의 상한으로 적용하지
않는다. 같은 에이전트가 여러 Task를 차례로 처리할 수 있으며 capability와 독립 Reviewer
조건은 유지한다. 기존 격리 Run은 이전 배정 상한을 유지한다.

Planning 모델과 Task 실행 제공자는 별도 선택이다. 실행 전 Task 화면의
`전체 Task 실행 제공자 변경`에서 모든 Task에 공통으로 가능한 제공자를 선택한 뒤
변경 저장·계획 재확정을 할 수 있다. 개별 모델과 추론 강도도 Task별로 변경할 수 있다.
Codex SDK 프로필은 외부 `command`가 없어도 실행 목록에 포함된다. Planning 대화와
Task 반영에는 최신 목록이 전달되며, 목록에 없는 제공자를 사용하려면 프로젝트의
에이전트 구성을 먼저 변경해야 한다. 대화 자체가 프로젝트 설정을 자동 변경하지는 않는다.

구조화된 task에는 완료 조건과 dependency 외에 `expected_paths`,
`forbidden_paths`, argv 배열 형태의 `verify_commands`와 `low|medium|high`
`risk_level`이 포함된다. 저장소 상대 POSIX 경로가 아니거나 필수 예상 경로·검증
명령이 빠진 Planning AI 결과는 schema 오류로 거부하고 설정된 횟수만큼 다시
계획한다. 이 범위와 명령은 Worker와 Reviewer prompt에도 포함된다. Task별 검증
명령은 자동·수동 Task 완료 직전에 해당 worktree에서 오케스트레이터가 독립
실행하며 `logs/<task-id>-verify.log`에 결과를 남긴다. 명령이 없는 기존 Markdown
fallback Task는 명령 실행을 건너뛴다. 명시 경로가 있는 Task는 검증 명령 유무와 관계없이
자동·수동 commit과 완료 전에 실제 변경 경로를 검사한다.

자동 실행 중 개별 Task의 검증 명령이 실패하면 같은 실행에서 자동 복구를 총 3회까지
이어간다(최초 실행 포함 최대 4번).
일반 검증 실패는 수정 지시 작성·기존 Reviewer 확인·동일 명령 재검증을 수행한다.
같은 Task의 현재 실행에서 이미 만든 구현 commit이 증명되면 새 commit 없이 리뷰·검증을
이어간다. 같은 오류가 반복돼도 새 수정 commit이 있으면 한도 안에서 다른 원인을 확인해 계속한다.
증명된 구현도 없거나 같은 commit에서 코드 변경 없이 동일 진단 반복, 파일 잠금·범위 위반·검증 중 HEAD 변경은
진행을 멈추고 이유를 남긴다. 공급자 오류·사전 환경 조회 실패·명령 시작 실패와 사용자 중지는
자동 수정 대상에서 제외하며, Task 완료 기준·허용/금지 경로·검증 명령을 자동 변경하지 않는다.
기존 수동 완료는 자동 Agent 실행 없이 검증 결과를 반환한다. 최초 실패 action과
`logs/<task-id>-verify-<attempt-id>.log`, 자동 수정 prompt·로그·이벤트는 보존한다.

에이전트가 허용 경로 밖의 파일 수정이 필요하다고 보고하면 `수정 범위 확인 필요`로
구분한다. 필요한 경로·이유와 기존 구현·실패 기록을 유지한다. 채팅에서 제시된 정확한
파일 목록에 자연스럽게 동의하면 AI가 문맥에서 승인 의도를 판단하고, 백엔드가 현재
제안과 사용자 원문의 근거를 검증한다. 실행에도 동의하면 해당 Task의 허용 경로만
계획에 반영하고 같은 Task를 수정·재검증한다. 경로만 추가해 달라고 하면 실행하지 않는다.
질문·거절·불명확한 뜻을 승인으로 처리하지 않으며 정해진 승인 문구는 필요하지 않다.
기존 완료 조건·검증 명령·금지 경로·모델·완료 작업은 유지한다. 오래된 제안·질문·인용이나
에이전트의 승인 요청 자체로는 경로를 확대하지 않는다. 여러 실패나 금지 경로처럼
단순 경로 추가로 해결할 수 없는 변경은 기존 계획 검토가 필요하다.
승인 의도와 범위 적용은 백엔드가 검증하며 사용자 동의 없이 수정 경로를 확대하지 않는다.

실행 이후의 Task 카드는 별도 상태 팝업 대신 해당 Task의 채팅을 연다. 다음 실행 모델·
추론 강도와 사용량·선택 이유·기록 파일은 채팅 입력창 설정 메뉴에서 확인한다.
대화 모델과 다음 Task 실행 모델은 별도로 표시하며 모델 저장만으로 재실행하지 않는다.
실행 전 계획 편집과 수동 완료 확인은 기존 흐름을 유지한다.

MSB4018/MSB3101 진단에서 obj/bin 산출물 경로의 접근 거부가 확인되면 환경 실패로
기록하고 AI 코드 수정을 시작하지 않는다. 기존 구현 commit을 유지하고 빌드 서버/노드
재사용을 끈 자식 프로세스 환경에서 같은 argv의 전체 검증을 자동 재시도한다. 이 재시도도
총 3회 복구 한도에 포함하되 환경 변경 뒤 같은 접근 오류가 계속되면 동일 환경으로 반복하지 않는다.
실패 이력·프로파일을 로그에 보존한다. 부모 환경·파일 권한·
검증 옵션은 바꾸지 않으며 실제 앱 종료가 필요한 파일 잠금은 임의로 해제하지 않는다.
AI의 테스트 통과 보고만으로 완료하지 않는다. 이미 멈춘 과거 실행은 자동 재개하지 않는다.

Task 검증의 기본 제한은 명령당 900초·전체 1800초다. 명시 설정과 기존 Run에 저장된 값은
유지한다. 시간 초과는 테스트 실패와 구분해 `검증 시간 초과 · 완료 여부 미확인`으로 표시한다.
시간 초과 복구를 채팅이나 카드에서 명시적으로 요청하면 실행 잠금·최신 실패를 확인한 뒤
저장 한도를 최소 900/1800초로 보완하고 구현 AI 없이 검증부터 이어간다. 이미 더 긴 값은
줄이지 않으며 실행 중인 명령에는 적용하지 않는다. 검증 명령·완료 조건은 바꾸지 않는다.
같은 commit·명령·한도·검증 자식 환경에서 시간 초과한 기록이 있으면 같은 검증을 다시
시작하지 않고 지연 테스트 진단을 안내한다. 조건이 바뀌면 다시 검사한다. 과거 metadata가
없는 기록은 반복으로 추정하지 않는다. 일반 실패도 실행 시각·소요 시간만 달라졌다면
동일 진단으로 비교하지만 실제 오류 내용은 유지하고 새 commit의 수정 기회는 보존한다.

`expected_paths`가 있으면 실제 변경은 그 목록 안에 있어야 하며 `forbidden_paths`는
항상 우선한다. 경로는 저장소 루트 기준으로 대소문자를 구분한다. `src` 같은 일반 경로는
해당 경로와 하위를 포함하고, `src/*.py`의 `*`는 한 단계 안에서만 일치한다.
`src/**/*.py`의 `**`는 0개 이상의 디렉터리에 일치하며 `?`, `[]`도 사용할 수 있다.
필요한 테스트·문서 경로도 실행 전 계획의 허용 범위에 포함해야 한다.
공유 작업공간의 후속 Task는 실제 실행 직전 HEAD부터 범위를 계산하므로 앞서 완료된
Task의 commit을 자신의 변경으로 판정하지 않는다. 재시도 전에 해당 Task가 직접 만든
commit이 있으면 원래 기준을 유지해 기존 범위 위반을 숨기지 않는다.
원래 기준을 유지하는 공유 Task 재시도에서는 같은 Run·작업공간의 다른 완료 Task가
성공 이력으로 증명한 commit만 검사에서 제외한다. 현재 Task의 실행·수정 commit은
우선 포함하며, 귀속 근거가 없는 commit과 현재 stage·미커밋·새 파일도 계속 검사한다.
같은 파일을 다시 수정하면 그 변경은 검사하므로 파일 이름을 제외 목록으로 사용하지 않는다.

계획을 생성·저장·확정할 때 예상 경로가 겹칠 수 있는 Task를 충돌 가능 그룹으로 묶고
자동 선행 관계를 계산한다. 공용 계약·스키마 작업은 `is_prerequisite: true`로 표시하면
경로가 겹치는 일반 Task보다 먼저 실행한다. 경로가 겹치지 않아도 필요한 선행 작업은
`depends_on`에 명시한다. 명시 의존성과 선행 역할이 모순되면 계획 저장·확정을 거부한다.
화면에는 저장된 그룹과 자동 선행 Task가 표시되며, 경로나 역할을 편집한 뒤 저장하면
다시 계산된다. 자동 관계는 `conflict_dependencies`, 그룹은 `conflict_group`에 기록된다.
두 glob의 교집합과 금지 경로의 제외 효과는 보수적으로 판단하므로 실제 충돌이 없는
Task도 같은 그룹에 포함될 수 있다. 예상 경로가 없는 Task는 예측 대상에서 빠진다.
기존 실행 중 Run에는 새 분석을 소급 적용하지 않는다.

검사는 의존성 통합 이후 Task의 최초 시작 commit부터 수행하며 재시도에도 그 기준을
유지한다. commit 이력, stage·미커밋·ignore되지 않은 새 파일, 삭제와 이름 변경의 양쪽
경로를 포함한다. 위반하면 경로와 실패 action을 남기고 자동 commit·완료를 차단한다.
실제 기준·HEAD·expected/forbidden 경로·제외 commit과 소유 Task·검사 파일·판정은
Run의 `logs/<task-id>-scope.jsonl`에 기록한다. 실패 메시지에도 실제 검사 규칙과
기록 경로를 포함한다. 저장된 과거 기록에 없던 판정 자료는 소급 생성하지 않는다.
수동 완료의 사전 검사 위반은 대기 상태로 남아 파일을 수정한 뒤 다시 완료할 수 있다.
에이전트가 이미 만든 위반 commit은 자동 삭제하지 않으며, 나중에 되돌린 commit을
추가해도 최초 이력의 위반이 사라지지 않는다. 시작 기준이 없는 기존 실행 중 scoped
Task는 새 계획이 필요하다는 오류로 차단한다. 두 경로 목록이 없는 기존 Markdown
Task는 이전처럼 처리한다. 이 검사는 작업 결과 검증이며, worktree 밖의 쓰기나
ignore된 비추적 생성물을 통제하는 filesystem sandbox를 대신하지 않는다.

Planning AI를 설정하지 않은 기존 프로젝트에서는 Markdown 명세의 `## 작업`,
`## 작업 목록`, `## Tasks` 또는 `## Implementation Tasks` 아래에 bullet 항목을
작성한다. capability를 명시할 때는 `[capability]` 형식을 사용한다.

```markdown
## 작업

- [backend, qa] 실행 상태 전이 검증 추가
- [docs] 운영 가이드 보강
```

태그가 없으면 한글·영문 키워드로 capability를 추론한다. Planner가 capability와
라우팅 규칙을 조합해 실행 공급자를 선정하고, 다른 공급자를 리뷰어로 배정한다.
라우팅 이유와 신뢰도, 실제 실행·리뷰 공급자는 상태 JSON에 기록된다.
Markdown fallback task에는 제목 기반 완료 조건과 capability 기반 위험도가 채워진다.
기존 형식에 없는 예상·금지 경로와 task별 검증 명령은 명시되지 않은 값으로 유지한다.

## 실행 흐름

```bash
ai-orchestrator start planning-docs/
ai-orchestrator clarify <run-id> answers.md
ai-orchestrator execute <run-id> --manual
ai-orchestrator resume <run-id>
ai-orchestrator retry-task <run-id> <task-id>
ai-orchestrator complete-task <run-id> <task-id>
ai-orchestrator verify <run-id>
ai-orchestrator push <run-id> --approve
ai-orchestrator merge <run-id> --approve
ai-orchestrator deploy <run-id> --approve
```

공유 worktree는 계획 시점의 base commit에서 만들어지므로 계획 뒤 Main HEAD가
변경돼도 Task 실행 기준은 유지된다. `verify`는 Main을 변경하지 않고 최신 로컬 Main을
공유 작업 branch에 통합한 뒤 같은 worktree에서 `execution.verify_commands`를 실행한다.
설정이 비어 있으면 계획된 Task별 검증 명령을 중복 제거해 사용한다.
`push --approve`는 검증된 `ai/<run-id>` 작업 branch를 원격에 Push하고 원격 branch의
commit을 다시 조회해 검증 대상과 일치하는지 확인한다. `merge --approve`는 그 commit을
Main에 fast-forward하고 Main을 Push한 뒤 원격 Main commit을 확인하고 로컬 공유
worktree와 branch를 정리한다. 검증 뒤 Main 또는 작업 branch가 바뀌면 기존 검증을
무효화하고 재검증과 작업 branch Push를 다시 요구한다. 저장된 기존 Task 격리 Run은
기존 detached 통합 검증과 `merge → push` 순서를 유지한다.

성공한 Push는 대상 remote·branch, 로컬 commit, 확인한 원격 commit, operation 요청 ID와
완료 시각을 Run 상태에 기록한다. 데스크톱 `통합·정리`의 `Push 기록`에서 작업 branch와
Main 결과를 각각 확인할 수 있다. Push 명령이 성공했더라도 원격 ref를 확인할 수 없거나
commit이 다르면 해당 단계를 실패로 기록한다.

상태를 바꾸는 명령은 run별 lock을 획득한다. 같은 run에 대해 `execute`,
`complete-task`, `merge`, `verify`, `push`, `deploy`가 동시에 실행되면 나중 호출은
현재 작업, PID, host와 획득 시각을 포함한 오류로 중단된다. lock은 정상 종료와 오류
종료 시 해제되며, 프로세스가 강제 종료되어 남은 stale lock은 자동 삭제하지 않는다.
상태 JSON에는 schema version 33, workspace mode, 공유 작업 branch/worktree, Task별
시작·완료 commit, 계획 시점의 base commit, 검증 commit, 원격 Push 기록, 현재 단계와 마지막
실패 단계가 저장된다. 기존 상태는 격리 workspace mode와 새
필드의 호환 기본값으로 읽으며 통합 commit 기록이 없는 기존 `verified` run은 Main
반영 전에 재검증해야 한다.

에이전트 실행이 실패하거나 중단되면 다음 명령으로 전체 실패 task 또는 선택한
task만 다시 실행한다. `--manual`을 사용하면 공급자를 실행하지 않고 worktree를
수동 대기 상태로 전환한다.

```bash
ai-orchestrator resume <run-id>
ai-orchestrator resume <run-id> --manual
ai-orchestrator retry-task <run-id> <task-id>
ai-orchestrator retry-task <run-id> <task-id> --manual
```

task 상태에는 마지막 `execute`, `review`, `revise` action과 시도 횟수가 기록된다.
`action_results`에는 구현·수정·리뷰·검증 시도별 결과가 누적된다. Worker 응답은
자체 보고로 보관하고, 실제 변경 경로·commit·통과한 검증 명령은 오케스트레이터가
기록한다. action 성공이 Task 완료를 뜻하지는 않으며 기존 Reviewer 판정과 Task
검증을 모두 거쳐야 한다. 이전 상태는 빈 기록으로 읽고 과거 실행 증거를 추정하지 않는다.

통합 검증은 `verification_attempts`에 시도별 대상 Main·Task·통합 commit, 마지막 실행
명령, 통과한 명령, 통합 실패 Task와 오류를 보존한다. 로그는 `logs/verify-attempt-N.log`에
남기고 `logs/verify.log`에는 최신 명령 로그를 제공한다. 전체 테스트 실패만으로 특정
Task를 원인으로 확정하지 않는다. 검증 명령이 HEAD를 변경하거나 검증 종료 시 미커밋
결과가 남으면 검증 성공을 거부한다. 이 검사는 Task 검증과 공유·격리 통합 검증에 적용된다.
재시도는 이전 기록과 Task commit을 보존하되 전체 검증을 다시 실행한다. 검증 후 작업
branch나 Main이 바뀌는 경우에도 기존대로 재검증이 필요하다.

`dotnet test`, `dotnet build` 등 SDK 명령의 검증 로그에는 앱이 선택한 `dotnet` 실행 파일,
같은 작업 디렉터리에서 실행한 `--list-sdks`와 `--version` 결과가 먼저 기록된다.
통합 검증의 `dotnet restore/build/test`는 해당 검증 프로세스에서만 MSBuild 서버와 노드를
재사용하지 않는다. 다른 앱·빌드 서버를 종료하거나 명령·전역 설정을 변경하지 않으며,
산출물 접근 실패가 계속되면 환경 오류로 남기고 코드 자동 수정을 시작하지 않는다.
SDK 선택에 실패하면 일반 테스트 실패 대신 `.NET SDK 환경 오류`로 표시한다.
진단 출력에서 확인한 경우 오류 요약에 `global.json 요구 SDK 7.0.100 / 설치 SDK 10.0.301`처럼
실제 요구 버전과 선택한 실행 파일의 설치 SDK를 함께 표시한다. AI의 자체 설명과 다르면
해당 Task 작업 디렉터리에서 수집한 진단을 기준으로 SDK 조건을 확인한다.
`--version` 오류의 `global.json` 요구 버전과 실행 경로를 확인하고, 앱의 SDK 환경을
맞춘 뒤 검증을 재시도한다. 진단은 SDK 설치나 PATH·global.json 변경을 자동 수행하지 않는다.

데스크톱 상단의 **설정**에서 프로젝트별 `dotnet.exe` 절대 경로를 입력하거나 파일을
선택할 수 있다. 빈 값은 앱의 PATH 자동 탐색이다. 경로는 이 PC의 프로젝트 registry에
저장되고 저장소의 `orchestrator.toml`은 수정하지 않는다. **저장 후 SDK 확인**은 선택한
Task의 작업 디렉터리(미배정이면 프로젝트 저장소)에서 진단하며 로그를 복사할 수 있다.
Task를 선택하지 않은 공유 작업 그룹은 그룹 작업 디렉터리를 사용한다.
저장한 경로는 오케스트레이터의 사전 진단과 최종 검증뿐 아니라 dotnet 검증 명령이 있는
Task의 실행 계약에도 전달된다. 따라서 Codex 에이전트가 실행하는 추가 .NET SDK 명령도
PATH에서 다시 찾지 않고 같은 `dotnet.exe`를 사용한다. 이미 생성된 대기 Task에도 실행
시점의 최신 프로젝트 설정이 적용된다.
설정은 다음 실행/재시도부터 적용되며 이미 실행 중인 작업에는 적용되지 않는다.
자동 실행과 수동 인계 전에 Task 및 프로젝트 검증의 SDK 명령을 사전 검사한다.
검사 실패 시 구현 agent는 시작하지 않으며 Task 로그에 진단을 남긴다.
구현 후 검증에서 실패했다면 환경 수정 후 **재시도**로 검증 action부터 이어간다.

실패 상태에서도 Planning 대화를 이어갈 수 있다. 기존 Task와 실패/검증 기록은 유지하며,
대화의 Task 적용 요청은 같은 그룹의 미실행·실패 Task에 반영한다. 완료·수동 확인 결과,
Task ID와 실행 이력은 보존하며 추가 작업은 같은 그룹에 새 Task로 넣는다.
실행 중 요청은 대기시킨 뒤 현재 실행 batch가 끝나면 반영하고 다음 실행을 멈춘다.
변경 내용을 확인한 뒤 실행·재시도한다. 실패 Task의 요구사항이 바뀌면 구현부터 재시도한다.
잘못된 계획은 원래 Task와 대기 요청을 보존하며 오류를 표시한다.

Task 상세·로그 상단에는 현재 단계, 단계 경과시간, 마지막 활동 보고 시각과
구현/리뷰/검증 결과를 표시한다. 통과한 검증 명령 수는 현재 검증 시도의 실제 기록을
사용하며, SDK의 계획 단계 완료 수는 agent가 보고한 계획 진행 정보다.
SDK 진행 로그에는 초 단위 시각, 알려진 명령 종류, 명령 종료 코드와 파일 적용 결과를
표시한다. 임의 명령 인자와 reasoning 원문은 진행 정보로 복제하지 않는다.
같은 작업이라도 SDK 알림이 계속 오면 최대 5초 간격으로 활동 시각을 갱신한다.
알림이 없는 시간만으로 중단을 판정하지 않는다.
로그 탭은 2초 간격으로 자동 갱신하고, 위로 스크롤해 읽는 동안에는 위치를 유지한다.
오케스트레이터 검증 중에는 명령과 순서를 표시하며 stdout은 명령 종료 후 기록한다.

재시도는 worktree를 삭제하거나 reset하지 않고 실패 action부터 이어간다. 병합 전
`verify` 실패는 `ready_to_merge`, 공유 작업 branch `push` 실패는 `verified`, Main
반영·Push 실패는 `work_branch_pushed`로 복원한다. 기존 병합 완료 run의 호환 검증
실패는 `merged`, 기존 `push` 실패는 `merged`, `deploy` 실패는 `pushed`로 복원한다.
복원 뒤 merge, push와 deploy는 기존 명령의 `--approve`를 다시 요구한다. 공유 Run은
Main이 이미 fast-forward된 뒤 Main Push만 실패해도 같은 검증 commit에서 재개한다.
기존 격리 Run의 부분 merge, planning과 task 준비 실패는 자동 resume하지 않는다.

강제 종료 뒤 lock이 남았으면 다음 명령으로 먼저 진단한다.

```bash
ai-orchestrator lock status <run-id>
ai-orchestrator --json lock status <run-id>
ai-orchestrator lock clear <run-id> --approve
```

해제는 현재 host와 lock의 host가 같고 소유 PID가 종료돼 `stale`로 확인된 경우에만
가능하다. 살아 있는 PID는 `active`, 다른 host나 확인할 수 없는 PID는
`unverifiable`, 필수 메타데이터가 잘못된 lock은 `malformed`로 표시하며 삭제하지
않는다. PID가 재사용된 경우에도 활성 프로세스로 보고 보수적으로 해제를 거부한다.

Run 공유 branch/worktree와 기존 Task별 작업공간 상태는 다음 명령으로 진단한다.

```bash
ai-orchestrator workspace status
ai-orchestrator workspace status <run-id>
ai-orchestrator --json workspace status <run-id>
ai-orchestrator workspace clear <run-id> <task-id> --approve
```

정리는 알려진 Run의 deterministic 작업공간만 대상으로 한다. Main 반영·Push가
완료됐고 worktree가 clean이며 run lock이 없을 때만 `stale`과 `cleanup=yes`로
표시한다. 새 공유 작업공간은 Main Push 성공 직후 자동 정리한다. dirty 또는 미병합
branch, 등록 정보가 다른 worktree와 실행 중인 run은 삭제하지 않는다. clear는 local
공유 branch/worktree 또는 기존 local task branch/worktree만 제거하며 main commit,
run 상태, 기획문서, prompt와 log는 보존한다. 데스크톱 앱에서는 task 선택 후
`작업공간 정리` 버튼으로 같은 진단과 승인 경계를 사용한다.

Task 준비가 중단된 뒤 `execute`를 다시 실행하면 base commit과 같은 clean
deterministic 공유 branch/worktree만 상태에 다시 연결한다. 기존 commit이나 미커밋 변경이
발견되면 자동 reset 또는 삭제하지 않고 실패한다. agent 실행 이후의 재실행은 기존
resume/retry 계약에 따라 현재 worktree와 마지막 action을 이어간다.

새 Run의 일반적인 상태 흐름은
`received → reviewed → planned → executing → ready_to_merge → verified → work_branch_pushed → pushed → deployed`다.
여기서 `work_branch_pushed`는 작업 Branch Push 완료, `pushed`는 Main 반영과 Main Push
완료를 뜻한다. 기존 격리 Run은 `verified → merged → pushed` 흐름을 유지한다.
공유 Run은 Main에 미커밋 변경이 있어도 검증 결과와 변경 경로가 겹치지 않으면,
로컬 변경을 보존하는 검사를 거쳐 승인된 Main 반영·Push를 진행한다. 겹치는 경로나
확인할 수 없는 상태는 차단하고 원본 변경을 자동 commit·stash·reset하지 않는다.
확인이 필요한 계획은 `reviewed → needs_clarification → planned` 흐름을 거친다.
`executing` 안에서 각 작업은
`running → reviewing → revising → reviewing → completed` 순환을 가질 수 있다.
리뷰어는 마지막 출력에 구조화된 `AI_REVIEW_RESULT` 판정을 남기며, 수정 요청이면
원 실행 에이전트가 피드백을 반영한다.
작업 실패나 merge·검증·배포 실패는 `failed` 상태로 기록한다.

상태 확인은 다음 명령을 사용한다.

```bash
ai-orchestrator status
ai-orchestrator status <run-id>
ai-orchestrator --json status <run-id>
```

일반 status는 각 task의 lifecycle 상태와 별도로 dependency readiness를 표시한다.
미완료 dependency가 있으면 `blocked`와 `blocked-by`, 모두 완료됐으면 `ready`이며,
실행·완료·실패 task는 각각 `active`, `done`, `failed`로 표시한다. 위험도, 예상·금지
경로와 task별 검증 명령도 함께 출력하며 JSON 출력에는 원래 배열 구조가 보존된다.

## 검증

```bash
python -m compileall -q src
python -m unittest discover -s tests -v
```

저장소에 테스트가 추가되기 전에는 `compileall`만 실행 가능하다. 대상 프로젝트의
전체 공통 검증 명령은 `execution.verify_commands`에 인자 배열로 등록하며, 비어 있으면
Planning 결과의 Task별 검증 명령을 통합 검증에 사용한다. 검증 명령은 비대화형으로
실행하고 Git 명령은 30초, 일반 빌드·테스트 명령은 명령당 10분 제한시간을 적용한다.
오케스트레이터가 소유하는 `git worktree` 명령은 기존 계획에 포함되어 있어도 통합
검증에서 제외한다. `npm run` 검증 대상에 `package-lock.json`은 있지만
`node_modules`가 없는 경우에는 같은 검증 작업공간에서 `npm ci`를 한 번 선행한다.
검증 후 Main 반영에 사용하는 로컬 Git 조회·fast-forward·정리도 비대화형으로 실행하고
각 호출에 30초 제한시간을 적용한다.


### 실패 그룹의 복구안 확인·적용

실패한 공유 작업 그룹의 Tasks 화면에서 **자동 복구**를 누르면 현재 실패 응답과
같은 프로젝트의 다른 그룹에 남은 완료 commit 후보를 확인할 수 있습니다.
필요한 그룹만 선택하고 **복구안 적용**의 확인창에서 승인하세요.
선택한 commit의 이전 변경 이력도 함께 포함되므로 후보가 필요한 선행 결과인지 확인해야 합니다.
선택하지 않으면 실패 원인을 바탕으로 현재 그룹의 Task만 재계획합니다.

통합은 임시 worktree에서 먼저 확인합니다. 충돌·미커밋 변경·변경된 복구안은 거절하며,
Git 통합 후 재계획이 실패하면 통합된 기준선과 적용 대기 요청을 보존하고 별도 오류를 표시합니다.
완료 Task와 실패 이력은 유지합니다. 재계획한 Task를 확인한 뒤 **그룹 재개**로 실행하세요.
이 기능은 main 반영이나 push, 원래 그룹 삭제를 수행하지 않습니다.

## 라이선스와 공개 소스

MIT 라이선스로 제공한다. [LICENSE](LICENSE)와 [제3자 고지](THIRD_PARTY_NOTICES.md)를 확인한다.
공개 소스 갱신과 바이너리 발행은 [공개 릴리즈 절차](Docs/PublicReleases.md)를 따른다.
