# AI 호출·실행 목록 조회 흐름: 63~72단계

**상태: 63~72단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

사용자의 다음 10단계 요청에 따라 63~72단계를 진행한다. 앞선 1~62단계 기록과 기존
미커밋 변경을 유지한다. 시작 Pipeline은 8,083줄이며 아래 세 흐름을 분리한 뒤 종료한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 63 | provider transport·사용량 기록의 좁은 호출 계약 정의 | 완료 |
| 64 | 작업 도구 lease/연결 검사와 호출·사용량 종료 조합 분리 | 완료 |
| 65 | 도구 대기/실패와 사용량/취소/timeout 관련 확인 | 완료 |
| 66 | 기획 호출의 고정 정책·프로필·진행 기록 계약 정의 | 완료 |
| 67 | 기획 호출 준비와 진행 기록을 명시적 runtime으로 분리 | 완료 |
| 68 | 기획 binding/보관 대화/session/진행 저장 관련 확인 | 완료 |
| 69 | 목록·주의/활동 그룹·대기 안내의 조회 계약 정의 | 완료 |
| 70 | 조회 조합을 실행 부작용 없는 모듈로 분리 | 완료 |
| 71 | 보관/잠금 snapshot·주의/대기 안내 관련 확인 | 완료 |
| 72 | 이동 순서·공개 계약/의존 관계·diff와 완료 기록 확인 | 완료 |

## 책임과 호환성

- `execution.invocation`은 제공된 transport와 사용량 기록 callback으로 작업 도구 lease와
  사전 연결 검사·사용량 시작/모델/관측/재시도/종료를 조합한다. 실제 SDK/credential/process
  수명은 기존 Pipeline과 `ProviderRunner`에 남긴다. 도구는 execute/revise에만 연결한다.
- `planning.invocation`은 명시적으로 제공된 정책 문맥과 기록/command/provider callback으로
  고정 profile 검증·기획 command 준비·진행 기록을 조합한다. ContextVar scope·정책 binding과
  SDK 수명·호출자의 잠금 소유권은 Pipeline에 남긴다. planning 기본 import는 무겁게 만들지 않는다.
- 실행 목록 조회는 기존 `run_queries`의 순수 판정을 재사용한다. 좁은 조회 callback과 DTO만 받고
  Store/Pipeline/Config/Git 객체를 받지 않는다. 목록별 오류 처리 차이와 잠금 전후 비교를 유지하며
  실행/승인/상태 변경 권한을 추가하지 않는다.
- public/private signature와 CLI/RPC/MCP/저장 schema·기존 메시지/예외/순서/재생 계약을 유지한다.
  세부 파일 배치는 책임이 선명한 기존 패키지를 우선한다.

## 영향 파일과 검증

`pipeline.py`, 신규 실행/기획 호출·조회 모듈, 필요한 공개 export와 `Docs/Architecture.md`,
직접 영향받는 기존 테스트의 patch 경로만 수정한다. 기존 callback/고정 정책·도구 대기/마스킹과
목록/잠금/대기 안내 테스트를 좁혀 선택한다. 새 회귀 경계가 없으면 테스트를 추가하지 않는다.
이동 전 snapshot과 AST 본문/서명·callback 연결을 대조하고 변경 파일 구문·전역 참조·diff를 확인한다.

전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
commit/push/deploy는 실행하지 않는다. 통과한 검사는 변경이 없는 한 재실행하지 않는다.

## 진행과 결과

### 63~65단계: provider 호출과 사용량 기록

- `ProviderInvocation`과 transport/사용량 기록 계약으로 작업 도구 lease·대기 진행·Claude 연결
  검사와 사용량 시작/실제 모델/관측/재시도/종료를 분리했다. 취소 신호는 기존 구체 타입을 보존하는
  Protocol/Generic 계약으로 전달하며 실제 SDK/credential/process 소유자는 바꾸지 않았다.
