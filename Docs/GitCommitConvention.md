# Git Commit Convention

AI Work Orchestrator 저장소에 적용할 기본 커밋 메시지 기준이다.

## 기본 형식

```text
[AI Orchestrator, 담당자] - 작업 내용
```

예시:

```text
[AI Orchestrator, 홍길동] - 실행 상태 전이 검증 추가
```

## 자동 작업 브랜치

오케스트레이터가 Run 공유 worktree에서 Task별로 자동 생성하는 커밋은 현재 런타임 형식을
사용한다.

```text
feat(<task-id>): <task-title>
```

통합 검증 전에 최신 Main을 공유 작업 branch에 동기화하면서 merge commit이 필요한
경우에는 다음 형식을 사용한다.

```text
merge(<run-id>): synchronize main before verification
```

검증된 작업 branch와 Main은 원격 Push 전 별도 승인을 받는다. Main 반영은 검증한
공유 작업 commit으로 fast-forward하므로 별도 merge commit을 만들지 않는다.

## 커밋 범위

- 작업 범위 밖의 기존 변경 사항은 커밋에 섞지 않는다.
- 생성물, 로그, 실행 상태, worktree, 로컬 비밀 정보는 커밋하지 않는다.
- 규칙 문서 변경과 기능 코드는 가능하면 별도 커밋으로 나눈다.
- 공개 CLI나 상태 JSON 계약 변경은 커밋 메시지 또는 본문에 호환성 영향을 기록한다.
