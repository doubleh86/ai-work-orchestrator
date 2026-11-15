# 외부 기획 입력·초기 상태·저장소 기획 문맥: 183~192단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 183~192단계를 수행한다. 시작 Pipeline은 6,271줄이다.
기획 초기화의 입력·초기 상태와 저장소 문맥 구성을 분리한다. 기존 미커밋 변경과 공개 API·
저장/CLI/RPC, 승인·잠금·기준 commit 검사·SDK/정책 수명·최종 Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 183 | 외부 기획 입력 검증 계약 정의 | 완료 |
| 184 | ID/정규화/크기·동일 digest 구성 분리 | 완료 |
| 185 | 유효 입력·중복/충돌 제출·잘못된 입력 관련 확인 | 완료 |
| 186 | 외부 기획 초기 상태 구성 계약 정의 | 완료 |
| 187 | 저장소/스타일·공유 작업공간·초기 대화/사용자 확인 구성 분리 | 완료 |
| 188 | 초기 상태/확인 계획·기준 commit 보호 확인 | 완료 |
| 189 | 일반 기획의 저장소 문맥 계약 정의 | 완료 |
| 190 | 성숙도/명시적 의도 검사·스타일 snapshot 구성 분리 | 완료 |
| 191 | 모호한/문서 전용 저장소·스타일 문맥 보존 확인 | 완료 |
| 192 | 본문/순서·공개 계약·의존 관계·diff 및 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `planning.initialization`의 순수 함수가 기존 외부 기획 ID/본문/Task 수/크기와 digest를 확인하고
  정규화한 제목/요구사항·digest를 반환한다. 저장과 잠금·실행 권한은 갖지 않는다.
- 저장소 문맥 서비스는 명시적 repo 경로와 성숙도/스타일 조회 callback만 받는다. 외부 기획의
  초기 RunState 구성에서는 기존 main branch/작업공간 조회도 좁은 callback으로 받는다.
  callback을 호출하는 순서와 초기 상태/공유 작업공간·대화/사용자 확인 필드를 유지한다.
- 일반 기획은 명시적 저장소 의도에 따른 성숙도 검사와 코드 스타일 snapshot·초기 기획 의도/
  phase를 구성한다. 최초 단계 기록·문서/상태 저장·effort 초기화와 최종 전이는 Pipeline에 남긴다.
- 외부 제출의 chat 잠금·같은 ID 재생/충돌, 기준 commit의 양쪽 재확인·Task 검증·검증 정책과
  최종 단계/초기화는 Pipeline에 유지한다. 전체 Pipeline/Store/Config를 전달하지 않는다.
- `pipeline.py`, 위 모듈·아키텍처/계획과 직접 관련 테스트만 다룬다. 실제 외부 AI/계정/화면·다른
  저장소/Rust/공개 checkout 및 사용자 저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 검증/digest/초기 상태 필드와 callback·잠금/기준 commit·검사/저장/전이
순서를 대조한다. 변경 Python의 구문·전역 참조·150자/공백·diff 및 공개 계약/모델/RPC/의존
관계를 확인한다. 기존 외부 기획 제출/중복·실패와 사용자 확인, 일반 기획의 저장소/스타일 관련
case만 선택한다. 충분하면 테스트를 추가하지 않는다. 전체 테스트·renderer·빌드/패키징을
실행하지 않고 필요한 검사 통과 후 종료한다.

## 진행과 결과

### 183~185단계: 외부 입력과 digest

- `planning.initialization.external_plan_input`으로 기존 ID/제목/요구사항/Task 수·크기 검증과
  사용자 확인을 포함하는 canonical JSON/digest 구성을 옮겼다. 정규화한 제목/요구사항·digest를
  반환하고 Pipeline의 chat 잠금·같은 ID 재생/충돌 검사는 그대로 유지한다.
- 선택한 MCP case에서 유효/잘못된 Task 제출·중복/다른 내용 제출과 기준 commit 변경을 확인했다.
  ID·제목/본문·Task 수/크기 조건과 digest 전체 본문은 snapshot AST로도 같음을 확인했다.

### 186~188단계: 외부 기획 초기 상태

