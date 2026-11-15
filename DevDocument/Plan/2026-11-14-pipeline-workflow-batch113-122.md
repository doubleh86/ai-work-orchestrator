# 실행 시작 준비·정책 검증·채팅 실행 AI 변경: 113~122단계

**상태: 113~122단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

다음 10단계 요청에 따라 113~122단계를 수행한다. 시작 Pipeline은 6,902줄이다.
앞선 완료 기록과 기존 미커밋 변경을 보존하고 이번 묶음의 구현·국소 확인·기록 후 종료한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 113 | 실행 입력/재시도 준비와 단계 결정 결과 계약 정의 | 완료 |
| 114 | 누락 파일/override 검증·적용과 재시도 Task 준비 분리 | 완료 |
| 115 | 실패/선택 재시도·파일 복원·override 관련 확인 | 완료 |
| 116 | 기존 정책과 모델/리뷰어 사전 검증 계약 정의 | 완료 |
| 117 | 복구 mode·preview/원본 프로필/리뷰어 검증 분리 | 완료 |
| 118 | binding 재개/예약·변경된 프로필/리뷰어 차단 확인 | 완료 |
| 119 | 채팅 실행 AI 저장 결과와 복구 callback 계약 정의 | 완료 |
| 120 | 대상/취소·가용 모델 선택·저장 재확인/후속 복구 기록 분리 | 완료 |
| 121 | 직접 지정/재시도·저장 실패/취소/대상 변경 관련 확인 | 완료 |
| 122 | 이동 순서·공개 계약/의존 관계·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 범위

- 실행 시작 모듈은 좁은 파일 준비/프로필 검증·적용/기록 callback으로 입력을 준비하고 재시도할
  Task의 상태와 readiness를 정리한다. Pipeline은 승인/검증 정책·작업공간 준비와 Run resume/단계
  전이·최종 저장, Task 준비 step·dispatch를 유지한다. 재시도 결과는 명시적 DTO로 전달한다.
- 실행 정책 사전 검증은 제공된 모델 목록·확정 계획/preview/가용성/리뷰어 callback으로 복구 mode와
  현재 worker/reviewer/기준선의 일치를 확인한다. 기존 binding 검사·해제·정책 snapshot 생성 및
  prepare/start·RunState 참조 저장은 Pipeline에 남긴다. 독립적인 승인·binding 쓰기를 만들지 않는다.
- 채팅 실행 AI 변경 모듈은 기존 요청 기록/제어 잠금과 가용성/프로필 저장/실제 복구 callback으로
  저장 전후 대상 검증·설정 재확인과 후속 결과를 조합한다. Pipeline의 run/chat 잠금 안에서 저장하고
  잠금 해제 뒤 원래 복구 진입점을 사용한다. 저장 실패나 취소가 복구를 시작하게 하지 않는다.
- `pipeline.py`, execution 하위 모듈·필요한 공개 export/아키텍처와 직접 관련 테스트만 다룬다.
  전체 Pipeline/Store/Config를 전달하지 않는다. 기존 public/private signature·예외/문구·저장/
  CLI/RPC/MCP 계약과 정책/승인/실행 순서를 유지한다.

## 검증

이동 전 snapshot과 AST로 본문·callback·Task/Run 상태 변경·오류/잠금/기록 순서를 대조한다.
변경 Python의 구문·전역 참조·줄 길이/공백/diff와 공개 계약/의존 관계를 확인하고 기존 실행 준비/
재시도·정책 binding/프로필·채팅 모델 변경의 관련 case만 선택한다. 기존 관찰이 충분하면 테스트를 추가하지 않는다.
전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
commit/push/deploy는 포함하지 않으며 통과한 검사는 후속 변경의 영향을 받지 않으면 반복하지 않는다.

## 진행과 결과

### 113~115단계: 실행 입력과 재시도 Task 준비

- `execution.startup.ExecutionStartup`으로 누락 파일 복원·override 검증/적용과 실패/선택 Task의
  재시도 준비를 옮겼다. `ExecutionRetryQueue`는 resume 여부와 원래 기록 문구만 전달한다.
  Pipeline의 승인/검증 정책·작업공간 준비, Run resume/저장과 최초 준비 step/전이·dispatch는 유지했다.
