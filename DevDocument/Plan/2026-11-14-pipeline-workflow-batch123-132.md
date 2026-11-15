# 기획 메시지 분기·미리보기 적용·통합 검증 기록: 123~132단계

**상태: 123~132단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

다음 10단계 요청에 따라 123~132단계를 수행한다. 시작 Pipeline은 6,769줄이다.
앞선 완료 기록과 기존 미커밋 변경을 보존하고 이번 묶음의 구현·국소 확인·기록 후 종료한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 123 | 기획 메시지 분기/기록과 기존 대화·반영 callback 계약 정의 | 완료 |
| 124 | 보관/실행 대화·초기 Task/inline 변경/미리보기 경로 분리 | 완료 |
| 125 | 지시 보존·중복 제어 문구·기존 대화/실패/보관 경계 확인 | 완료 |
| 126 | 미리보기 조회/검증·실제 적용/결과 기록 계약 정의 | 완료 |
| 127 | 후보 복원·오래된/보호 Task 검사·요청/방향 변경 기록 분리 | 완료 |
| 128 | 단일 적용·stale/실행 중/보호·의존성/실패 보존 확인 | 완료 |
| 129 | 통합 검증의 시간/진행/결과/취소 callback 계약 정의 | 완료 |
| 130 | 명령 준비·attempt/로그·진행/성공/실패 기록 조합 분리 | 완료 |
| 131 | timeout/중단·명령 환경/원인·검증 결과 관련 확인 | 완료 |
| 132 | 이동 순서·공개 계약/의존 관계·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 범위

- 기획 메시지 분기는 좁은 조회/대화 기록과 기존 chat 잠금 factory, 대화/미리보기/반영 callback으로
  처리한다. 일반 기획 대화의 run 잠금·프로필/AI 호출·단계 기록은 Pipeline에 유지한다. 기존 요청을
  만드는 순서와 inline 지시의 선저장을 바꾸지 않으며 독립된 잠금을 만들지 않는다.
- 미리보기 적용은 Pipeline이 기존 run/chat 잠금을 획득한 뒤 수행한다. 저장 후보/요청/상태를
  검증하고 원래 계획 적용 callback을 호출해 결과/방향 변경 기록을 저장한다. 최종 Run 단계
  전이는 기존 Pipeline의 실제 계획 적용 API에 남기며 저장 형식/후보 digest 의미를 유지한다.
- 통합 검증 기록은 기존 runner와 명시적인 설정/기록/명령/취소/HEAD 검사 callback으로 조합한다.
  실제 명령 실행·취소 신호 소유권·검증 입력 보호와 최종 Run 단계 전이는 기존 소유자에 유지한다.
  준비 경과 시간·command/total timeout·passed/failure 기록과 예외 원인을 유지한다.
- `pipeline.py`, 관련 planning/execution 하위 모듈·아키텍처와 직접 관련 테스트만 다룬다. 전체
  Pipeline/Store/Config/Git 객체를 신규 구성에 전달하지 않는다. 기존 public/private signature,
  문구/예외·저장/CLI/RPC/MCP 계약과 승인/실행 순서를 유지한다.

## 검증

이동 전 snapshot과 AST로 본문·callback·잠금·상태/기록·오류 순서를 대조한다. 변경 Python의
구문·전역 참조·줄 길이/공백/diff와 관련 공개 계약/의존 관계를 확인한다. 기획 메시지/inline 지시,
미리보기 적용/보호·실패와 통합 검증 timeout/진행/중단의 기존 case만 선택하고 충분하면 테스트를 추가하지 않는다.
전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
commit/push/deploy는 포함하지 않으며 통과한 검사는 후속 변경의 영향을 받지 않으면 반복하지 않는다.

## 진행과 결과

### 123~125단계: 기획 메시지 경로 분기

- `planning.message_routing`에 조회/기록·기존 대화 잠금 factory와 대화/미리보기/반영 callback을
  받는 `PlanningMessageRouter`를 추가했다. 보관/실행 대화, 초기 Task와 inline 수정 지시·반영
  요청을 같은 순서로 처리한다. 일반 기획 대화는 Pipeline의 기존 run 잠금/프로필·AI/단계 기록에 남겼다.
