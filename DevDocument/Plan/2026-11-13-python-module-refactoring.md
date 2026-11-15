# Python 기능 모듈 경계와 점진적 리팩터링

## 목표와 현재 상태

**상태: 최초 1~28단계 완료. 후속 흐름 정리도 302단계에서 종료했다.**
1~28단계 완료 당시 Pipeline은 9,219줄이며 공개 호출/상태/저장 계약과 승인·잠금·Git 최종 소유권을 유지했다.
실계정·화면·릴리스·원격 발행은 아래 미수행 범위이며 이번 코드 완료와 구분한다.

기능 규칙 분리의 종료 기록은 [293~302단계 최종 정리](2026-11-15-pipeline-workflow-batch293-302.md)다.
당시 Pipeline은 5,620줄이었다. 사용자의 추가 축소 요청에 따라
[진입점/실행 호출 경계 축소](2026-11-15-pipeline-facade-reduction.md)를 진행했고 현재 5,495줄이다.
아래 단계/후보는 최초 범위의 당시 기록이며 새로운 필수 단계로 해석하지 않는다.

별도 프로젝트로 분리 중인 Rust 개발과 독립적으로 현재 Python 제품의 기능 모듈 경계를 복원한다. 코드·UI의 동작과
CLI·RPC·MCP 계약, 저장 형식, 승인·상태 전이·Git 부작용을 유지하면서 한 단계씩 진행한다.
착수 당시 `pipeline.py`는 14,517줄·메서드 440개이며 요청 처리·상태 조정과 실제 AI 실행까지
집중되어 있다. `desktop_rpc.dispatch`는 643줄, `RunState.from_dict`는 395줄이고
`tests/test_pipeline.py`도 11,435줄이다. 파일 길이보다 책임과 의존 관계를 분리 기준으로 삼는다.

## 모듈 설계 원칙

- 목표 기능 경계는 `projects`(등록·설정), `planning`(계획·태스크 구성), `execution`
  (실행·리뷰·검증·중지·재시도), `integration`(Git 통합·반영·배포), `notifications`
  (알림 생성·전달)이다. 실제로 옮길 코드가 있을 때만 패키지를 만든다.
- 각 기능의 공개 API와 규칙·데이터 소유자를 정한다. 필요한 하위 계층 분리는 각 모듈
  안에서 수행한다. 기존 provider·Git·저장 어댑터는 공개 API로 재사용한다.
- `Pipeline`은 기존 진입점과 실행 순서·승인·잠금·상태 전이의 최종 권한을 유지한다.
  추출한 구성요소에 Pipeline 전체, 상태 저장 객체나 무제한 context를 넘기지 않는다.
  필요한 값과 callback만 명시적으로 전달하고 결과·오류를 공개 계약으로 돌려받는다.
- 다른 모듈의 내부 함수·저장 파일 우회 접근과 순환 의존성을 만들지 않는다. 파일만 옮기는
  mixin 분할, DI 컨테이너·이벤트 버스·별도 네트워크 서비스·새 의존성은 도입하지 않는다.
- 기존 import·호출·예외 계약은 필요한 호환 계층으로 유지한다. 실행 요청 ID, 취소 신호,
  진행·사용량 callback, timeout, 키 마스킹과 SDK 소유권도 보존한다.
- 한 단계마다 코드와 해당 검사를 함께 정리한다. 다음 단계의 구체적인 이동 범위는 그 단계
  착수 시 호출부를 확인하되, 아래 확정된 25~28단계 범위 안에서만 세부를 조정한다.
  새 후보를 이유로 단계를 자동 추가하지 않는다. Rust worktree·공개 배포 checkout·등록 프로젝트는 변경하지 않는다.

## UI·데스크톱 셸·엔진 경계

설계와 현재 런타임은 이미 React renderer → preload → Electron main → JSON Lines RPC →
Python 코어로 나뉘어 있다. 한 설치 제품의 로컬 프로세스 경계를 유지하며 새로운 네트워크
서비스를 도입하지 않는다. CLI·MCP는 화면 없이 같은 코어를 사용할 수 있어야 한다.

- UI는 입력·화면 상태·표시 문구·시간 표현과 사용자 확인 흐름을 소유한다. 실행 가능 여부의
  최종 판정, 모델 배정, 상태 전이와 Git 변경 권한은 코어가 재검증한다.
- Electron 셸은 창·트레이·파일 선택·OS 알림·안전한 credential 저장·native 확인과 backend
  수명을 소유한다. renderer의 Node 접근 차단과 기존 승인 경로를 유지한다.
- 공용 응용 계층은 기능별 공개 API를 조합하는 얇은 진입점으로 구성한다. 현재 MCP도
  `desktop_rpc.DesktopApplication`을 참조하므로, 4단계에서 공용 동작의 소유권을 엔진 측으로
  옮기고 desktop RPC·CLI·MCP를 각각의 진입 어댑터로 정리한다.
- RPC 메서드별 요청·응답·오류·권한 계약을 명시한다. UI 조회 모델과 저장 모델의 책임을
  구분하고, 기존 메서드 이름·request ID·revision·응답 형식을 호환하면서 내부 분리를 진행한다.
  UI의 상태 표시·중복 클릭 방지·최신 상태 확인은 유지하며 코어의 검증을 대체하지 않는다.
- 이 경계 정리는 현재 Python 제품 내부에만 적용한다. Rust는 별도 프로젝트로 분리하며,
  두 프로젝트의 엔진 교체·공통 API 통합·UI 공유·코드 동기화를 이번 계획의 목표로 두지 않는다.

## 진행 순서

| 단계 | 범위와 완료 조건 | 상태 |
|---|---|---|
| 1 | `execution` 공개 API로 실제 AI 실행·프로세스 종료·출력 처리를 추출한다. Pipeline 없이 호출할 수 있고 기존 facade 동작을 유지한다. | 완료 |
| 2 | 실행·리뷰·검증·재시도 흐름을 같은 기능 경계 안에서 나눈다. 승인·상태 전이는 한 소유자를 유지한다. | 완료 (상태·실행 조정은 Pipeline 유지) |
| 3 | 기획 요청·재시도·프롬프트 조립과 순수 계획 검증·배정을 나눈다. 외부 관제 앱과 기존 호환 동작을 유지한다. | 완료 (문서/AI·상태 조정은 기존 소유자 유지) |
| 4 | UI 독립 공용 기능 API를 추출하고 desktop RPC·CLI·MCP 어댑터를 정리한다. 기능별 handler·요청/응답 타입을 나누며 native 승인·executor·필수값 검증을 보존한다. | 완료 (상태 전이·잠금·Git 조회/변경은 Pipeline 유지) |
| 5 | 상태 모델·JSON 복원·이전 형식 호환과 상태/사용량/기획 기록 저장을 나눈다. 기존 데이터·원자적 쓰기·잠금을 유지한다. | 완료 (잠금·상태 조합·effort 트랜잭션은 StateStore 유지) |
| 6 | Git 조회·작업공간 수명·통합 처리를 분리한다. 원자적 Main 갱신·소유권·선택 파일과 승인 경계를 유지한다. | 완료 (승인·잠금·상태 조정과 guarded Main 반영은 기존 소유자 유지) |
| 7 | 알림 수집·저장·전달을 분리한다. 중복 방지·취소·수명과 실패 표시를 보존한다. | 완료 (Run 저장·사건 동기화는 기존 소유자, polling·commit은 center 유지) |
| 8 | Pipeline의 계획 생성 재시도·캐시·결과 검증·대화/문서 문맥을 기획 모듈로 옮긴다. 승인·잠금·최종 계획 적용은 유지한다. | 완료 (최종 계획 적용·강도 scope·승인·잠금은 기존 소유자 유지) |
| 9 | 기본 구조 명세·지침 생성 선택·경로 snapshot과 실행 직전 변경 재검증을 분리한다. 기존 파일 보호와 승인·잠금·계획 저장을 유지한다. | 완료 (요청 검증·잠금·계획 저장·실행 전 호출 위치는 Pipeline 유지) |
| 10 | 충돌 후보의 격리 생성·검사와 요청/반영 증거 처리를 분리한다. 승인·잠금·반영 후 전체 검증의 진입 경계를 유지한다. | 완료 (승인·UUID·run lock·반영 후 정리/verify는 Pipeline 유지) |
| 11 | 준비된 실행의 수동 인계·배정/중단·묶음 결과와 작업 순서/Git 선행 준비를 분리한다. 승인·정책 binding·초기/최종 전이와 취소 신호 소유권을 유지한다. | 완료 (승인/정책·초기 준비/전이·완료 전이 callback·Task/중지 실행은 Pipeline 유지) |
| 12 | 개별 Task 자동 복구·시도/리뷰 재개와 완료 기록을 분리한다. 실제 action/검증·정책/범위·중지·오류/기록 계약을 유지한다. | 완료 (scope/stop·실제 action/검증/모델 승격·정책·최종 저장은 Pipeline 유지) |
| 13 | Task action 실행/리뷰·검증 근거와 scope/HEAD·코드 스타일 기록을 분리한다. action context·취소·정책/SDK·저장 계약을 유지한다. | 완료 (action 등록/종료·원래 취소 신호·실제 SDK/정책·최종 저장은 이전 진입점 유지) |
| 14 | 실행 session/활성 대상·중지/체크포인트와 Task action/활동 기록을 분리한다. 소유자·attempt 경계와 잠금·저장·중지 신호를 유지한다. | 완료 (입력/채팅·원래 중지 신호·실제 실행/정책·run/SDK 수명은 Pipeline 유지) |
| 15 | Task 실행 프로필의 정규화/검증·다음 설정 저장/조회·대기 적용을 분리한다. 현재 시도·계획 revision·정책 receipt와 저장/복구 순서를 유지한다. | 완료 (update/queue 잠금·재조회/stage·승인/정책 binding·quota/실제 실행은 Pipeline 유지) |
| 16 | 자동 한도 전환·정책 receipt 일치/재적용을 분리한다. 수동/시작된 작업 보호·연결/리뷰/병렬 제한·전환 선저장과 정책 검증을 유지한다. | 완료 (한도 조회/캐시·dispatch 잠금/시작·승인/정책 binding·승격/최종 검증은 Pipeline 유지) |
| 17 | 자동 모델 승격의 증거 판정/반영을 분리한다. 코드 실패·1회 제한·시작된 정책/binding·원래 프로필/잠금/복원·저장을 유지한다. | 완료 (복구 루프·최종 정책 검증·실제 SDK/승인/정책 고정은 Pipeline 유지) |
| 18 | 실행 정책 snapshot과 현재 작업/리뷰/receipt 일치 검사를 분리한다. 승인/revision·집합/프로필·runtime·기록된 예외와 재개/호출 직전 위치를 유지한다. | 완료 (기존 재개/호출 전 진입점·승인/잠금·정책 생성/예약/binding·실제 SDK는 Pipeline 유지) |
| 19 | preview에서 고정 실행 정책 snapshot을 구성하는 부분을 분리한다. Planning/Task/리뷰·수동 예외·UUID/버전/시각과 예약/저장 위치를 유지한다. | 완료 (기존 생성 진입점·선택/검토·예약/저장/binding·실제 AI는 Pipeline 유지) |
| 20 | 실행 강도 미리보기의 Planning/Task 모델·추론/리뷰 판단 조합을 분리한다. 수동/기존/시작된 설정·가용성·보존/제외 옵션과 재검토 판정을 유지한다. | 완료 (mode/revision·상태/정책 조회·설정 저장/계획 반영/승인·실행 예약은 Pipeline 유지) |
| 21 | 강도 미리보기를 계획의 프로필/리뷰 변경안으로 조합하는 부분을 분리한다. 리뷰 명시 선택/역량·원본 복사·baseline/추가/제거와 revision/재승인/저장 순서를 유지한다. | 완료 (mode/revision·잠금/stage·그래프/readiness·계획 재승인/파일/상태/채팅 저장은 Pipeline 유지) |
| 22 | 실행 강도 상태/desktop 미리보기 조회 모델을 분리한다. 상태 재조회/expected snapshot·정책/보관 이력·후보 lazy 조회와 응답/변경 가능 표시를 유지한다. | 완료 (public/static 진입점·application/RPC/renderer 계약·쓰기/승인/revision 검증은 기존 소유자 유지) |
| 23 | 공급자 선택 목록·연결 판정/기획 실행 후보 조합을 분리한다. 역량/선택 가능·기본 프로필/정렬·인증/한도·수동/legacy 규칙과 응답을 유지한다. | 완료 (기존 진입점·status/SDK/credential·실행 파일/캐시·실제 배정/실행/설정 쓰기는 이전 소유자 유지) |
| 24 | 공급자 상태 응답 조합을 분리한다. 공급자/agent 순서·SDK/CLI·인증/키 존재·오류/미확인 표시를 유지하고 실제 probe와 민감값은 Pipeline에 둔다. | 완료 (public 진입점·SDK/credential·명령/실행 파일·실제 인증 확인과 선택/연결/application 계약은 기존 소유자 유지) |
| 25 | 기획·계획 변경 규칙을 일괄 정리한다. draft 검증/프로필 보존·같은 그룹 병합·반영 요청·결과 수정 제안/진행 조회를 기능 API로 옮기고 트랜잭션/rollback은 유지한다. | 완료 (잠금·AI/준비·최종 전이/저장·실패 복원은 Pipeline 유지) |
| 26 | 실행 복구·연결 응답 경계를 정리한다. 통합 검증 복구의 AI 호출 준비/진행/결과 조합과 Claude 연결 응답 검증/표시를 분리하고 Git/최종 상태·CLI/credential 소유권은 유지한다. | 완료 (Git 트랜잭션·최종 저장·CLI/환경/키는 기존 소유자 유지) |
| 27 | 최종 모듈 의존/공개 계약·저장/오류 경계를 점검하고 발견한 범위 내 결함을 수정한다. 기존 통과 증거를 재사용하고 필요한 관련 검사만 수행한다. | 완료 (의존/계약 점검, 추가 제품 결함 없음) |
| 28 | 필수 정리·문서와 남은 책임/미검증 범위를 확정하고 이번 리팩터링을 종료한다. 새 기능이나 추가 분리 후보로 단계를 늘리지 않는다. | 완료 (이번 리팩터링 종료) |

## 확정된 마무리 범위와 종료 기준

사용자의 28단계까지 진행 요청에 따라 26~28단계를 일괄 수행했고 **1~28단계를 완료했다.** 과거 완료 기록의
`다음 후보`는 당시 메모이며 이 표보다 우선하지 않는다. 작은 선언/호출부/회귀 수정은 해당 묶음에서
완결하고, 새 기능·별도 구조 개선은 이번 계획에 자동 추가하지 않는다.

- 마무리 범위 확정 당시 Pipeline은 9,573줄·415개 메서드이고 이 중 187개는 8줄 이하의 진입점/위임이었다.
  파일 길이를 종료 기준으로 삼지 않는다. 25/26의 명시한 규칙/조합 단위가 기능 모듈의 공개 API로
  이동하고 Pipeline에는 실제 실행 순서·권한/트랜잭션과 필요한 호환 위임이 남으면 구현 범위를 충족한다.
- 25단계 대상은 `_validated_plan_draft`, `_apply_pending_task_changes` 안의 병합/보호/그래프 규칙,
  `_new_planning_apply_request`, `_parse_result_revision_proposal`, `_planning_preview_operations`다.
  각 기능의 저장·요청 상태/rollback·실제 AI·계획 반영 승인은 기존 진입점에 둔다.
- 26단계 대상은 `_repair_verification_failure`의 복구 조합과 `_claude_connection_details`의 응답
  해석이다. branch/HEAD 재검증·실제 Git 반영·최종 상태/기록 저장, subprocess/환경/실제 키 확인을
  우회하지 않는다. 단순히 짧게 만들기 위한 client/lock·계층/서비스는 추가하지 않는다.
- `prepare_planning`, 계획 preview/대화 수행, `_begin_effort_execution`, `_step`, archive/delete,
  merge/push/deploy와 provider/Planning 호출의 정책·사용량·SDK 수명 조정은 Pipeline의 허용 책임이다.
  27단계에서는 이 소유권과 기능 모듈의 역참조/순환 의존·무제한 context 부재를 확인한다.
- 기존 public/private 진입점·오류 객체·CLI/RPC/MCP와 저장/복원 계약, 승인·취소·진행·사용량·Git
  경계가 유지되고 바뀐 부분의 정적/관련 검사가 통과하면 **코드 리팩터링을 완료**한다.
  이전 통과 증거는 재사용하며 최종 점검이라는 이유로 전체 테스트·빌드·실제 AI/앱을 실행하지 않는다.
- 실계정/화면·릴리스/ZIP·공개 저장소·commit/push/deploy는 완료 상태와 구분하며 별도 요청 범위다.
  27/28단계에서 이번 변경의 결함이 발견되면 같은 범위 안에서 수정/재확인하고, 알려진 필수 결함을
  남긴 채 완료하거나 단계를 무기한 늘리지 않는다. 범위 밖 개선은 별도 후속 항목으로 보고한다.

각 단계에서 관련 테스트를 기능별로 이동하고, 모델 데이터는 명시적 fixture factory를
사용한다. 테스트 분리는 수정한 영역만 고르기 쉽게 하기 위한 것이며 전체 실행 횟수를 늘리지 않는다.

## 1단계 계약과 영향 범위

- `execution/__init__.py`가 공개 API를, `execution/provider_runner.py`가 raw provider
  실행을 소유한다. 의존 방향은 `pipeline → execution → 기존 SDK/credential/MCP 어댑터`다.
  `execution`은 `pipeline`, `store`, `registry`, `git`을 참조하지 않는다.
- 설정 전체 대신 저장소 경로·기본 timeout·MCP 연결만 담은 불변 `ProviderRuntimeOptions`와
  SDK·credential snapshot·실행 파일 해석/종료 callback을 명시적으로 주입한다.
  실행기는 인증 파일을 조회하거나 SDK client를 새로 소유·종료하지 않는다.
- `_run_provider_command`와 기존 helper 호출은 Pipeline의 얇은 호환 계층으로 남긴다.
  실행기 고유 오류는 기존 Pipeline 예외와 메시지로 변환하며 SDK 원인 예외를 보존한다.
- 실행·수정 단계의 MCP 전달과 키 마스킹은 이동한 실행기에서 유지한다. 공유 도구 lease·
  사전 연결 확인·사용량 저장과 상태 판정은 이번 단계에서 기존 조정자에 남긴다.
- 작업 대상은 새 실행 패키지, Pipeline 위임부, 관련 테스트와 `Docs/Architecture.md`다.
  사용자 흐름·설정·저장 schema·Git 동작·제품 버전·릴리스 파일은 바꾸지 않는다.

## 2단계 첫 범위: 통합 검증 명령 실행

- `execution/verification_runner.py`가 명령 순서·NPM 의존성 복원 선택·공유 제한시간·
  출력 로그와 .NET 실패 분류를 소유한다. 작업별 검증·자동 복구 흐름은 아직 이동하지 않는다.