- `pytest -q tests/test_pipeline.py`에서 누락 파일 복원, 실행 사전 검사 실패 후 재개, agent override와
  리뷰어 재배정, 선택한 실패 Task만 재시도, 단계가 없는 legacy 실패 거부를 `-k`로 선택해
  `5 passed`(5.44초)였다. Task 상태/readiness와 최종 Run 전이·저장 순서는 AST로도 대조했다.

### 116~118단계: 실행 정책 사전 검증

- 기존 `execution.policy_snapshot`에 `ExecutionPolicyPreflight`를 추가했다. 복구 mode와 확정 계획/
  preview·worker/reviewer·원본 프로필 기준선을 검증하고 preview만 반환한다. 모델 목록은 callback으로
  현재 값을 조회한다. 기존 binding/참조 검사·해제와 policy 생성/예약/저장/시작은 Pipeline에 남겼다.
  기존 snapshot 생성 함수와 실행 중 정책 검증 클래스는 바꾸지 않았다.
- `pytest -q tests/test_effort_execution_binding.py`에서 호출 전후 binding 수명, 준비 중단 후 예약 보존,
  저장 프로필 복구와 승인/필수 리뷰, runtime 불일치·plan/snapshot 변경 차단의 `-k` 선택을 실행해
  `6 passed, 12 subtests passed`(0.84초)였다.

### 119~121단계: 채팅 실행 AI 저장과 후속 복구

- `execution.chat_profiles`에 요청 기록 API·`SavedChatProfile`·`ChatExecutionProfiles`를 추가했다.
  Pipeline의 기존 run/chat 잠금 안에서 현재 대상/취소·가용 AI 선택·저장/재확인을 수행하고 저장
  결과 DTO를 전달한다. 잠금 해제 후 원래 복구 진입점과 operation/채팅 기록을 같은 순서로 사용한다.
- `pytest -q tests/test_project_chat.py`에서 명시한 실패 Task의 설정만 저장, 저장 후 결합 재시도,
  저장할 수 없는 연결/새 시도에서 복구 금지, 늦은 응답의 새 대상 변경 차단을 `-k`로 선택해
  `9 passed`(0.83초)였다. 모델 출력을 실행 권한으로 해석하는 규칙은 바꾸지 않았다.

### 122단계: 묶음 종료

- 이동 전 snapshot과 AST로 입력/override·재시도 Task/readiness와 반환 문구, mode/preview/현재
  모델/리뷰어 검증, 채팅 대상/저장/재조회·잠금 해제 후 복구/결과 기록을 대조했다. Pipeline의 Run
  전이·binding 참조/쓰기/시작·준비/dispatch와 기존 모든 서명/데코레이터, 범위 밖 메서드 420개가 그대로다.
- 수정 Python 4개 파일의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline
  112개·Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로를
  확인했다. 코어 151개 모듈 import 선언에 순환/기능 역참조가 없고 전체 Pipeline/Store/Config/Git를
  신규 구성에 전달하지 않는다. planning 기본 import와 새 모듈 및 기존 선택 함수의 호환 별칭도 확인했다.
- 관련 검사 합계는 20개와 하위 사례 12개다. 새 테스트와 기존 테스트/기대값 변경은 없다. 통과한
  동작 검사는 반복하지 않았으며 줄바꿈·호환 별칭/문서 정리 뒤에는 해당 정적 확인만 수행했다.
- Pipeline은 6,902줄에서 6,769줄로 133줄 줄었다. 대상 함수는 각각 95→45줄, 89→63줄,
  73→12줄이다. 신규 시작/채팅 프로필 모듈은 105/138줄, 확장한 정책 snapshot 모듈은 178줄이다.
  전체 리팩터링의 완료를 뜻하지 않으며 다음 단계는 시작하지 않았다.
- 기존 미커밋 변경을 보존했다. 전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/
  Rust/공개 checkout과 commit/push/deploy는 이번 범위에 필요하지 않아 수행하지 않았다.
