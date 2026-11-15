# Pipeline 진입점과 실행 호출 경계 축소

## 목표와 범위

사용자가 5,620줄의 Pipeline도 더 줄여야 한다고 요청했다. 앞선 302단계는 기능별 규칙 분리의
완료 기록으로 유지하고, 이번에는 중복 호출 어댑터와 호환 위임의 구현을 줄인다. 작은 항목에
연속 단계 번호를 붙이지 않고 아래 두 책임 단위를 한 묶음으로 처리한다.

1. 공급자 호출의 usage/tool lease 경계와 실제 transport 전달/오류 변환을 `execution.provider_runtime`으로
   모은다. Pipeline에는 기존 자원으로 invocation/runner를 만드는 좁은 factory만 남긴다.
2. 인자·기본값·반환 타입이 소유 함수와 같고 모든 인자를 그대로 전달하는 private static 위임을
   기존 함수의 명시적 static 별칭으로 바꾼다. 공개 메서드와 실제 조건/규칙을 가진 함수는 유지한다.

초기 측정은 Pipeline 5,620줄/직접 정의 메서드 433개다. 파일 분할만을 위한 mixin·상속/동적
`__getattr__`/DI 컨테이너나 전체 Pipeline/Store를 넘기는 context는 만들지 않는다.

## 계약과 소유권

- `ProviderRuntime`은 invocation/runner factory와 기존 오류 변환 callback만 받는다. Config/Store/
  Git/SDK·인증키를 보유하거나 새 수명을 만들지 않는다. 실제 사용량/도구 lease와 transport는
  기존 `ProviderInvocation`/`ProviderRunner`가 동일하게 수행한다.
- factory는 실제 호출 시점에 실행한다. 현재 설정/SDK/인증키와 실행 파일·취소/진행/사용량
  callback을 기존 순서로 전달하고 자원 구성 실패와 transport 실패의 예외 경계도 유지한다.
- `_invoke_provider_command`/`_run_provider_command`는 instance의 명시적 bound callable로 연결한다.
  호출의 인자/기본값과 instance hook 대체는 보존한다. 내부 메서드 두 개의 class-level 정의는
  runtime으로 이동하며 공개 Pipeline API·CLI/RPC/MCP와 저장 형식은 바꾸지 않는다.
- private static 별칭은 signature와 전달 인자 전체를 대조한 경우만 적용한다. 변환/검증·기본값
  보정·정책/자원 수명을 가진 메서드는 이 규칙으로 옮기지 않는다.
- 승인·잠금·최종 Run 전이, 정책 binding·SDK/프로세스 수명과 실제 Git 부작용은 기존 소유자에 유지한다.

## 영향 파일과 검증

- `pipeline.py`, 새 `execution/provider_runtime.py`, 아키텍처·이 계획과 앞선 종료 기록의 후속 링크만 수정한다.
  기존 다른 변경을 보존한다. 다른 저장소/Rust/공개 checkout·실제 AI/계정/화면·commit/push/deploy는 다루지 않는다.
- 이동 전 snapshot으로 호출 인자/기본값·오류/원인·factory 실행 시점과 모든 범위 밖 메서드를
  대조한다. static 별칭은 실제 함수 signature 및 기존 본문의 인자 전달이 일치하는지 확인한다.
- 기존 provider 오류/SDK·사용량과 instance transport 대체 관련 사례만 선택한다. 기존 검사가
  새 lazy factory/override 경계를 다루지 못할 때만 해당 사례를 추가한다. 구문·전역 참조/변경 줄
  길이·diff와 공개 API/모델/RPC·의존 관계를 확인하고 필요한 검사가 통과하면 종료한다.
- 전체 테스트·renderer·빌드/패키징과 기존 묶음의 재검증은 기본 실행하지 않는다.

## 진행과 결과

- public API를 제외한 동일 signature의 순수 static 위임 후보와 두 공급자 호출 경계를 확인했다.
  Pipeline의 private transport를 instance에서 대체하는 기존 테스트/호출부를 확인했고 해당 hook은 유지한다.

### 이번 구현

- `execution.provider_runtime.ProviderRuntime`에 두 공급자 호출의 typed endpoint를 모았다.
  invocation/runner 생성은 실제 호출 시 Root의 좁은 factory로 수행하며 기존 생성 실패/실행 실패의
  예외 경계와 오류/원인을 보존한다. 기존 instance hook은 직접 bound callable로 연결한다.
- 값과 callback을 그대로 전달하던 private static 메서드 22개를 소유 함수의 static 별칭으로 바꿨다.
  기존 선언의 모든 인자/기본값/반환 annotation과 실제 전달 방식이 같은 경우만 선택했다.
  공개 메서드·self/cls 문맥이나 추가 검증/변환이 필요한 메서드는 유지했다.
