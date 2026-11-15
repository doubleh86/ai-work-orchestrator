# Pipeline 공개 API의 목표 소유권

- 상태: **P1~P5 적용 완료. 공개 API 112/112개를 실제 owner에 배정했다.**
- 기준: 2026-11-15의 `src/ai_orchestrator/pipeline.py`, 5,495줄/공개 메서드 112개.
- 상세 구조/잠금/호환 계약은 [재설계](2026-11-15-pipeline-orchestration-redesign.md)를 따른다.
- 아래 줄 번호는 설계 시점의 탐색 위치이며 구현 후 실제 소유 모듈로 갱신한다.
- 공개 이름/인자/기본값/반환/오류는 유지한다. 이름이 조회처럼 보여도 실제 부작용을 별도로 검증한다.

P2의 실제 owner는 `src/ai_orchestrator/orchestration/queries.py`, `providers.py`, `effort.py`이고,
P3는 `orchestration/planning.py`, P4는 `orchestration/execution.py`·`control.py`,
P5는 `orchestration/integration.py`·`lifecycle.py`다.
각 절의 기존 줄 번호는 원본 추적용으로 유지하며 현재 구현 위치는 아래 소스 링크를 따른다.
공통 자원은 bootstrap이 구성하고 이 owner들은 facade의 private callback/전체 자원을 받지 않는다.

| 목표 책임 | 공개 API 수 |
|---|---|
| `PlanningCommands` | 26 |
| `ExecutionCommands` | 16 |
| `RunControlCommands` | 16 |
| `IntegrationCommands` | 21 |
| `LifecycleCommands` | 6 |
| `EffortCommands` | 6 |
| `ProviderQueries` | 5 |
| `RunQueries` | 16 |
| **합계** | **112** |

## PlanningCommands

**P3 적용 완료:** [기획 명령 구현](../../../src/ai_orchestrator/orchestration/planning.py).
접수/AI 세션/계획 적용은 `planning.intake`·`ai`·`lifecycle` 기능을 직접 사용하며
메시지 라우팅은 같은 명령 계층의 `planning_routing`에서 수행한다.

기획 생성/대화·계획 확정·Task 초안 변경. 읽기 성격의 기획 API도 이 책임과 함께 유지한다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `external_planning_context` | 529 |
| `submit_external_plan` | 550 |
| `start` | 597 |
| `prepare_planning` | 621 |
| `result_revision_requests` | 707 |
| `propose_result_revision` | 719 |
| `create_result_revision_request` | 756 |
| `run_planning` | 775 |
| `clarify` | 790 |
| `clarify_text` | 794 |
| `send_planning_message` | 814 |
| `request_direction_change` | 865 |
| `planning_apply_preview` | 955 |
| `planning_preview_status` | 963 |
| `preview_planning_apply` | 968 |
| `apply_planning_preview` | 994 |
| `request_planning_conversation_apply` | 1004 |
| `apply_planning_conversation` | 1072 |
| `confirm_tech_stack` | 1115 |
| `preview_bootstrap` | 1159 |
| `configure_bootstrap_agent_instructions` | 1165 |
| `generate_feature_plan` | 1192 |
| `refresh_planning_index` | 1519 |
| `exclude_tasks` | 2443 |
| `update_plan` | 2453 |
| `confirm_plan` | 2583 |

## ExecutionCommands

**P4 적용 완료:** [명령 구현](../../../src/ai_orchestrator/orchestration/execution.py).

작업 시작/재개·수동 인계·프로필/사용자 확인과 실행 결과. 실제 task phase와 기존 실행 세션을 조합한다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `update_task_execution_profile` | 2508 |
| `execution_profile_view` | 2536 |
| `execute` | 2670 |
| `resume` | 2693 |
| `approve_task_scope` | 2860 |
| `retry_task` | 3316 |
| `execute_task` | 3345 |
| `set_manual_task_deferred` | 3652 |
| `record_user_check` | 3668 |
| `complete_manual_verification` | 3695 |
| `handoff_manual_task_to_ai` | 3714 |
| `complete_task` | 3748 |
| `task_retry_context` | 5126 |
| `record_task_diagnosis` | 5138 |
| `save_task_retry_instruction` | 5153 |
| `task_failure_message` | 5240 |

## RunControlCommands

**P4 적용 완료:** [명령 구현](../../../src/ai_orchestrator/orchestration/control.py).