- `pytest -q tests/test_pipeline.py`에서 제어 문구와 inline 수정 구분, 미리보기 실패 전 지시 보존,
  실행 중 완료 Task/원래 계획 보존, 신규 프로젝트의 revision/제어 문구 중복 방지, 초기 Task 생성,
  보관 대화의 `-k` 선택을 실행해 `6 passed, 19 subtests passed`(5.91초)였다.

### 126~128단계: 저장된 미리보기 적용

- `planning.preview_apply`에 기록 API와 `PlanningPreviewApplication`을 추가했다. 저장 후보/요청과
  현재 fingerprint·보호 Task·형식/차이를 검증하고 원래 계획 적용 callback을 호출한다. 적용 지표와
  방향 변경/대화 기록도 같은 순서로 저장한다. Pipeline의 기존 run/chat 잠금과 실제 단계 전이는 유지했다.
- `pytest -q tests/test_pipeline.py`에서 저장 후보의 단일 적용, stale/보호 Task 거부, 의존 Task 제외
  보호와 허용된 제외, 실패 시 Task/receipt 보존의 `-k` 선택을 실행해 `4 passed`(3.04초)였다.

### 129~131단계: 통합 검증 명령의 근거 기록

- `execution.run_verification`의 `RunVerificationCommands`로 기존 runner 앞뒤의 log/attempt,
  준비 경과 시간·command/total timeout, 명령 환경 준비·진행/성공/실패와 원인 예외 기록을 옮겼다.
  설정/명령/HEAD/취소는 기존 owner callback만 사용하며 구체적인 취소 신호 타입을 Generic 계약으로 유지한다.
- `pytest -q tests/test_pipeline.py tests/test_execution_control.py`에서 실행 중 명령 기록, command timeout,
  누락 npm 의존성 준비, 파일 잠금 근거/재시도와 복구 중단 기록의 `-k` 선택을 실행해 `5 passed`(0.59초)였다.
  실제 설치/모델 대신 기존 fixture/mock을 사용했고 최종 Run 단계 전이는 바꾸지 않았다.

### 132단계: 묶음 종료

- 이동 전 snapshot과 AST로 메시지 분기/잠금/선저장과 일반 대화 전체 본문, 미리보기 후보 복원/
  적용/요청·방향 기록, 검증 명령 log/시간/진행/성공/실패·원인과 모든 callback을 대조했다.
  기존 모든 Pipeline 서명/데코레이터와 범위 밖 메서드 420개가 그대로다.
- 수정 Python 4개 파일의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 한 줄의 길이
  초과는 줄바꿈으로 보정하고 정적 확인을 마쳤다. 공개 Pipeline 112개·Store 91개·응용 API 121개
  서명과 모델 80개·기존 오류/모델/기획 import·RPC 122개 경로가 유지된다. 코어 154개 모듈의
  import 선언에 순환/기능 역참조가 없고 전체 소유 객체를 전달하지 않는다. planning 기본 import와
  새 모듈 및 기존 검증 오류/options 호환 별칭도 확인했다.
- 관련 검사 합계는 15개와 하위 사례 19개다. 새 테스트와 기존 테스트/기대값 변경은 없다. 통과한
  동작 검사는 반복하지 않았고 줄바꿈·호환 별칭/문서 정리 뒤에는 해당 정적 확인만 수행했다.
- Pipeline은 6,769줄에서 6,636줄로 133줄 줄었다. 대상 함수는 각각 80→50줄, 65→9줄,
  61→10줄이다. 신규 메시지 분기/미리보기 적용/통합 검증 모듈은 102/102/104줄이다.
  전체 리팩터링의 완료를 뜻하지 않으며 다음 단계는 시작하지 않았다.
- 기존 미커밋 변경을 보존했다. 전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/
  Rust/공개 checkout과 commit/push/deploy는 이번 범위에 필요하지 않아 수행하지 않았다.