- 불변 `VerificationRuntimeOptions`에는 작업/로그 경로와 제한시간·이미 사용한 준비 시간만
  전달한다. 명령 실행 어댑터는 기존 비대화형 `run_command`를 재사용하며, Git 모듈 자체는
  실행기에 의존시키지 않는다. 기존 `GitError` 원인과 Pipeline 예외·메시지를 보존한다.
- Pipeline이 진행·통과 callback에서 상태를 저장하고, 실행기가 반환한 명령·실패 단계·
  코드 실패 여부로 기존 원인 후보 기록을 수행한다. 중지 확인·HEAD 확인·.NET 환경 진단은
  명시적 callback으로 주입한다. 실행기에 상태 객체·저장소·Pipeline 전체를 넘기지 않는다.
- 기존 helper 진입점은 얇은 위임으로 유지한다. 준비 시간 포함 전체 deadline, 명령별 상한,
  취소 전파, 로그 파일 이름·출력, 통과 명령 저장 순서와 파일 잠금의 자동 수정 제외를 보존한다.
- 독립 실행과 상태 기록 경계를 확인하고 기존 진행 저장·NPM 복원·timeout·.NET 환경/잠금·
  HEAD 변경 관련 케이스만 선택한다. 전체 테스트·제품 빌드·실제 AI 호출은 실행하지 않는다.

## 2단계 두 번째 범위: 작업별 검증 명령 실행

- `execution/task_verification.py`로 작업별 명령 루프·준비 시간 포함 deadline·출력/시도별
  실패 로그를 추출한다. 통합 검증과 다른 시간 제한·진행·로그 규칙을 보존하며 공통 명령
  실행 Protocol·오류와 Pipeline의 비대화형 명령 어댑터만 재사용한다.
- 실행기는 작업 ID·경로·시간 값·환경 snapshot만 담은 불변 옵션과 명시적인 callback을
  받는다. RunState·WorkTask·StateStore·Pipeline·Git 모듈을 참조하지 않는다.
- Pipeline은 작업 시작/종료·잠금·scope/HEAD 확인·검증 조건 digest와 과거 timeout 비교·
  진행/통과/코드 스타일 증거 저장을 소유한다. 실행기는 명령 실패·timeout 정보를 반환하고
  facade가 기존 TaskVerificationFailure/TaskVerificationTimeout 및 원인 예외로 변환한다.
- 준비 후 남은 예산 재확인, 명령 완료 후 전체 시간 초과 판정, 반복 timeout 차단,
  .NET 자식 프로세스에만 복구 환경 전달, 취소 전파와 실패 시 통과 처리 금지를 유지한다.
- 관련 timeout/재시도·진행/통과 기록·코드 스타일 증거·.NET 복구와 scope/HEAD 차단 검사만
  선택한다. 새로운 실행기 독립 호출·오류 변환 경계만 필요한 만큼 보강한다.

## 2단계 세 번째 범위: 리뷰 요청·응답 계약

- `execution/review.py`가 불변 `ReviewRequest`로 리뷰 프롬프트를 구성하고, 수정 요청을
  렌더링하며, `AI_REVIEW_RESULT` 응답을 파싱·검증한다. I/O와 Pipeline·모델·저장·Git
  모듈에 의존하지 않고, 경로/기준/코드 스타일/작업공간 규칙은 필요한 값만 전달한다.
- Pipeline은 최신 코드 스타일 증거 선택·snapshot 렌더링·에이전트 호출·리뷰 상태 저장·
  HEAD/clean 확인·리뷰 반복과 수정 재실행을 유지한다. 기존 helper signature와 dict 결과,
  marker import·오류 메시지·JSON 원인 예외는 호환 계층으로 유지한다.
- 잘못된 verdict가 list/dict이면 기존 set 포함 검사에서 TypeError가 발생한다. malformed
  응답을 리뷰 실패로 다루는 기존 계약에 맞춰 이 경계만 ReviewProtocolError → PipelineError로
  보완한다. 그 외 유효/무효 응답의 판정·프롬프트와 저장 형식은 바꾸지 않는다.
- 새 순수 API의 승인/수정 요청·잘못된 응답과 facade 오류 변환을 확인하고, 기존 교차 리뷰·
  수정/재시도·리뷰어의 파일/HEAD 변경 차단·코드 스타일 프롬프트 관련 케이스만 선택한다.

## 2단계 네 번째 범위: 실패 분류·재시도 판정

- `execution/recovery.py`로 통합 검증의 수정 가능 여부, 작업 실패 fingerprint, 자동 복구의
  중단/환경 재검증/코드 수정 선택과 timeout 복구 한도·조건 비교를 추출한다. 순수 함수와
  불변 결정 모델만 사용하며 Pipeline·상태/모델·저장·Git 모듈을 참조하지 않는다.
- 명령/출력·복구 횟수·반복 여부, 시간 한도 tuple과 실패 digest/최신 검증 metadata만 받는다.
  기존 dict 응답의 kind/reason_code/한도/fingerprint/변경 항목 순서와 해시 입력을 유지한다.
- Pipeline은 실패 이력의 선택·scope 확인·HEAD 조회·상태/증거 저장·모델 변경·실제 재실행과
  사용자 승인 처리를 유지한다. 기존 private helper는 공개 정책 API에 위임해 호환한다.
- 파일 잠금 → .NET 접근 오류 → 복구 횟수 한도 → 동일 조건 반복의 우선순위를 보존한다.
  기존 정책과 timeout/default 값·메시지·저장 형식은 변경하지 않는다.
- 새 정책의 독립 판정과 우선순위, 기존 반복 실패 중단·환경 1회 재검증·timeout 한도/조건
  변경·최신 복구 fingerprint 차단 관련 케이스만 선택하고 전체 테스트·빌드는 실행하지 않는다.

## 2단계 다섯 번째 범위: 작업 실행·자동 수정 요청문

- `execution/task_prompts.py`에 불변 작업/부트스트랩 지침 snapshot과 작업 요청·자동 수정·
  중단 후 이어하기/구현 메모·사용자 확인 수정 지시의 순수 렌더링을 둔다. RunState·WorkTask·
  저장·Git 모듈과 I/O를 참조하지 않고, 코드 스타일도 렌더링한 값으로 받는다.
- 작업공간/실행 효율 상수와 추가 지침(.NET 실행 파일·작업 강도 포함)을 같은 모듈로 옮긴다.
  기존 Pipeline 상수 import와 helper signature를 유지한다. 각 지침의 중복 방지·줄바꿈·
  작업공간 계약 위치와 기본/자동/수동 요청문을 이전과 동일하게 유지한다.
- Pipeline은 의존성/부트스트랩 지침 선택·검증된 재시도 요청 조회·중단 상태 판별·파일 저장·
  실행·상태 전이를 소유한다. 확정되지 않은 수정 지시를 새로 전달하거나 승인 경계를 바꾸지 않는다.
- 원본 작업/완료 선행 작업 보존·범위/검증 약화 금지·미신뢰 출력 안내와 마지막 12,000자
  진단 전달을 보존한다. 기존 요청문과 문자열을 대조하고 계약/부트스트랩/지침·실제 수정/
  재시도/중단 후 이어하기 관련 케이스만 선택한다. 전체 테스트·빌드는 실행하지 않는다.

## 3단계 첫 범위: 기획 요청·응답 계약과 계획 검증

- `planning/contracts.py`는 기존 Plan/PlanningSourceDocument/PlanningError와 공용 marker/
  ID·capability 정규화 계약을 소유한다. 기존 planner import는 같은 객체를 다시 노출한다.
- `planning/prompts.py`는 기존 계획 요청·실행 profile catalog·기술 구성 예제와 기획 대화/
  재시도 요청문 조립을 소유한다. 대화/재시도 조립에는 문자열·조건 값만 넘기며 문구·조건부
  continuation·추가 요청과 profile catalog의 순서를 유지한다.
- `planning/protocol.py`는 응답 파싱·필드/기술 구성 schema 검증·dict 변환을,
  `planning/validation.py`는 Task ID/범위·의존성·충돌 순서·사용자 확인의 검증을 소유한다.
  메모리의 기존 Plan/WorkTask/설정 DTO만 사용하고 파일/프로세스·Pipeline·저장·Git을 참조하지 않는다.
- 기존 planner는 문서 I/O·Markdown fallback·capability 추론·AI/리뷰어 배정과 공개 호환
  진입점으로 유지한다. 새 planning 패키지는 planner를 역참조하지 않는다. 기존 private helper를
  다른 모듈에서 우회 호출하지 않고, 공유 prerequisite 검증은 공개 API로 제공한다.
- Pipeline은 문서/지침 선택·source/base commit 검증·AI 연결/대화·timeout/캐시·재시도 횟수·
  배정·상태 저장·승인을 유지한다. CLI/RPC/MCP 이름·입출력·예외/JSON 원인·저장 형식은 바꾸지 않는다.
- 이동 코드의 AST·기존 요청문/응답을 대조하고 관련 prompt/schema/graph·외부 계획·기획
  재시도/continuation 검사만 선택한다. 문서 I/O·배정의 관련 없는 검사나 전체 테스트·빌드는 실행하지 않는다.

## 3단계 두 번째 범위: AI 배정과 기획 단계 판정

- `planning/assignment.py`로 기존 실행 AI/리뷰어 배정·공급자 라우팅·수동 override 함수를
  그대로 이동한다. 기존 planner 공개 import와 Markdown fallback의 내부 배정 연결은 공개
  API 별칭으로 유지하고 모델·배정·리뷰 정책은 변경하지 않는다.
- `planning/validation.py`에 기획 문서/지침 참조 및 초기 기술 선택·bootstrap·feature 단계의
  순수 판정을 분리한다. Plan과 경로 집합·조건 값만 받으며 실제 문서 읽기는 Pipeline에 남긴다.
  문서 읽기와 검증의 기존 순서·오류 우선순위 및 수동 프로필 보존·배정 시점을 유지한다.
- AI/대화 수명·deadline·캐시/재시도 횟수·상태 전이와 승인은 Pipeline이 소유한다.
  기존 배정/검증 본문을 대조하고 배정·수동 프로필/리뷰·기획 단계 판정의 관련 검사만 추가로
  선택한다. 이미 통과했고 영향이 없는 검사와 전체 테스트·빌드는 반복하지 않는다.

## 4단계 범위: 공용 응용 API·RPC 어댑터·실행 조회

- `application` 패키지로 프로젝트/SDK 조합과 공개 기능 facade를 옮긴다. MCP는 desktop
  transport 대신 이 API를 직접 사용하고, `DesktopApplication` import는 호환 별칭으로 유지한다.
  CLI도 공용 Pipeline 생성 API를 사용하되 기존 설정·SDK 수명과 registry override를 유지한다.
- `rpc` 패키지는 명시적인 메서드 allowlist·요청 범위/참조와 기능별 handler·입력 검증을
  소유한다. 공용 응용 오류와 RPC 오류 코드는 같은 객체의 호환 이름으로 유지한다.
  params → 메서드 → project → run → 세부 필드의 기존 검증 순서, native 승인·revision·
  request ID와 응답 형식을 보존한다. 상태/제어/장기 executor와 JSON Lines 수명은 바꾸지 않는다.
- `run_queries`로 실행 가능 상태·사용자 확인·알림/그룹 표시의 조회 판정을 추출한다.
  RunState/lock/실행 기록 DTO와 좁은 조회 callback만 받고 Pipeline·Store·Git 객체는 받지 않는다.
  조건별 Git 조회/실패 우선순위를 유지하며 실제 조회·잠금 snapshot과 상태/승인/Git 변경은
  Pipeline이 소유한다. 파일 길이만 줄이기 위한 mixin이나 새로운 전권 조정자는 만들지 않는다.
- 기존 facade/dispatcher와 추출 본문을 대조하고 입력/승인·요청 참조·SDK 소유권·MCP 소비자·
  실행 상태/사용자 확인의 관련 경계만 선택한다. 전체 테스트·renderer·빌드·실제 AI는 실행하지 않는다.

## 5단계 범위: 상태 모델·JSON 복원과 기록 저장

- 순수 `state` 패키지 안에서 공통 enum/시간·작업/실행·기획·통합·작업 강도·Run 모델을
  책임별로 나눈다. 기존 `models`는 동일 클래스의 호환 import로 유지한다. 상태 전이와
  readiness 규칙의 소유자는 RunState이며 승인 규칙이나 JSON schema 39/legacy 기본값은 바꾸지 않는다.
- JSON 복원은 `state.codec`의 필드 복원과 하위 기록 decoder로 분리한다. codec은 leaf 모델만
  참조하고 RunState나 기존 models facade를 역참조하지 않는다. RunState는 복원된 필드로
  자신을 생성하고 기존 순서대로 readiness를 갱신한다. 모델 클래스와 codec의 순환 의존을 피한다.
- `persistence`에 원자적 파일 쓰기·사용량 ledger·기획 결과 cache/대화 sidecar를 분리한다.
  StateStore는 기존 공개 경로·메서드·오류 별칭과 잠금·run 존재 확인·상태 파일 조합을 유지한다.
  ledger에는 경로/상태 읽기·잠금·쓰기 callback만 주입하며 Store/Pipeline 전체를 넘기지 않는다.
- 기존 저장 경로/형식·일시 Windows 오류 재시도·기존 파일/복구용 임시 파일 보존·사용량 중복/역행
  차단·pagination/전체 집계·삭제된 run의 늦은 callback 차단·대화 revision/오류 우선순위를 보존한다.
  캐시와 상태 저장의 서로 다른 임시 파일 정리 규칙도 통일하지 않는다. 잠금 구현과 effort 변경
  트랜잭션·알림/보관 저장은 StateStore에 남기고 실제 상태·Git 부작용 권한은 Pipeline에 유지한다.
- 모델 정의/복원 본문과 저장 처리의 이동을 대조하고, 기존 round-trip/legacy·오류·원자적 교체·
  사용량/기획 기록·실제 소비자의 관련 케이스만 선택한다. 사용자 데이터는 읽거나 마이그레이션하지 않는다.
  전체 테스트·renderer·빌드·실제 AI/Rust/공개 배포 checkout은 이번 범위에 포함하지 않는다.

## 6단계 범위: 통합 조회·Main 변경·작업공간 수명

- `integration`에 workspace layout/경계·청결/상태 조회, 보관/삭제 대상의 소유권 검증과
  정리, Main 변경 snapshot/선택 검증, 통합/복구 상태 조회와 충돌 상세/정책을 분리한다.
  기존 GitWorkspace 공개 API를 사용하고 Pipeline·Store 전체를 넘기거나 역참조하지 않는다.
- 경로는 ProjectConfig·RunState DTO로 해석하되 고정 root/legacy 기록·run ID·공유/격리
  layout과 link/junction/미등록 경로·HEAD/branch·사용자/ignored 파일 차단을 유지한다.
  보관 정리의 대상 metadata는 동일 객체에 기록하고 실제 Run 상태 저장·잠금·승인은 Pipeline이 소유한다.
- 사용량/기획과 달리 이 단계는 로컬 Git/파일 정리 부작용을 포함한다. Pipeline의 기존 승인과
  잠금 안에서만 수명 관리 API를 호출한다. SDK client 정리·실패 사건 저장은 좁은 callback으로
  연결해 기존 호출 순서와 부분 실패의 증거 보존을 유지한다. 실제 사용자 작업공간은 실행하지 않는다.
- Main 변경 서비스에는 Git·remote/Main 설정·관리 경로와 snapshot 읽기/쓰기 callback만,
  통합 inspector에는 operation/프로젝트 잠금 조회 callback만 전달한다. 현재/저장 snapshot
  비교·선택 파일·원격 실패 표현과 검증 결과/중단된 Main 반영의 판정 우선순위를 유지한다.
- 공용 PipelineError는 순환 의존을 피하는 오류 계약 모듈로 옮기고 기존 pipeline import에서
  같은 객체를 재노출한다. 다른 공개 메서드·오류·응답과 Git timeout/비대화형 옵션은 유지한다.
- Main guarded fast-forward와 승인/잠금/상태 전이·검증·실제 conflict AI 실행은 기존 소유자에
  남긴다. 파일 길이만 줄이는 mixin 대신 독립된 조회/수명/선택 작업 API를 만든다.
- 기존 코드의 이동을 대조하고 관련 workspace/보관/삭제·Main 선택/겹침·중단 복구·충돌 조회만
  임시 저장소에서 선택 검사한다. 실제 원격 push·사용자 데이터·전체 테스트·빌드·Rust는 실행하지 않는다.

## 7단계 범위: 알림 사건·조회·기록·OS 전달

- Python `notifications`를 기존 사건 생성 규칙과 조회 collector로 나눈다. 기존 공개 import와
  ID/source key·정렬·cursor/중복 판정을 유지한다. collector는 project/설정과 Run/별도 사건
  조회 callback만 받고 Pipeline/Store를 역참조하지 않는다. limit 검증과 실제 조회 순서도 유지한다.
- `persistence.notifications`가 별도 사건 파일의 ID·경로/metadata 검증과 읽기/쓰기를 소유한다.
  StateStore의 기존 공개 메서드는 같은 validator·run 경로·원자적 쓰기 callback을 연결한다.
  Run 저장 시 사건 동기화와 사용자 읽음/숨김 기록의 권한은 기존 소유자에 유지한다.
- Electron main의 `workNotifications`는 공개 center/IPC 진입점과 polling·상태 commit을 유지한다.
  `notifications/` 안에 내부 계약·기록 조작·형식 복원·파일 저장·갱신 진단·OS 전달을 분리한다.
  renderer/preload·shared wire 타입이나 RPC/IPC 이름을 바꾸지 않는다.
- OS 전달기는 queue/묶음 timer·전달 취소 epoch를, center는 polling 취소 epoch와 commit을 소유한다.
  center 종료가 양쪽을 함께 중지한다. 전달기는 현재 기록 읽기·저장과 기다림 상태 조회 callback,
  제한된 OS host만 받으며 center/bridge 전체를 넘기지 않는다. await 뒤 읽음/숨김·설정·취소 재확인과
  전달 시도 저장 후 OS 표시의 기존 순서를 유지한다.
- Python 사건/별도 파일 schema와 데스크톱 schema 4 및 1~3 복원, future schema 쓰기 차단·
  backup 복구, 안정적인 읽음/숨김 receipt, 최초 catch-up·cursor 재수신·중복 방지·실패 표시를 보존한다.
  실제 사용자 기록을 읽거나 변환하지 않고 실제 OS 알림·AI·다른 프로젝트는 실행하지 않는다.
- 이동 본문과 공개 계약을 대조하고 Python 알림 관련 검사, TypeScript typecheck와 알림 기록/
  진단·취소의 관련 Node 검사만 선택한다. 전체 renderer/제품 테스트·빌드·패키징은 실행하지 않는다.

## 8단계 범위: 계획 생성 실행과 문맥·결과 계약

