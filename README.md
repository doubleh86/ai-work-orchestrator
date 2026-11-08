# AI Work Orchestrator

Codex·Claude 앱에서 만들 내용을 정하고, 여러 작업 AI로 제작하는 로컬 데스크톱 앱입니다.
오케스트레이터는 MCP로 계획을 받아 태스크·모델을 준비하고 진행 상황과 결과를 보여줍니다.

## 주요 기능

- 외부 AI 앱의 MCP 계획 제출·실행 제어
- 여러 작업 AI 연결과 태스크별 모델 설정
- Git worktree 기반 실행, 중지·재개와 실패 복구
- 결과 실행·사용자 확인과 승인 후 반영·Push

## Windows에서 바로 실행하기

[v0.6.0 릴리스](https://github.com/doubleh86/ai-work-orchestrator/releases/tag/v0.6.0)에서 앱 ZIP 전체를 받아
새 폴더에 압축을 풀고 `AI Work Orchestrator.exe`를 실행합니다. MCP만 사용할 때는 MCP 전용 ZIP을 받습니다.
앱 실행에 Python·Node.js 설치는 필요하지 않습니다. Git과 작업 AI·프로젝트별 개발 도구는 별도로 준비합니다.
ZIP은 v0.6.0 배포 시점의 UI입니다. 이후 Claude 연결·진행 표시 개선은 최신 소스에 반영되어 있습니다.

## 소스로 실행하기

Python 3.11 이상, Node.js 22.12 이상, Git이 필요합니다.

Windows PowerShell:

```powershell
git clone https://github.com/doubleh86/ai-work-orchestrator.git
cd ai-work-orchestrator
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[mcp]'
npm ci
npx --no-install install-electron
npm start
```

macOS/Linux에서는 `python3 -m venv .venv`와 `.venv/bin/python -m pip install -e '.[mcp]'`를 사용합니다.
이후 npm 명령은 같습니다.

## 사용하기

1. **새 채팅**에서 MCP 설치·연결 프롬프트를 복사해 Codex·Claude 등의 앱에 붙여 넣습니다.
2. 연결한 앱에서 무엇을 만들지 정하고 오케스트레이터에 계획을 전달합니다.
3. **작업 AI**에서 제작할 AI들을 연결하고, 태스크를 눌러 모델과 기록을 확인합니다.
4. **제작 준비 완료** 알림에서 계획을 확인한 뒤 제작을 시작합니다.
5. 진행·최근 활동·대기·중지는 앱에서 확인합니다. 관제 AI는 요청 접수 후 답변을 끝냅니다.

기획 대화는 외부 앱에서 진행합니다. 오케스트레이터에서는 결과 실행·사용자 확인,
프로젝트 관리·알림과 반영·보관을 처리합니다. Push·Main 반영·배포는 사용자 승인 후 진행합니다.

연결 프롬프트에는 현재 실행 경로와 MCP 등록 도우미가 들어 있습니다.
로컬 설정을 수정할 도구가 없는 대화 앱에서는 수동 설정이 필요할 수 있습니다.
연결한 앱에서 도구 조회까지 확인하세요. CLI 명령은 `ai-orchestrator --help`를 참고합니다.
Claude 실행 파일을 찾지 못하면 **작업 AI** 화면에서 직접 선택하고 연결을 다시 확인할 수 있습니다.

## 문서와 라이선스

- [구조와 설계](Docs/Architecture.md)
- [개발 문서 안내](Docs/ProjectDocumentGuide.md)
- [수정 범위에 맞춘 검증](Docs/Testing.md)
- [공개 소스 갱신·릴리즈](Docs/PublicReleases.md)
- [MIT 라이선스](LICENSE) · [제3자 소프트웨어 고지](THIRD_PARTY_NOTICES.md)
