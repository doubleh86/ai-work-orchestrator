# 실행 파일 준비·채팅 복구·통합 후 재계획: 93~102단계

**상태: 93~102단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

다음 10단계 진행 요청에 따라 93~102단계를 수행한다. 시작 Pipeline은 7,281줄이다.
앞선 완료 기록과 기존 미커밋 변경을 보존하고 이번 묶음의 구현·국소 확인·기록 후 종료한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 93 | Task 실행 파일/작업공간 준비의 명시적 의존 계약 정의 | 완료 |
| 94 | 공유/개별 worktree와 프롬프트/로그 경로 준비 조합 분리 | 완료 |
| 95 | 경계 검증·프롬프트/경로·누락 실행 파일 복원 확인 | 완료 |
| 96 | 채팅 복구 지시/기록과 재생·검증 전용 결과 계약 정의 | 완료 |
| 97 | 부모/실패/대화 근거 검증·복구 지시 저장 분리 | 완료 |
| 98 | 중복/저장 실패·오래된 상담·중지/시간 초과 복구 관련 확인 | 완료 |
| 99 | 복구 반영 operation/통합/재계획 callback 계약 정의 | 완료 |
| 100 | 요청 claim·통합 결과/후속 기획·부분 실패 receipt 조합 분리 | 완료 |
| 101 | 승인/오래된 복구안·통합 후 실패/재시도·중단 보존 확인 | 완료 |
| 102 | 이동 순서·공개 계약/의존 관계·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 범위

- `execution.preparation`은 주어진 Git adapter와 명시적인 경로/경계/프롬프트·기록 callback으로
  Task 실행 파일을 준비한다. 기존 workspace 경계 검사·누락 파일 복원과 persist 옵션을 유지하며
  새 작업공간 규칙이나 승인·정책·최종 Run 단계 전이를 추가하지 않는다.
- 채팅 복구 모듈은 부모/요청 재생·실패/대화/범위/검증 근거와 상담의 Task/시각을 확인하고 복구
  지시와 대화 기록을 저장한다. Pipeline은 기존 run/chat/revision 잠금과 실행 session·timeout 보완·
  실제 실행 루프를 유지한다. 기록 저장에 실패하면 실행하지 않고 재전달도 중복 실행하지 않는다.
- 복구 반영 모듈은 operation과 통합 결과·재계획·부분 실패 기록을 조합한다. 명시적 승인과
  run/chat 잠금, 실제 Git 통합과 기획 effort scope는 Pipeline callback에 남긴다. 통합이 끝난 후
  기획이 실패하면 통합 commit/후속 요청을 보존하고 재시도는 기획만 수행한다.
- `pipeline.py`, 관련 execution/integration 모듈·필요한 공개 export와 아키텍처 및 직접 관련
  테스트만 다룬다. 전체 Pipeline/Store/Config를 전달하지 않는다. 기존 public/private signature,
  오류/문구·저장/CLI/RPC/MCP 계약과 Git 부작용 범위를 유지한다.

## 검증

이동 전 snapshot과 AST로 본문/기록/오류/잠금·callback 순서를 대조한다. 변경 Python 구문·
전역 참조·줄 길이/공백·diff, 관련 공개 계약·의존 방향을 확인한다. 기존 경계/프롬프트 준비,
채팅 복구 지시·검증 재시도와 복구 반영/부분 실패 case만 선택하며 관찰이 충분하면 테스트를 추가하지 않는다.
전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
commit/push/deploy는 포함하지 않으며 통과한 검사는 후속 변경의 영향을 받지 않으면 반복하지 않는다.

## 진행과 결과

### 93~95단계: Task 실행 파일 준비

- 기존 `execution.preparation`에 `TaskExecutionRecords`/`TaskExecutionPreparation`을 추가했다.
  명시적 Git adapter와 경로/경계/프롬프트·저장 callback으로 작업공간과 실행 파일을 준비한다.
  공유/개별 branch·worktree 검증, 선택 Task와 persist 옵션, 기존 의존성/시작 기준선 클래스는 유지했다.