- `planning.runner`가 계획 생성의 provider 세션 연속성·재시도·시간 예산·캐시·시도 기록을
  조합한다. repository/설정 값·SDK와 사용 가능한 agent/실행 프로필/검증/호출·저장 callback만
  받고 Pipeline/Store/Config 전체를 전달하지 않는다. 실제 SDK 수명과 강도 scope는 기존 소유자에 둔다.
- `planning.output`으로 문서 근거 확인·단계 검증·이전 수동 프로필 유지·모델 배정과 캐시 identity를,
  `planning.conversation`으로 제어 문장 판별·복구 문맥·응답/태스크 초안 표현을 옮긴다.
  `planning.documents`가 선택 문서 복사·digest·manifest를 소유하며 기존 저장 경로/형식은 유지한다.
- 기존 private/public 진입점은 위임 또는 같은 함수 별칭으로 유지한다. 공유 provider 실패 타입은
  `errors`에서 정의하고 기존 pipeline import에서도 동일 객체를 재노출한다. 순수 planning package의
  기본 import는 계속 I/O·Pipeline/Store/Git을 로드하지 않도록 runtime은 명시적 하위 모듈로만 연결한다.
- source root/active instruction·추가 질문·greenfield 단계의 검증 순서, 캐시 재검증·우회/손상 처리,
  SDK inactivity/비SDK 전체 시간 예산·capacity/request-limit 중단·preview 별도 진행 기록을 보존한다.
  승인·run/대화 lock·계획 revision/상태 전이·최종 저장과 실제 provider 호출의 강도 binding은 옮기지 않는다.
- 원본 메서드와 이동 본문을 대조하고 Python 구문/전역 참조·기획 import 및 직접 관련된 계획 생성/
  캐시·재시도·문서/대화·preview 소비자만 선택 검사한다. UI·Rust·전체 테스트·빌드·외부 AI는 실행하지 않는다.

## 9단계 범위: 기본 구조 명세와 파일 보호

- `planning.bootstrap`이 확정된 기술 결정에서 BootstrapSpec·AGENTS.md 미리보기를 만들고,
  생성/제외 선택에 따른 Task·명세 갱신과 계획 경로 snapshot/digest·실행 직전 재검증을 소유한다.
  repository 경로와 기존 Run/Task/명세 DTO만 받으며 Pipeline/Store/Config/Git은 참조하지 않는다.
- 기존 파일·디렉터리·symlink/junction 기록과 비추적, 제외 디렉터리·최대 10,000개 제한,
  파일 digest·변경 경로 표시·오류 원인 보존을 유지한다. 실제 AGENTS.md나 프로젝트 파일은 쓰지 않는다.
  기존 AGENTS.md 보존과 자동 주입 항목에 한정한 생성 제외/복원을 유지한다.
- Pipeline의 public/private 진입점과 BOOTSTRAP 상수 import는 유지한다. 공개 설정 요청의
  stage/revision/digest 검증·잠금·idempotency와 plan revision/이벤트·구조화 계획/Run 저장,
  실행 직전 재검증 위치와 worktree 생성 전 중단은 그대로 둔다. 저장 schema나 UI 계약은 바꾸지 않는다.
- 이동 본문·상수와 나머지 Pipeline 메서드를 대조하고 수정 Python의 구문·전역 참조·diff,
  기존 기본 구조 미리보기/변경 차단·지침 생성 선택/보존 검사를 선택한다. 기존 검사에 없는
  경로 개수 제한·읽기 오류 경계만 작게 보강한다. 전체 테스트·UI·빌드·실제 AI는 실행하지 않는다.

## 10단계 범위: 충돌 해결 후보 생성과 반영 기록

- `integration.candidates`가 detached 후보 worktree에서 고정한 충돌을 재현하고 AI 호출·진행 증거,
  허용 파일/표식·index·commit 부모·내용 digest를 검사한다. `integration.resolution`은 prepare/apply
  요청의 중복·stale·operation claim과 conflict/candidate 상태·실패/정리 증거를 조합한다.
- GitWorkspace·repo·기존 DTO와 경로/저장/조회/프로필·명령/호출/정리 callback만 받는다.
  Pipeline/Store/Config 전체를 전달하지 않고 progress 기록에는 기존 state lock을 사용한다.
  기존 실제 provider 호출·모델/추론 검증은 Pipeline의 좁은 연결 API를 재사용한다.
- Pipeline은 UUID 검증, prepare/apply의 기존 run lock·명시적 승인, 반영 뒤 정리 잠금과 verify 호출·
  검증 결과/복구 연결을 유지한다. Main/작업 HEAD·candidate revision/digest·부모 재검증과
  request 재사용·원래 오류/부분 실패 저장·cleanup 시점·최종 조회 오류 처리도 보존한다.
- 설정 fallback의 `planning.agent`는 실제 PlanningConfig 필드가 아닌 확인된 오류다. 현재 계약의
  `planning.agent_id`로 고치고 override/Run 지정이 없는 기본 AI 선택만 작은 회귀 검사로 보강한다.
  다른 기능·저장 schema·UI/외부 API는 바꾸지 않는다.
- 이동 본문/상태·저장 순서를 대조하고 수정 Python 정적 검사와 기존 실제 임시 Git 충돌→격리 후보→
  승인·반영/검증, residue 보존과 import 경계를 선택한다. 기존 검사가 놓치는 stale/tamper·실패/
  중복·진행 이벤트 경계만 작게 보강한다. 실제 AI·원격 push·전체 테스트·UI·빌드는 실행하지 않는다.

## 11단계 범위: 준비된 작업의 배정·묶음 실행과 선행 준비

- Pipeline의 `_execute`와 `_execute_with_bound_policy` 앞부분은 기존 승인·계획/프로필 검증,
  정책 binding·초기 Task 준비/재시도·EXECUTING 전이를 유지한다. 그 뒤 준비된 작업의 manual
  인계·agent 사전 확인·배정 묶음·대화/방향 변경·quota 전환·중단/실패 결과 조합만 `execution.dispatch`로 옮긴다.
- `execution.batch`는 기존 ThreadPool 수명·shared 단일/isolated max_parallel, state lock 안에서의
  future 결과·DispatchPaused/ExecutionStopped·개별 실패 격리와 저장 순서를 소유한다. 실제 작업 실행·
  SDK/정책·취소 신호/중지 확인은 기존 Pipeline callback을 사용한다. 전체 Pipeline/Store/Config는 넘기지 않는다.
- `execution.scheduling`은 기존 위험도/계획 순서·의존 관계·deferred 전파·user-check 대기를,
  `execution.preparation`은 선행 branch 병합과 Task scope baseline 기록/조상 검증을 소유한다.
  기존 공개/내부 진입점은 위임/같은 함수 별칭으로 유지하며 `_ready_tasks`·`_run_task_batch` 등의
  실행 경계 callback을 유지해 실행 중 방향 변경과 재배정 시점이 바뀌지 않도록 한다.
- 완료 그룹의 READY_TO_MERGE 전이는 기존 Pipeline callback에 유지한다. 기존 run/대화/state lock,
  user check·manual/deferred·review 재시도·partial/stop 상태·기록·저장 순서와 실제 AI 호출을 보존한다.
  Dispatcher가 Store를 역참조하지 않도록 RunLockedError 정의만 persistence.errors로 옮기고 기존
  store/pipeline import에서 동일 객체를 노출한다. 저장 형식·UI·CLI/RPC·동작 정책은 바꾸지 않는다.
- 이동 본문/순서와 소비자를 대조하고 수정 Python 정적 검사, 관련 배정·manual/선행·사용자 확인·
  방향/대화 lock·quota/stop·선택 재시도 검사만 고른다. 기존 검사가 부족한 독립 batch 실패/취소 격리만
  작게 보강한다. 전체 테스트·UI·빌드·실제 AI/원격 저장소는 실행하지 않는다.

## 12단계 범위: 개별 Task 시도·복구·완료 증거

- `execution.task_runner`가 기존 검증 실패의 자동 복구 loop·반복/환경 실패 판정·검증 전용 재시도와
  수정 프롬프트/기록을 소유한다. 최초 scope 검토와 중지 신호 객체·HEAD/범위/청결·모델 승격은
  Pipeline의 좁은 callback을 사용한다. 한도·실패 fingerprint·기존 action 증거 기준과 저장 순서는 유지한다.
- `execution.task_attempts`에서 EXECUTE/REVIEW/REVISE/VERIFY 재개·자동 수정 아티팩트/이전 로그 보존과
  리뷰 cycle을 나눈다. Git·DTO·run 경로와 executor/verification/review·결과 기록 callback만 받고
  Pipeline/Store/Config 전체를 받지 않는다. 실제 action context·SDK·검증/정책·scope/중지 검사는 남긴다.
- `execution.results`로 Task 완료 self-report·commit 파일 근거·중복 없는 완료 기록을 옮긴다.
  manual 확인 메모와 파일 근거의 confirmed/none/unavailable, verification 증거·UTC 시각·기록 형식을
  유지한다. 그룹 완료 기록과 최종 저장 시점은 Pipeline에 남긴다.
- 검증 실패/timeout의 기존 공유 오류 클래스는 execution.errors에 옮기고 pipeline import에서도
  같은 객체로 노출한다. timeout/provider/stop은 여전히 일반 검증 실패 복구와 구분하며 오류 원인·
  기존 재개 진입점·정책 binding과 모델 승격/다음 예약은 바꾸지 않는다.
- 본문/호출·오류 계약을 대조하고 수정 Python 정적 검사와 실제 영향받는 자동 수정 한도/증거·환경/
  stop·리뷰/수정 재개·완료 기록·timeout/모델 승격 소비자만 선택한다. 기존 관련 검사를 우선하며,
  전체 테스트·UI·빌드·실제 AI·원격 저장소는 실행하지 않는다.

## 13단계 범위: Task action과 변경 범위·검증 근거

- `execution.task_actions`가 기존 실행·리뷰·검증 action 안에서 prompt 구성·전송·Git 근거·scope/
  청결·commit/no-commit 검사를 조합한다. `_task_action`의 attempt/invocation 등록·기록·중지
  checkpoint와 실제 `_invoke_agent`의 정책/사용량·SDK 경계는 Pipeline callback으로 유지한다.
- `execution.task_evidence`가 공유 workspace의 다른 완료 action 범위 제외, Task 소유 변경 확인·
  scope JSONL, 계약 digest/저장된 범위 검토·기존 구현 근거와 코드 스타일 증거를 소유한다.
  기존 root-anchored path 규칙·소유 commit 우선·Git 조회 실패/표시·상태별 검토 판정 순서를 유지한다.
- `execution.verification_evidence`는 기존 TaskVerificationRunner의 시간 예산·준비/실패/통과
  callback·문맥 digest·반복 timeout/오류 원인·progress/상태 기록을 조합한다. 기존 CancellationSignal
  객체와 그 소유자의 check closure만 받아 처음 캡처한 신호를 모든 command/check에 재사용한다.
  timeout 기본값/tool은 필요한 시점에 읽고 저장 형식·오류 클래스·부분 실패를 바꾸지 않는다.
- Git·기존 DTO·action/저장/경로·검증·scope·신호/실행 callback만 전달한다. 전체 Pipeline/Store/
  Config·새 SDK client·lock은 만들지 않는다. 기존 private 진입점과 실제 검사/commit/중지 호출의
  순서를 유지하고 그룹 상태 전이·정책 binding·최종 저장/SDK 수명은 이전 소유자에 둔다.
- 이동 본문과 callback/취소 신호를 원래 흐름으로 펼쳐 대조하고 Python 정적 검사·관련 scope/
  reviewer 변조·검증 중 HEAD 변경·명령 예산/timeout·코드 스타일 근거·기존 구현 보존을 선택한다.
  기존 검사를 우선하고 새 취소 전달 경계의 소유 신호 재사용만 1개 보강한다.
  전체 테스트·UI·빌드·실제 AI/원격 저장소는 실행하지 않는다.

## 14단계 범위: 실행 제어 수명과 Task 활동 기록

- `execution.lifecycle`이 execution control session/종료·활성 대상 등록/정리·중지 확인·요청 claim/
  대상 판정·checkpoint 저장을 조합한다. 제어 lock·load/save·operation claim/load/save/result의
  좁은 callback만 받는다. Pipeline은 UUID/범위/메시지 검증·채팅 기록과 session/task 진입점,
  기존 `_StoredStopSignal` 생성/판정과 실제 실행/취소·run/정책/SDK 경계를 유지한다.
- `execution.task_activity`가 기존 state lock 안의 Task action 시작/성공/실패/중지와 finally 정리,
  progress·유효 모델 기록과 중단된 action 수집/판정을 소유한다. 활성 대상·중지 신호·checkpoint는
  기존 Pipeline callback으로 연결한다. 전체 Pipeline/Store/Config·새 lock/client는 전달하지 않는다.
- 이전 session의 execution ID·다른 owner PID·바뀐 attempt의 늦은 정리를 차단하는 기존 조건,
  종료된 action 활동 무시·중지 요청 연결/중복·병렬 대상 보존·부분 실패/confirmation_required와
  이전 running 증거 중단 기록, save/checkpoint/clear 순서·오류 원인을 유지한다. 새로운 event ID 필터나
  승인 정책을 추가하지 않고 현재 action/progress 판정과 wire/저장 형식을 그대로 보존한다.
- 중지 claim의 기존 재요청 반환은 채팅 기록을 다시 쓰지 않아야 한다. public request_stop의
  검증/생성·중복 반환·기존 채팅 요약/저장 경계는 유지한다. contextmanager의 yield/예외/finally
  의미와 중지 신호의 request/attempt/invocation 대상도 바꾸지 않는다.
- 이동 본문/수명/저장 순서를 대조하고 Python 정적 검사와 기존 중지 대상/변경·action 증거/활동/
  재개 관련 검사만 선택한다. 기존에 없는 늦은 정리/종료·중복 채팅과 실제 중지 checkpoint 경계만 작게 보강한다.
  전체 테스트·UI·빌드·실제 AI/원격 저장소는 실행하지 않는다.

## 15단계 범위: Task 실행 프로필과 대기 설정

- `execution.profiles`가 프로필 snapshot/수동 배정·정규화·추론 강도·모델/역량/리뷰 호환성 검증과
  pending 대상 검사를 담당한다. 현재 agent 목록·설정된 agent tuple·등록 모델 이름 조회와 기존
  가용성/선택 가능 여부·리뷰 호환성 callback만 받는다. 실제 credential·SDK·전체 Config를 전달하지 않는다.
  공유 정규화/강도 함수는 기존 Pipeline static 진입점에서 같은 함수로 재노출하며 오류 문구를 유지한다.
- `execution.profile_requests`가 정지 상태의 다음 설정 저장·실행 owner를 바꾸지 않는 조회/대기 저장과
  dispatch 시 적용/소비를 조합한다. sidecar load/save·상태 저장·정책 조회와 검증/Task 조회/계획 갱신
  callback만 받는다. 새 잠금·저장 형식·네트워크 서비스는 추가하지 않는다.
- Pipeline은 update/queue의 run/Planning chat 잠금과 잠금 재조회·stage 확인, 계획 승인과 정책 binding,
  자동 quota 전환·실제 dispatch/실행·채팅 명령을 유지한다. pending 검증 실패·활성 작업 거부와
  prepared/started 예약 차단, 현재 snapshot·revision 비교와 reviewer/역량 제한을 그대로 보존한다.
- receipt를 먼저 저장하고 상태/계획 저장 후 대기 항목을 소비하는 순서와 실패 원인을 바꾸지 않는다.
  원래 RunState/Task는 조회에서 수정하지 않고 malformed 기록·모델/추론 오류를 빈 결과로 숨기지 않는다.
- 이동 본문/호출과 잠금·저장 순서를 대조하고 Python 정적 검사, 기존 다음 프로필·정책 receipt/재개·
  dispatch·채팅 지정/재시도와 관련 모델/추론 검사만 선택한다. 기존 검사가 경계를 다루므로 새 테스트를
  기본 추가하지 않으며 전체 테스트·UI·빌드·실제 AI/원격 저장소는 실행하지 않는다.

## 16단계 범위: 자동 한도 전환과 정책 근거 복구

- `execution.quota`가 dispatch 직전의 자동 전환·중단 저장 재적용과 정책 receipt 일치 판정을 담당한다.
  기존 agent 목록/불변 routing 설정·TaskProfileRecords와 사용량/연결/선택 가능/리뷰 호환성·공유
  작업공간/계획 갱신 callback만 받는다. 배정은 기존 planning 공개 순수 함수와 같은 객체를 사용한다.
- 계정별 사용량 조회/캐시·credential/SDK 수명, 실제 dispatch의 Planning chat lock·Task 시작,
  최종 정책 snapshot 검증/모델 승격·그룹 실행 승인·자동 후보 초기 조회는 Pipeline에 남긴다.
  전체 Pipeline/Store/Config·비밀값·새 cache/lock/client는 전달하지 않는다.
- 미시작 pending·자동 MODE/ROUTING만 전환하고 수동/고정 rule·기존 시도/활동/결과를 보호한다.
  한도 불명 시 유지, 호환 대안 부재의 명시적 실패/원인, lazy 연결 조회와 manual-only 제외·리뷰
  계약·병렬 수 제한, receipt/상태/계획 저장 순서와 기존 revision/snapshot 재적용 조건을 유지한다.
- receipt 일치는 policy/revision/baseline/source를 먼저 검사하고 실제 선택 또는 기존 자동 모델
  승격 증거를 인정한다. 승격 판정은 기존 Pipeline callback으로 연결하고 저장 schema와 오류를 바꾸지 않는다.
  기존 private 진입점/정적 helper도 같은 함수/위임으로 유지한다.
- 이동 본문과 callback/저장 순서·배정 객체를 대조하고 Python 정적 검사와 기존 quota 전환·보호/
  불명·대안/병렬 제한·중단 재적용·정책/모델 승격·dispatch 저장 관련 검사만 선택한다. 기존 검사로
  경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 17단계 범위: 자동 모델 승격 증거와 반영

- `execution.model_escalation`에 기존 순수 승격 증거 판정과 자동 모델 승격 조합을 옮긴다.
  정책/프로필 기록 조회·quota receipt 일치·상태 저장 callback과 기존 state lock만 받는다.
  전체 Pipeline/Store/Config·credential·새 lock/client는 전달하지 않는다.
- provider/원래 모델/source·기존 승격 index·정책 버전/ID·실패 action/status/kind를 그대로 검사한다.
  환경 오류·수동 선택 제외, started binding과 정책/Task snapshot 존재 확인, quota 전환 후 원래
  프로필 복원, 잠금 안의 임시 승격/근거 불일치 시 필드 복원·이벤트/저장 순서를 유지한다.
- 기존 Pipeline static 진입점은 같은 함수를 재노출하며 `_promote_automatic_model`의 signature와
  TaskRecoveryRunner callback·최종 정책 snapshot/한도 receipt 검증의 호출 관계를 유지한다.
  승격 기준/모델·오류/저장 schema·새 정책/복구 동작은 추가하거나 바꾸지 않는다.
