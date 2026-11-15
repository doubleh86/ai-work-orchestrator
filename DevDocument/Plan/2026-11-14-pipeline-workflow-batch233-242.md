# 공급자 명령 구성·가용성 판정: 233~242단계

## 목표와 범위

기존 10단계 묶음 승인에 따라 233~242단계를 수행한다. 시작 Pipeline은 5,970줄이다.
모델/작업 명령 선택·추론 강도/Claude 세션 인자 구성과 Agent 가용성 판정을 실행 모듈로 분리한다.
공개/기존 private API·설정/저장·RPC 계약과 실제 실행·승인/잠금·Run 전이를 보존한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 233 | 모델/작업 명령 구성 계약 정의 | 완료 |
| 234 | 공급자별 모델 override와 execute/review 명령 선택 분리 | 완료 |
| 235 | 기존 모델 인자/수동 NVIDIA 명령과 오류 보존 확인 | 완료 |
| 236 | 추론 강도/Claude 세션 인자 계약 정의 | 완료 |
| 237 | 검증 callback·중복 인자 제거·세션 소유권/UUID 검사 분리 | 완료 |
| 238 | 강도 검증/실제 호출 전달·세션 시작/재개 경계 확인 | 완료 |
| 239 | Agent 가용성의 좁은 조회 계약 정의 | 완료 |
| 240 | SDK/키 존재 bool·명령/실행 파일 callback으로 가용성/필수 Agent 검사 분리 | 완료 |
| 241 | SDK/설정 변경·실행 파일 부재·custom/수동 후보 보존 확인 | 완료 |
| 242 | 본문/호출 순서·서명/의존 방향·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 파일

- `execution.provider_commands`에 상태/수명이 없는 명령 구성 함수를 둔다. 기존 공급자 분기·
  인자 순서·오류를 보존한다. 추론 강도 검증은 기존 classmethod의 callback을 받아 override를 유지한다.
- `execution.provider_choices`의 가용성 서비스는 Agent 조회, SDK 준비 여부/키 존재 여부 bool,
  작업 명령/실행 파일 해석 callback만 받는다. SDK/인증키/환경 조회 자체는 Pipeline에 남긴다.
  선택 제외 공급자 정책과 기존 동적 private 호출은 Pipeline이 유지한다.
- `pipeline.py`, 위 실행 모듈·아키텍처/계획과 직접 관련 검사만 다룬다. 실제 provider 실행과
  SDK/프로세스/인증키 수명, 사용량/연결 상태 조회, 승인·잠금·Run 단계는 변경하지 않는다.
- 기존 미커밋 변경을 보존한다. 실제 외부 AI/계정/화면·다른 저장소/Rust/공개 checkout 및
  사용자 저장소의 commit/merge/push/deploy는 실행하지 않는다.

## 검증

이동 전 snapshot AST로 명령 구성/오류·검증/조회 순서와 callback 결선을 대조한다. 기존 메서드의
서명/데코레이터와 범위 밖 구현을 보존하고 변경 Python 구문·전역 참조·150자/공백·diff 및
공개 계약/모델/RPC·의존 관계를 확인한다. 기존 모델/강도/세션·SDK/NVIDIA/명령 부재와 후보 조회
관련 사례만 선택한다. 기존 검사로 충분하면 새 테스트를 추가하지 않고 통과 후 종료한다.
전체 테스트·renderer·빌드/패키징은 이번 분리의 기본 검증에 포함하지 않는다.

## 진행과 결과

- 기존 구조/호출부/선택 관련 테스트와 정책 문서를 확인했다. 구현 전 계약과 범위를 기록했다.

### 233~235단계: 모델/작업 명령

- `execution.provider_commands`에 작업/리뷰 명령 선택과 공급자별 모델 인자 구성을 옮겼다.
  기존 NVIDIA 모델/명령, SDK Codex 처리와 Claude 모델 인자 교체·오류 조건을 보존했다.
- Pipeline의 기존 static 진입점과 기획용 전달 함수를 유지했다. 기존 함수 본문 전체를 snapshot
  AST로 대조했고 모델/명시적 NVIDIA 명령 사례가 통과했다. 새 추상 클래스나 상태는 만들지 않았다.

### 236~238단계: 강도/Claude 세션 인자