- `PlanningRepositoryContext.external`로 기존 성숙도 검사와 초기 RunState 필드를 옮겼다.
  main branch·작업공간·스타일 snapshot은 좁은 callback으로 원래 평가 시점에 조회한다.
  공유 작업공간·directed mode·대화 revision/요구사항·사용자 확인과 digest 필드가 동일하다.
- 기획 AI 없이 빈 프로젝트에 외부 계획을 제출하고 사용자 검토를 기다리는 상태, MCP 제출의
  app 승인/기준 commit 보호, 사용자 확인과 Task/통합 의존성 보존 case가 통과했다.
  양쪽 기준 commit 검사·Task/정책 검증과 최종 Run/문서/effort 초기화 순서는 Pipeline에 남겼다.

### 189~191단계: 일반 기획의 저장소 문맥

- `PlanningRepositoryContext.apply`로 명시적 의도에 따른 모호한/문서 전용 저장소 검사·성숙도/
  코드 스타일 snapshot과 신규 프로젝트 초기 phase 구성을 옮겼다. 스타일/설정 조회 callback은
  외부 기획과 공유하되 각 원래 위치에서 실행한다. 이후 단계/문서/상태 저장과 전이는 Pipeline이 유지한다.
- 문서 전용 저장소의 기술 결정 gate, 모호한 저장소의 명시적 선택 요구, 고정된 스타일 snapshot과
  revision이 작업/리뷰 prompt 및 복원 모델까지 유지되는 case가 통과했다.

### 192단계: 묶음 종료

- 다음 기존 case 여섯 개만 선택했다. 직접 경로 다섯 개는 **5 passed**(18.94초), MCP 전달 한 개는
  **1 passed**(2.99초)로 총 **6개 통과**다. 새 테스트나 기존 테스트/기대값 변경은 없다.
  - `tests/test_maker_workflow.py::test_empty_project_accepts_external_plan_without_planning_ai_and_rejects_stale_control`
  - `tests/test_mcp_operations.py::test_external_plan_submission_is_scoped_replayable_and_requires_app_approval`
  - `tests/test_user_checks.py::test_user_checks_gate_only_their_dependents_and_integration`
  - `tests/test_pipeline.py::PipelineTest::test_docs_only_planning_records_greenfield_gate_without_creating_tasks`
  - `tests/test_pipeline.py::PipelineTest::test_ambiguous_repository_requires_explicit_intent_for_desktop_planning`
  - `tests/test_pipeline.py::PipelineTest::test_run_fixes_code_style_snapshot_for_worker_and_reviewer_prompts`
- 최초 묶음은 MCP case의 Windows 비동기 루프 초기화에서 대기해 중단했다. 출력/stack을 켠
  한정 진단에서 테스트 시나리오 진입 전 `asyncio`의 `_fallback_socketpair`/`socket.accept` 대기를
  확인했다. 도구 승인 절차로 이 case만 sandbox 밖에서 통과했으며 나머지 다섯 개는 sandbox에서
  따로 확인했다. MCP는 프로세스 내부 memory 연결과 임시 저장소를 사용했고 실제 외부 AI/원격은 호출하지 않았다.
- snapshot AST로 입력/digest·초기 상태 전체와 callback 평가·chat 잠금/재생·양쪽 기준 commit·
  검사/저장/전이 순서를 대조했다. 기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 424개가
  그대로다. 좁은 저장소 문맥 factory 하나만 추가했고 새 모듈에 전체 소유 객체/최종 전이를 주지 않았다.
- 변경 Python 2개의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로가 유지된다.
  코어 164개 모듈 import 선언에 순환/기능 역참조가 없다. 기존 `pipeline.RepositoryMaturityKind`
  import도 명시적 별칭으로 유지하고 같은 enum 객체인지 확인했다.
- Pipeline은 **6,271 → 6,249줄(22줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  통과한 검사는 문서 정리를 위해 반복하지 않았다. 전체 테스트·renderer·빌드/패키징·실제 AI/
  계정/화면·다른 저장소/Rust/공개 checkout 및 사용자 저장소의 commit/merge/push/deploy는 실행하지 않았다.
