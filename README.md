# AI Work Orchestrator

Codex와 Claude를 연결해 코딩 작업을 계획하고 실행하는 로컬 데스크톱 앱입니다.
채팅으로 요청하고, 진행 상황과 결과를 한곳에서 확인할 수 있습니다.

## 주요 기능

- AI와 대화하며 작업 계획 수립·수정
- 작업별 AI 배정과 Git worktree 기반 실행
- 진행 확인, 중지·재개와 실패 복구
- 변경 검증과 승인 후 프로젝트 반영·Push

## 시작하기

Windows x64에서는 [v0.5.0 릴리스](https://github.com/doubleh86/ai-work-orchestrator/releases/tag/v0.5.0)에서 앱 ZIP을 받아 실행할 수 있습니다.
소스 실행에는 Python 3.11 이상, Node.js 22.12 이상, Git이 필요합니다.

Windows PowerShell:

```powershell
git clone https://github.com/doubleh86/ai-work-orchestrator.git
cd ai-work-orchestrator
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
npm ci
npx --no-install install-electron
npm start
```

macOS/Linux에서는 `python3 -m venv .venv`로 가상환경을 만들고,
`.venv/bin/python -m pip install -e .`를 실행한 뒤 `npm ci`, `npx --no-install install-electron`, `npm start`를 실행합니다.

## 사용하기

1. **AI 연결**에서 Codex 또는 Claude를 연결합니다. Claude는 Claude Code CLI가 필요합니다.
2. 작업할 Git 프로젝트를 등록합니다.
3. 채팅으로 요청하고 계획을 확인한 뒤 작업을 시작합니다.

Push·Main 반영·배포는 사용자 승인 후 진행합니다.
CLI 명령은 `ai-orchestrator --help`에서 확인할 수 있습니다.

## Codex에서 MCP 연결

Windows 앱에서 **설정 → Codex 연결 → Codex에서 진행 상황 보기**를 누르면 동봉된 연결 파일을 설치하고 조회 연결을 등록합니다.
Codex를 다시 열고 “오케스트레이터 작업 진행 상황 알려줘”라고 물어보세요. 새 버전의 앱을 열면 다음 Codex 연결에 동봉된 새 버전이 적용됩니다.

수동 연결과 작업 변경 권한은 같은 화면의 고급 설정에서 설정합니다.

소스로 연결하려면 `python -m pip install -e '.[mcp]'`로 준비한 뒤
`codex mcp add orchestrator -- ai-orchestrator mcp`로 등록합니다.

## 문서

- [구조와 설계](Docs/Architecture.md)
- [개발 문서 안내](Docs/ProjectDocumentGuide.md)
- [공개 소스 갱신·릴리즈](Docs/PublicReleases.md)

## 라이선스

[MIT](LICENSE) · [제3자 소프트웨어 고지](THIRD_PARTY_NOTICES.md)