- 같은 모듈에 추론 강도와 Claude 세션 인자 구성을 옮겼다. 빈 강도 조기 반환·기존 classmethod
  검증 callback·공급자 분기와 인자 제거/삽입 순서, UUID와 세션 플래그 소유권 오류를 보존했다.
- 기존 강도/Claude 세션 사례로 시작/재개 명령과 실제 호출에 전달되는 인자를 확인했다. 실제
  provider/SDK 호출과 세션 정리는 옮기지 않았고 본문·오류·검증 순서는 snapshot AST로 대조했다.

### 239~241단계: Agent 가용성

- 기존 `execution.provider_choices`에 `ProviderAvailability`를 추가했다. 전체 Config/Store/SDK나
  인증키 대신 Agent 조회·SDK/키 준비 여부 bool·명령 선택/실행 파일 해석 callback만 받는다.
  키 존재 확인은 기존 단락 평가 시점에 Pipeline callback이 수행한다.
- 사용 가능 여부와 필수 Agent 조회의 분기/오류를 옮겼다. 선택 제외 공급자 정책과 기존 동적
  private 호출은 그대로 유지했다. SDK 부재/CLI 불필요, 키 제거·재연결과 실행 파일 부재,
  custom 후보 및 수동 NVIDIA 설정 보존 사례가 통과했다. 저장/배정·연결 상태 조회는 변경하지 않았다.

### 242단계: 묶음 종료

- `.venv/Scripts/python.exe -m py_compile`로 변경 Python 3개를 확인했다.
- `.venv/Scripts/python.exe -m pytest -q`로 다음 기존 10개 node ID만 선택했다.
  `--basetemp=.tmp/pytest-batch233-242 --junitxml=.tmp/batch233-242-tests.xml`을 사용했고
  **10 passed, 8 subtests passed (2.98초)**였다. 기존 fixture/mock만 사용했고 실제 AI는 호출하지 않았다.
  - `tests/test_pipeline.py::PipelineTest::test_planning_model_override_normalizes_provider_commands`
  - `tests/test_pipeline.py::PipelineTest::test_reasoning_override_normalizes_provider_commands`
  - `tests/test_pipeline.py::PipelineTest::test_claude_planning_session_flags_are_orchestrator_owned`
  - `tests/test_nvidia_agent.py::test_trial_profile_is_available_only_after_setup_and_never_changes_default`
  - `tests/test_nvidia_agent.py::test_command_uses_explicit_provider_model_and_disables_plugins`
  - `tests/test_pipeline.py::PipelineTest::test_sdk_marks_codex_provider_available_without_external_cli`
  - `tests/test_pipeline.py::PipelineTest::test_sdk_unavailable_stops_planning_without_schema_retry_and_preserves_cause`
  - `tests/test_connected_provider_choices.py::test_reconnection_and_key_removal_change_choices_without_reassigning_configuration`
  - `tests/test_connected_provider_choices.py::test_missing_nvidia_cli_hides_key_configured_profiles`
  - `tests/test_connected_provider_choices.py::test_custom_provider_keeps_eligible_agents_when_another_custom_agent_is_missing`
- `.tmp/check_batch233_242.py`로 이동 전 snapshot과 전체 본문·오류/검증·lazy 조회/결선을 대조했다.
  기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 423개, 기존 provider choice 선언이 같다.
  변경 전역 참조·150자/공백과 좁은 callback·기존 NVIDIA import 별칭도 확인했다. 검사 스크립트의
  반환 주석 없는 서명 처리 한 곳을 보정한 뒤 정적 검사만 다시 실행했고 제품 코드는 추가 수정하지 않았다.
- `.tmp/check_stage27.py`로 공개 Pipeline 112개·Store 91개·응용 API 121개 서명, 모델 80개와
  기존 오류/모델/기획 import·RPC 122개 경로를 확인했다. 코어 171개 모듈 import 선언에 순환이나
  기능 역참조가 없다. `git diff --check`와 변경 문서의 참조/완료 기록도 확인했다.
- Pipeline은 **5,970 → 5,879줄(91줄 감소)**이다. 기존 미커밋 변경을 보존했고 다음 단계는 시작하지 않았다.
  새 테스트나 기존 테스트/기대값 변경은 없다. 통과한 검사는 문서 정리를 위해 반복하지 않았다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 이번 분리의 확인에 필요하지 않아 실행하지 않았다.
