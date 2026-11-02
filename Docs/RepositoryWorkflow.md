# Repository Workflow

## 저장소 작업 원칙

이 절은 저장소 개발 작업의 승인 범위에 적용하며 재확인 기준은 `AGENTS.md`를 따른다.
아래 오케스트레이터 실행의 `--approve`와 native 확인 절차를 대신하지 않는다.

- 작업 전 `git status --short --branch`로 기존 변경을 확인한다.
- 기존 사용자 변경은 되돌리거나 다른 작업의 커밋에 섞지 않는다.
- 브랜치 생성, commit, merge, push는 사용자 요청 또는 승인 범위 안에서만 수행한다.
- deploy는 대상과 명령을 확인하고 명시적으로 승인된 경우에만 수행한다.
- 작업 후 변경 파일이 요청 범위 안인지 확인하고 `git diff --check`를 실행한다.
- 이번 작업에서 직접 만든 임시 파일·테스트 생성물은 경로와 소유권을 확인한 뒤 정리할 수 있다.
  기존 untracked 파일, 사용자 데이터, 공유 캐시를 생성물로 추정해 지우지 않는다.

## Agent와 Worktree 조정

- 새 자동 실행 Run은 `ai/<run-id>` branch와 deterministic 공유 worktree 하나를
  소유한다. 모든 Task는 이 worktree에서 계획 순서대로 실행하며 각 결과를 독립
  commit으로 남긴다. 저장된 기존 Run의 `ai/<run-id>/<task-id>` branch와 Task별
  worktree는 호환 경로로 유지한다.
- Agent는 Run 공유 worktree에서 현재 Task 범위만 수정하고 Main을 직접 변경하지 않는다.
  `expected_paths`와 `forbidden_paths`는 Task별 실행·리뷰 계약으로 유지한다.
- Task는 dependency와 계획 순서를 따라 직렬 실행한다. `max_parallel` 설정은 기존 격리
  Run 호환 실행에만 적용한다.
- 전체 검증을 통과한 공유 작업 commit만 명시적 승인 후 작업 branch로 Push한다. 별도
  승인 뒤 같은 commit을 Main에 fast-forward하고 Main을 Push한다.
- Codex의 Task `@` 참조, Task 읽기·생성·메시지와 Handoff는 진행 상황을 확인하거나
  전달하는 보조 수단으로만 사용할 수 있다. 이 프로젝트는 해당 기능을 자동
  delegation, 작업 소유권 이전, 자동 merge의 근거로 사용하지 않으며 현재
  애플리케이션 상태에도 통합하지 않는다.
- Handoff 요약보다 repository의 현재 Git 상태, run/task 상태와 등록 worktree를
  우선한다. dirty checkout을 자동 이동시키는 흐름은 기본 운영 절차로 사용하지 않는다.

## Codex 권한과 Session 운영

- Git worktree는 branch별 작업 디렉터리일 뿐 filesystem security sandbox가 아니다.
  Codex sandbox, approval policy와 managed deny-read 같은 관리 정책은 별도 경계이며
  permission mode 변경, Task 참조 또는 `AGENTS.md` 지침으로 완화되지 않아야 한다.
- 현재 Planning은 등록 저장소 루트의 `AGENTS.md`, `AGENTS.local.md`를 프롬프트에
  직접 포함한다. Codex 자체의 project trust 판정이 이 입력을 대신 검증하지 않으므로
  사용자가 신뢰하지 않은 프로젝트에서는 Planning을 실행하지 않는다.
- 같은 문맥의 code-only 반복 작업은 필요하면 긴 Codex session을 유지할 수 있다.
  긴 session 자체를 금지하지 않으며, 이미지와 스크린샷이 많이 누적된 경우에만
  compaction의 context pressure를 고려한다.
- 현재 오케스트레이터는 Codex Planning, 실행, 리뷰와 수정 action을 공식 Python SDK
  turn으로 호출한다. Claude와 custom provider만 외부 command 프로세스를 사용한다.
  Codex thread/session 상태는 authoritative run 상태가 아니며 재개 판단은 저장된
  run/task 상태와 worktree를 따른다.
