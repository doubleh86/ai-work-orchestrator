# Claude 작업 AI의 API 키 연결

## 목표와 범위

작업 AI의 Claude 연결에 Anthropic API 키 저장·교체·삭제를 제공한다. 기존 Claude Code
실행과 구독 로그인은 유지하며 API 사용량은 별도 과금된다고 안내한다. 키 저장과 CLI 인증
상태 조회는 실제 유료 호출·키 유효성 검증과 구분한다.

Electron main은 단일 키를 OS safeStorage로 암호화해 userData에 원자적으로 저장한다.
보안 저장소 미지원·Linux basic_text는 평문으로 대체하지 않는다. renderer에는 키 조회
API를 제공하지 않고 공개 RPC params·프로젝트 설정·로그·실행 상태에 키를 넣지 않는다.

main→Python의 내부 JSON Lines credential 필드와 요청별 scope를 추가한다. Pipeline은
생성 당시 키를 고정해 작업 스레드에서도 유지하고, 앱 키를 Claude 자식 프로세스의 환경에만
주입한다. 앱 키 사용 시 상충하는 외부 인증·프록시·cloud provider 환경은 이 자식에서만
제외해 Anthropic 직접 인증을 선택하며 CLI의 관리 정책은 변경하지 않는다.
앱 키가 없으면 기존 CLI·환경 인증을 따른다.
저장·삭제는 다음 요청부터 반영하며 진행 중 작업을 재시작하지 않는다.

## 영향과 검증

main credential 저장·preload·bridge, Python 요청 경계·Pipeline 인증 조회와 외부 실행,
Claude 연결 UI와 관련 문서를 수정한다. 기존 NVIDIA·Codex 연결 계약은 유지한다.
타입·수정 Python 구문·diff 검사와 키 저장/실패·요청 격리·스레드 snapshot·환경 주입/
출력 마스킹·키 입력/삭제의 관련 검사만 실행한다. 실제 키·계정·유료 API 호출은 사용하지 않는다.

## 참고

- [Claude Code 인증](https://code.claude.com/docs/en/authentication)
- [API 키 우선순위와 과금](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code)

## 진행과 결과

Claude 키의 암호화 저장·교체·삭제와 전용 preload API, main→Python 요청별 전달,
Pipeline snapshot과 Claude 자식 환경 주입을 구현했다. 구독으로 오인한 인증 결과는
받아들이지 않으며 API 인증 실패는 키 설정 확인을 안내한다. UI는 키를 읽어오지 않고
입력값을 전송 전에 비운다. 키 저장과 실제 유료 API 검증은 구분한다.

`npm run typecheck`, 수정 Python의 `py_compile`과 diff 검사를 통과했다.
관련 Python 두 파일은 최종 내용 기준 36개 통과·POSIX 전용 1개 제외이며, renderer/main은
키·연결 UI 두 파일과 bridge/종료 경계의 선택 사례 총 17개가 통과했다. 실패한 검사만
재확인했다. 기본 Python에 pytest가 없어 기존 `.venv`를 사용했고, 임시 폴더 생성 권한
오류는 저장소 내부의 새 테스트 경로로 해결했다. preload 모의 실행의 exports 누락도
수정했다. 전체 검사·프로덕션 빌드·실제 OS 저장소·화면 조작·유료 API 호출은 하지 않았다.
