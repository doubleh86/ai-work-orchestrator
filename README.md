# AI Work Orchestrator

Codex·Claude 앱에서 만들 내용을 정하고, 여러 작업 AI로 제작하는 로컬 데스크톱 앱입니다.
오케스트레이터는 MCP로 계획을 받아 태스크·모델을 준비하고 진행 상황과 결과를 보여줍니다.

## 주요 기능

- 외부 AI 앱의 MCP 계획 제출·실행 제어
- 여러 작업 AI 연결과 태스크별 모델 설정
- 프로젝트별 외부 MCP 도구 연결과 공유 도구 사용 순서 조정
- Git worktree 기반 실행, 중지·재개와 실패 복구
- 결과 실행·사용자 확인과 승인 후 반영·Push

## Windows에서 바로 실행하기

[v0.7.2 릴리스](https://github.com/doubleh86/ai-work-orchestrator/releases/tag/v0.7.2)에서 앱 ZIP 전체를 받아
새 폴더에 압축을 풀고 `AI Work Orchestrator.exe`를 실행합니다. MCP만 사용할 때는 MCP 전용 ZIP을 받습니다.
앱 실행에 Python·Node.js 설치는 필요하지 않습니다. Git과 작업 AI·프로젝트별 개발 도구는 별도로 준비합니다.
v0.7.2 ZIP에는 프로젝트별 외부 MCP 연결·공유 도구 대기 표시를 포함합니다.

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

**프로젝트 관리 → 도구 연결**에서 Unity 등 외부 MCP를 연결할 수 있습니다.
도구가 제공하는 주소나 MCP JSON을 넣고 연결을 확인하면 다음 Codex·Claude 제작부터 사용합니다.
도구 서버의 설치·실행과 실제 에디터 작업공간 연결은 별도로 준비합니다.

기획 대화는 외부 앱에서 진행합니다. 오케스트레이터에서는 결과 실행·사용자 확인,
프로젝트 관리·알림과 반영·보관을 처리합니다. Push·Main 반영·배포는 사용자 승인 후 진행합니다.

창의 닫기 버튼은 트레이로 숨기며 작업은 계속됩니다. 트레이 아이콘이나 `열기`로 창을
다시 열고, 완전히 끝내려면 트레이 메뉴의 `종료`를 선택합니다.

보관한 작업은 기본 목록에서 빠지고 **보관함**에서 열 수 있습니다. 긴 설명은 펼쳐서 확인합니다.

일반 Claude 작업은 Sonnet, 중요하거나 복잡한 작업은 Opus로 자동 배정합니다.
구독 한도 소진이 확인되면 미시작 자동 작업은 다른 연결 AI로 전환합니다. 직접 지정·진행 중인 작업은 유지합니다.
현재 작업 계정의 한도는 **AI 사용량**에서 확인합니다. 조회 실패를 소진으로 판단하지 않습니다.

연결 프롬프트에는 현재 실행 경로와 MCP 등록 도우미가 들어 있습니다.
로컬 설정을 수정할 도구가 없는 대화 앱에서는 수동 설정이 필요할 수 있습니다.
연결한 앱에서 도구 조회까지 확인하세요. CLI 명령은 `ai-orchestrator --help`를 참고합니다.
Claude 실행 파일을 찾지 못하면 **작업 AI** 화면에서 직접 선택하고 연결을 다시 확인할 수 있습니다.
**작업 AI → Claude → API 키로 연결**에서 Anthropic 키를 암호화해 저장·교체·삭제할 수 있습니다.
Claude Code 설치가 필요하며 [API 사용량은 별도 과금](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code)됩니다.

## 문서와 라이선스

- [구조와 설계](Docs/Architecture.md)
- [개발 문서 안내](Docs/ProjectDocumentGuide.md)
- [수정 범위에 맞춘 검증](Docs/Testing.md)
- [공개 소스 갱신·릴리즈](Docs/PublicReleases.md)
- [MIT 라이선스](LICENSE) · [제3자 소프트웨어 고지](THIRD_PARTY_NOTICES.md)