- Pipeline은 **5,620 → 5,495줄(125줄 감소)**, 직접 정의 메서드는 **433 → 411개**다.
  호출을 우회하는 동적 dispatch나 mixin·컨테이너/무제한 owner context를 추가하지 않았다.

### 검증 결과

- 변경 Python 2개의 `py_compile`이 통과했다. 신규 factory/runtime는 실제 요청 전까지 자원을
  만들지 않으며, instance transport 대체와 호출 후 SDK 변경을 기존 관련 사례로 확인했다.
- 기존 함수 다섯 개를 선택한 첫 실행은 **9 passed (1.55초)**였다. SDK 오류 원인/예외 변환,
  execute/review의 요청 ID/모델·강도/timeout·진행/취소/usage callback과 SDK 비소유, MCP 도구
  전달/키 마스킹, SDK 교체와 인증키 snapshot·수동 NVIDIA 프로필 보존을 확인했다.
  - `tests/execution/test_provider_runner.py::test_standalone_failure_is_translated_by_facade_with_the_same_message_and_sdk_cause`
  - `tests/execution/test_provider_runner.py::test_standalone_and_facade_preserve_request_identity_callbacks_and_sdk_ownership`
  - `tests/test_worker_mcp.py::test_pipeline_propagates_tools_only_to_worker_calls_and_redacts_claude_output`
  - `tests/test_nvidia_agent.py::test_request_credentials_are_isolated_and_pipelines_keep_their_snapshot`
  - `tests/test_nvidia_agent.py::test_manual_task_override_persists_nvidia_without_adding_a_reviewer`
- instance `_run_provider_command` 대체 후 기존 실제 Task 완료/commit·검증 흐름도 관련 한 함수로
  별도 확인했다. **1 passed, 2 subtests passed (8.83초)**였다. 앞서 통과한 아홉 사례는 반복하지 않았다.
  - `tests/test_pipeline.py::PipelineTest::test_manual_nvidia_profile_runs_through_existing_task_commit_and_verification`
- 두 실행은 `.venv/Scripts/python.exe -m pytest -q`에 위 node ID와 각각
  `--basetemp=.tmp/pytest-pipeline-facade-reduction --junitxml=.tmp/pipeline-facade-reduction-tests.xml`,
  `--basetemp=.tmp/pytest-pipeline-runtime-hook --junitxml=.tmp/pipeline-runtime-hook-tests.xml`을 사용했다.
  기존 임시 저장소/fixture/mock만 사용했고 실제 외부 AI/계정은 호출하지 않았다. 새 테스트나 기대값 변경은 없다.
- `.tmp/check_pipeline_facade_reduction.py`로 이전 두 호출의 인자/기본값·factory·오류 경계를
  AST로 복원해 대조했다. 기존 22개 private static callable의 signature/기본값/반환과 소유 함수
  동일성, 초기화 이전 본문 및 범위 밖 메서드 408개 보존을 확인했다. 전역 참조·150자/공백과
  runtime의 세 callback 외 owner/SDK/인증키 보유가 없음도 확인했다.
- `.tmp/check_stage27.py`에서 공개 Pipeline 112개·Store 91개·응용 API 121개 서명과 모델 80개,
  RPC 122개 경로/기존 오류·모델·기획 별칭이 유지된다. 코어 175개 모듈 import에 순환/기능 역참조가 없다.
  `git diff --check`와 변경 문서 참조/계측도 확인했다.
- 전체 테스트·renderer·빌드/패키징·실제 AI/계정/화면·다른 저장소/Rust/공개 checkout 및 사용자
  저장소의 commit/merge/push/deploy는 실행하지 않았다. 기존 변경과 앞선 완료 기록을 보존했다.

### 남은 구조 판단

이번 묶음은 호출 어댑터와 순수 호환 위임의 중복을 줄였다. Pipeline의 크기 문제 전체가 끝났다는
뜻은 아니다. 다음 큰 검토 단위는 기획 명령 조합과 실행/통합 조정의 명확한 owner다. 승인·잠금·
정책/SDK/Git 수명을 누가 보유하는지 먼저 정하고, 단순 파일 분할이나 전체 Pipeline 인계로 옮기지 않는다.
이 후보에 세부 연속 번호나 임의의 수백 단계 일정을 붙이지 않는다.

후속 구조와 구현 순서는 [Pipeline 명령 소유권 재설계](../Design/Technical/2026-11-15-pipeline-orchestration-redesign.md)와
[5단계 이행 계획](2026-11-15-pipeline-orchestration-redesign.md)을 따른다. 위 구현/검증은 이 문서 당시의 기록으로 유지한다.
