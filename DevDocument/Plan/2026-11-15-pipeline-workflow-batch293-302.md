# Pipeline 리팩터링 최종 정리: 293~302단계

이 문서는 기능 규칙 분리의 당시 완료 기록이다. 이후 사용자의 추가 요청에 따른
[Pipeline 자체의 축소](2026-11-15-pipeline-facade-reduction.md)는 별도 범위이며 아래 수치/검증을 소급해 바꾸지 않는다.

## 목표와 종료 범위

사용자가 남은 단계와 다음 작업을 요청했다. **이번 293~302단계를 마지막 묶음으로 잡고,
확인된 결함이 없으면 302단계에서 이번 Python 리팩터링을 종료한다.** 새 후보를 자동으로 추가하지 않는다.
시작 Pipeline은 5,636줄·433개 메서드다. 256개는 8줄 이하의 진입점/위임이며 가장 긴 메서드는
최종 상태 전이와 오류 복구를 소유하는 `_step` 94줄이다. 파일 길이 자체는 종료 조건이 아니다.

기존 [1~28단계](2026-11-13-python-module-refactoring.md)와
[29~32단계](2026-11-14-application-state-settings-refactoring.md)는 완료 기록이다.
33~292단계의 흐름별 계획 26개/260개 항목도 누락 없이 완료 상태임을 확인했다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 293 | 기존 묶음 완료/누락과 현재 Pipeline 구성 계측 | 완료 |
| 294 | 유지할 조정 책임과 선택적 후보 구분 | 완료 |
| 295 | 마지막 묶음/302 종료 기준 확정 | 완료 |
| 296 | 남은 기획 반영 입력 검증의 소유 모듈/호환 계약 정의 | 완료 |
| 297 | request ID·기술 구성/기획 반영 재전달 검증을 기존 모듈에 모으기 | 완료 |
| 298 | 기존 stale/재전달·실패/답변 보존 관련 사례 확인 | 완료 |
| 299 | 변경 본문/호출·기존 공개/내부 서명/모델·RPC 보존 확인 | 완료 |
| 300 | 전역 참조·의존 방향/순환·diff 확인 | 완료 |
| 301 | 아키텍처/최초 계획에서 최신 종료 기록으로 연결 | 완료 |
| 302 | 구현/국소 검증·남은 책임/미수행 범위 확정 후 종료 | 완료 |

## 유지할 책임과 종료 기준

| 영역 | Pipeline에 남기는 근거 | 대표 진입점 |
|---|---|---|
| 승인·잠금·최종 Run 전이/복구 | 하나의 소유자가 순서/권한을 보장해야 한다 | `_step`, `_execute`, `archive_run`, `delete_run`, merge/push/deploy |
| 정책 binding·SDK/프로세스·사용량/credential 수명 | 실제 실행 전에 최종 검증과 실패/취소를 조정한다 | `_begin_effort_execution`, `_planning_effort_scope`, provider/Planning 호출 |
| 기능 모듈 조합·호환 진입점 | 기존 CLI/application/RPC/MCP 호출 계약을 유지한다 | `prepare_planning`, 계획 반영/미리보기, `recover_main_apply` |

- 기획/실행/통합/저장/알림·응용/RPC 책임이 해당 모듈의 공개 API로 협력하고, 전체 Pipeline/
  Store/Config 역참조·순환 의존 없이 기존 승인/잠금·Run/SDK/Git 소유권을 유지하면 구조 조건을 충족한다.
- 마지막 코드 범위는 기획 반영의 순수 입력/재전달 검증 네 개다. 기존 `planning.apply_requests`로
  모으되 Root static 진입점과 모든 오류/분기·호출 시점을 그대로 보존한다. 새 모듈/추상화는 만들지 않는다.
- 변경된 부분의 구문/본문·공개 계약/의존 관계와 관련 기존 검사가 통과하고 확인된 필수 결함이 없으면 종료한다.
  줄 수/메서드 수를 맞추기 위한 위임 삭제·mixin·추가 callback 계층/빈 모듈은 만들지 않는다.
- 짧은 조회/표시 조합의 추가 이동은 선택적 개선이다. 현재 동작 결함이나 경계 위반이 확인되지 않은
  후보를 추가 필수 단계로 만들지 않는다. 기능 변경/새 결함 수정은 이후 별도 요청 범위다.

## 영향 파일과 검증

- `pipeline.py`, `planning/apply_requests.py`, 이 계획·최초 리팩터링 계획·`Docs/Architecture.md`만 수정한다.
  기존 미커밋 변경과 공개/저장/오류 계약을 보존한다.
- 이동 전 snapshot AST로 네 검증 함수와 범위 밖 메서드/기존 모듈 선언·서명/데코레이터를 대조한다.
  변경 Python 구문·전역 참조/150자/공백·diff와 API/모델/RPC·의존 관계를 확인한다.
- 기존 기획 반영 revision/재전달·실패 기록과 기술 질문의 stale/실패 후 재전달·구성 확정 사례만 선택한다.
  이전 묶음의 통과 증거를 재사용하며 새 테스트/전체 테스트·renderer·빌드/패키징을 기본 실행하지 않는다.
- 실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자 저장소의 commit/merge/push/deploy는
  이번 코드 완료와 구분하며 수행하지 않는다. 이 확인들을 미완료 리팩터링 단계로 세지 않는다.

