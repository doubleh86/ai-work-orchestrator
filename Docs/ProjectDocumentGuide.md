# 프로젝트 문서 안내

AI Work Orchestrator 작업자가 먼저 확인할 문서를 안내한다.

## 먼저 볼 문서

- 작업 시작: `AGENTS.md`, 있으면 로컬 참고용 `AGENTS.local.md`
- 코드 작업: `Docs/CodeStyle.md`
- 모듈 구조와 의존 방향: `Docs/Architecture.md`
- Git·worktree 운영: `Docs/RepositoryWorkflow.md`; 커밋 요청 시 `Docs/GitCommitConvention.md`
- 계획 문서 필요 여부와 구현·검증 기록: `DevDocument/Plan/README.md`
- 프로젝트 최종 목표와 단계별 로드맵: `DevDocument/Plan/2026-08-25-target-orchestrator-roadmap.md`
- 설치, 설정, CLI 실행: `README.md`

## 빠른 참조

| 작업 범위 | 코드 | 먼저 읽을 문서 |
|---|---|---|
| 사용자 흐름·화면·사용성 제보 | `desktop/renderer/` | `README.md`, `Docs/Architecture.md` |
| 기획을 구현 계약으로 구체화 | 해당 기능의 Python 코어·renderer | `Docs/Architecture.md`, [코드 작업 계획](../DevDocument/Plan/README.md) |
| CLI 명령과 출력 | `src/ai_orchestrator/cli.py` | `README.md`, `Docs/Architecture.md` |
| 단계 전이와 실행 조정 | `src/ai_orchestrator/pipeline.py` | `Docs/Architecture.md`, 계획 문서 |
| 명세 파싱과 에이전트 배정 | `src/ai_orchestrator/planner.py` | `Docs/Architecture.md` |
| Git과 외부 명령 | `src/ai_orchestrator/git.py` | `Docs/RepositoryWorkflow.md` |
| 상태 모델과 저장 | `src/ai_orchestrator/models.py`, `store.py` | `Docs/Architecture.md` |
| TOML 설정 | `src/ai_orchestrator/config.py` | `README.md` |
| 커밋 메시지 | Git history | `Docs/GitCommitConvention.md` |

관련 문서의 필요한 절만 읽고 이미 확인한 내용은 재사용한다. 두 영역에 걸친 작업은
각 영역의 계약을 확인한다. 문서와 실제 동작이 다르면 `AGENTS.md`의 판단 기준을 따른다.
요청과 근거가 명확한 버그·낡은 설명은 수정하고 차이를 보고하며, 의도나 호환 계약을
확정할 수 없는 부분만 사용자에게 질문한다.
