# 공용 응용 계층의 기획 인계와 프로젝트 설정 분리

**상태: 29~32단계 완료. 사용자가 요청한 32단계까지의 범위를 종료했다.**

## 목표와 승인 범위

1~28단계의 [기능 모듈 리팩터링](2026-11-13-python-module-refactoring.md)은 완료 상태로 유지한다.
후속 [프로젝트 요약 조회 수명 분리](2026-11-14-project-summary-query-lifecycle.md)를 29단계로 부르고,
사용자의 32단계까지 진행 요청에 따라 아래 세 작업을 일괄 수행한다. 새로운 단계는 자동 추가하지 않는다.

| 단계 | 범위 | 상태 |
|---|---|---|
| 29 | 프로젝트 요약 executor·캐시·종료 수명 | 완료, 앞선 계획의 증거 재사용 |
| 30 | 준비된 Planning 색인의 발급·일회용 소비·응답 표시 | 완료 |
| 31 | 프로젝트 설정 조회/수정·도구 연결 확인·코드 스타일과 등록 설정 검증 | 완료 |
| 32 | 직접 영향받는 공개 계약/의존 관계·완료 기록 확인 | 완료 |

## 계약과 소유권

- `application.planning_indexes.PreparedPlanningIndexes`가 기존 project/정규화된 source 경로별
  준비 색인과 잠금을 소유한다. 발급과 소비 위치는 기존 공용 앱에 남기며 Agent 선택 후 소비한다.
  빈 입력, generated_at 불일치 때도 먼저 pop하는 순서, 프로젝트 격리와 1회성·동일 객체 인계를 유지한다.
  응답 필드는 `application.views`로 모으고 실제 색인 생성/재검증은 기존 Pipeline에 둔다.
- `application.project_settings.ProjectSettingsService`가 도구 설정 목록/추가/교체·revision 검증/
  연결 probe, 작업공간·프로젝트 역량·코드 스타일 조회/수정을 맡는다. 프로젝트 DTO·좁은 조회/수정
  callback만 받으며 전체 공용 앱/registry/Pipeline/Store·SDK는 전달하지 않는다.
- 설정 파일의 repo 일치 검사는 공개 `registered_project_config`로 재사용한다. `_pipeline`의
  최신 등록 정보/expected snapshot 검증·도구 override/SDK와 credential 구성 순서를 유지한다.
- 승인/형식/append 검증 순서, ID 대소문자 병합·명시적 빈 override, probe 전후 revision 검사와
  작업 도구 lease, 코드 스타일 저장/검사 순서를 유지한다. 최종 설정 쓰기는 기존 registry가 수행한다.
- 공개 응용 API·RPC/MCP 메서드/오류/응답·저장 schema·프로젝트/Git 변경 권한은 바꾸지 않는다.
  다른 저장소·Rust·공개 checkout·실제 도구/AI·commit/push/deploy는 이번 범위가 아니다.

## 영향 파일과 검증

- `application/service.py`, 신규 `application/planning_indexes.py`, `application/project_settings.py`,
  `application/views.py`, `Docs/Architecture.md`와 직접 관련 테스트.
- 정적 검사·직접 diff와 이동 본문/호출 순서를 확인한다. 기존 준비 색인/문서 없는 기획·설정 조회/
  코드 스타일·worker MCP 관련 case를 선택한다. patch 경로는 실제 소유 모듈로만 맞춘다.
- 기존 검사가 없는 색인 불일치 소비·프로젝트 격리/동시 1회 소비 경계만 보강한다. 31단계는
  기존 검사를 우선하고 실제 빈틈이 확인될 때만 추가한다.
- 32단계는 이번 변경의 공개 signature·호환 객체/route·의존 방향과 기록을 확인한다. 통과한 검사는
  재사용하고 전체 테스트/renderer·빌드·실제 계정/앱·패키징을 실행하지 않는다.

## 진행과 결과

### 30단계 완료

- 준비 색인과 잠금을 `PreparedPlanningIndexes`에 묶었다. 새 색인의 발급·정규화 경로와 프로젝트별
  격리·빈 입력·generated_at 비교 전 pop·동일 객체의 1회 소비를 유지했다. 응답 8개 필드는
  `planning_index_view`로 옮기고 Pipeline 생성/모델 선택·준비 호출 순서는 유지했다.
- 기존 인계/문서 없는 directed 준비와 새 stale/빈 입력/프로젝트 격리·최신 색인/동시 1회 소비를
  골라 `4 passed`(0.31초)였다. 빈 입력 보존의 관찰을 보강한 뒤 해당 case만 다시 확인해 `1 passed`(0.32초)였다.
  다른 통과 case는 반복하지 않았다. 실제 Planning AI·문서 색인은 호출하지 않았다.

### 31단계 완료

- 도구 목록/추가/교체·revision/lease/probe와 작업공간/역량·코드 스타일 처리 9개 메서드를
  `ProjectSettingsService`로 옮겼다. 전체 소유 객체 대신 4개 callback을 사용하고 기존 승인 검사와
  registry의 최종 revision/원자적 저장을 유지했다. 실제 Pipeline/SDK 구성은 공용 앱에 남겼다.
- 등록 설정 repo 검사를 `registered_project_config`로 재사용한다. 최신 등록 정보와 expected snapshot
  검사 뒤 설정을 읽으며 도구 override의 None/빈 목록 의미·SDK와 preference 전달 순서를 유지했다.
- 기존 worker 도구 append/빈 override·probe 잠금/전후 변경, metadata/코드 스타일과 SDK 수명 8개 case에
  기존 검사가 없던 repo 불일치 3개 소비자 경계를 보강해 `11 passed`(1.38초)였다. 실제 MCP/AI/계정 조회는
  호출하지 않았고 테스트 patch는 새 소유 모듈로만 옮겼다.

### 32단계 완료

- 이동한 색인/응답·설정 본문과 wrapper 인자, 등록/설정/SDK 호출 순서를 AST로 대조했다.
  공용 앱의 나머지 116개 메서드와 기존 signature는 그대로다. 변경 Python 8개 파일의 구문,
  제품/새 테스트의 전역 참조·변경 줄 길이·공백과 직접 diff를 확인했다.
- 기존 점검 방식으로 Pipeline 112개·StateStore 91개·응용 API 121개의 public signature와 모델 80개,
  모델/오류/desktop/기획 호환 import·RPC 122개 route를 확인했다. 코어 128개 모듈의 import 선언에
  순환 의존이 없고 새 응용 기능에서 service/runtime/Pipeline/Store/transport를 역참조하지 않는다.
- 아키텍처와 완료 기록을 맞췄다. 공용 앱은 952줄에서 874줄로 줄었고 Pipeline은 기존 9,219줄을 유지한다.
  29단계 통과 증거는 재사용했으며 이번 범위의 고유 관련 검사 15개가 통과했다.
- 기존 미커밋 변경과 다른 작업을 보존했다. 전체 테스트/renderer·빌드·실제 AI/도구/화면·패키징·
  다른 저장소·Rust·공개 checkout·commit/push/deploy는 실행/변경하지 않았다.

**32단계까지의 미완료 작업은 없다.** 추가 기능이나 구조 변경은 별도 요청 범위로 정한다.