- `pytest -q tests/test_pipeline_usage.py -k 'not purpose_from_planning_binding'
  tests/test_worker_mcp.py::test_pipeline_propagates_tools_only_to_worker_calls_and_redacts_claude_output`를
  실행해 `6 passed, 1 deselected`(1.28초)였다. 실제 모델 대신 기존 mock을 사용했다.
  worker MCP 테스트는 소유 모듈로 이동한 연결 검사 patch 경로 두 곳만 변경했다.

### 66~68단계: 기획 호출 준비와 진행 기록

- `PlanningInvocation`은 전달받은 정책 문맥과 저장/command/provider callback으로 고정 profile과
  보관 대화 정책·자동 모델 기준·Claude session·timeout/usage 문맥을 검증/준비한다. 정책 시작 기록은
  원래 provider 호출 직전 순서다. 진행 기록은 caller의 기존 RLock과 저장 callback을 사용한다.
- `pytest -q tests/test_effort_planning_binding.py tests/test_pipeline_usage.py tests/test_pipeline.py`에
  이번 경계의 `-k` 선택을 적용했다. 고정 요청/모델·저장 실패 시 AI 차단·보관 대화 정책/오염·legacy
  보관 대화·usage 목적·모델 command·session·진행 중복 방지의 기존 9개와 하위 사례 7개가 통과했다
  (`9 passed, 7 subtests passed`, 0.70초). 테스트와 기대값은 추가/변경하지 않았다.

### 69~71단계: 실행 목록과 대기 안내 조회

- `queries.summaries`에 목록/보관 필터·정렬·주의 항목·활동 그룹·사용자 확인 목록을,
  `queries.waiting`에 현재 사건/실패/남은 Task/검증 근거에 맞는 다음 단계 안내를 묶었다.
  실제 Git 조회와 기존 순수 판정은 Pipeline callback으로 연결한다. 조회 모듈은 쓰기 API를 받지 않는다.
- `pytest -q tests/test_attention_inbox.py tests/test_next_step_waiting.py tests/test_pipeline.py`에
  잠금/조회 실패·완료/보관 제외·로컬 완료/배포·주요 결정·실패 지시/마지막 Task·계획 변경·사용자 중지/
  오래된 성공 근거·다음 Task 순서·활동 그룹의 `-k` 선택을 적용해 `12 passed`(1.31초)였다.
  오래된 안내 차단과 run/파일 불변 여부는 기존 사례로 확인했다.

### 72단계: 묶음 종료

- 이동 전 snapshot과 AST로 세 흐름의 본문/오류/기록/잠금 순서와 callback 연결을 대조했다.
  기존 모든 Pipeline 메서드 서명과 이번 범위 밖 410개 메서드는 그대로다. 새 테스트는 없다.
- 수정 Python의 `py_compile`, 전역 참조·변경 줄 길이/공백·diff를 확인했다. 기존 공개 Pipeline 112개·
  Store 91개·응용 API 121개 서명과 모델 80개·호환 오류/모델/기획 import·RPC 122개 경로를 확인했다.
  코어 139개 모듈 import 선언에 순환이 없고, 신규 모듈은 전체 소유 객체나 역참조를 받지 않는다.
  새 runtime import와 별도 프로세스의 planning 기본 import도 확인했다. 기본 import에는 SDK/Git/runtime이 없다.
- 관련 검사 합계는 27개와 하위 사례 7개다. 통과한 동작 검사는 재실행하지 않았고 annotation/문서 정리
  뒤에는 해당 정적 확인만 수행했다. 아키텍처에 신규 호출·조회 책임과 의존 방향을 반영했다.
- Pipeline은 8,083줄에서 7,766줄로 317줄 줄었다. 신규 호출/조회 파일은 각각 178/170/191/100줄이다.
  기존 미커밋 변경을 보존했으며 전체 리팩터링 완료를 뜻하지 않는다. 추가 단계는 시작하지 않았다.
- 전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
  commit/push/deploy는 이번 범위에 필요하지 않아 실행하지 않았다.