- 이동 본문/호출·잠금·저장 순서를 대조하고 Python 정적 검사와 기존 승격 1회/정책 원본 보존·
  변조 거부·실제 복구 루프의 승격 모델/반복 guard·환경/수동 제외·quota 전환 후 승격 검사만 선택한다.
  기존 검사로 경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 18단계 범위: 실행 정책 snapshot 일치 검사

- `execution.policy_snapshot.ExecutionPolicyValidator`가 승인된 plan revision·작업/리뷰 집합,
  현재 실행 프로필/worker runtime·리뷰 설정/runtime과 고정 정책의 일치 여부를 읽기 전용으로 검사한다.
  현재 agent mapping·프로필 기록 조회·기존 승격/quota 일치 callback만 받는다.
- 수동 receipt의 policy/revision/baseline/selection/source와 승격/quota 예외의 short-circuit 순서,
  policy 버전별 리뷰 검사와 원래 오류·조회 시점을 유지한다. 잘못된 기록을 기본값/성공으로 숨기지 않는다.
  새 검증 기준·상태 쓰기·저장 schema·오류 타입은 추가/변경하지 않는다.
- Pipeline은 `_validate_effort_execution_snapshot` signature와 started binding 재개·AI 호출 직전의
  호출 위치/순서를 유지한다. 실제 승인·잠금·정책 생성/예약·binding 수명·agent 호출별 추가 검사·
  SDK/credential은 이전 소유자에 둔다. 전체 Pipeline/Store/Config·새 client/lock은 전달하지 않는다.
- 이동 본문과 callback/오류/조회 순서·나머지 호출부를 대조하고 Python 정적 검사와 기존 snapshot
  drift/수동 receipt·worker/reviewer·재개/호출 차단·승격/quota 근거·이전 정책 호환 검사만 선택한다.
  기존 검사로 경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 19단계 범위: 고정 실행 정책 snapshot 구성

- 기존 `execution.policy_snapshot`에 `build_execution_policy_snapshot`을 추가한다. 현재 RunState·
  EffortModePreview와 agent mapping·기본 Planning agent ID만 받아 기존 ResolvedEffortPolicy를 만든다.
  전체 Pipeline/Store/Config·SDK/credential·저장/잠금 callback은 받지 않는다.
- RunState의 Planning agent 우선/기본값 대체·현재 모델/추론/source, Task 순서별 프로필과
  preview의 리뷰 required/optional/reason·정책 추가/기존 리뷰 대체 조건·reviewer provider/model,
  수동 예외/미지원 항목을 그대로 복사한다. 없는 agent/preview 항목을 임의 기본값으로 숨기지 않는다.
- UUID·버전 3·execution scope·plan revision·UTC 시각을 기존 순서/호출 시점에 생성한다.
  `_resolved_execution_policy` signature와 호출 위치는 유지하고 승인/worker/reviewer 재검사·
  preview 생성/검토·정책 예약/RunState 저장/started binding 수명·실제 AI는 Pipeline에 남긴다.
  기존 validator·저장 schema·정책 선택/모델/리뷰 동작은 바꾸지 않는다.
- 이동 본문·호출/객체/생성 순서와 기존 validator/나머지 Pipeline을 대조하고 Python 정적 검사와
  기존 정책 생성/예약/저장·중단/재개·수동 설정/다음 예약·리뷰 snapshot·Codex/Claude 호환 검사만 선택한다.
  기존 검사로 경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 20단계 범위: 실행 강도 미리보기 조합

- `execution.effort_preview.EffortPreviewBuilder`로 Planning/Task의 모델·추론과 리뷰 판단 조합을 옮긴다.
  현재 agent mapping·설정된 agent tuple·기본 Planning agent ID·필수 리뷰 여부와 기존 리뷰 호환성/
  선택 가능/가용성 callback만 받는다. 전체 Pipeline/Store/Config·SDK/credential·새 client/lock은 받지 않는다.
- 기존 effort_policy의 DTO/순수 판단 함수를 같은 객체로 사용한다. Planning 우선/기본값, provider/
  model 대체, 수동 예외/legacy·시작된 작업 보호, 정책 추가 리뷰의 제거/필수 리뷰 보존과 미지원/
  재검토 판정·Task 순서를 유지한다. 저장된 실행 프로필 보존과 runtime 제외 ID 전달도 바꾸지 않는다.
- 후보 호환성→역량→선택 가능 여부의 lazy 조회와 기존 reviewer의 별도 가용성 확인을 유지한다.
  미리보기는 상태/설정을 저장하지 않으며 오류를 임의 결과로 숨기거나 새 리뷰/모델 정책을 추가하지 않는다.
- 기존 `_effort_mode_preview` signature와 public preview의 mode/revision 검증·정책/상태 조회,
  실행 재개/보존 호출 위치를 유지한다. 설정 저장·계획 반영/승인·정책 예약과 실제 AI는 Pipeline에 남긴다.
- 이동 본문/옵션·callback/조회 순서와 나머지 호출부를 대조하고 Python 정적 검사와 기존 읽기 전용
  미리보기·수동/legacy·리뷰 가용성/적용·모델 고정/보존·저장 프로필 복구 관련 검사만 선택한다.
  기존 검사로 경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 21단계 범위: 강도 적용의 프로필·리뷰 변경안

- `execution.effort_plan`에 변경된 RunState 사본과 전체/Planning 변경 여부의 결과 DTO,
  미리보기/리뷰 선택을 검증하고 변경안을 만드는 EffortPlanApplicator를 둔다. 현재 agent mapping·
  기본 Planning agent ID와 기존 agent 가용성/리뷰 호환성/선택 가능 callback만 받는다.
- baseline/리뷰 미지원·필수 reviewer 검사, 새로 리뷰할 Task 집합과 명시 선택 집합의 일치·
  가용성→호환성→역량→선택 가능 순서, 원본 deepcopy 뒤 Planning/Task의 모델/추론/source·
  baseline·선택 이유와 정책 추가 리뷰의 제거/추가·review 상태, strict zip/변경 flag를 유지한다.
- Pipeline은 mode/계획 revision 검증·run/Planning chat 잠금과 stage/archive/시작 여부·정책 revision/
  선택 모드 확인·미리보기 조회를 유지한다. 변경안 반환 뒤 그래프 검증/readiness·계획 revision/
  재승인과 계획 파일/상태·Planning 변경 시 기존 채팅 저장 순서도 원래 위치에 둔다.
  원본을 직접 수정하거나 저장 schema·리뷰 기준·오류/승인·부분 실패 처리를 바꾸지 않는다.
- 전체 Pipeline/Store/Config·SDK/credential·새 lock/client는 전달하지 않는다. 기존 public method의
  signature/반환과 변경 없는 경우 사본 반환·비저장도 유지한다.
- 이동 본문과 전/후 잠금·revision/저장 순서·변경 flag를 대조하고 Python 정적 검사와 기존 명시적
  reviewer/재승인·모드 추가/제거/baseline·필수/legacy 보존·가용성/역량과 실제 적용 호출 검사만 선택한다.
  기존 검사로 경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 22단계 범위: 실행 강도 조회 모델

- `execution.effort_queries`가 상태/desktop 미리보기 응답과 상태 비교 key·예약 가능 순수 판정을 소유한다.
  상태/정책 읽기·잠금 상태·보관 정책 존재 조회의 좁은 records와 기존 미리보기/agent 목록·선택 가능/
  연결 공급자/리뷰 호환 callback만 받는다. 전체 Pipeline/Store/Config·SDK/credential·경로는 받지 않는다.
- 상태→정책/현재 binding/snapshot→선택/예약 모드 미리보기→잠금→최신 상태→보관 정책 순서와
  expected_state 비교·editable/reserve/cancel·일관성 사유, Planning 이력/마지막 변경 기록을 유지한다.
  정책 참조 오류/깨진 기록을 legacy나 빈 결과로 바꾸지 않는다. 경로/존재 확인은 기존 Store callback이다.
- desktop 미리보기의 preview→상태 재조회/revision 검사·asdict/Task 순서와 새 정책 리뷰일 때만
  agent 목록/선택 가능 확인, 연결→호환성→역량 필터·reviewer_options/can_apply 판정을 유지한다.
  agent 목록 callback은 원래 조회 지점에서 읽으며 응답 field·enum/null/bool 의미를 바꾸지 않는다.
- 기존 Pipeline public signature/반환과 static 진입점은 같은 위임/함수로 유지한다. 설정/예약/계획
  반영의 쓰기·승인·잠금·revision 검증, application/RPC adapter와 renderer 계약은 바꾸지 않는다.
  새 저장·자동 refresh/retry·client/lock은 만들지 않는다.
- 이동 본문·입력/옵션/읽기 순서·기존 호출부를 대조하고 Python 정적 검사와 기존 읽기 전용/가용성/
  후보·예약/상태 일치·깨진 정책·보관 Planning 이력·application/RPC 응답 관련 검사만 선택한다.
  기존 검사로 경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 23단계 범위: 공급자 선택과 기획 실행 후보 조회

- `execution.provider_choices`에 실행/기획 선택 목록과 기획 실행 후보를 조합하는 ProviderChoiceQueries,
  redacted ProviderStatus callback으로 연결을 판정하는 connected_provider_ids를 둔다. agent 목록/
  공급자 균형 설정·가용성/선택 가능·기존 연결 조회·계정 사용량 callback만 받는다.
- 실행 목록의 역량/선택 가능·연결 필터/정렬과 기획 목록의 NVIDIA 제외·기본 프로필 우선·기존
  select_agent_for_provider·PlanningError skip·ProviderChoice field/기본 표시/정렬을 유지한다.
  연결은 공급자 정렬 순서와 기존 설치/인증 true 조건을 그대로 적용하며 실제 status 조회는 Pipeline callback이다.
- 기획 실행 후보의 가용성→균형 설정→연결/한도와 commandless custom legacy 후보 추가 순서를
  유지한다. 목록/설정은 기존 지점에서 callback으로 읽고 실제 수동 전용/제외 규칙·순수 배정 함수와 같은 객체를 쓴다.
  새 가용성/인증·모델·한도 규칙을 추가하거나 실패/미확인을 기본 성공으로 바꾸지 않는다.
- 기존 public/private 진입점과 연결 callback 호출 관계를 유지한다. provider_statuses·SDK/credential/
  실행 파일 확인·사용량 캐시·실제 배정/작업 실행/설정 쓰기와 application/RPC 계약은 이전 소유자에 둔다.
  전체 Pipeline/Store/Config·비밀값·새 SDK/cache/client/lock은 전달하지 않는다.
- 이동 본문/입력·lazy 조회/정렬과 기존 호출부를 대조하고 Python 정적 검사와 기존 연결/인증 matrix·
  재연결/키 제거·역량/기본 프로필·기획 균형/한도·수동 설정·배정/호출과 응답 관련 검사만 선택한다.
  기존 검사로 경계를 다루며 새 테스트·전체 테스트·UI·빌드·실제 AI/원격 저장소는 기본 추가/실행하지 않는다.

## 24단계 범위: 공급자 상태 응답 조합

- `execution.provider_status.ProviderStatusQueries`가 기존 ProviderStatus 목록을 조합한다. agent 목록과
  현재 SDK의 account_status callback 또는 None·실행 파일 probe·NVIDIA 키 존재/등록 방식 bool·
  Claude 인증 상태 callback만 받는다. 실제 SDK/키·전체 Pipeline/Store/Config는 전달하지 않으며
  명령 구성/인자 확인은 Pipeline probe 안에서 처리한다.
- Pipeline의 SDK 참조는 생성 시 고정되는 기존 수명을 사용한다. account 조회는 해당 공급자에서만
  수행하고 CodexSdkError·SDK 없음/로그아웃·외부 CLI 불필요 표시와 공급자/agent 순서를 유지한다.
- 실행 파일 probe는 기존 `_agent_command(execute) or review_command`와 빈 명령/미해결 처리를
  Pipeline에 둔다. 새 조립부에는 실행 파일 결과만 전달하며 자식 실행·새 resolver/client/lock은 만들지 않는다.
- NVIDIA 키 값은 Pipeline callback 안에 두고 기존 bool/model-key 우선/환경 대체와 CLI/키 안내 우선순위,
  Claude의 기존 executable/인증 callback·미확인/실패와 auth label/field를 유지한다. 계정 세부/비밀값을
  새 응답에 추가하거나 인증 실패를 성공으로 바꾸지 않는다.
- public provider_statuses signature와 선택 목록·연결/사용량·application/RPC 소비자를 유지한다.
  이동 본문/조회/예외/응답과 probe 확장을 대조하고 Python 정적 검사·기존 SDK/로그인/인증 matrix·
  sanitized Claude/API 키·NVIDIA 존재/CLI/요청 격리 관련 검사만 선택한다. 기존에 없는 새 probe 경계의
  SDK 없음·review_command 대체/빈 명령 건너뛰기만 1개 보강한다.
  전체 테스트·UI·빌드·실제 AI/원격 저장소는 실행하지 않는다.

## 25단계 범위: 기획·계획 변경 규칙 일괄 정리

- `planning.changes`가 draft parsing/배정·수동/legacy/리뷰 보존, 같은 그룹의 보호 Task/새 Task
  병합/그래프 검사 결과, 반영 요청 revision/중복/응답 구성과 결과 수정 제안을 맡는다.
  `planning.preview`는 기존 잠금/진행 DTO로 진행 중 작업 표시만 파생한다.
- agent/routing/등록 모델 이름·선택 모드 조회, bootstrap 보호·실행 후보·가용성/리뷰 호환과
  대화 메시지/문맥·수정 가능 Task/계획 draft/근거 경로 callback만 명시적으로 받는다.
  전체 Pipeline/Store/Config·새 client/lock·독자적 승인/저장은 전달하지 않는다.
- 원래 parsing/오류·legacy/manual/source/baseline·리뷰 보존·Task 순서, 중복 요청 반환/추가 응답과
  보호된 완료 결과/실행 이력, progress 사건의 owner/time 조건을 바꾸지 않는다.
- Pipeline은 같은 그룹의 stage/활성 작업 확인·원본 rollback snapshot·AI/준비·최종 전이/계획/상태/
  대화 저장·실패 복원과 기존 진입점을 유지한다. 병합 결과 DTO는 tasks/준비 ID만 돌려준다.
- 이동 본문·입력/결과/콜백과 앞뒤 트랜잭션 순서를 대조하고 기존 계획 편집·같은 그룹 완료/실패
  보존·요청 중복/추가 답변·결과 제안/근거·preview 활동 관련 검사만 선택한다.

## 검증과 종료 기준

### 26~28단계 일괄 진행 범위

- 26: `execution.verification_repair`는 기존 가용 Agent 우선순위, 실패 로그/허용 경로에 따른 prompt와
  호출 준비·중지/진행 callback·결과 Task/검증 시도를 조합한다. 전체 Pipeline/Store/Config와 Git을 받지 않는다.
  Pipeline은 작업공간 생성/정리·청결/HEAD·변경 범위/실제 commit/branch 갱신·최종 복구 근거 저장을 유지한다.
- `execution.claude_connection`은 JSON 해석 뒤 payload/종료 코드/앱 키 사용 여부 bool만으로 기존
  구독/API/외부 인증·미확인 응답을 만든다. CLI 실행·환경/키·timeout·JSON 오류 처리는 기존 진입점에 둔다.
- 기존 검사가 실제 통합 검증 복구 본문을 실행하지 않으므로 새 경계의 취소/실패·Git 반영/정리 순서만
  국소 회귀 검사로 보강한다. 기존 Claude 응답/앱 키 관련 검사를 재사용하며 실제 AI/계정은 호출하지 않는다.
- 27: 이번 계획에서 분리한 기능 패키지와 직접 진입 어댑터의 의존 방향·공개 import/오류/모델·RPC route,
  저장/복원 경계를 정적으로 확인한다. 전체 저장소 리뷰나 재검증으로 확대하지 않는다.
- 28: 발견한 필수 누락만 같은 범위에서 정리하고 완료 기록·남겨 둔 Pipeline 책임과 미검증 범위를 확정한다.
  새 후보·빈 패키지·Git 발행 작업은 추가하지 않는다. 기존 문서 경로는 링크 호환을 위해 유지한다.

수정 파일의 기존 정적 검사·diff와 공개 import 경계를 확인한다. 각 단계에서 옮긴 책임의
관련 테스트만 선택하고, 기존 검사가 다루지 못하는 독립 API·실패·호환 경계만 보강한다.
후속 수정은 실패하거나 수정한 부분만 다시 확인하며 통과한 전체 선택을 반복하지 않는다.
실제 AI·사용자 인증·다른 프로젝트·Unity·전체 테스트·전체 renderer·빌드·패키징은 실행하지 않는다.
관련 확인이 통과하면 그 단계의 결과와 다음 대상을 기록하고 종료한다. commit·push는 별도 요청 범위다.

## 진행과 결과

착수 전 원본 main이 clean임을 확인했다. 1단계 실제 AI 실행부 추출을 완료했다.

- `execution` 공개 API와 377줄의 `provider_runner.py`를 추가했다. 실행기는 저장소 경로·
  기본 timeout·MCP 연결만 담은 불변 옵션과 주입된 SDK·credential·callback으로 호출된다.
- Pipeline의 기존 호출 signature·예외·메시지와 SDK 원인을 유지했다. SDK 수명·사용량 기록·
  공유 도구 점유·승인·상태 전이의 소유권은 기존 위치에 유지했다. Pipeline은 14,517줄에서
  14,291줄로 줄었다. 실행 본체는 명시적인 API/옵션/오류 이름 변환 외에 기존 AST와 같음을 확인했다.
- 새 실행기 독립 호출·SDK 요청/오류/소유권, 기존 UTF-8·입력 한도·중단·timeout·출력 drain,
  Claude/NVIDIA 키 마스킹·사용량과 MCP 전달·대기 등 관련 검사 33개가 통과했다.
  최종 선택 실행 결과는 `33 passed, 384 deselected`다.
- 공개 실행 패키지만 import해도 Pipeline·store·registry·Git 모듈이 로드되지 않는 경계를
  확인했다. 수정 Python 파일 구문과 diff 검사도 통과했다.
- 실제 AI·사용자 인증·Unity·다른 저장소·Rust·전체 테스트·renderer·빌드·패키징과
  commit·push는 실행하지 않았다. 공개 릴리스 checkout과 기존 ZIP은 변경하지 않았다.

2단계 첫 범위인 통합 검증 명령 실행부 추출을 완료했다.

- `VerificationRunner`로 명령 실행 순서·NPM 복원 선택·공유 제한시간·출력 로그와 .NET
  실패 분류를 옮겼다. Pipeline은 상태·진행·통과 기록·실패 원인 후보와 Git 확인을 소유한다.
  불변 경로/시간 옵션과 명시적인 callback만 전달하며 기존 `GitError` 원인과 취소를 보존한다.
