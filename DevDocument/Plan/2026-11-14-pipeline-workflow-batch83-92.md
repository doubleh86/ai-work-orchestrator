# 보관 기록·기획 반영·채팅 후속 판단: 83~92단계

**상태: 83~92단계 완료. 이번 10단계 묶음의 구현·국소 확인·기록을 종료했다.**

## 목표와 승인 범위

사용자의 다음 10단계 요청에 따라 83~92단계를 수행한다. 시작 Pipeline은 7,559줄이다.
앞선 완료 기록과 기존 미커밋 변경을 보존하며 아래 묶음의 구현/국소 확인/기록 후 종료한다.

| 단계 | 완료 조건 | 상태 |
|---|---|---|
| 83 | 보관 판정/표시의 입력·출력과 기존 호환 계약 확인 | 완료 |
| 84 | 보관 차단 사유·fingerprint·결과 요약/보관 조회 표현 분리 | 완료 |
| 85 | 결과 근거/이미 보관/완료 조건 관련 확인 | 완료 |
| 86 | 기획 반영 입력·준비 결과/기록 callback 계약 정의 | 완료 |
| 87 | 요청 재생/실행 중 대기/잠금 안의 반영 요청 처리 분리 | 완료 |
| 88 | 중복/stale/revision·실행 중 대기·기술 구성 재시도 확인 | 완료 |
| 89 | 채팅 중지/복구 후속 판단의 기록/조회 계약 정의 | 완료 |
| 90 | 현재 요청/대상/중지 확인과 다음 행동 응답 조합 분리 | 완료 |
| 91 | 취소/중단/오래된 대상·복구/검증 후속 응답 관련 확인 | 완료 |
| 92 | 이동 순서·공개 계약/의존 관계·diff와 완료 기록 확인 | 완료 |

## 책임과 영향 범위

- `integration`의 보관 표시 모듈은 상태/정리 대상 DTO, 원격/배포 여부와 기록 디렉터리 조회로
  차단 사유·표시/해시/요약을 만든다. 실제 Git 조회·commit 보호·snapshot 저장과 worktree 정리,
  archive 저장/권한·승인·실행 잠금은 기존 Pipeline/WorkspaceLifecycle에 유지한다.
- 기획 반영 모듈은 명시적 입력/준비 결과 DTO와 run 조회·대화 기록/잠금 조회 및 기존 검증/프로필/
  요청 생성/실제 적용 callback으로 요청을 조합한다. 기획 run/chat 잠금은 Pipeline이 기존 위치에서
  획득하며 실제 계획 적용과 최종 단계 전이도 소유자에 남긴다. 실행 중 요청은 대화 잠금만 사용한다.
- 채팅 후속 판단은 현재 요청/상태와 중지 영수증을 확인해 다음 stop/repair/verify 또는 보류 응답을
  만든다. 기존 요청 제어 잠금과 operation 기록 API만 사용한다. 실제 stop/repair/verify 실행과
  승인·run 잠금·SDK 수명은 기존 소유자에 남긴다. 프로젝트 채팅의 별도 분기를 유지한다.
- `pipeline.py`, 관련 `integration`/`planning`/`execution` 하위 모듈·필요한 export와 아키텍처 및
  직접 영향받는 기존 테스트만 다룬다. 전체 Pipeline/Store/Config를 넘기거나 새 서비스/잠금을 만들지 않는다.
  기존 public/private signature·문구/예외·CLI/RPC/MCP·저장 schema와 부작용 범위를 유지한다.

## 검증

이동 전 snapshot과 AST로 본문/기록/오류/잠금/callback 순서를 대조한다. 변경 Python의 구문·
전역 참조·줄 길이/공백·diff 및 관련 공개 계약/의존 방향을 확인한다. 기존 보관 요약·기획 요청/
재시도·중지/복구 후속 판단 case만 선택하며 기존 관찰로 충분하면 테스트를 추가하지 않는다.
전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/Rust/공개 checkout과
commit/push/deploy는 이번 범위에 없으며, 통과한 검사는 후속 변경의 영향을 받지 않으면 반복하지 않는다.

## 진행과 결과

### 83~85단계: 보관 표시와 결과 근거

- `integration.archive_views`로 차단 사유·fingerprint·Task/통합 결과 요약·이미 보관된 그룹 조회와
  정리 대상 표현/요청 ID 검증을 옮겼다. 원격/배포 판정의 실제 조회는 Pipeline에 남겼다.
  기록 디렉터리 callback은 기존 보관 상태 검사 뒤 같은 위치에서 호출한다.
