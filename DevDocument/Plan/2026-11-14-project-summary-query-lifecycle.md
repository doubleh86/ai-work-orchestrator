# 프로젝트 상태 요약 조회의 수명 분리

후속 단계 표기에서는 이 완료 작업을 29단계로 부른다. 30~32단계의 별도 승인 범위는
[공용 응용 계층 후속 계획](2026-11-14-application-state-settings-refactoring.md)에 기록한다.

## 목표와 범위

앞선 Python 모듈 리팩터링의 1~28단계는 완료 상태로 유지한다. 후속 `다음` 요청은 이 작업
한 단위로 진행하며 추가 기능이나 미리 정한 후속 단계를 만들지 않는다.

`application.service.OrchestratorApplication`에 있는 프로젝트 상태 요약 조회의 executor,
종류별 Future 캐시, 잠금과 bounded wait를 `application.summaries.ProjectSummaryQueries`로 묶는다.
느린 프로젝트 조회를 중복 실행하지 않는 규칙과 종료 시 대기 작업 취소를 한 객체가 소유하게 한다.

- 공용 앱은 프로젝트 목록/이름 선택과 실제 Pipeline 조회 callback, SDK 수명·종료를 유지한다.
- 요약 객체는 프로젝트 이름 조회 callback만 받고 전체 application/registry/Pipeline/Store는 받지 않는다.
- 기존 active_groups/attention_items/user_check_items signature와 RPC/MCP 응답 형식을 유지한다.
- 조회 종류별 캐시 격리, worker 4개·5초 대기, 미완료 Future 재사용, 완료 Future 교체/동일 객체만 제거,
  checked_at·프로젝트 오류 격리·정렬·project_name 필드 우선순위를 유지한다.
- 종료는 기존처럼 wait=False/cancel_futures=True이며 실행 중 작업을 강제 종료하거나 기다리지 않는다.
  요약 객체 종료 뒤 SDK를 닫는 순서를 유지한다. 실제 조회·실행·상태 저장·승인 정책은 바꾸지 않는다.

## 영향 파일과 검증

- `src/ai_orchestrator/application/service.py`, 신규 `application/summaries.py`, `Docs/Architecture.md`.
- 기존 desktop RPC의 프로젝트 오류/느린 조회 재사용·공개 라우팅 검사를 선택한다.
  mock 대기 함수의 소유 모듈 경로만 이동한다.
- 기존 검사가 없는 조회 종류/선택 프로젝트의 캐시 경계와 종료 시 대기 작업 취소만 보강한다.
- 수정 Python 구문·직접 diff·이동 로직과 의존/공개 계약을 확인한다. 전체 테스트·빌드·실제 AI·
  외부 저장소·commit/push/deploy는 이번 작업 범위가 아니다.

## 진행과 결과

**완료. 이번 요청의 한 단위 작업을 종료했다.** 앞선 1~28단계 완료 상태는 변경하지 않았다.

- `ProjectSummaryQueries`가 executor·종류별 미완료 조회·잠금·대기/오류/정렬과 종료 취소를 맡는다.
  공용 앱은 프로젝트 선택·실제 조회 callback·SDK 수명을 유지한다. 공개 메서드/응답과 기존
  미완료 재사용·동일 Future만 제거·5초 대기·worker 4개·SDK 종료 순서를 바꾸지 않았다.
- 공용 앱의 나머지 메서드 123개와 public signature는 그대로다. 전체 application/registry/
  Pipeline/Store를 새 객체로 전달하거나 transport 의존성을 추가하지 않았다.
- 기존 mock의 wait 경로 1개만 소유 모듈로 맞췄다. 기존 RPC/프로젝트 오류·느린 조회 재사용과
  headless import 검사, 새 조회 종류/선택 프로젝트 격리·실행 중 작업을 기다리지 않는 종료/대기 취소를
  선택해 `8 passed`(1.34초)였다. 실제 SDK/AI는 mock이며 executor 취소는 로컬 thread/Future로 확인했다.
- 수정 Python 4개 파일의 구문, 전역 참조·변경 줄 길이/공백과 직접 diff를 확인했다.
  필요한 관련 확인이 통과한 뒤 전체 테스트·빌드·실제 AI·원격 발행은 실행하지 않았다.