- 기존 helper 호출과 import를 유지했다. 이동한 순수 helper 5개의 AST 본문이 이름 변경 외에
  동일하며 다른 Pipeline 메서드 429개가 바뀌지 않았음을 확인했다. Pipeline은 14,291줄에서
  14,115줄로 줄었다. 작업별 검증과 자동 복구·리뷰·재시도 조정은 기존 위치에 남겼다.
- 독립 실행·공유 시간 예산·로그/통과 순서·중지/HEAD 오류 전파·기존 진행 저장·NPM 복원·
  timeout·.NET 환경/파일 잠금과 HEAD 변경 차단 관련 검사 결과는
  `30 passed, 312 deselected, 11 subtests passed`다. 이후 테스트 assertion 표현만 단순화한
  5개 케이스를 재확인했으며 `5 passed, 4 deselected`로 통과했다.
- 공개 execution import의 Pipeline·store·registry·Git 비의존, 수정 파일 구문·diff를 확인했다.
  변경 범위에 따라 전체 테스트·renderer·빌드·패키징·실제 AI 호출은 실행하지 않았다.
  commit·push·공개 릴리스와 Rust 프로젝트는 변경하지 않았다.

2단계 두 번째 범위인 작업별 검증 실행부 추출을 완료했다.

- `TaskVerificationRunner`가 명령 루프·준비/명령 완료 후 deadline 확인·진행 통지·현재/시도별
  로그와 .NET 자식 환경 전달을 소유한다. 경로·시간·환경 tuple snapshot과 좁은 callback을
  받고, 상태·Git 모듈을 참조하지 않는다. 통합 검증과 기존 명령 어댑터를 공유한다.
- 작업 상태와 검증 조건 digest·동일 timeout 차단·통과 기록·코드 스타일 증거·scope/HEAD
  확인·자동 복구 판정은 Pipeline에 유지했다. 기존 공개 오류 클래스·메시지·속성과 GitError/
  OSError 원인·취소 전파도 보존했다. Pipeline은 14,115줄에서 14,096줄로 줄었다.
- 기존 명령 어댑터 본문과 다른 Pipeline 메서드 429개의 AST가 그대로임을 확인했다.
  이전 공개 오류 생성자와 현재 생성자의 메시지·속성도 대조했다.
- 실행기 독립 호출과 timeout/원인 오류·진행/통과 저장·.NET 복구·파일 잠금·scope/HEAD·
  코드 스타일 증거, 공유 어댑터의 통합 검증 관련 선택 실행 결과는
  `40 passed, 5 subtests passed`(51.46초)다. `tests/execution/test_task_verification.py`,
  `tests/test_task_verification_timeouts.py`와 관련 기존 nodeid만 실행했다.
  `python -m py_compile`로 수정 Python 파일을 확인했고 `git diff --check`도 통과했다.
- 변경 영향에 따라 전체 테스트·renderer·제품 빌드·패키징·실제 AI 호출은 실행하지 않았다.
  commit·push·공개 릴리스와 Rust 프로젝트는 변경하지 않았다.

2단계 세 번째 범위인 리뷰 요청·응답 계약 분리를 완료했다.

- `execution.review`에 불변 `ReviewRequest`, 리뷰/수정 프롬프트 렌더링과 응답 파싱을
  옮겼다. 필요한 값만 전달하며 I/O·상태/모델·저장·Git 모듈에 의존하지 않는다.
  기존 helper signature·marker import·dict 결과·PipelineError와 JSON 원인 예외를 유지했다.
- 리뷰 응답의 verdict가 list/dict일 때 TypeError로 빠지던 경계를 명시적인 리뷰 형식 오류로
  보완했다. 정상 승인/수정 요청과 나머지 검증 규칙·오류 메시지는 유지했다.
- 리뷰어 호출·리뷰/수정 반복·상태 기록·scope/HEAD/clean 확인은 기존 위치에 남겼다.
  다른 Pipeline 메서드 429개의 AST가 바뀌지 않았고, 자동/수동·기준 유무에 따른 리뷰
  프롬프트 4개와 수정 프롬프트 4개가 이전과 동일함을 대조했다. 파서도 오류 타입과
  verdict 타입 검사 외에 AST 본문이 같다. Pipeline은 14,096줄에서 14,019줄로 줄었다.
- `python -m pytest -q`로 새 리뷰 API 파일과 기존 관련 nodeid 7개를 선택해
  `22 passed`(13.26초)를 확인했다. 승인/수정 요청·잘못된 응답·오류 변환·독립 import,
  교차 리뷰/수정·실패 리뷰 재시도·리뷰어의 파일/커밋 변경 차단·코드 스타일 요청을 다뤘다.
  수정 Python 파일의 `python -m py_compile`과 `git diff --check`도 통과했다.
- 변경 범위에 따라 전체 테스트·renderer·제품 빌드·패키징·실제 AI 호출은 실행하지 않았다.
  commit·push·공개 릴리스와 Rust 프로젝트는 변경하지 않았다.

2단계 네 번째 범위인 실패 분류·재시도 판정 분리를 완료했다.

- `execution.recovery`에 통합 검증의 수정 가능 여부·실패 fingerprint·timeout 판별·복구
  한도·조건 비교와 불변 `AutomaticRecoveryDecision`을 추가했다. 필요한 문자열·tuple·
  최신 검증 metadata만 받으며 I/O·Pipeline·상태/모델·저장·Git 모듈에 의존하지 않는다.
- 파일 잠금 → .NET 접근 오류 → 복구 횟수 → 동일 실패 반복의 우선순위를 유지했다.
  환경 변경 후 1회 재검증과 기존 중단 이유·dict 응답·fingerprint·변경 항목 순서도 같다.
  scope/HEAD 확인·상태/증거 저장·모델 변경·실제 재실행과 사용자 승인 처리는 Pipeline에 남겼다.
- 이전 코드와 자동 복구 판정 64개, retry 응답/해시 36개, 한도/이벤트 5개를 대조했다.
  fingerprint/수정 가능 분류 본문과 이전 timeout 판별도 동일함을 확인했다. 실제 재실행·중지·
  상태/Git 처리 블록과 다른 Pipeline 메서드 426개의 AST가 바뀌지 않았다.
  Pipeline은 14,019줄에서 13,984줄로 줄었다.
- `python -m pytest -q`로 새 정책 API 파일과 기존 관련 nodeid만 선택해
  `29 passed, 4 subtests passed`(61.36초)를 확인했다. 복구 우선순위·저장된 실행 파일/
  fingerprint 호환·timeout/한도 변경·최신 조건 차단·반복/횟수 제한·파일 잠금·환경 재검증과
  작업 범위/실패 증거 보존을 다뤘다. 수정 Python 파일 구문과 `git diff --check`도 통과했다.
- 변경 범위에 따라 전체 테스트·renderer·제품 빌드·패키징·실제 AI 호출은 실행하지 않았다.
  commit·push·공개 릴리스와 Rust 프로젝트는 변경하지 않았다.

2단계 다섯 번째 범위인 작업 실행·자동 수정 요청문 분리를 완료했다.

- `execution.task_prompts`에 불변 `TaskPromptRequest`/`BootstrapInstructionSnapshot`과 작업·
  자동 수정·재시도/중단 후 이어하기·작업공간/실행 효율/.NET/강도 지침의 순수 렌더링을
  추가했다. 기존 상수 import와 helper signature는 Pipeline의 호환 계층으로 유지했다.
- 작업 범위·선행 작업·기존 결과 보존, AGENTS.md 생성/보존/제외, 미신뢰 진단 출력의 마지막
  12,000자 전달과 작업공간 계약 위치를 유지했다. 지침 선택·요청 조회/유효성 확인·파일 저장·
  실행과 상태 전이는 Pipeline에 남겼으며 모델·저장·Git 객체를 렌더링 모듈에 넘기지 않는다.
- 이전 코드와 작업 요청문 20개·.NET 지침 18개·작업 강도 전체·자동 수정 12개·재시도/메모/
  중단 문맥 24개를 비교해 문자열과 재시도 조회 호출이 같음을 확인했다. 작업공간/효율 상수,
  실행·상태·파일/수정 지시 유효성 확인 블록과 다른 Pipeline 메서드 424개의 AST도 유지됐다.
  Pipeline은 13,984줄에서 13,754줄로 줄었다.
- `python -m pytest -q`로 새 요청문 API 파일과 관련 기존 nodeid만 선택해
  `19 passed, 2 subtests passed`(17.19초)를 확인했다. 작업공간 계약·.NET/효율/강도 지침·
  부트스트랩/기존 지침 보존·코드 스타일 snapshot·확인 전 수정 지시 차단·자동 수정의 범위/
  실패 증거 보존을 다뤘다. 수정 Python 파일 구문과 `git diff --check`도 통과했다.
- 변경 범위에 따라 전체 테스트·renderer·제품 빌드·패키징·실제 AI 호출은 실행하지 않았다.
  commit·push·공개 릴리스와 Rust 프로젝트는 변경하지 않았다.

이로써 2단계의 실행기·검증·리뷰 계약·복구 정책·작업 요청문 경계 분리를 완료했다.
상태·승인·실행 순서와 Git 부작용 조정은 원칙대로 Pipeline에 유지한다.

3단계 기획 요청·응답·검증·배정 분리를 완료했다.

- `planning` 패키지를 contracts/prompts/protocol/validation/assignment로 나눴다. 기존
  Plan/PlanningSourceDocument/PlanningError 객체와 공개 함수는 planner 호환 진입점에서도
  동일하게 사용할 수 있다. 공유 경로/배정 helper는 공개 API와 로컬 호환 별칭으로 연결했다.
- 기획 대화·재시도·continuation·추가 요청·profile catalog 조립과 schema·Task/사용자 확인·
  문서 참조/기획 단계 검증, 공급자/AI/리뷰어 배정을 분리했다. 기존 모델·수동 프로필·리뷰
  정책과 dict/schema·문구·JSON 원인 예외를 유지했다. 문서 읽기 순서·배정 시점과 AI/대화 수명·
  deadline·캐시/재시도 횟수·상태/승인 처리는 기존 조정자에 남겼다.
- 이동한 정의 29개와 남은 legacy 정의 12개 및 모든 상수를 AST로 대조했다. 공유 helper의
  공개 이름 변경 외에 본문이 같고, 다른 Pipeline 메서드 427개와 AI/캐시/timeout·수동 프로필/
  상태/승인 처리 블록도 유지됐다. 계획 요청 24개·대화 8개·시도 요청/호출 선택 128개도 이전과 같다.
- 첫 선택 검사에서 `42 passed, 7 failed, 40 subtests passed`를 확인했다. 실패 원인은 문서
  I/O에서 공유하던 경로 검증 연결 누락이었으며 공개 validate_relative_paths와 호환 별칭으로
  수정했다. 실패 소비자와 해당 문서 읽기 경계만 다시 실행해 `10 passed, 10 subtests passed`
  (6.61초)를 확인했다. 통과했고 영향이 없는 검사는 반복하지 않았다.
- 이어서 배정·수동 모델/리뷰·legacy fallback·기획 단계·문서 오류 우선순위·기존 SDK 기획/
  수동 프로필 보존 관련 nodeid만 선택해 `34 passed, 14 subtests passed`(25.04초)를 확인했다.
  새 planning 패키지의 planner/Pipeline·문서 I/O·저장·Git 비의존과 공개 타입/오류 호환,
  수정 파일 구문·전역 참조·diff도 확인했다. 외부 계획 수신과 승인/최신 revision 차단 관련
  기존 선택 검사 결과도 재사용했다. 실제 MCP 전송이나 실계정 AI 호출을 실행한 것은 아니다.
- planner.py는 1,454줄에서 225줄로, Pipeline은 13,754줄에서 13,666줄로 줄었다. 전체 테스트·
  renderer·제품 빌드·패키징·commit·push·공개 릴리스와 Rust 프로젝트는 변경/실행하지 않았다.

4단계 공용 기능 API·RPC 어댑터·실행 조회 분리를 완료했다.

- `application.OrchestratorApplication`으로 UI 독립 facade와 프로젝트/SDK 조합을 옮기고,
  같은 패키지의 `create_pipeline`을 CLI에서도 사용한다. MCP는 desktop RPC를 import하지 않는다.
  기존 DesktopApplication/RpcError는 같은 클래스/오류 객체의 호환 별칭이다. 기존 SDK 수명·
  credential snapshot·registry override와 프로젝트 등록 변경 검증을 유지했다.
- RPC는 연결·프로젝트·기획·실행·통합·그룹 조회 6개 handler와 입력 검증으로 나눴다.
  정확한 메서드별 global/project/run 범위와 공통 요청/route·성공/실패 frame 타입을 정의했다.
  기존 122개 메서드의 처리 AST·101개 프로젝트 메서드 allowlist와 참조 검증 범위를 대조했다.
  승인·필수값의 순서, request ID/revision·반환값·오류와 executor/stdio 수명은 유지됐다.
- `run_queries`로 실행 상태·사용자 확인·주의 항목·활동 분류를 옮겼다. 잠금·기록 DTO와
  좁은 조회 callback만 받으며 원래 분기의 순서대로 조회한다. branch 실패를 실행 가능으로
  숨기지 않고, Pipeline은 Git 조회/오류 수집·잠금 snapshot과 상태·승인·부작용을 유지한다.
  나머지 Pipeline 메서드 424개와 응용 API 메서드 128개의 AST도 그대로임을 확인했다.
- RPC 전체 메서드의 입력/승인 계약과 API 독립 호출·오류 우선순위·실제 stdio 초기 조회를
  다룬 관련 선택 실행은 `95 passed`(7.79초)다. 이어서 상태/잠금·branch 불일치·사용자 확인·
  주의 항목·worker MCP 설정/승인·CLI SDK/registry·MCP 계획 gate/제어 receipt 관련 선택
  실행은 `61 passed`(24.60초)다. 총 156개 관련 검사이며 제품 전체 테스트를 실행한 것은 아니다.
  이동 코드 대조에서 호출 이름 치환 오류 2곳과 누락 참조를 검출해 테스트 전 수정했다.
  수정/신규 Python 23개 파일의 구문·공백과 `git diff --check`를 확인했고 공용 별칭·응답
  frame 타입·MCP server import도 통과했다. 응답 타입 annotation 추가 뒤 테스트는 반복하지 않았다.
- `desktop_rpc.py`는 2,013줄에서 251줄로, Pipeline은 13,666줄에서 13,389줄로 줄었다.
  Pipeline은 여전히 크다. 상태 저장/복원과 Git 통합·작업공간의 조정 책임은 5·6단계에서
  분리하며 기존 기획/실행의 상태 전이 경계도 계속 검토한다. 파일 길이만 줄이는 분할은 하지 않는다.
- 전체 테스트·renderer·제품 빌드·패키징·실제 AI/MCP 전송·commit·push·공개 릴리스와
  Rust 프로젝트는 변경/실행하지 않았다. 실제 stdio 검사는 데스크톱 backend의 초기 조회다.

5단계 상태 모델·JSON 복원과 기록 저장 분리를 완료했다.

- `state`를 common/effort/planning/execution/integration/run/codec으로 나눴다. 모델 정의
  97개를 대조했으며 공통 helper의 공개 이름 변경과 RunState/RunSummary의 복원 위임 외에
  정의·필드·기본값·상태 규칙은 같다. `models`는 동일 객체를 재노출하는 호환 facade다.
- RunState의 JSON 필드 복원과 하위 기록 decoder, RunSummary의 가벼운 요약 복원을
  분리했다. 추출한 하위 식을 다시 펼쳐 이전 AST와 비교해 기본값·필드 평가 순서가 같음을
  확인했다. `from_dict`의 호출 subclass 생성과 readiness 갱신 순서도 유지했다. state 패키지는
  Store/Pipeline/models facade를 역참조하지 않으며 내부 의존이 순환하지 않음을 확인했다.
- `persistence.atomic`으로 파일 교체/재시도를, `UsageLedger`로 사용량 읽기·중복/역행 차단·
  갱신·전체 집계/pagination을, `persistence.planning`으로 결과 cache와 대화 payload/revision
  복원을 옮겼다. 이전 원자적 쓰기 본문·사용량 7개 메서드·대화 payload/오류 처리와 같음을
  대조했다. 새로 미사용이 된 Store의 private usage helper 2개와 관련 import는 제거했다.
- StateStore의 나머지 메서드 94개와 Pipeline 파일은 그대로다. 잠금·존재 확인·상태/보관
  쓰기·effort 트랜잭션·알림의 기존 소유권, schema 39/legacy 기본값·파일 경로·오류 타입·
  Windows 재시도와 복구용 임시 파일 보존·캐시의 별도 정리 정책을 유지했다.
- `tests/test_models.py`, 새 codec 독립/subclass 경계와 관련 Store nodeid 선택 결과는
  `38 passed, 13 deselected, 17 subtests passed`(0.71초)다. 사용량 ledger 관련 선택 실행은
  `27 passed, 1 skipped, 7 deselected`(2.88초)이며 POSIX 전용 권한 케이스 1개는 Windows에서
  건너뛰었다. 사용량 callback·실제 desktop stdio 초기 조회·effort 저장/복원·기획 기록·CLI
  소비자는 `17 passed, 4 subtests passed`(1.31초)다. 총 82개 관련 검사와 21개 subtest이며
  실제 AI/MCP 전송·GUI 검사나 전체 제품 테스트를 실행한 것은 아니다.
  수정/신규 Python 17개 파일의 구문·전역 참조·공백·150자 제한, 공개 모델 별칭과
  `git diff --check`도 통과했다. 문서 기록을 마친 뒤 통과한 검사를 반복하지 않았다.
- `models.py`는 2,451줄에서 호환 import 190줄로, `store.py`는 1,287줄에서 998줄로
  나눴다. 새 모델 파일은 최대 650줄이다. Pipeline은 이번 단계에서 수정하지 않았으며
  여전히 13,389줄이다. 저장소/모델 분리 자체를 Pipeline 축소나 전체 분리 완료로 보고하지 않는다.
- 사용자 상태 파일·다른 저장소·Rust·공개 릴리스 checkout은 읽거나 변경하지 않았다.
  전체 테스트·renderer·빌드·패키징·commit·push도 실행하지 않았다.

6단계 통합 조회·Main 변경·작업공간 수명 분리를 완료했다.

- `integration`을 layout/workspaces/lifecycle/inspection/main_changes/conflicts/main_review로
  나눴다. workspace 고정/legacy root·공유/격리 경계·청결/정리 가능 상태, 보관/삭제 대상의
  소유권·정리, Main 변경 snapshot/선택·검증, 통합/복구 상태·충돌 상세/정책·반영 검토를 옮겼다.
  Git·DTO·설정과 필요한 읽기/쓰기 callback만 전달하며 Pipeline/Store 전체는 전달하지 않는다.