- `pytest -q tests/test_pipeline.py`에서 최종 commit 파일 근거와 보관 요약, 완료 그룹의 기록 보존/
  소유 worktree 정리, 오래된 충돌의 완료 조건 관련 `-k` 선택을 실행해 `3 passed`(3.75초)였다.
  이미 보관된 조회/표시·UUID·해시와 출력 형식은 이동 전 본문과 AST로 대조했다.

### 86~88단계: 기획 대화 반영 요청

- `PlanningApplyInput`/`PlanningApplyPreparation`과 `PlanningApplyWorkflow`에 입력 정규화·재생/
  사전 상태 조회, 실행 중 요청 대기와 잠금 안의 재검증/요청 claim·실제 적용 callback 호출을 묶었다.
  Pipeline은 사전 결과에 따라 기존 chat 잠금 또는 run+chat 잠금을 같은 위치에서 획득한다.
  같은 revision의 요청 재사용·기술 답변/실패 재시도·프로필/대화 변경 순서를 유지했다.
- `pytest -q tests/test_pipeline.py`에서 revision 안전/중복 요청, 실행 중 대화 snapshot 대기,
  기술 답변의 요청/문맥 공유·실패 후 재시도·오래된 후보/계획/대화 거부·후속 대화 보호·확정한 기본
  구조의 계획 실패 재시도를 `-k`로 선택해 `7 passed, 3 subtests passed`(4.82초)였다.
  이후 입력 DTO와 저장 요청의 지역 변수 타입을 구분했고, 해당 준비/처리 본문은 AST로 대조했다.

### 89~91단계: 채팅 중지·복구의 다음 행동

- 기존 `execution.project_chat`에 `ChatControlAdvancement`를 추가했다. 상태/중지 영수증·대상/
  중지 확인 시간·복구 가능 여부를 확인해 stop/repair/verify 또는 보류 응답을 조합한다. 기존
  `ProjectChatRecords`의 요청 제어 잠금/기록 API를 재사용하며 실제 작업 실행 권한은 추가하지 않았다.
  프로젝트 채팅의 진행/중단 기록도 옮기고 기존 판단/행동 workflow 세부 구현은 유지했다.
- `pytest -q tests/test_chat_control_review.py tests/test_chat_task_recovery.py tests/test_project_chat.py`에서
  대상 변경·중지 완료 영수증/잠금·진행 확인 후 취소/실행 변경·중지/검증 명령 중복·프로젝트 실제 결과의
  관련 `-k` 선택을 실행해 `11 passed`(0.94초)였다. 프로젝트 진행 분기의 중단 처리를 별도로 확인한
  `tests/test_project_chat.py::test_transport_failure_is_not_replayed_after_restart`도 통과했다(0.36초).

### 92단계: 묶음 종료

- 이동 전 snapshot과 AST로 보관의 여섯 함수, 기획 사전/대기/적용 본문·입력/callback과 Root의
  두 잠금 경계, 채팅 후속 판단/중단·오류/기록 순서를 대조했다. 기존 모든 Pipeline 서명/데코레이터와
  범위 밖 메서드 411개가 그대로이며 기존 프로젝트 채팅 클래스도 변하지 않았다.
- 수정 Python 5개 파일의 `py_compile`·전역 참조·변경 줄 길이/공백·diff를 확인했다. 공개 Pipeline
  112개·Store 91개·응용 API 121개 서명과 모델 80개·기존 오류/모델/기획 import·RPC 122개 경로를
  확인했다. 144개 코어 모듈 import 선언에 순환/기능 역참조가 없고 전체 소유 객체를 전달하지 않는다.
  planning 기본 import가 SDK/Git/runtime을 로드하지 않는 것과 새 모듈/실행 export도 확인했다.
- 관련 검사 합계는 22개와 하위 사례 3개다. 새 테스트나 기존 테스트/기대값 변경은 없다. 통과한
  동작 검사를 반복하지 않았고 입력 이름/annotation·export/문서 정리는 해당 정적 확인만 수행했다.
- Pipeline은 7,559줄에서 7,281줄로 278줄 줄었다. 기획 반영 함수는 125→39줄, 채팅 후속 판단은
  86→5줄, 프로젝트 진행은 16→2줄이다. 보관 표시 모듈 148줄, 기획 요청 모듈 220줄, 확장한 채팅
  모듈은 307줄이다. 전체 리팩터링의 완료를 뜻하지 않으며 다음 단계는 시작하지 않았다.
- 기존 미커밋 변경을 보존했다. 전체 테스트/renderer·빌드/패키징·실제 AI/계정/도구/화면·다른 저장소/
  Rust/공개 checkout과 commit/push/deploy는 이번 범위에 필요하지 않아 수행하지 않았다.