- worktree·branch·run 삭제는 정확한 소유권과 경계를 확인하고 사용자가 승인한 대상·범위
  안에서만 수행한다. 이미 승인한 동일 범위의 재시도는 재승인을 요구하지 않되, 대상이나
  보존할 데이터가 바뀌면 다시 확인한다. 앱의 native 확인·`--approve` 요구는 그대로 적용한다.

## 모듈러 모놀리스 저장소 구조

```text
ai_work/
  AGENTS.md
  Docs/
  DevDocument/Plan/
  src/ai_orchestrator/
  tests/
  pyproject.toml
```

모든 런타임 모듈은 하나의 `ai_orchestrator` 패키지에 두고 함께 버전 관리하고
배포한다. 모듈 경계는 저장소 분리 대신 코드 의존 방향과 테스트로 유지한다.

## 생성물 관리

- Python: `__pycache__/`, `*.py[cod]`, `*.egg-info/`
- 테스트·도구: `.pytest_cache/`, `.coverage`, `htmlcov/`
- 가상 환경·빌드: `.venv/`, `dist/`, `build/`
- 런타임 상태: `.ai-orchestrator/`
- 격리 작업 공간: 대상 저장소의 `.ai_auto_work/worktree/`
- IDE: `.idea/`, `.vscode/`
- 로컬 환경: `.env`, `*.local`, `*.local.toml`

생성물과 로컬 상태는 커밋하지 않는다. 공유 가능한 설정 예시는 비밀 정보가 없는
별도 예제 파일로 제공한다.

Run worktree에서 검증 명령이 상대 `state_dir`을 만들더라도 해당 untracked 생성물만으로
후속 검증·Push·Main 반영을 막지 않는다. 다른 untracked 파일과 tracked 변경은 기존처럼
차단하며, 완료 worktree 정리 시 관리 상태 디렉터리를 함께 제거한다.

완료 그룹 보관 중 `git worktree remove`가 Git 등록을 제거한 뒤 Windows 파일 잠금으로
디렉터리 삭제에 실패하면 대상별 보관 receipt에 실패 경로를 남긴다. 이후 승인된 정리 재시도는
그 receipt와 Run의 deterministic 경로가 정확히 일치할 때만 남은 디렉터리를 제거한다.
기록 없는 폴더와 다른 저장소의 Git marker는 계속 정리 대상에서 제외한다.

## 오케스트레이터 부작용 경계

- 프로젝트 등록 시 기존 `orchestrator.toml`이 없으면 대상 저장소가 아니라 사용자
  설정 root의 프로젝트별 관리 디렉터리에 기본 설정을 생성한다. 사용자가 명시한 설정
  경로는 자동 생성하거나 덮어쓰지 않는다.
- 프로젝트별 기획 문서 디렉터리 선택은 registry JSON에만 저장하며 기획 디렉터리
  자체에는 파일을 만들지 않는다.
- Planning 결과 캐시는 설정된 로컬 `state_dir/planning-cache/`에만 저장한다.
  clean 저장소의 정확히 같은 입력만 재사용하며, 대상 기획 디렉터리나 다른 저장소에는
  캐시 파일을 만들지 않는다.
- `start`, `status`는 원격 저장소나 배포 환경을 변경하지 않는다.
- 데스크톱 `최신 받기`는 native 확인 후 clean main worktree에서만
  `git pull --ff-only`를 실행한다.
- `execute`는 계획 당시 base commit에서 Run 전용 local branch와 공유 worktree를
  만들고 Task를 순차 실행한다. Task 완료 전에는 task별 검증 명령을 같은 worktree에서
  실행하고 결과를 Task별 commit으로 남긴다.
- `verify`는 Main을 변경하지 않고 최신 로컬 Main을 공유 작업 branch에 통합한 뒤
  공유 worktree에서 전체 검증을 실행한다.
- 데스크톱 `작업 그룹 삭제`는 native 확인 후 해당 run의 deterministic local
  worktree·branch와 run 기록을 제거할 수 있다. Main과 remote는 변경하지 않는다.
  Git 등록이 먼저 사라진 잔여 worktree는 현재 저장소의 worktree marker 또는 같은
  경로의 이전 제거 실패 기록으로 소유권을 확인한 경우에 정리한다. marker가 이미
  사라졌다면 빈 경로 또는 설정된 관리 `state_dir`만 남은 경로까지 정리할 수 있다.
  Windows에서 IDE·터미널·Explorer가 짧게 파일 핸들을 유지하면 잔여 경로 삭제를
  제한적으로 재시도한다. 공유 잠금이 계속되면 Run 기록을 보존하고, 표시된 경로를
  해당 프로그램에서 닫은 뒤 같은 작업 그룹 삭제를 다시 시도한다.