- 공용 오류 계약 `errors.PipelineError`를 기존 pipeline import에서도 동일 객체로 재노출한다.
  이동한 46개 메서드의 본문·조건/평가 순서·기본값과 충돌 요청문/fingerprint를 대조했다.
  나머지 Pipeline 메서드 385개와 Git 어댑터는 그대로다. 기존 공개 메서드와 Main 변경의
  승인·잠금 진입부, shared 정리의 SDK 해제/부분 실패 저장/완료 저장 위치도 유지했다.
- 실제 Main guarded fast-forward, conflict AI 호출, 검증·상태 전이·잠금·승인·저장은
  기존 소유자에 남겼다. 수명 관리 API는 동일 보관 target metadata만 갱신하고 Pipeline이
  최종 Run을 저장한다. 새로 미사용이 된 private bridge 11개와 관련 import를 제거했다.
- workspace/보관/삭제/SDK 부분 정리와 독립 API의 선택 실행은 처음
  `24 passed, 1 failed, 6 subtests passed`(49.33초)였다. 새 경계 검사는 기존 legacy 경로
  검증에서 더 먼저 차단됐고, 기대 오류 문구만 수정한 해당 1개가 `1 passed`(0.15초)로 통과했다.
  통과했던 다른 검사는 반복하지 않았다.
- Main 선택 커밋·충돌 후보/조회·중단 복구·겹침·실행 잠금 관련 선택 실행은
  `12 passed, 5 failed, 2 subtests passed`(34.98초)였다. 실패는 모두 제품 코드에 도달하기
  전 임시 로컬 bare Git 저장소로 최초 push하는 fixture 단계였다. 해당 단계만 짧은 trace로
  확인한 뒤 실패한 4개 함수만 샌드박스 밖에서 재실행해
  `4 passed, 5 subtests passed`(33.98초)를 확인했다. 실제 원격 저장소에는 접근하지 않았다.
- 수정/신규 Python 11개 파일의 구문·전역 참조·공백·신규 줄의 150자 제한과
  `git diff --check`, 공개 오류 alias와 독립 import를 확인했다. 테스트를 위해 제품 코드를
  우회하거나 기존 실패 판정을 완화하지 않았다.
- Pipeline은 13,389줄에서 12,335줄로 1,054줄 줄었다. 새 통합 모듈 파일은 최대 410줄이다.
  기획·실행·통합의 상태 조정은 여전히 Pipeline에 남아 있으며 전체 분리 완료로 보고하지 않는다.
  실제 사용자 작업공간·다른 저장소·Rust·공개 릴리스 checkout은 변경하지 않았다.
  전체 테스트·renderer·빌드·패키징·사용자 저장소 commit/push/deploy는 실행하지 않았다.

7단계 알림 사건·조회·기록·OS 전달 분리를 완료했다.

- Python `notifications`를 events/collection과 기존 공개 import를 유지하는 package로 나눴다.
  `NotificationCollector`는 project/설정·Run/별도 사건 조회 callback만 받는다. 기존 사건 생성
  정의, collector의 검증·병합·정렬·cursor 본문과 `persistence.notifications`로 옮긴 저장/복원
  메서드 3개의 AST를 대조했다. 나머지 Pipeline 메서드 424개와 Store 메서드 102개는 그대로다.
- 별도 사건 저장은 StateStore의 기존 validator·run 경로·원자적 writer를 연결한다. Run 저장·
  동기화·읽음 처리의 권한을 바꾸지 않았고 기존 ID/source key·저장 schema·충돌/손상 오류를 유지했다.
- Electron `workNotifications`는 center의 polling·commit·공개 API를 유지하고 내부
  contracts/records/codec/storage/refresh/delivery를 분리했다. 원래의 TypeScript 선언 49개와
  OS 전달 메서드 3개 본문을 대조했고, center의 위임·취소 세대 이름 변경 외 기존 메서드도 일치한다.
  전달기는 queue/timer·전달 취소를 소유하고 center 종료가 polling과 전달 모두를 중지한다.
  center/bridge 전체를 전달하지 않으며 현재 기록·저장·대기 근거 조회 callback과 OS host를 받는다.
- 읽음/숨김 receipt·schema 1~3 복원/4 저장·future 쓰기 차단·backup 복구·최초 baseline·
  pagination 원자성·중복 방지·조회/전달 오류 구분과 await 중 읽음/숨김/설정/종료 처리를 유지했다.
  renderer/preload/shared DTO·IPC/RPC 이름은 바꾸지 않았다.
- Python 알림 사건·새 collector 실패 경계·기존 대기 근거 소비자의 선택 실행은 처음
  `22 passed, 1 failed`(2.01초)였다. 기존 대기 안내가 쓰던 사건 생성 import가 빠진 것을 복구했고
  실패한 1개만 재실행해 `1 passed`(0.64초)를 확인했다. 총 23개 관련 케이스를 확인했다.
  데스크톱 알림 기록·갱신 진단/취소의 Node 검사 32개(0.99초)와 `npm run typecheck`가 통과했다.
  수정/신규 Python 7개 파일의 구문·전역 참조·신규 파일 150자 제한과 diff/공백을 확인했다.
- `workNotifications.ts`는 870줄에서 293줄로 줄었고 새 셸 알림 파일은 최대 214줄이다.
  Pipeline은 12,335줄에서 12,313줄로, Store는 998줄에서 969줄로 줄었다. 이번 단계의 주요
  분리 대상은 셸 알림이며 Pipeline 상태 조정 전체를 분리한 것은 아니다.
- 실제 사용자 기록·OS 알림·AI·다른 저장소·Rust·공개 릴리스 checkout은 읽거나 실행/변경하지 않았다.
  전체 테스트·전체 renderer·실화면·빌드·패키징·commit·push·deploy는 실행하지 않았다.

8단계 계획 생성 실행·문맥·결과 계약 분리를 완료했다.

- `planning.runner.PlanningRunner`가 기존 계획 생성 루프를 소유한다. Pipeline은 구체적인
  PlanningConfig/RoutingConfig·repository·SDK와 agent/프로필/배정 후보·Git 변경 조회·검증·
  provider 호출을 연결하고 `PlanningPersistence`에 run 경로/상태·preview 진행·결과 cache callback만 넣는다.
  Store/Pipeline/전체 Config를 전달하지 않는다. 실제 provider 호출·강도 binding·SDK 소유권과
  승인·잠금·계획 적용·최종 상태 전이는 기존 소유자에 남긴다.
- `planning.output`으로 문서 근거·greenfield 단계 검증·수동 프로필 유지·모델 배정과 캐시
  fingerprint를, `planning.conversation`으로 명시적 반영 문장 판별·저장 문맥·응답/Task 초안을,
  `planning.documents`로 선택 문서 복사·digest·manifest를 옮겼다. 기본 planning import는 계속 순수하며
  runtime 모듈만 명시적으로 I/O·SDK/기존 planner helper를 사용한다. 새 의존성은 추가하지 않았다.
- 이동한 메서드 14개의 본문/계약과 제어 문장 정규식·상수, 공용 provider 실패 클래스 4개를
  AST로 대조했다. 나머지 Pipeline 메서드 411개는 그대로다. 기존 private 진입점은 같은 함수
  별칭/위임이고 실패 클래스는 `errors`와 기존 pipeline import가 같은 객체를 노출한다.
- 최초 검사 수집에서 multiline 요청문을 포함한 함수의 들여쓰기 오류를 발견했다. 함수 선언
  들여쓰기를 바로잡고 문자열 값/본문의 AST 일치를 확인한 뒤 관련 케이스를 실행했다.
  선택 결과는 `25 passed, 307 deselected, 44 subtests passed`(42.45초)다. 정상/dirty/손상 cache,
  timeout 예산·SDK inactivity·실패 중단/재시도·세션 복원·문서 snapshot/근거·preview 수동 모델·
  대화 제어/요구 구분과 greenfield 검증을 확인했다. 새 테스트는 추가하지 않았다.
- 수정/신규 Python 7개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백과 공개 오류/
  helper 별칭을 확인했다. planning 기본 import의 I/O/작업 소유자 미로딩도 기존 검사로 확인했다.
  통과한 관련 검사는 문서/주석 정리 뒤 반복하지 않았다.
- Pipeline은 12,313줄에서 11,747줄로 566줄 줄었고 새 기획 파일은 최대 359줄이다.
  남아 있는 큰 책임은 실제 실행 묶음 조정·기획 적용·greenfield 기본 구조 명세·충돌 후보 적용이다.
  다음 후보는 기본 구조 명세/경로 snapshot과 실행 직전 재검증의 책임 분리이며 착수 시 범위를 기록한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout은 변경하지 않았다. 실제 AI/OS 알림·
  전체 테스트·전체 renderer·빌드·패키징·commit·push·deploy는 실행하지 않았다.

9단계 기본 구조 명세·지침 선택과 경로 보호 분리를 완료했다.

- `planning.bootstrap`으로 BootstrapSpec 생성·digest, 파일/디렉터리/link snapshot과 파일 hash,
  실행 직전 기술 결정/대상/경로 재검증 및 AGENTS.md 생성 제외/복원 시 명세 갱신을 옮겼다.
  `BootstrapPlanner`는 repository 경로와 기존 DTO만 받고 Pipeline/Store/Config/Git을 참조하지 않는다.
  문서 렌더링은 기존 greenfield_instructions를 재사용한다. 프로젝트 파일은 생성/수정하지 않는다.
- Pipeline의 공개 설정 요청은 기존 잠금·stage/revision/digest 검증, 변경 없는 선택의 반환,
  plan revision·이벤트·구조화 계획 갱신·Run 저장을 유지한다. 실행 전 재검증의 위치와 workspace
  생성 전 중단도 그대로다. 기본 구조 helper는 같은 함수/위임이고 기존 상수 import를 유지한다.
  이동 결과 미사용이 된 관련 모델/렌더링 import만 제거했다.
- 이동한 메서드 6개의 본문과 상수 4개를 AST로 대조했고 나머지 Pipeline 메서드 409개는 그대로다.
  지침 선택 본문을 기존 진입점에 다시 펼쳐 검증·idempotency·잠금·revision/저장의 순서를 비교했다.
  Bootstrap 모듈이 Pipeline/Store/Git/registry를 로드하지 않는 독립 import도 확인했다.
- 기존 기본 구조 미리보기/파일 변경의 실행 차단·기존 지침 보존·생성 제외/복원 관련 검사 2개가
  통과했다. 추가한 경로 제한(파일·디렉터리)과 읽기 오류 원인 보존 3개는 최초에 날짜별 임시 폴더가
  없어 setup에서 시작하지 못했다(`2 passed, 309 deselected, 3 errors`, 2.46초).
  작업 전용 부모 폴더를 만든 뒤 실행하지 못했던 3개만 다시 실행해 `3 passed`(0.14초)를 확인했다.
  제품 코드의 실패나 기대값을 완화한 것은 아니며 총 5개 관련 케이스를 확인했다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백과 helper/상수
  호환을 확인했다. 저장 schema·UI·실행 정책은 바꾸지 않았고 통과한 관련 검사는 반복하지 않았다.
- Pipeline은 11,747줄에서 11,543줄로 204줄 줄었고 새 기본 구조 모듈은 254줄이다.
  후속 후보는 Pipeline의 충돌 해결 후보 준비·증거 기록·반영 조정이며 실제 승인/잠금/Git 변경 경계를
  확인한 뒤 다음 단계 범위를 정한다. 이번에는 해당 흐름을 수정하지 않았다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout은 변경하지 않았다. 실제 AI·전체 테스트·
  전체 renderer·실화면·빌드·패키징·commit·push·deploy는 실행하지 않았다.

10단계 충돌 해결 후보 생성·검사와 요청/반영 기록 분리를 완료했다.

- `integration.candidates`로 충돌 재현·요청문/로그·AI 호출·진행 증거와 허용 파일/표식·index·
  commit 부모·내용 digest 검사를, `integration.resolution`으로 요청 claim·중복·stale 검증과
  후보/반영 상태·실패/정리 증거를 옮겼다. Git 어댑터·DTO·repository와 필요한 좁은 callback만 받는다.
  `ConflictResolutionRecords`는 상태 저장·operation claim/저장 세 기능만 연결한다.
- Pipeline은 기존 prepare/apply UUID·현재 충돌 검증과 run lock, 명시적 승인·모델/추론 검증·실제
  provider 호출, 반영 후 정리 잠금·verify와 복구 검증 연결을 유지한다. 후보 생성의 마지막 조회도
  같은 try 안에서 실행해 조회 실패가 기존 실패/정리 경로를 우회하지 않도록 했다.
- 확인된 기본 AI fallback의 `planning.agent` 오류를 실제 필드 `planning.agent_id`로 고쳤다.
  지정 override/Run agent가 없을 때 설정 AI를 선택하는 회귀 검사로 확인했다. 다른 모델 선택·
  request digest·저장 schema·진행 이벤트의 attempt/invocation 검증은 유지했다.
- 새 모듈의 본문·프로필/명령 조립·증거 전달을 원래 진입점으로 다시 펼쳐 AST로 대조했다.
  기본 agent 필드 수정 외 prepare의 Git/AI·진행/claim·저장/실패/정리 순서는 같고, apply의 승인·
  중복·잠금·HEAD/내용/부모 검증·fast-forward·정리·verify 순서도 같다. 나머지 Pipeline 메서드
  410개는 그대로이며 기존 private digest API와 기능 API의 독립 import도 유지했다.
- 실제 임시 Git 충돌→격리 후보/허용 범위 실패→진행 이벤트→중복 생성→승인/반영/검증,
  비어 있지 않은 residue 보존, import 경계와 새 stale Main/변경된 후보 차단·중복 반영 차단·
  설정 AI fallback만 선택했다. 처음에는 새 fallback fixture의 필수 ExecutionConfig 누락으로
  `6 passed, 1 failed, 311 deselected`(11.31초)였다. fixture를 실제 Config 계약에 맞춰 고친 뒤
  실패한 1개만 실행해 `1 passed`(0.24초)를 확인했다. 총 7개 관련 케이스이며 실제 AI/원격 push는 없다.
- 수정/신규 Python 6개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff를 확인했다.
  새 테스트는 기존 검사에 없던 변경/중복 차단과 실제 설정 fallback 경계만 보강했으며 통과한 검사를
  문서 정리 뒤 반복하지 않았다. 사용자 작업공간이나 다른 저장소의 상태는 건드리지 않았다.
- Pipeline은 11,543줄에서 11,260줄로 283줄 줄었다. 새 파일은 candidates 197줄·resolution 239줄이다.
  다음 후보는 실행 묶음의 준비·스케줄/중단·결과 조정이다. 실제 실행/취소/정책 binding 호출 경계를
  확인한 뒤 후속 범위를 정하며 이번 단계에서는 수정하지 않았다.
- Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·패키징·commit·push·deploy는 실행/변경하지 않았다.

11단계 준비된 Task의 배정·묶음 결과와 선행 준비 분리를 완료했다.

- `execution.dispatch`에 manual 인계·agent 사전 확인·실행 묶음·중단/실패·대화/방향/모델/한도
  변경의 조합을 옮겼다. Pipeline은 승인·정책 binding·확정 계획/프로필 검증과 초기/재시도 준비·
  EXECUTING 전이를 유지하며 완료 그룹 전이도 기존 callback을 사용한다. DispatchRecords는 기존
  상태 읽기/쓰기·대화 lock API만 연결하고 전체 Store/Pipeline/Config는 전달하지 않는다.
- `execution.batch`는 기존 ThreadPool·max_parallel/shared 단일 처리와 state lock 안에서의
  future 완료·DispatchPaused·ExecutionStopped·독립 실패/리뷰 실패·중지 확인·저장을 소유한다.
  실제 작업 실행/취소 신호와 SDK·정책은 기존 callback에 남았다. `execution.scheduling`에 위험도/
  계획/의존 순서·deferred 전파·user-check 대기를, preparation에 선행 branch·scope baseline 준비를 옮겼다.
  기존 `_ready_tasks`·`_run_task_batch`와 Task 준비 hooks는 계속 같은 실행 경계에서 호출한다.
- 이동한 8개 메서드의 배정/준비 callback을 원래 본문으로 펼쳐 AST로 대조했다. manual/자동
  배정·락·중지·방향/모델 변경·실패·최종 저장 순서가 같고 나머지 Pipeline 메서드 408개는 그대로다.
  StateStore 클래스 본문 전체도 그대로이며 RunLockedError 정의만 persistence.errors로 옮겼다.
  store/pipeline/dispatcher import가 동일 오류 객체임과 실행 API의 Pipeline/Store 미로딩을 확인했다.
- 선행/위험도·scope baseline·실행 파일 복원·manual/deferred·선택/리뷰 재시도·작업 준비 표시·
  방향 변경/실패·대화 lock·batch 뒤 계획 반영·사용자 확인·한도 전환 기록 후 호출의 기존 검사와
  새 독립 batch 실패/일시 중단/중지/성공 격리 1개를 선택했다. 결과는
  `19 passed, 324 deselected, 4 subtests passed`(68.68초)다. 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 9개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  public/helper 오류 호환을 확인했다. 실제 AI·사용자 상태·다른 저장소·Rust·공개 checkout은 건드리지 않았다.
- Pipeline은 11,260줄에서 11,003줄로 257줄 줄었다. 새 dispatch/batch/preparation/scheduling 파일은
  각각 180/59/83/56줄이다. 다음 후보는 개별 Task 실행 시도와 리뷰/검증 재개 조정이며,
  실패·중지·재시도 정책/기록과 실제 호출 소유권을 확인한 뒤 후속 범위를 정한다.
- UI·전체 테스트·전체 renderer·빌드·패키징·실제 원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

12단계 개별 Task의 복구·시도/리뷰 재개와 완료 기록 분리를 완료했다.

- `execution.task_runner.TaskRecoveryRunner`에 검증 실패의 반복/환경 분류·수정/검증 전용 재시도와
  prompt/상태 증거를 옮겼다. 최초 scope 검토·중지 신호 생성과 HEAD/범위/청결·모델 승격은 기존
  Pipeline callback을 사용하며 수정 한도·실패 fingerprint·기존 구현 action 시작 기준과 lock/저장 순서를 유지한다.
- `execution.task_attempts`의 TaskAttemptRunner/TaskReviewCycles로 실행·리뷰·수정·검증 재개와
  자동 수정 아티팩트/이전 로그 보존, 리뷰 반복을 옮겼다. 실제 executor/verification/review·action
  context·SDK·정책 binding과 저장/오류 처리는 기존 진입점이며 Pipeline/Store/전체 Config를 전달하지 않는다.
- `execution.results`에 제한된 worker report·commit 파일 증거·중복 없는 Task 완료 기록을 옮겼다.
  confirmed/none/unavailable과 실패 이유·manual 메모·검증 성공 기록·UTC 시각은 같으며 그룹 기록과
  최종 저장 시점은 그대로다. TaskVerificationFailure/Timeout은 execution.errors에서 정의하고 기존
  pipeline import와 동일 객체로 노출한다. timeout/provider/stop은 여전히 검증 실패 복구로 흡수하지 않는다.
