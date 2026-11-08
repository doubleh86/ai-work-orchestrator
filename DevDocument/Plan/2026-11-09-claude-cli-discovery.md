# Claude Code 실행 파일 탐색 수정

## 목표

macOS에서 공식 설치된 Claude Code가 `~/.local/bin/claude`에 있으나 데스크톱 앱의
`PATH`에 그 디렉터리가 없으면 "Claude CLI 설치 필요"로 표시되는 문제를 수정한다.

## 참고 문서

- `AGENTS.md`, `Docs/CodeStyle.md`, `Docs/Architecture.md`
- `README.md`의 Electron 데스크톱 앱 및 Claude 연결 안내

## 범위와 영향 파일

- 기존 `PATH`와 명시적인 실행 파일 경로를 우선하고, Claude에 한해
  `~/.local/bin/claude`의 실행 가능한 파일을 추가로 찾는다.
- 연결 상태, 실제 작업 실행, 사용량 조회 및 MCP 등록이 같은 탐색 결과를 사용한다.
- `src/ai_orchestrator/provider_executable.py`, `pipeline.py`, `account_usage.py`,
  `mcp_bundle.py`와 관련 테스트를 수정한다.
- 인증 정보 파일을 조회하거나 변경하지 않는다. 기존 CLI 명령과 승인 경계는 유지한다.

## 미결정 사항

없음. 확인된 설치 위치와 기존 `PATH` 우선순위만 적용한다.

## 검증 방법

- `PATH`에 Claude가 없는 경우의 설치 경로 탐색과 실행 불가 파일 거부를 테스트한다.
- 연결 상태와 사용량 조회의 호출 경계를 테스트한다.
- 관련 Python 테스트와 `python -m compileall -q src`를 실행한다.
- 앱을 재시작해 Claude 연결 표시를 확인한다.

## 진행과 결과

- 2026-11-09: 원인 확인 및 구현 시작. 실제 설치 위치는
  `~/.local/bin/claude`, 앱 실행 환경의 `PATH`에는 `~/.local/bin`이 없다.
- 연결 상태·실행·사용량·MCP 등록에 공통 실행 파일 탐색을 적용했다.
- 관련 테스트 39개, provider 선택·Claude 테스트 29개, 정적 컴파일과 diff 검사를 통과했다.
- 전체 Python 테스트는 1,390개 통과·11개 건너뜀·2개 실패했다. 실패한 두 테스트는
  테스트 환경에 선택 `mcp` 의존성과 `python` 명령 경로가 없어 발생했으며,
  해당 환경을 준비한 뒤 두 테스트를 재실행해 통과했다.
- 실제 arm64 backend는 CLI 설치를 인식했다. 샌드박스 안의 직접 조회에서는
  인증되지 않은 것으로 반환됐으나, 재시작한 실제 데스크톱 앱 화면에서는
  `연결 완료 · Claude Pro 구독 로그인`을 확인했다.