## 진행과 결과

- 기존 계획과 현재 코드 구성/의존 기준을 확인해 종료 범위를 확정했다. 큰 조정 함수를 다른 객체에
  그대로 넘기면 권한 경계를 흐리므로 유지하고, 마지막 순수 입력 검증만 기존 소유 모듈로 정리한다.

### 293~295단계: 종료 범위

- 이전 1~32단계 완료 기록과 33~292단계의 26개 계획/260개 표 항목에 누락·미완료 단계가 없음을
  확인했다. 현재 코드와 최초 아키텍처의 허용 책임을 대조해 위 표의 조정/수명/호환 진입점은 유지한다.
- 마지막 코드 정리와 국소 검증·최신 문서 연결 후 302단계에서 종료하기로 확정했다. 큰 함수의
  본문 전체를 다른 객체로 넘기거나 단순 표시/짧은 위임까지 추가로 분리하는 후속 단계는 만들지 않았다.

### 296~298단계: 마지막 입력 검증 정리

- 기존 `planning.apply_requests`에 `normalize_planning_apply_request_id`, `validate_tech_stack_apply`,
  `validate_tech_stack_apply_replay`, `validate_planning_apply_replay`를 모았다. 기존 Root static
  서명/호출 지점과 모든 검증 본문·반환/오류·None/0 의미를 그대로 보존했다.
- 새 모듈/owner/callback 계층이나 테스트/기대값 변경 없이 기존 request ID와 revision/대화 재전달,
  실패 후 답변 보존·stale 후보/질문 거부와 구성 확정 사례를 확인했다.
- `.venv/Scripts/python.exe -m py_compile`로 변경 Python 2개를 확인했다.
- `.venv/Scripts/python.exe -m pytest -q`에 다음 기존 5개 node ID를 선택하고
  `--basetemp=.tmp/pytest-batch293-302 --junitxml=.tmp/batch293-302-tests.xml`을 사용했다.
  **5 passed, 3 subtests passed (3.87초)**였다. 기존 임시 저장소/fixture/mock만 사용했다.
  - `tests/test_pipeline.py::PipelineTest::test_planning_apply_request_is_revision_safe_and_idempotent`
  - `tests/test_pipeline.py::PipelineTest::test_planning_apply_failure_preserves_tasks_and_receipt`
  - `tests/test_pipeline.py::PipelineTest::test_greenfield_answer_failure_preserves_answer_and_retries_without_appending_twice`
  - `tests/test_pipeline.py::PipelineTest::test_greenfield_answer_rejects_stale_candidate_plan_or_discussion_without_saving`
  - `tests/test_pipeline.py::PipelineTest::test_greenfield_choice_questions_allow_direct_confirmation_without_new_run_or_tasks`

### 299~301단계: 계약과 문서 연결

- `.tmp/check_batch293_302.py`로 이동 전 snapshot과 네 검증 본문/오류·인자/반환과 Root 결선을
  대조했다. 기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 429개·기존 반영 모듈 선언은 같다.
  변경 전역 참조·150자/공백과 순수 검증 소유권도 확인했다.
- `.tmp/check_stage27.py`로 공개 Pipeline 112개·Store 91개·응용 API 121개 서명, 모델 80개와
  기존 오류/모델/기획 import·RPC 122개 경로를 확인했다. 코어 174개 모듈 import 선언에 순환이나
  기능 역참조가 없다. 앞선 묶음의 검증은 반복하지 않고 해당 변경에 적용되는 통과 증거를 유지했다.
- `Docs/Architecture.md`에 검증 소유 모듈과 302단계 종료를 명시했다. 최초 계획의 9,219줄은
  당시 값으로 분명히 하고 최신 5,620줄/종료 기록을 연결했다. 이전 완료 기록은 삭제하지 않았다.
- `git diff --check`와 변경 문서의 참조/완료 항목·계측값을 확인했다.

### 302단계: 종료 결과

**이번 Python 모듈/흐름 리팩터링의 구현과 국소 검증을 완료했다. 추가 필수 리팩터링 단계는 없다.**
확인한 범위에 미해결 필수 결함을 남기지 않았고 선택적 분리 후보를 다음 자동 단계로 만들지 않는다.

- 마지막 묶음 Pipeline은 **5,636 → 5,620줄(16줄 감소)**이다. 최종 433개 메서드 중 257개는
  8줄 이하이며 가장 긴 `_step`은 94줄이다. 최초 계획의 시작값 14,517줄 대비 8,897줄 감소했다.
- 앞서 정의한 승인·잠금·최종 상태 전이/복구와 정책/SDK/Git 수명, 호환 진입점은 의도적으로 유지한다.
  단순히 파일이 길다는 이유로 새로운 owner/서비스/mixin·필수 단계를 추가하지 않는다.
- 기존 미커밋 변경을 보존했고 새 브랜치/커밋·push는 만들지 않았다. 문서 마무리를 이유로 통과한
  테스트나 과거 전체 검사를 다시 실행하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/제품 화면·다른 저장소/Rust·릴리스/공개 checkout과
  commit/merge/push/deploy는 이번 코드 완료의 증거가 아니며 실행하지 않았다. 해당 작업이 필요하면
  별도 요청 범위로 진행하며, 남은 리팩터링 단계로 세지 않는다.