- 기존 6개 메서드 본문/순서를 callback 확장 후 AST로 대조했고 공유 오류 클래스 2개의 정의도 같다.
  나머지 Pipeline 메서드 409개는 그대로다. 중지 신호는 기존 소유자가 만들고 check closure만 전달한다.
  Task 실행 API의 Pipeline/Store 미로딩과 기존 오류·worker report 별칭의 동일 객체도 확인했다.
- 자동 수정 계약/이전 증거·재리뷰·한도/반복·환경 검증 재시도·중지/변조 거부·기존 구현 보존,
  리뷰/수정 재개·완료 기록·모델 승격/반복 guard·검증 전용 실행/timeout 비수정의 관련 검사만 선택했다.
  `17 passed, 339 deselected, 12 subtests passed`(101.43초)이며 새 테스트는 추가하지 않았다.
  실패나 후속 동작 수정은 없었고 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 6개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff를 확인했다.
  오류 정의 제거 자리의 공백 정리 뒤 해당 Python 구문만 확인했다. 저장 schema·CLI/RPC·UI 계약은 바꾸지 않았다.
- Pipeline은 11,003줄에서 10,838줄로 165줄 줄었다. 새 task_runner/task_attempts/errors/results는
  각각 99/140/22/52줄이다. 다음 후보는 실제 Task action의 실행/리뷰/검증 근거 수집과 scope/HEAD·
  기록 조합이며, action context·취소·정책/SDK 호출의 소유권을 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

13단계 Task action·scope/HEAD·검증 근거 조합 분리를 완료했다.

- `execution.task_actions`로 실행/리뷰/검증 action의 prompt·전송·Git 근거·범위/청결·commit/no-commit와
  리뷰 JSON을 옮겼다. 기존 `_task_action` 등록/종료·attempt/invocation·중단 checkpoint와 실제
  `_invoke_agent`의 정책/사용량·SDK 경계는 같은 callback이다. 중지 check도 처음 캡처한 신호를 재사용한다.
- `execution.task_evidence`에 공유 workspace의 완료 action 범위 제외·소유 변경 우선·scope JSONL과
  계약 digest/저장된 scope 검토·경로 규칙·기존 구현/코드 스타일 근거를 옮겼다. Git 조회 실패와 위반
  로그/오류를 보존하고 Root private 진입점은 같은 함수/위임으로 유지했다. 전체 Pipeline/Store는 전달하지 않는다.
- `execution.verification_evidence`는 기존 runner의 command/전체 시간 예산·문맥 digest·반복 timeout·
  progress·준비/실패/통과 기록·원인 unwrap을 조합한다. TaskCancellation은 기존 신호 객체와 check
  closure만 전달하며 command/check가 같은 소유 신호를 재사용한다. timeout 기본값/tool은 기존 시점에 읽는다.
- 이동한 13개 메서드의 prompt/callback/취소 전달을 원래 본문으로 펼쳐 AST로 대조했다.
  action context·범위 소유/로그·HEAD/commit·예산/문맥·진행/예외/저장 순서가 같고 나머지 Pipeline
  메서드 403개는 그대로다. action context·정책/SDK·그룹 전이와 저장 형식은 바꾸지 않았다.
- bounded Git/action·scope 위반/소유 commit/다른 완료 Task 제외·리뷰어 변경/검증 중 HEAD 변경·
  scope 검토·기존 구현·progress/코드 스타일·반복 timeout/총 예산/명령 불가/원인 보존의 기존 케이스와
  새 취소 신호 재사용 1개만 선택했다. `25 passed, 310 deselected, 8 subtests passed`(48.69초)다.
  새 케이스는 두 command가 같은 소유 신호를 받고 factory가 한 번만 호출되는 경계를 확인한다.
  실패나 추가 동작 수정은 없었으며 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 6개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff, scope/style
  helper 별칭과 실행 API의 Pipeline/Store 미로딩도 확인했다. 관련 import만 옮겼고 새 의존성은 추가하지 않았다.
- Pipeline은 10,838줄에서 10,552줄로 286줄 줄었다. task_actions/task_evidence/verification_evidence는
  각각 137/197/151줄이다. 다음 후보는 Task action/진행 상태 기록과 중단 checkpoint 연결이며
  상태 소유권과 오래된 활동/종료 이벤트 차단을 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

14단계 실행 제어 수명·Task action/활동 기록 분리를 완료했다.

- `execution.lifecycle`은 execution control의 session/종료·활성 대상 등록/정리·중지 claim/대상 판정/
  확인·checkpoint를 조합한다. execution ID·owner PID·attempt 조건과 병렬 대상·중지 연결/부분 실패를
  그대로 유지한다. 제어 lock·load/save·operation claim/load/save/result callback만 받는다.
- `execution.task_activity`는 기존 state lock 안의 action 시작/성공/실패/중지·finally 정리,
  progress/유효 모델 기록과 중단 수집/판정을 소유한다. 활성 대상·신호·checkpoint는 기존 Pipeline
  진입점으로 연결하며 기존 action/이벤트 수신 조건·상태/예외/저장 순서를 바꾸지 않는다.
- Pipeline의 입력 정규화/UUID·scope/메시지 검증, 채팅 기록과 재요청의 조기 반환을 유지했다.
  `_StoredStopSignal`·생성/판정, `_step`과 실제 SDK/정책·run 경계는 그대로다. 기존 Pipeline의
  DispatchPaused/TaskActionResult import도 같은 객체를 재노출한다. 전체 Pipeline/Store/Config는 전달하지 않는다.
- 이동한 13개 메서드 본문과 request_stop의 검증·payload/digest·claim/잠금 판정·채팅을 나눠
  callback 확장 후 AST로 대조했다. 14개 기존 signature/decorator와 나머지 Pipeline 메서드 404개는 같다.
  실행 API가 Pipeline/Store를 로딩하지 않는 것과 수정/신규 Python 6개 파일의 구문·전역 참조·
  신규/수정 줄의 150자 제한·공백/diff를 확인했다.
- 기존 중지 대상/호출 변경·검증 중지·활동 시각/저장·action 증거 보존/실패/재시도·중단 재개·
  legacy 복원과 환경 재검증 중지 케이스를 선택했다. 새 검사는 늦은 attempt 정리·이전 session 종료·
  재요청의 채팅 중복 방지·실제 중지 신호의 action/checkpoint/종료 저장 4개다.
  `14 passed, 339 deselected, 3 subtests passed`(19.89초)이며 실패·추가 동작 수정 없이 통과했다.
  문서/재노출 import 정리 뒤 구문·diff만 확인하고 통과한 관련 검사는 반복하지 않았다.
- Pipeline은 10,552줄에서 10,279줄로 273줄 줄었다. lifecycle/task_activity는 각각 267/166줄이다.
  다음 후보는 Task 실행 프로필의 검증·대기 설정 적용이며 정책 binding·sidecar 트랜잭션과
  승인/현재 시도 경계를 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

15단계 Task 실행 프로필·다음 설정 저장/대기 적용 분리를 완료했다.

- `execution.profiles`로 snapshot/수동 배정·공유 정규화/강도·pending 대상 판정과 다음 프로필·
  모델/추론 override 검증을 옮겼다. 현재 agent 목록·설정 tuple·등록 모델 이름과 가용성/선택 가능/
  리뷰 호환 callback만 받는다. root static 진입점 7개는 같은 함수이고 검증 3개는 위임한다.
- `execution.profile_requests`의 불변 TaskProfileRecords/TaskProfileService는 기존 sidecar·정책 조회/
  상태 저장과 Task 조회/검증/계획 갱신 callback으로 다음 설정 저장·조회·대기 저장/적용을 조합한다.
  실행 중인 owner 상태를 건드리지 않는 조회, snapshot/revision과 보호된 상태/예약 검사, 수동 지정·
  receipt 선저장/부분 실패·재개/소비 순서를 유지한다. 저장 schema·오류 문구/원인을 바꾸지 않았다.
- update/queue의 run/Planning chat 잠금·잠금 재조회·stage 확인은 Pipeline에 남겼다. 현재 run_id도
  그대로 전달하고 계획 승인·정책 binding·dispatch·quota 전환·채팅 명령과 실제 실행은 그대로다.
  전체 Pipeline/Store/Config·credential 값·새 lock/client는 전달하지 않는다.
- 이동/분할한 기존 진입점 14개의 본문/정규화·callback·기록 순서를 AST로 대조했다. 7개 static
  별칭의 인자/반환 계약과 나머지 7개 진입점 signature, queue의 기존 잠금/재확인 prefix도 같다.
  나머지 Pipeline 메서드 406개는 그대로이며 실행 API가 Pipeline/Store를 로딩하지 않는 것도 확인했다.
- 기존 다음 프로필의 성공/실패/보호 상태·오래된 시도/모델·잠금 경합·조회/저장·계획 변경·malformed·
  중간 상태 저장/소비 실패와 재개를 선택했다. 고정 정책 receipt/다음 강도 예약·다른 인스턴스의
  dispatch·실패 재시도·채팅 지정/저장 후 재시도·등록 NVIDIA 모델과 공유 모델/추론 호출도 확인했다.
  `43 passed, 420 deselected, 7 subtests passed`(17.18초)이며 새 테스트·실패·추가 동작 수정은 없다.
  통과한 관련 검사는 반복하지 않았다.
- 수정/신규 Python 4개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와 static 별칭을
  확인했다. 새 의존성·CLI/RPC/UI 계약은 추가/변경하지 않았다.
- Pipeline은 10,279줄에서 10,099줄로 180줄 줄었다. profiles/profile_requests는 각각 148/160줄이다.
  다음 후보는 자동 한도 전환과 정책 receipt의 일치/재적용이며 한도 조회·수동 지정 보호와
  dispatch/정책 binding 경계를 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

16단계 자동 한도 전환·정책 receipt 검사/재적용 분리를 완료했다.

- `execution.quota.QuotaFallbackService`로 dispatch 전 미시작 자동 Task의 한도 전환·중단 기록 재적용을
  옮겼다. 기존 TaskProfileRecords와 agent/routing·사용량/연결·선택/리뷰 호환·공유 workspace/계획
  callback만 받는다. 캐시와 실제 조회·credential/SDK 수명은 Pipeline이 소유한다.
- 순수 `apply_quota_profile`은 기존 static 진입점과 같은 함수이며 `quota_fallback_matches`는
  기존 policy/revision/baseline/source와 선택/승격 근거를 검사한다. 승격 판정은 원래 Pipeline
  callback이다. 모델/실패/회복·한도 cache/시간·wire/저장 schema와 오류 클래스/원인을 바꾸지 않았다.
- 이전 시도/활동/결과·수동/고정 rule 보호, 한도 불명 유지·수동 전용 제외, lazy 연결 조회와
  리뷰 계약/병렬 수 제한, receipt 선저장 뒤 상태/계획 저장과 재적용 순서를 유지했다.
  배정은 기존 planning 공개 API를 쓰며 Plan/PlanningError/assign_plan_agents는 기존과 같은 객체다.
- 이동한 3개 본문과 callback/오류/저장 순서를 AST로 대조했다. 기존 signature/static 별칭과
  나머지 Pipeline 메서드 412개는 그대로다. dispatch의 Planning chat lock/Task 시작과
  최종 snapshot/승격 판정·정책 binding·실제 한도 조회/캐시·초기 후보 조회는 변경하지 않았다.
- 기존 quota 검사에서 전환·보호 상태/한도 불명·호환 대안 부재·계정 변경 허용·병렬 제한·
  중단 저장 재적용·고정 정책 복원/변조 거부·코드 실패 승격 근거·dispatch 저장을 선택했다.
  수정하지 않은 원시 한도 판정/캐시·초기 후보 케이스는 제외했다.
  `21 passed, 9 deselected`(0.77초)이며 새 테스트·실패·추가 동작 수정은 없다. 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·공유 배정/오류/static helper 동일 객체를 확인했다.
- Pipeline은 10,099줄에서 10,019줄로 80줄 줄었고 새 quota 모듈은 136줄이다.
  다음 후보는 자동 모델 승격의 증거 판정/반영이며 현재 정책·binding·상태 잠금과
  quota receipt를 통한 최초 프로필 복원 경계를 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

17단계 자동 모델 승격의 증거 판정/반영 분리를 완료했다.

- `execution.model_escalation`에 순수 automatic_model_escalation_matches와 불변
  AutomaticModelEscalation을 추가했다. 정책/프로필 조회·quota receipt 일치·상태 저장 callback과
  기존 state lock만 받으며 전체 Pipeline/Store/Config·credential·새 lock/client는 전달하지 않는다.
- provider/원래 모델/source·정책 버전/ID·실패 action/status/kind·1회 제한과 환경/수동 제외,
  started binding/정책/Task 존재 확인·quota 전환 후 프로필 복원·잠금 안의 임시 승격과 판정 실패 시
  네 필드 복원·이벤트/저장 순서를 그대로 옮겼다. 승격 기준·모델·오류/저장 schema는 바꾸지 않았다.
- 기존 static 진입점은 같은 함수를 재노출하고 `_promote_automatic_model`은 같은 signature에서
  좁은 callback을 연결한다. 두 본문과 callback/잠금/복원/저장 순서를 AST로 대조했으며 나머지
  Pipeline 메서드 413개는 같다. 복구 루프·최종 정책 snapshot/한도 검증·실제 SDK·승인/정책 고정은 그대로다.
- 기존 승격 1회/원본 정책 보존·수동 변경/실패 근거 변조 거부·복구 루프의 승격 모델 전달 mock과
  반복 실패 guard·환경/수동 제외·legacy/이전 고정 정책 보호·quota 전환 후 승격 근거를 선택했다.
  `8 passed, 44 deselected, 16 subtests passed`(0.90초)이며 새 테스트·실패·추가 동작 수정은 없다.
  문서 정리 뒤 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·공유 오류/static helper 동일 객체를 확인했다. 관련 모델 상수
  import도 사용 모듈로 옮겼으며 CLI/RPC/UI 계약이나 의존성은 추가/변경하지 않았다.
- Pipeline은 10,019줄에서 9,981줄로 38줄 줄었고 새 model_escalation 모듈은 69줄이다.
  다음 후보는 실행 정책 snapshot의 작업/리뷰/receipt 일치 검증이며 승인·binding과
  SDK 호출 직전 검사 위치를 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

18단계 실행 정책 snapshot 일치 검사 분리를 완료했다.

- `execution.policy_snapshot.ExecutionPolicyValidator`가 기존 승인/revision·작업/리뷰 집합·프로필/
  worker/reviewer runtime과 정책의 일치 여부를 대조한다. agent mapping·프로필 기록 조회와
  기존 승격/quota 일치 callback만 받으며 전체 Pipeline/Store/Config·SDK/credential·새 lock은 전달하지 않는다.
- 프로필 불일치 시 승격/quota/수동 receipt를 확인하는 short-circuit 순서와 receipt의 policy/
  revision/baseline/selection/source, 버전별 리뷰 검사·조회/오류 순서를 그대로 옮겼다.
  읽기 전용이며 새 기준·상태 쓰기·오류 타입/문구·저장 schema는 추가/변경하지 않았다.
- `_validate_effort_execution_snapshot` signature와 callback 연결·본문을 AST로 대조했다. 나머지
  Pipeline 메서드 413개는 같다. started binding 재개와 AI 호출 직전의 검사 위치/순서, 승인·잠금·
  정책 생성/예약/binding 수명·호출별 추가 검사·실제 SDK는 그대로다.
- 기존 실행 시작/종료·수동 receipt/정책 원본·실패 재개·plan/snapshot drift와 worker/reviewer
  불일치의 호출 차단을 선택했다. 모델 승격/변조 거부·quota 전환/원본 복원과 dispatch·이전 Sonnet
  정책/호출 호환도 확인했다. provider 호출은 기존 mock이고 실제 AI를 실행하지 않았다.
  `11 passed, 69 deselected, 8 subtests passed`(0.95초)이며 새 테스트·실패·추가 동작 수정은 없다.
  문서 정리 뒤 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·공유 오류 동일 객체를 확인했다. 의존성·CLI/RPC/UI 계약은 바꾸지 않았다.
- Pipeline은 9,981줄에서 9,949줄로 32줄 줄었고 새 policy_snapshot 모듈은 59줄이다.
  다음 후보는 preview에서 실행 정책 snapshot을 구성하는 부분이며 UUID/버전·Planning/Task/
  리뷰 snapshot과 수동 예외·정책 고정/예약의 소유권을 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

19단계 고정 실행 정책 snapshot 구성 분리를 완료했다.

- 기존 `execution.policy_snapshot`에 build_execution_policy_snapshot을 추가했다. RunState/미리보기와
  현재 agent mapping·기본 Planning agent ID만 받고 기존 ResolvedEffortPolicy를 만든다. 전체
  Pipeline/Store/Config·SDK/credential·저장/잠금 callback은 받지 않는다.
- Planning agent 우선/기본값과 모델/추론/source, Task 순서·리뷰 required/optional/reason/추가/
  대체 조건·reviewer provider/model, 수동 예외/미지원 항목과 UUID·버전 3·scope/revision/UTC 시각을
  같은 순서/시점에 구성한다. 없는 agent/preview 항목을 기본값으로 숨기지 않으며 오류/저장 schema도 같다.
- `_resolved_execution_policy` signature와 입력 연결·이동 본문을 AST로 대조했다. 기존 validator와
  나머지 Pipeline 메서드 413개는 같다. 선택/검토·worker/reviewer 재확인·생성 뒤 예약/RunState
  저장/started binding 수명·실제 AI/승인/잠금은 그대로다. 관련 DTO import만 사용 모듈로 옮겼다.
- 기존 정책 생성/시작/완료·prepared 중단 후 예약 보존·수동 설정/다음 예약·리뷰 snapshot/runtime,
  짧은 잠금의 실행 중 예약/저장·Claude 모델/이전 Sonnet 정책 호환을 선택했다. provider는 기존 mock이다.
  `7 passed, 41 deselected`(0.74초)이며 새 테스트·실패·추가 동작 수정은 없다.
  문서 정리 뒤 통과한 검사는 반복하지 않았다.
- 수정 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·미리보기/모델/오류/UTC 동일 객체를 확인했다. 새 의존성·CLI/RPC/UI 계약은 없다.
- Pipeline은 9,949줄에서 9,910줄로 39줄 줄었고 policy_snapshot 모듈은 59줄에서 109줄이 됐다.
  다음 후보는 실행 강도 미리보기의 모델/리뷰 판단 조합이며 현재 설정·가용성·계획 검토와
  읽기/적용의 소유권을 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

20단계 실행 강도 미리보기 조합 분리를 완료했다.

- `execution.effort_preview.EffortPreviewBuilder`에 Planning/Task 모델·추론/리뷰 판단 조합을 옮겼다.
  agent mapping/설정 tuple·기본 Planning agent ID·필수 리뷰 여부와 기존 리뷰 호환성/선택 가능/
  가용성 callback만 받는다. 전체 Pipeline/Store/Config·SDK/credential·새 client/lock은 전달하지 않는다.
