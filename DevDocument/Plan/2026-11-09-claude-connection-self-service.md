# Claude 연결 경로를 앱에서 직접 지정

## 목표

Claude Code가 설치돼 있어도 앱의 실행 환경에서 찾지 못하는 사용자가 코드를 수정하거나
환경 변수를 설정하지 않고 연결을 완료할 수 있게 한다.

## 참고 문서

- `AGENTS.md`, `Docs/CodeStyle.md`, `Docs/Architecture.md`
- `DevDocument/Plan/2026-11-09-claude-cli-discovery.md`
- `README.md`의 Claude 연결 및 데스크톱 실행 안내

## 범위와 영향 파일

- Claude 연결 화면에 실행 파일 선택과 자동 탐색 복귀를 제공한다. 기존 설치·로그인·재확인
  흐름은 유지한다.
- Electron의 허용된 파일 선택 kind를 추가하고, 선택한 경로는 Python RPC에서 검증한다.
- 선택한 실행 파일은 로그인 터미널에도 전달한다. 터미널에 넘기는 명령의 인용 처리를
  플랫폼별로 확인하고 renderer는 로그인 명령을 직접 조립하지 않는다.
- 선택한 경로를 앱 사용자 설정 root에 원자적으로 저장한다. 명시적 경로가 유효하면
  연결 조회·작업 실행·사용량·MCP 등록에서 우선한다. 파일이 사라지면 자동 경로로
  조용히 전환하지 않고 사용자가 다시 선택하거나 자동 탐색을 선택하게 한다.
- 저장 파일에는 경로만 기록하며 인증 정보는 읽거나 저장하지 않는다. 프로젝트 저장소와
  작업 계획은 바꾸지 않는다.
- 영향: `provider_executable.py`, `pipeline.py`, `desktop_rpc.py`, Electron 파일 선택·로그인
  allowlist, `ClaudeConnectionPanel.tsx`, 관련 테스트·문서.

## 검증 방법

- 저장·복원·잘못된 경로·자동 탐색 복귀를 임시 사용자 설정 root에서 검증한다.
- RPC 입력 검증, 파일 선택 allowlist, 화면의 선택·취소·오류 흐름을 검증한다.
- Python 관련 테스트와 renderer 테스트·typecheck·빌드를 실행하고 공통 실행 경계의
  영향이 확인되면 전체 Python 테스트를 실행한다.
- 실제 데스크톱 화면에서 경로 선택 동작을 확인하되 사용자 설정은 임의 변경하지 않는다.

## 진행과 결과

- 2026-11-09: 실행 파일 선택·저장·복구·RPC와 화면 구현. 로그인 터미널도 선택한
  실행 파일을 사용하도록 연결했다. 관련 Python 테스트 118개, renderer 테스트 320개,
  TypeScript 검사와 빌드 통과. macOS 로그인 AppleScript는 실행 없이 컴파일 통과.
- 전체 Python 회귀는 1,402 통과·4 건너뜀·1 실패. 실패는 변경하지 않은
  `test_stdio_creates_and_connects_document_then_handles_current_failure`에서 새 Git 저장소
  준비 상태가 `invalid`로 판정되는 문제이며 단독 실행에서도 재현된다.
- `npm start`로 macOS 앱을 다시 실행해 실제 AI Work Orchestrator 창을 확인했다.
  사용자가 앱의 다른 화면을 조작 중이어서 파일 선택 UI의 실제 클릭 검증은 진행하지 않았다.