- `push`는 검증한 공유 작업 branch를 원격에 Push한 뒤 정확한 원격 branch ref를 다시
  조회한다. 이후 `merge`는 같은 commit을 Main에 fast-forward하고 Main을 Push한 뒤
  원격 Main ref를 확인하고 local 공유 worktree와 branch를 정리한다. 의도한 commit과
  확인한 원격 commit이 다르면 성공 단계로 전이하지 않으며, 일치한 Push 결과는 Run
  상태에 대상 branch, 로컬·원격 commit, 요청 ID와 완료 시각으로 보존한다.
  두 작업과 `deploy`는 각각 `--approve`가 있어야 실행한다.
- `verify`는 프로젝트 공통 검증 명령을 우선하고, 없으면 계획된 Task별 검증 명령을
  중복 제거해 격리된 통합 worktree에서 실행하므로 명령의 쓰기 범위를 사전에 확인한다.
- 작업 branch Push, Main 반영·Main Push와 deploy를 자동 승인하거나 하나의 암묵적
  단계로 합치지 않는다.

## 변경 전후 확인

- 변경 전: 현재 branch, clean 여부, 적용 대상 저장소 root를 확인한다.
- 변경 중: 계획된 모듈 경계와 상태 전이 범위를 유지한다.
- 변경 후: `AGENTS.md`의 검증 기준을 적용한다. 문서만 바꾼 경우는 내용·참조·diff를
  확인하고, 코드 변경은 가장 작은 관련 테스트부터 시작해 영향 범위에 따라 넓힌다.
- 검증하지 못한 외부 에이전트, 원격 push, 실제 deploy 범위는 완료 보고에 남긴다.

## 커밋·push 전 개인정보·내부 정보 제거

- 저장소의 공개 여부와 관계없이 커밋·push 전에 개인정보와 불필요한 회사·내부 프로젝트 식별정보를 제거하거나 공개 가능한 예시로 바꾼다. 코드·문서·주석·예제·제작 기록·manifest와 전송할 압축/배포 산출물에 같은 기준을 적용한다.
- 실명, 회사 이메일, PC 이름·OS 사용자명, 개인 절대 경로, 사내 IP·도메인·서비스 주소와 비밀정보를 점검한다. 기능에 필요한 로컬 환경값은 환경 변수나 Git에서 제외한 개인 설정으로 분리하고, 공유 문서에는 상대 경로·자리표시자·일반 예시를 사용한다.
- 커밋 작성자·커미터는 공개용 닉네임과 GitHub noreply 이메일을 사용한다. 다른 커밋 규약의 ‘실제 작성자’ 표기도 이 개인정보 보호 기준에 맞는 공개용 닉네임으로 해석한다.
- 현재 파일과 staged diff뿐 아니라 원격에 보낼 전체 커밋의 내용·메타데이터, 함께 전송할 브랜치·태그와 산출물을 확인한다. 발견 항목을 제거·익명화하고 재검증을 통과한 뒤 승인된 커밋·push를 수행한다. 미확인 항목은 검증 완료로 처리하지 않는다.
- 인증 파일·`.env`·키·비밀번호·토큰 원문을 직접 읽거나 출력하지 않는다. 해당 파일의 추적 여부와 제외 상태를 확인하고, 점검 보고서·커밋 메시지에도 비밀 원문을 복사하지 않는다.
- 현재 파일 삭제나 `.gitignore` 추가만으로 과거 이력이 제거되지는 않는다. 이미 게시된 정보의 이력 재작성·강제 push·저장소 삭제/재생성은 그 작업이 명시적으로 승인된 범위에서만 수행한다. 보존할 로컬 원본과 다른 작업자의 변경은 임의 삭제하지 않는다.
- 이 규칙은 승인된 커밋·push의 필수 준비 순서이며 자동 커밋·push·공개 전환 승인을 추가하지 않는다.