요청/중단·프로젝트 채팅과 복구. recovery_plan은 operation을 기록하므로 단순 조회로 이전하지 않는다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `request_stop` | 468 |
| `recovery_plan` | 1666 |
| `apply_recovery` | 1715 |
| `recovery_operation` | 1747 |
| `latest_recovery_operation` | 1750 |
| `begin_planning_request` | 1858 |
| `finish_planning_request` | 1865 |
| `interrupt_planning` | 1898 |
| `run_lock_status` | 2213 |
| `clear_run_lock` | 2217 |
| `decide_project_chat` | 3059 |
| `perform_project_chat` | 3062 |
| `request_chat_control` | 3160 |
| `advance_chat_control` | 3208 |
| `cancel_chat_control` | 3214 |
| `repair_task_from_chat` | 3262 |

## IntegrationCommands

**P5 적용 완료:** [명령 구현](../../../src/ai_orchestrator/orchestration/integration.py).

검증·Main 변경/반영·충돌·결과 등록/실행·push/deploy. 내부는 Main/검증/배포 흐름으로 나누고 한 클래스에 재집중하지 않는다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `update_main` | 1937 |
| `main_changes` | 1953 |
| `main_change_diff` | 1963 |
| `commit_main_changes` | 1967 |
| `push_main_commits` | 1975 |
| `commit_and_push_main_changes` | 1981 |
| `preview_main_apply` | 3848 |
| `apply_reviewed_main` | 3858 |
| `merge` | 3868 |
| `recover_main_apply` | 3894 |
| `retry_main_push` | 4039 |
| `result_artifact_info` | 4124 |
| `register_result_artifact` | 4141 |
| `launch_result_artifact` | 4154 |
| `verify` | 4168 |
| `verify_and_repair` | 4180 |
| `integration_conflict` | 4307 |
| `prepare_conflict_resolution` | 4348 |
| `apply_conflict_resolution` | 4368 |
| `push` | 4594 |
| `deploy` | 4681 |

## LifecycleCommands

**P5 적용 완료:** [명령 구현](../../../src/ai_orchestrator/orchestration/lifecycle.py).

보관/삭제/정리·작업공간 상태. 승인/경로 소유권과 기록 선보존·부분 실패를 하나의 작업 경계로 유지한다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `archive_plan` | 2226 |
| `archive_run` | 2259 |
| `retry_archive_cleanup` | 2292 |
| `delete_run` | 2347 |
| `workspace_statuses` | 2380 |
| `cleanup_workspace` | 2388 |

## EffortCommands

**P2 적용 완료:** [강도 명령 구현](../../../src/ai_orchestrator/orchestration/effort.py).
preview 검증은 `execution.effort_previews`, 실제 계획 적용은 기존 `EffortPlanApplication`을 직접 사용한다.

선택 모드/예약·계획 적용과 관련 표시. 읽기 API도 같은 정책 소유자의 조회 API를 사용한다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `preview_effort_mode` | 2004 |
| `effort_control` | 2048 |
| `desktop_effort_mode_preview` | 2055 |
| `set_effort_mode` | 2058 |
| `cancel_effort_reservation` | 2083 |
| `apply_effort_mode_to_plan` | 2091 |

## ProviderQueries

**P2 적용 완료:** [provider 조회 구현](../../../src/ai_orchestrator/orchestration/providers.py).
상태·가용성·연결 집합·계정 조회의 기능 API를 연결하며 static 호출에 runtime 생성을 추가하지 않았다.

AI 연결/가용성·계정 한도. 실제 인증키/SDK는 공유 runtime의 좁은 조회 API로만 확인한다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `planning_provider_choices` | 2001 |
| `execution_provider_choices` | 2124 |
| `provider_statuses` | 2140 |
| `account_usage` | 2151 |
| `claude_connection_status` | 2162 |

## RunQueries

**P2 적용 완료:** [상태 조회 구현](../../../src/ai_orchestrator/orchestration/queries.py).
제어 snapshot·summary/waiting/notification 기능을 직접 사용하며 기존 오류 허용/전파 차이를 유지한다.

상태/목록/주의/결과 안내·로그/사용량/환경 진단. check_dotnet은 subprocess를 실행할 수 있어 순수 함수가 아니다.

| 기존 API | 기존 코드 줄 |
|---|---|
| `status` | 1585 |
| `notifications` | 1588 |
| `waiting_prompt` | 1595 |
| `status_with_execution_control` | 1604 |
| `latest_main_operations` | 1608 |
| `status_with_controls` | 1620 |
| `list_statuses` | 1789 |
| `list_summaries` | 1804 |
| `planned_user_checks` | 1808 |
| `user_checks` | 1812 |
| `user_check_summaries` | 1815 |
| `attention_item_summaries` | 1818 |
| `active_group_summaries` | 1823 |
| `task_log` | 1916 |
| `check_dotnet` | 1921 |
| `usage` | 2033 |