- `pytest -q tests/test_pipeline.py`에서 누락 실행 파일 복원, 재계획한 허용 경로와 저장 프롬프트/
  검사기의 일치, 작업공간 계약 프롬프트의 `-k` 선택을 실행해 `3 passed`(7.25초)였다.
  공유/개별 준비의 전체 분기와 Git 호출·저장 순서는 이동 전 본문과 AST로 대조했다.

### 96~98단계: 채팅 복구 지시 수락

- `execution.chat_recovery`에 기록 API와 `ChatRecoveryPreparation`/`ChatTaskRecovery`를 추가했다.
  부모/요청 재생·실패/대화/범위/검증 근거와 상담의 Task/시각·지시 길이를 확인해 저장한다.
  Pipeline은 입력 검증과 원래 run/chat/revision 잠금, 재생 시 즉시 반환, 실행 session·timeout 보완과
  실제 실행 본문을 유지한다. 완료 Task/계약과 기존 실행 프로필을 보존한다.
- `pytest -q tests/test_chat_task_recovery.py tests/test_task_verification_timeouts.py`에서 지시 선저장,
  변경/부적격 대상, 저장 실패, 실패 실행의 재전달, 오래된/다른 Task 상담, 확인된 중지, 검증 전용
  timeout 보완과 조회 후 조건 변경의 `-k` 선택을 실행해 `18 passed`(0.76초)였다.

### 99~101단계: 복구 통합 후 재계획

- `integration.recovery_apply`에 명시적 operation/기록 API와 `RecoveryApplication`을 추가했다.
  요청 claim/재생·복구안 검증·통합 결과/지시 기록과 재계획 성공·부분 실패 기록을 조합한다.
  승인과 run/chat 잠금은 Pipeline에 유지한다. 실제 commit 통합과 기획 effort scope는 두 작은
  Root helper를 통해 기존 인수/순서로 실행한다. 새 Git 작업이나 정책 binding 규칙은 추가하지 않았다.
- `pytest -q tests/test_pipeline.py`에서 승인/오래된 복구안 거부와 그룹 보존, 통합 후 capacity 실패의
  기획 전용 재시도, 재계획 중단의 통합 commit/부분 결과 보존을 `-k`로 선택해 `3 passed`(7.10초)였다.

### 102단계: 묶음 종료

- 이동 전 snapshot과 AST로 실행 파일 준비·복구 지시/재생/timeout·operation 통합/재계획/오류의
  본문과 callback 연결을 대조했다. 승인·모든 기존 잠금/실행 본문과 실제 Git/effort helper의
  인수/순서를 확인했다. 보조 비교 스크립트의 iterable 표현을 보정한 뒤 대조를 완료했으며 제품 수정은 없었다.
  기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 418개가 그대로다.
- 수정 Python 5개 파일의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline
  112개·Store 91개·응용 API 121개 서명, 모델 80개와 기존 오류/모델/기획 import·RPC 122개 경로를
  확인했다. 146개 코어 모듈 import 선언에 순환/기능 역참조가 없고 전체 소유 객체를 넘기지 않는다.
  명시적 준비 Git adapter 외에는 신규 모듈에 Git 객체가 없으며 planning 기본 import도 SDK/Git/runtime을
  로드하지 않는다. 새 모듈과 execution 공개 export도 별도 import로 확인했다.
- 관련 검사 합계는 24개다. 새 테스트와 기존 테스트/기대값 변경은 없다. 통과한 동작 검사는 반복하지
  않았으며 import 줄바꿈·annotation/문서 정리 뒤에는 해당 정적 확인만 수행했다.
- Pipeline은 7,281줄에서 7,080줄로 201줄 줄었다. 대상 함수는 각각 79→8줄, 98→44줄,
  110→22줄이다. 확장한 준비 모듈은 185줄, 신규 채팅 복구/복구 반영 모듈은 128/153줄이다.
  전체 리팩터링의 완료를 뜻하지 않으며 다음 단계는 시작하지 않았다.
- 기존 미커밋 변경을 보존했다. 전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/
  Rust/공개 checkout과 commit/push/deploy는 이번 범위에 필요하지 않아 수행하지 않았다.