- 기존 effort_policy의 DTO/판단과 같은 객체를 사용한다. Planning 우선/기본값·provider/model 대체,
  수동 예외/legacy·시작된 설정 보존과 정책 추가 리뷰 제거/필수 리뷰 보존·미지원/재검토 판정,
  후보 lazy 조회/기존 reviewer 확인과 저장 실행 프로필 보존/runtime 제외 옵션을 그대로 유지했다.
- `_effort_mode_preview`와 새 build의 signature·옵션/입력 연결·본문/조회 순서를 AST로 대조했다.
  나머지 Pipeline 메서드 413개는 같다. public preview의 mode/revision·정책/상태 조회와 실행 재개,
  설정 저장·계획 반영/승인·정책 예약/실제 AI는 그대로이며 미리보기는 상태를 쓰지 않는다.
- 기존 읽기 전용/수동/legacy·필수/선택 리뷰·로그아웃/역량/공급자별 가용성과 명시적 reviewer/계획
  재승인·기존 리뷰 보존을 선택했다. Terra 모델/미리보기 고정·이전 Sonnet 실행 프로필 보존·
  Claude Planning 모델과 수동 선택·작업 복구 시 저장 프로필/다음 예약 보존도 확인했다.
  `15 passed, 64 deselected, 4 subtests passed`(1.03초)이며 새 테스트·실패·추가 동작 수정은 없다.
  문서 정리 뒤 통과한 검사는 반복하지 않았다. 실제 provider는 기존 mock이다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·판단/DTO/오류 동일 객체를 확인했다. 관련 미사용 import만 옮겼으며
  모델/리뷰 기준·저장 schema·의존성·CLI/RPC/UI 계약은 추가/변경하지 않았다.
- Pipeline은 9,910줄에서 9,827줄로 83줄 줄었고 새 effort_preview 모듈은 119줄이다.
  다음 후보는 계획에 실행 강도를 반영하는 프로필/리뷰 설정 조합이며 잠금·revision·명시적
  reviewer 선택과 계획 재승인 경계를 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

21단계 강도 적용의 프로필·리뷰 변경안 분리를 완료했다.

- `execution.effort_plan`에 EffortPlanChange와 EffortPlanApplicator를 추가했다. agent mapping/기본
  Planning agent ID와 기존 가용성/리뷰 호환성/선택 가능 callback만 받는다. 전체 Pipeline/Store/
  Config·SDK/credential·새 lock/client는 전달하지 않고 변경안도 직접 저장하지 않는다.
- baseline/리뷰 미지원·필수 reviewer, 새 리뷰 Task와 명시 선택의 집합 일치·가용성/호환성/역량/
  선택 가능 검사 뒤 원본을 deepcopy한다. Planning/Task 모델/추론/source·baseline·선택 이유와
  정책 리뷰 추가/제거·review 상태·strict zip·전체/Planning 변경 flag를 그대로 조합해 반환한다.
- `apply_effort_mode_to_plan` signature와 mode/계획 revision·잠금/stage/archive/시작 여부·정책
  revision/선택 모드·미리보기 조회를 유지했다. 반환 뒤 그래프/readiness·계획 revision/재승인과
  계획 파일/상태·Planning 변경 시 기존 채팅 저장, 변경 없는 경우 사본 반환/비저장도 같은 순서다.
- 이동 본문/입력/변경 flag와 기존 전/후 구간을 AST로 대조했다. 결과 DTO는 사본과 두 bool만
  전달하며 나머지 Pipeline 메서드 413개는 같다. 오류/저장 schema·리뷰 기준·승인/부분 실패 의미는 바꾸지 않았다.
- 기존 명시적 reviewer/계획 재승인·모드 추가/제거와 baseline·필수/legacy 리뷰 보존, 설정 저장과
  실제 적용의 분리·Codex 리뷰의 편집/확인/별도 turn·공급자/역량/가용성별 거부를 선택했다.
  `11 passed, 18 deselected`(0.89초)이며 새 테스트·실패·추가 동작 수정은 없다. provider는 기존 mock이고
  문서 정리 뒤 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·미리보기/모델/오류 동일 객체를 확인했다. 새 의존성·CLI/RPC/UI 계약은 없다.
- Pipeline은 9,827줄에서 9,767줄로 60줄 줄었고 새 effort_plan 모듈은 101줄이다.
  다음 후보는 실행 강도 상태와 desktop 미리보기의 조회 모델이며 정책/revision 일치와
  읽기·가용성/후보 조회·UI 응답 계약을 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

22단계 실행 강도 상태/desktop 미리보기 조회 모델 분리를 완료했다.

- `execution.effort_queries`에 EffortQueryRecords/EffortQueries와 상태 key/예약 가능 순수 함수를
  추가했다. 상태/정책·잠금 상태·보관 정책 존재 조회와 기존 미리보기/agent 목록/선택 가능/연결/
  리뷰 호환 callback만 받는다. 전체 Pipeline/Store/Config·SDK/credential·경로는 전달하지 않는다.
- 상태/정책/binding/snapshot·모드 미리보기·잠금·최신 상태·보관 정책 순서와 expected_state 비교,
  변경/예약/취소 가능 표시·Planning 이력/마지막 변경·불일치 사유를 유지했다. 보관 경로 존재 확인은
  기존 Store callback이며 참조 오류/깨진 기록을 legacy나 빈 결과로 숨기지 않는다.
- desktop preview의 상태 재조회/revision 검사·asdict/Task 순서, 새 정책 리뷰일 때의 agent 목록/
  선택 가능 조회·연결/호환성/역량 필터와 reviewer_options/can_apply를 그대로 옮겼다.
  agent 목록은 lambda로 원래 지점에서 조회한다. 응답 field·enum/null/bool 의미도 같다.
- 기존 public signature/위임·static 함수 별칭을 유지했고 이동한 4개 본문/옵션과 좁은 callback,
  lazy/보관/재조회 순서를 AST로 대조했다. 나머지 Pipeline 메서드 410개와 실제 설정/예약/계획
  쓰기·승인/잠금/revision 검증, application/RPC adapter와 renderer 계약은 그대로다.
- 기존 읽기 전용·로그아웃/역량/공급자별 후보·실행 중 예약/원본 정책·상태/expected snapshot
  일치·깨진 정책 오류·application/RPC 응답과 보관된 Planning 정책의 실패/재시도 이력을 선택했다.
  `12 passed, 23 deselected`(0.76초)이며 새 테스트·실패·추가 동작 수정은 없다. provider는 기존 mock이고
  문서 정리 뒤 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·모델/오류/static helper 동일 객체를 확인했다. 새 저장/refresh·
  의존성·CLI/RPC/UI 계약·client/lock은 추가/변경하지 않았다.
- Pipeline은 9,767줄에서 9,691줄로 76줄 줄었고 새 effort_queries 모듈은 138줄이다.
  다음 후보는 AI 공급자 선택 목록/가용성 조회 조합이며 현재 연결·역량·수동 전용 제한과
  기본 프로필/모델·UI 응답 계약을 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

23단계 공급자 선택·연결/기획 실행 후보 조회 조합 분리를 완료했다.

- `execution.provider_choices`에 ProviderChoiceQueries와 connected_provider_ids를 추가했다.
  agent 목록/균형 설정·가용성/선택 가능·기존 연결/사용량과 redacted status callback만 받는다.
  전체 Pipeline/Store/Config·SDK/credential·비밀값·새 client/cache/lock은 전달하지 않는다.
- 실행 목록의 역량/연결/정렬, 기획 목록의 NVIDIA 제외·기본 프로필 우선·기존 순수 선택 함수/
  PlanningError skip·field/기본 표시를 유지했다. 연결은 공급자 순서·Codex/Claude 인증 true와
  NVIDIA 가용성/다른 공급자의 기존 허용 조건을 그대로 판정한다.
- 기획 실행 후보의 가용성→균형 설정→연결/한도와 commandless custom legacy 후보 추가 순서를
  보존했다. 설정/목록은 lambda로 같은 지점에서 읽고 기존 선택/배정의 수동 전용 규칙·모델은 바꾸지 않았다.
- 기존 public/private signature와 연결 callback 호출 관계·이동한 4개 본문/입력/조회/정렬을 AST로
  대조했다. 나머지 Pipeline 메서드 409개와 실제 provider_statuses·SDK/credential·실행 파일/
  사용량 캐시·기획 선택/실제 배정/실행/설정 쓰기·application/RPC 계약은 그대로다.
- 기존 연결/인증 true/false/미확인 matrix·재연결/키 제거·빈 목록/연결 관리 보존·NVIDIA CLI/수동
  설정·custom 역량·오래된 선택 거부·기획 균형/모의 호출과 기본 프로필/역량/동시 수·확정 한도 제외를 선택했다.
  `24 passed, 385 deselected`(0.58초)이며 새 테스트·실패·추가 동작 수정은 없다. provider는 기존 mock이고
  문서 정리 뒤 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 3개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·응답 DTO/기존 Planning 선택/오류 동일 객체를 확인했다.
  새 가용성/인증/모델 기준·저장 schema·의존성·CLI/RPC/UI 계약은 추가/변경하지 않았다.
- Pipeline은 9,691줄에서 9,641줄로 50줄 줄었고 새 provider_choices 모듈은 94줄이다.
  다음 후보는 민감값 없는 공급자 상태 응답 조합이며 SDK/인증/실행 파일/키 확인 callback의
  소유권·lazy 조회와 오류/인증 미확인 표시를 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

24단계 공급자 상태 응답 조합 분리를 완료했다.

- `execution.provider_status.ProviderStatusQueries`로 기존 상태 목록 조합을 옮겼다. agent 목록과
  account_status callback 또는 None·실행 파일 결과·NVIDIA 키 존재/등록 방식 bool·Claude 인증 상태만
  받는다. 실제 SDK/키·전체 Pipeline/Store/Config·새 client/cache/lock은 전달하지 않는다.
- SDK 참조가 Pipeline 생성 시 고정됨을 확인하고 기존 인스턴스의 callback을 사용했다. 공급자 정렬/
  agent 순서와 CodexSdkError·SDK 없음/로그아웃·CLI 불필요 표시, NVIDIA CLI/키 안내 우선순위·
  Claude 미확인/인증/표시·ProviderStatus field를 유지했다. 계정 세부/키를 새 응답에 추가하지 않았다.
- `_provider_status_executable`은 기존 execute 명령 또는 review_command 대체와 빈 명령 건너뛰기/
  resolver 호출을 같은 위치에서 처리한다. 명령/인자와 SDK/credential·실제 인증 확인은 Pipeline에 남는다.
- 기존 public signature와 본문을 callback/probe 확장 후 AST로 대조했다. SDK 고정 소유 조건·
  입력 연결/조회/예외 순서가 같고 나머지 Pipeline 메서드 413개는 그대로다. 선택/연결/사용량과
  application/RPC 소비자·SDK/인증/명령/resolver·실제 dispatch도 변경하지 않았다.
- 기존 SDK/로그아웃·인증 true/false/미확인 matrix·빈 목록/연결 관리·sanitized Claude 구독/API 키와
  NVIDIA 존재/CLI·요청별 키 격리를 선택했다. 새 1개는 SDK 없음/Codex CLI 미조회·빈 명령과
  review_command 대체의 실제 Pipeline probe 연결을 확인한다.
  `17 passed, 377 deselected`(0.55초)이며 실패·추가 동작 수정은 없다. 실제 provider/process는 기존 mock이고
  문서 정리 뒤 통과한 검사는 반복하지 않았다.
- 수정/신규 Python 4개 파일의 구문·전역 참조·신규/수정 줄의 150자 제한·공백/diff와
  실행 API의 Pipeline/Store 미로딩·SDK/status/오류 DTO 동일 객체를 확인했다. 관련 미사용 type import만
  옮겼으며 새 인증/모델 기준·저장 schema·의존성·CLI/RPC/UI 계약은 추가/변경하지 않았다.
- Pipeline은 9,641줄에서 9,573줄로 68줄 줄었고 새 provider_status 모듈은 99줄이다.
  다음 후보는 Claude 연결 응답의 검증/표시 조합이며 CLI/환경/키 확인 소유권과
  API 키/구독/미확인·account 정보/오류 응답 경계를 확인한 뒤 후속 범위를 정한다.
- 실제 사용자 데이터·다른 저장소·Rust·공개 checkout·실제 AI·전체 테스트·전체 renderer·빌드·
  패키징·원격 저장소·commit·push·deploy는 실행/변경하지 않았다.

25단계 기획·계획 변경 규칙 일괄 정리를 완료했다.

- `planning.changes`에 초안 검증·프로필/리뷰 보존, 보호 Task와 새 Task 병합, 반영 요청 생성과
  결과 수정 제안 검증을 옮겼다. `planning.preview`는 기존 잠금/진행 snapshot에서 작업 표시를 파생한다.
  필요한 값/조회/메시지 callback만 받고 Pipeline/Store/전체 Config·실행 모듈은 참조하지 않는다.
- 기존 5개 로직과 callback 연결을 대조했다. 나머지 Pipeline 메서드 410개는 그대로이며,
  같은 그룹 변경의 앞뒤 stage 확인·AI/준비·계획/상태/대화 저장과 실패 복원 순서를 유지했다.
  기존 facade signature·static 별칭·Plan/모델/오류와 marker/import 호환을 유지했다.
- 수정 Python 4개 파일의 구문·전역 참조·변경 줄 길이·diff를 확인했다. planning 기본 import가
  execution/planner/Pipeline/Store/Git을 로드하지 않고 공유 계약이 같은 객체임을 확인했다.
- 기존 결과 제안/근거·계획 편집/자동 배정·완료/실패 이력 보존·revision/요청 중복과 추가 답변 재시도·
  preview 생성/Task/리뷰/검증/동시 대화 표시를 선택해 `18 passed`(8.10초)였다. 새 테스트는 추가하지 않았다.
  provider 응답은 기존 mock이며 문서/호환 import 정리 뒤 통과한 동작 검사를 반복하지 않았다.
- Pipeline은 9,573줄에서 9,335줄로 238줄 줄었다. 새 changes 모듈은 293줄, preview 모듈은 60줄이다.
  저장 schema·CLI/RPC/MCP·UI 동작은 바꾸지 않았으며 실제 AI·전체 테스트·빌드·원격 작업은 하지 않았다.

26단계 실행 복구·Claude 연결 응답 경계 정리를 완료했다.

- `execution.verification_repair`로 가용 Agent 우선순위·실패 로그/prompt·호출 준비/중지/진행과
  범위 검사할 Task/원래 검증 시도를 분리했다. Pipeline은 격리/공유 작업공간·청결/HEAD·범위 검사·
  commit/branch 갱신·복구 근거 저장과 finally 정리를 유지한다. provider/정책·사용량·SDK 호출도 기존 callback이다.
- `execution.claude_connection`은 payload/종료 코드/앱 키 사용 bool만 받아 기존 응답을 만든다.
  실제 CLI·환경/키·timeout/JSON 오류 처리는 Pipeline에 두고 미확인/로그아웃/API/구독·계정 필터를 보존했다.
- 이동한 선택/본문/응답을 AST로 대조했고 Git 트랜잭션과 나머지 Pipeline 메서드 412개는 그대로다.
  수정 Python 5개 파일의 구문·전역 참조·변경 줄 길이/공백을 확인했다.
- 기존 Claude 인증/계정 필터·timeout/앱 키 검사를 선택하고, 기존 검사가 실행하지 않던 복구 본문의
  격리/공유·Agent/모델·중지/진행·범위 검사·실패 시 branch 미갱신과 소유 worktree 정리를 7개 case로 보강했다.
  `18 passed, 26 deselected`(0.46초)다. AI/CLI/Git은 mock이며 prompt/실패 로그만 임시 경로에서 읽고 썼다.
  실행 파일: `tests/execution/test_verification_repair.py`, `tests/test_claude_connection.py`,
  `tests/test_claude_credentials.py`; 선택 조건은 repair/CLI 응답/계정 필터/timeout/앱 키 관련 case다.
- Pipeline은 9,335줄에서 9,219줄로 116줄 줄었다. 새 verification_repair 모듈은 140줄,
  claude_connection 모듈은 53줄이며 새 저장 schema·공개 사용자 기능·외부 의존성은 추가하지 않았다.

27단계 의존 관계·공개 계약 점검을 완료했다.

- 현재 HEAD의 원래 선언과 대조해 Pipeline 112개·StateStore 91개·공용 응용 API 121개의 public signature를
  확인했다. 기존 desktop 클래스/오류·모델/기획 API·공유 실행/저장 오류의 호환 import와 동일 객체를 확인했다.
- 상태 모델 80개의 필드/기본값과 enum 값을 대조했다. OperationRecord의 시계 helper 이름 이동은
  본문이 같음을 확인했으며 저장 형식 변경으로 처리하지 않았다. RPC 122개 route 집합도 같고 중복 handler가 없다.
- 코어 125개 모듈의 import 선언 그래프에 순환이 없고 분리한 execution/planning/integration/persistence/
  state/notifications에서 Pipeline/Store/UI 계층을 역참조하지 않음을 확인했다. 전체 Config/소유 객체를
  받는 선언도 추가하지 않았다. 이 정적 점검에서 추가 제품 결함은 발견하지 않았다.
- 앞 단계의 관련 통과 증거를 재사용했다. 점검을 이유로 전체 테스트·UI·빌드·실제 AI를 실행하지 않았다.

28단계 필수 정리와 완료 기록을 마쳤다.

- 아키텍처에 검증 복구/Claude 응답과 callback 기반 계획 변경 경계를 맞추고 이 계획의 상태/종료 기준을
  확정했다. 추가 수정이 필요한 범위 내 결함은 없었으며 새 함수 분리나 빈 패키지는 만들지 않았다.
- Pipeline의 승인·run/대화 잠금·실행 정책/SDK 수명·초기/최종 상태 전이·작업공간/Git 트랜잭션과
  최종 저장은 의도적으로 남긴 조정 책임이다. 프로젝트 등록/설정도 기존 registry/config/application/rpc가 맡는다.
- 착수 당시 14,517줄에서 최종 9,219줄로 5,298줄 줄었다. 파일 길이만으로 단계를 추가하지 않는다.
  기존 미커밋 변경을 유지했고 다른 저장소·Rust·공개 checkout·commit/push/deploy는 변경하지 않았다.
- 실계정/실제 provider·Electron 화면·전체 테스트·프로덕션 빌드/패키징·ZIP/릴리스·원격 발행은
  이번 요청의 검증/작업 범위가 아니므로 수행하지 않았다. 이 문서 경로는 기존 참조 호환을 위해 유지한다.

**이번 계획의 미완료 구현 단계는 없다.** 새 기능이나 추가 구조 개선은 별도 요청 범위로 정한다.
