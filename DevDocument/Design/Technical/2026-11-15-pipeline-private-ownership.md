# Pipeline private 소유권과 호환 hook 이전표

- 기준: 2026-11-15 P1 착수 직전 `pipeline.py` 5,495줄의 AST.
- 상태: **P1~P5 이전 완료. facade private 구현/별칭/endpoint는 최종 owner로 연결하거나 제거했다.**
- [공개 API 112개 배정](2026-11-15-pipeline-api-ownership.md),
  [설계](2026-11-15-pipeline-orchestration-redesign.md),
  [단계별 진행·검증](../../Plan/2026-11-15-pipeline-orchestration-redesign.md).

## 표의 의미와 제거 기준

299개 정의(생성자 포함) + static/class 별칭 75개 + runtime endpoint 2개 = **376개**를 배정했다.
표의 owner는 최종 동작 소유자다. 실제 기능 객체의 생성·port 배선은 `pipeline_bootstrap`이 맡고,
승인·잠금·호출 순서를 조정하는 부분은 해당 `orchestration` 명령에 둔다. 이 표가 기존 함수를
이름만 바꿔 통째로 복제하거나 새 owner마다 얇은 wrapper를 만들라는 지시는 아니다.

`(port)`는 초기 제한 계약의 배정 표기다. 최종 owner와 실제 구성은 현재 소스 및 P5 결과를 따른다.
private 이름을 그대로 기능 객체에 복제하거나 영구 호환 진입점으로 유지하지 않는다.
여러 명령에서 사용하는 helper는 표의 단일 기능 owner를 직접 사용한다. 명령끼리 같은 코드를 복제하지 않는다.
factory/callback 협력은 실제 기능 API로 연결했으며 facade 역참조를 제거했다.

P1의 실제 변경은 생성자 구성과 실행 제어 조립, `_stop_signal`, `_step`, `_planning_effort_scope`다.
`_step`/`_planning_effort_scope`는 클래스 구현을 제거했고 남은 명령이 동일한 owner를 호출하도록
instance callable을 임시 연결했다. 이 연결과 다른 제어 bridge는 해당 명령의 P3~P5 이전 시 제거한다.
기존 2개 provider endpoint는 이전 단계부터 존재하며 P1에서 새로 이전한 것으로 세지 않는다.

P2는 27개 공개 API와 첫 소비자에 필요한 조회/계획 파일/가용성 구현을 이전했다.
표에서 `P2 완료`는 facade의 기존 private 연결도 제거한 항목이다. `P2 구현 / P3~P5 연결 제거`는
아직 기획·실행·통합 명령에서 사용하는 연결만 남은 항목이며 P2 공개 API에서는 사용하지 않는다.
기준 376개 이름/57개 hook 후보 수는 최초 추적 자료로 유지한다. 현재 facade의 실제 개수와 혼동하지 않는다.

P3는 기획 공개 API 26개와 관련 56개 class 구현/조립 메서드를 실제 owner로 이전했다.
P3 당시 실행/통합이 사용하던 기획 연결과 provider endpoint는 P4~P5에서 제거했다.
P3에서 소비자가 없는 기획 연결 33개를 제거했고 당시 유지했던 Scope 연결도 P4~P5에서 정리했다.
공개 기획 API는 기능 owner를 직접 사용한다.

P4는 실행/관제 공개 API 32개와 내부 정의 145개를 실제 owner로 이전했다.
`ExecutionFlow`·`ExecutionPolicyLifecycle`·`ExecutionProfiles`·`TaskWorkflows`와 검증/복구 phase는
좁은 기록/설정/기능 port로 협력한다. 경로 승인·관제의 요청/잠금 순서는 `orchestration`이 소유한다.
P4 당시 P5가 사용하는 phase 연결 19개를 유지했고 P5에서 제거했다.
관련 별칭 22개와 기존 instance 연결 29개는 사용처와 함께 정리했다.
기존 공통 bridge·호환 별칭과 예전 helper도 P5에서 정리했다. P4 당시 facade는 2,215줄,
비-property 정의 176개(공개 112개)다. 최초 376개 항목은 계속 기준표로 유지한다.

P5에서 남은 private 정의 63개·class 별칭 61개와 instance bridge를 facade에서 제거했다.
현재 facade는 977줄이며 비-property 정의는 생성자 1개·공개 API 112개뿐이다.
아래 표는 최초 376개 이름의 최종 책임 추적표다. 구현이 이미 기능 API에 있는 호환 wrapper는
중복 복사하지 않고 해당 API를 직접 사용한다. `(port)`는 초기 배정 기록이며 전체 context나
facade callback을 구현했다는 뜻이 아니다. 실제 배선은 단계별 결과와 현재 소스를 따른다.

## 정의·별칭·endpoint 전수 배정

| 기준 private 이름 | 형태 | 동작 owner | 이전/별칭 제거 단계 | 기존 test hook 후보 수 |
|---|---|---|---|---:|
| `__init__` | definition | `pipeline_bootstrap.build_pipeline_runtime` | P1 | 0 |
| `_activate_manual_tasks` | definition | `execution.task_workflows.TaskWorkflows.activate_manual_tasks` | P4 완료 | 0 |
| `_active_group_kind` | alias | `run_queries.active_group_kind` | P5 완료 | 0 |
| `_advance_completed_tasks` | definition | `execution.preparation.advance_completed_tasks` | P4 완료 | 0 |
| `_advance_project_chat` | definition | `orchestration.control.RunControlCommands.advance_project_chat` | P4 완료 | 0 |
| `_agent_command` | alias | `execution.provider_commands.agent_command` | P5 완료 | 1 |
| `_agent_is_available` | definition | `execution.provider_choices.ProviderAvailability.is_available` | P4 완료 | 5 |
| `_agent_is_selectable` | definition | `execution.provider_choices.ProviderAvailability.is_selectable` | P4 완료 | 0 |
| `_append_planning_assistant_message` | definition | `planning.messages.PlanningMessages.append_assistant` | P4 완료 | 0 |
| `_append_planning_user_message` | definition | `planning.messages.PlanningMessages.append_user` | P4 완료 | 0 |
| `_apply_archive_cleanup` | definition | `integration.archive_flow.ArchiveFlow.apply_archive_cleanup` | P5 완료 | 0 |
| `_apply_chat_scope_approval` | definition | `orchestration.scope_approval.ScopeApprovalActions.apply_chat_scope_approval` | P4 완료 | 0 |
| `_apply_pending_task_changes` | definition | `planning.lifecycle.PlanningLifecycle.apply_pending` | P4 완료 | 2 |
| `_apply_plan` | definition | `planning.lifecycle.PlanningLifecycle.apply_plan` | P3 완료 | 0 |
| `_apply_planning_conversation_state` | definition | `planning.lifecycle.PlanningLifecycle.apply_conversation` | P3 완료 | 0 |
| `_apply_queued_changes_after_batch` | definition | `execution.flow.ExecutionFlow.apply_queued_changes_after_batch` | P4 완료 | 2 |
| `_apply_queued_execution_profiles` | definition | `execution.profile_workflows.ExecutionProfiles.apply_queued_execution_profiles` | P4 완료 | 0 |
| `_apply_quota_fallbacks` | definition | `execution.profile_workflows.ExecutionProfiles.apply_quota_fallbacks` | P4 완료 | 0 |
| `_apply_quota_profile` | alias | `execution.apply_quota_profile` | P5 완료 | 0 |
| `_apply_shared_run_to_main` | definition | `integration.main_apply_flow.MainApplyFlow.apply_shared_run_to_main` | P5 완료 | 0 |
| `_apply_task_agent_overrides` | definition | `execution.profile_workflows.ExecutionProfiles.apply_task_agent_overrides` | P4 완료 | 0 |
| `_apply_task_model_overrides` | definition | `execution.profile_workflows.ExecutionProfiles.apply_task_model_overrides` | P4 완료 | 0 |
| `_apply_task_reasoning_overrides` | definition | `execution.profile_workflows.ExecutionProfiles.apply_task_reasoning_overrides` | P4 완료 | 0 |
| `_archive_block_reasons` | definition | `integration.archive_flow.ArchiveFlow.archive_block_reasons` | P5 완료 | 0 |
| `_archive_cleanup_targets` | definition | `integration.workspace_flows.WorkspaceFlows.archive_cleanup_targets` | P5 완료 | 0 |
| `_archive_cleanup_workflow` | definition | `integration.archive_flow.ArchiveFlow.cleanup` | P5 완료 | 0 |
| `_archive_fingerprint` | definition | `integration.archive_views.archive_fingerprint` | P5 완료 | 0 |
| `_archive_request_id` | alias | `integration.archive_views.archive_request_id` | P5 완료 | 0 |
| `_archive_summary` | definition | `integration.archive_views.archive_summary` | P5 완료 | 0 |
| `_archive_target_payload` | alias | `integration.archive_views.archive_target_payload` | P5 완료 | 0 |
| `_archived_run_plan` | definition | `integration.archive_flow.ArchiveFlow.archived_run_plan` | P5 완료 | 0 |
| `_assign_next_execution_profile` | alias | `execution.assign_next_execution_profile` | P5 완료 | 0 |
| `_attention_decision` | alias | `run_queries.attention_decision` | P5 완료 | 0 |
| `_automatic_model_escalation_matches` | alias | `execution.automatic_model_escalation_matches` | P4 완료 | 0 |
| `_available_agent` | definition | `execution.provider_choices.ProviderAvailability.require` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_begin_effort_execution` | definition | `execution.policy_lifecycle.ExecutionPolicyLifecycle.begin_effort_execution` | P4 완료 | 1 |
| `_bootstrap_path_snapshot` | definition | `planning.bootstrap.bootstrap_path_snapshot` | P5 완료 | 0 |
| `_bootstrap_spec_digest` | alias | `planning.bootstrap.bootstrap_spec_digest` | P5 완료 | 0 |
| `_brief_worker_report` | alias | `execution.brief_worker_report` | P5 완료 | 0 |
| `_build_bootstrap_spec` | definition | `planning.bootstrap.BootstrapPlanner.build` | P3 완료 | 0 |
| `_build_plan` | definition | `planning.ai.PlanningAI.build_plan` | P3 완료 | 54 |
| `_build_plan_attempts` | definition | `planning.runner.PlanningRunner.run` | P3 완료 | 0 |
| `_candidate_content_digest` | definition | `integration.candidates.candidate_content_digest` | P5 완료 | 0 |
| `_candidate_verification` | definition | `integration.verification_flow.VerificationFlow.candidate_verification` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_chat_control_advancement` | definition | `orchestration.control.RunControlCommands.chat_control_advancement` | P4 완료 | 0 |
| `_chat_control_child` | definition | `orchestration.control.RunControlCommands.chat_control_child` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_chat_scope_proposal` | definition | `queries.scope_proposals.ScopeProposalQueries.proposal` | P4 완료 | 0 |
| `_chat_scope_question` | definition | `orchestration.control.RunControlCommands.chat_scope_question` | P4 완료 | 0 |
| `_chat_scope_was_offered` | definition | `orchestration.control.RunControlCommands.chat_scope_was_offered` | P4 완료 | 1 |
| `_check_external_plan_base` | definition | `orchestration.planning.PlanningCommands.check_base` | P3 완료 | 0 |
| `_check_manual_review` | definition | `execution.task_workflows.TaskWorkflows.check_manual_review` | P4 완료 | 0 |
| `_claim_git_operation` | definition | `integration.main_apply_flow.MainApplyFlow.claim_git_operation` | P5 완료 | 0 |
| `_claim_recovery_operation` | definition | `integration.recovery_flow.RecoveryFlow.claim_recovery_operation` | P4 완료 | 0 |
| `_clarification_context` | alias | `planning.conversation.clarification_context` | P5 완료 | 0 |
| `_claude_auth_status` | definition | `execution.provider_connection.claude_auth_status` | P2 완료 | 6 |
| `_claude_connection_details` | definition | `execution.provider_connection.read_claude_connection` | P2 완료 | 0 |
| `_clean_manual_workspace` | definition | `execution.task_workflows.TaskWorkflows.clean_manual_workspace` | P4 완료 | 0 |
| `_cleanup_archive_target` | definition | `integration.workspace_flows.WorkspaceFlows.cleanup_archive_target` | P5 완료 | 0 |
| `_cleanup_shared_workspace` | definition | `integration.workspace_flows.WorkspaceFlows.cleanup_shared_workspace` | P5 완료 | 1 |
| `_clear_active_execution_task` | definition | `execution.lifecycle.ExecutionControlService.clear_active_task` | P5 완료 | 0 |
| `_close_agent_process_streams` | alias | `execution.ProviderRunner.close_process_streams` | P5 완료 | 0 |
| `_codex_sdk_profile` | alias | `execution.ProviderRunner.codex_profile` | P5 완료 | 0 |
| `_collect_interrupted_tasks` | definition | `execution.task_workflows.TaskWorkflows.collect_interrupted_tasks` | P4 완료 | 0 |
| `_command_with_claude_session` | alias | `execution.provider_commands.command_with_claude_session` | P5 완료 | 0 |
| `_command_with_model` | alias | `execution.provider_commands.command_with_model` | P5 완료 | 0 |
| `_command_with_reasoning_effort` | definition | `execution.task_workflows.TaskWorkflows.command_with_reasoning_effort` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_commit_queue_tasks` | alias | `execution.commit_queue_tasks` | P4 완료 | 0 |
| `_committed_result_files` | definition | `execution.task_workflows.TaskWorkflows.committed_result_files` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_complete_greenfield_bootstrap` | definition | `integration.verification_flow.VerificationFlow.complete_greenfield_bootstrap` | P4 완료 | 0 |
| `_complete_task` | definition | `execution.task_workflows.TaskWorkflows.complete_task` | P4 완료 | 0 |
| `_completed_operation_replay` | definition | `integration.main_apply_flow.MainApplyFlow.completed_operation_replay` | P5 완료 | 0 |
| `_configure_planning_profile` | definition | `planning.profiles.PlanningProfiles.configure` | P4 완료 | 3 |
| `_confirm_execution_stopped` | definition | `execution.lifecycle.ExecutionControlService.confirm_stopped` | P5 완료 | 0 |
| `_confirm_push` | definition | `integration.main_apply_flow.MainApplyFlow.confirm_push` | P5 완료 | 0 |
| `_conflict_request_id` | alias | `integration.conflict_request_id` | P5 완료 | 0 |
| `_conflict_resolution_command` | definition | `integration.conflict_flow.ConflictFlow.conflict_resolution_command` | P5 완료 | 0 |
| `_conflict_resolution_profile` | definition | `integration.conflict_flow.ConflictFlow.conflict_resolution_profile` | P5 완료 | 0 |
| `_conflict_resolution_prompt` | alias | `integration.conflict_resolution_prompt` | P5 완료 | 0 |
| `_conflict_resolution_service` | definition | `integration.conflict_flow.ConflictFlow.service` | P5 완료 | 0 |
| `_connected_provider_ids` | definition | `execution.provider_choices.ConnectedProviderQueries.ids` | P4 완료 | 5 |
| `_control_planning_invocation` | definition | `orchestration.control.RunControlCommands.control_planning_invocation` | P4 완료 | 0 |
| `_create_planning_preview` | definition | `planning.PlanningPreviewWorkflow.create` | P3 완료 | 0 |
| `_decide_scope_consent` | definition | `orchestration.control.RunControlCommands.decide_scope_consent` | P4 완료 | 0 |
| `_deferred_execution_task_ids` | alias | `execution.deferred_execution_task_ids` | P4 완료 | 0 |
| `_deploy` | definition | `integration.main_apply_flow.MainApplyFlow.deploy_command` | P5 완료 | 0 |
| `_discard_conflict_candidate_worktree` | definition | `integration.conflict_flow.ConflictFlow.discard_conflict_candidate_worktree` | P5 완료 | 0 |
| `_effort_mode_preview` | definition | `execution.effort_previews.EffortPreviewQueries.build_preview` | P4 완료 | 0 |
| `_effort_queries` | definition | `pipeline_bootstrap → execution.EffortQueries` | P2 완료 | 0 |
| `_effort_reservation_allowed` | alias | `execution.effort_reservation_allowed` | P5 완료 | 0 |
| `_effort_state_key` | alias | `execution.effort_state_key` | P5 완료 | 0 |
| `_ensure_execution_workspace_ready` | definition | `integration.workspace_access.WorkspaceAccess.ensure_execution_workspace_ready` | P4 완료 | 0 |
| `_ensure_git_ready_for_planning` | definition | `planning.source_indexes.ensure_planning_git_ready` | P3 완료 | 1 |
| `_ensure_isolated_verification_inputs_current` | definition | `integration.verification.CandidateVerification.ensure_inputs_current` | P5 완료 | 0 |
| `_ensure_known_run` | definition | `persistence.run_lookup.RunLookup.require_known` | P5 완료 | 0 |
| `_ensure_main_worktree_ready` | definition | `integration.workspace_flows.WorkspaceFlows.ensure_main_worktree_ready` | P5 완료 | 1 |
| `_ensure_planning_provider_ready` | definition | `execution.provider_connection.ensure_planning_provider_ready` | P3 완료 | 1 |
| `_ensure_verification_head` | definition | `execution.verification_commands.VerificationCommands.ensure_verification_head` | P4 완료 | 2 |
| `_ensure_verification_policy` | definition | `planning.preparation.InitialVerificationSettings.ensure_verification` | P4 완료 | 0 |
| `_ensure_worktree_clean` | definition | `integration.workspace_access.WorkspaceAccess.ensure_worktree_clean` | 기존 구현 / P5 연결 제거 완료 | 2 |
| `_execute` | definition | `execution.flow.ExecutionFlow.execute` | P4 완료 | 31 |
| `_execute_project_chat_action` | definition | `orchestration.control.RunControlCommands.execute_project_chat_action` | P4 완료 | 0 |
| `_execute_task_locked` | definition | `execution.flow.ExecutionFlow.execute_task_locked` | P4 완료 | 0 |
| `_execute_verification_command` | definition | `execution.verification_commands.VerificationCommands.execute_verification_command` | P4 완료 | 0 |
| `_execute_with_bound_policy` | definition | `execution.flow.ExecutionFlow.execute_with_bound_policy` | P4 완료 | 14 |
| `_execution_branch_snapshot` | definition | `queries.control.RunControlQueries.branch_snapshot` | P2 완료 | 0 |
| `_execution_control_service` | definition | `execution.lifecycle.ExecutionControlService` | P5 완료 | 0 |
| `_execution_follow_up_request` | definition | `planning.messages.PlanningMessages.follow_up` | P3 완료 | 0 |
| `_execution_planning_chat_available` | definition | `planning.messages.PlanningMessages.execution_available` | P3 완료 | 0 |
| `_execution_session` | definition | `execution.lifecycle.ExecutionControlService.owned_session` | P5 완료 | 1 |
| `_extend_task_timeout_for_recovery` | definition | `execution.task_workflows.TaskWorkflows.extend_task_timeout_for_recovery` | P4 완료 | 0 |
| `_fail_git_operation` | definition | `integration.main_apply_flow.MainApplyFlow.fail_git_operation` | P5 완료 | 0 |
| `_fail_recovery_operation` | definition | `integration.recovery_flow.RecoveryFlow.fail_recovery_operation` | P4 완료 | 0 |
| `_file_sha256` | alias | `planning.bootstrap.file_sha256` | P5 완료 | 0 |
| `_find_task` | definition | `persistence.run_lookup.find_task` | P5 완료 | 0 |
| `_finish_effort_execution_binding` | definition | `execution.policy_lifecycle.ExecutionPolicyLifecycle.finish_effort_execution_binding` | P4 완료 | 0 |
| `_finish_execution_session` | definition | `execution.lifecycle.ExecutionControlService.finish_session` | P5 완료 | 0 |
| `_finish_isolated_main_apply` | definition | `integration.main_apply_flow.MainApplyFlow.finish_isolated_main_apply` | P5 완료 | 0 |
| `_finish_shared_main_apply` | definition | `integration.main_apply_flow.MainApplyFlow.finish_shared_main_apply` | P5 완료 | 0 |
| `_finish_verification_repair` | definition | `integration.verification_flow.VerificationFlow.finish_verification_repair` | P4 완료 | 0 |
| `_generate_greenfield_feature_plan` | definition | `planning.lifecycle.PlanningLifecycle.generate_features` | 기존 구현 / P5 연결 제거 완료 | 1 |
| `_generate_project_chat_decision` | definition | `orchestration.control.RunControlCommands.generate_project_chat_decision` | P4 완료 | 0 |
| `_generate_result_revision_proposal` | definition | `planning.proposals.ResultRevisionAI.generate` | P3 완료 | 0 |
| `_git_operation_recorder` | definition | `integration.main_apply_flow.MainApplyFlow.git_operation_recorder` | P5 완료 | 0 |
| `_infer_task_action` | alias | `execution.infer_task_action` | P4 완료 | 0 |
| `_integrate_recovery_commits` | definition | `integration.recovery_flow.RecoveryFlow.integrate_recovery_commits` | P4 완료 | 0 |
| `_integration_branch_name` | alias | `integration.integration_branch_name` | P5 완료 | 0 |
| `_integration_conflict_fingerprint` | alias | `integration.integration_conflict_fingerprint` | P4 완료 | 0 |
| `_integration_control` | definition | `queries.control.RunControlQueries.integration_control` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_integration_inspector` | definition | `pipeline_bootstrap → integration.IntegrationInspector` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_integration_verification_command_selection` | definition | `integration.verification_flow.VerificationFlow.integration_verification_command_selection` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_integration_verification_commands` | definition | `execution.run_verification.integration_verification_command_selection` | P5 완료 | 0 |
| `_invalidate_integration_verification` | definition | `integration.verification_flow.VerificationFlow.invalidate_integration_verification` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_invoke_agent` | definition | `execution.task_workflows.TaskWorkflows.invoke_agent` | P4 완료 | 52 |
| `_invoke_planning_agent` | definition | `planning.ai.PlanningAI.invoke` | P4 완료 | 25 |
| `_invoke_provider_command` | endpoint | `execution.provider_runtime.ProviderRuntime.invoke` | 기존 구현 / P5 연결 제거 완료 | 34 |
| `_is_dotnet_command` | alias | `execution.VerificationRunner.is_dotnet_command` | P4 완료 | 0 |
| `_is_orchestrator_managed_verification_command` | alias | `execution.run_verification.is_orchestrator_managed_verification_command` | P4 완료 | 0 |
| `_load_at` | definition | `persistence.run_lookup.RunLookup.at` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_main_apply_recovery_ready` | definition | `integration.main_apply_flow.MainApplyFlow.main_apply_recovery_ready` | P5 완료 | 0 |
| `_main_apply_review` | definition | `integration.main_apply_flow.MainApplyFlow.main_apply_review` | P5 완료 | 0 |
| `_main_change_service` | definition | `integration.main_changes.MainChangeService` | P5 완료 | 0 |
| `_main_changes_locked` | definition | `integration.main_changes.MainChangeService.snapshot` | P5 완료 | 1 |
| `_mark_task_interrupted` | definition | `execution.task_workflows.TaskWorkflows.mark_task_interrupted` | P4 완료 | 0 |
| `_merge` | definition | `integration.main_apply_flow.MainApplyFlow.merge_isolated` | P5 완료 | 0 |
| `_merge_shared_run` | definition | `integration.main_apply_flow.MainApplyFlow.merge_shared_run` | P5 완료 | 0 |
| `_merge_task_dependencies` | definition | `execution.task_workflows.TaskWorkflows.merge_task_dependencies` | P4 완료 | 0 |
| `_new_planning_apply_request` | definition | `pipeline_planning_bootstrap → planning.PlanningApplyRequests.create` | P3 완료 | 0 |
| `_normalize_agent_id` | alias | `execution.normalize_agent_id` | P4 완료 | 0 |
| `_normalize_planning_apply_request_id` | alias | `planning.apply_requests.normalize_planning_apply_request_id` | P5 완료 | 0 |
| `_normalize_planning_mode` | definition | `planning.profiles.normalize_planning_mode` | P5 완료 | 0 |
| `_normalize_planning_model` | alias | `execution.normalize_model` | P4 완료 | 0 |
| `_normalize_reasoning_effort` | alias | `execution.normalize_reasoning_effort` | P5 완료 | 0 |
| `_npm_dependency_restore_commands` | alias | `execution.VerificationRunner.npm_dependency_restore_commands` | P5 완료 | 0 |
| `_npm_verification_command` | alias | `execution.VerificationRunner.npm_verification_command` | P5 완료 | 0 |
| `_nvidia_command_failure` | definition | `execution.provider_runner.ProviderRunner.nvidia_failure + execution.provider_runtime.translate_provider_error` | P5 완료 | 0 |
| `_parse_result_revision_proposal` | definition | `planning.proposals.ResultRevisionAI.parse` | P3 완료 | 0 |
| `_parse_review` | definition | `execution.task_workflows.TaskWorkflows.parse_review` | P4 완료 | 0 |
| `_pause_for_direction_change` | definition | `execution.flow.ExecutionFlow.pause_for_direction_change` | P4 완료 | 0 |
| `_perform_chat_execution_profile` | definition | `orchestration.control.RunControlCommands.perform_chat_execution_profile` | P4 완료 | 0 |
| `_perform_project_chat` | definition | `orchestration.control.RunControlCommands.perform_project_action` | P4 완료 | 0 |
| `_perform_task_verification` | definition | `execution.task_workflows.TaskWorkflows.perform_task_verification` | P4 완료 | 1 |
| `_pin_automatic_planning_profile` | definition | `planning.profiles.PlanningProfiles.pin_automatic` | P3 완료 | 0 |
| `_plan_result_paths` | definition | `planning.plan_files.PlanFiles.result_paths` | P4 완료 | 0 |
| `_planning_apply_request` | alias | `planning.planning_apply_request` | P5 완료 | 0 |
| `_planning_base_commit` | definition | `pipeline_planning_bootstrap.base_commit` | P3 완료 | 0 |
| `_planning_cache_key` | definition | `planning.ai.PlanningAI.cache_key` | P3 완료 | 0 |
| `_planning_chat_prompt` | definition | `planning.ai.PlanningAI.chat_prompt` | P3 완료 | 0 |
| `_planning_command_with_model` | definition | `execution.provider_commands.command_with_model` | P5 완료 | 0 |
| `_planning_conversation_id` | alias | `planning.conversation.planning_conversation_id` | P5 완료 | 0 |
| `_planning_effort_scope` | definition | `planning.policy_scope.PlanningPolicyScope` | P4 완료 | 3 |
| `_planning_execution_agents` | definition | `execution.provider_choices.ProviderChoiceQueries.planning_execution_agents` | P4 완료 | 2 |
| `_planning_index_for_start` | definition | `planning.source_indexes.PlanningSourceIndexes.for_start` | P3 완료 | 0 |
| `_planning_materialization_prompt` | alias | `planning.conversation.planning_materialization_prompt` | P5 완료 | 0 |
| `_planning_message_is_apply_control` | alias | `planning.conversation.planning_message_is_apply_control` | P5 완료 | 0 |
| `_planning_message_requests_apply` | alias | `planning.conversation.planning_message_requests_apply` | P4 완료 | 0 |
| `_planning_message_requests_initial_tasks` | alias | `planning.conversation.planning_message_requests_initial_tasks` | P5 완료 | 0 |
| `_planning_preview_changes` | definition | `planning.PlanningPreviewWorkflow.changes` | P4 완료 | 0 |
| `_planning_preview_fingerprint` | definition | `planning.PlanningPreviewWorkflow.fingerprint` | P3 완료 | 0 |
| `_planning_preview_operations` | alias | `planning.planning_preview_operations` | P5 완료 | 0 |
| `_planning_preview_task_fields` | alias | `planning.planning_preview_task_fields` | P5 완료 | 0 |
| `_planning_preview_workflow` | definition | `pipeline_planning_bootstrap → planning.PlanningPreviewWorkflow` | P3 완료 | 0 |
| `_planning_profiles` | definition | `pipeline_planning_bootstrap → planning.profiles.PlanningProfiles` | P3 완료 | 0 |
| `_planning_repository_context` | definition | `pipeline_planning_bootstrap → planning.initialization.PlanningRepositoryContext` | P3 완료 | 0 |
| `_planning_request_records` | definition | `orchestration.control.RunControlCommands.planning_request_records` | P4 완료 | 0 |
| `_planning_response_text` | alias | `planning.conversation.planning_response_text` | P5 완료 | 0 |
| `_planning_source_index_snapshot` | definition | `planning.source_indexes.PlanningSourceIndexes.snapshot` | P3 완료 | 0 |
| `_planning_source_indexes` | definition | `pipeline_planning_bootstrap → planning.source_indexes.PlanningSourceIndexes` | P3 완료 | 0 |
| `_planning_source_manifest_document` | alias | `planning.documents.planning_source_manifest_document` | P5 완료 | 0 |
| `_planning_task_editable` | alias | `planning.planning_task_editable` | P5 완료 | 0 |
| `_preflight_task_environment` | definition | `execution.verification_commands.VerificationCommands.preflight_task_environment` | P4 완료 | 1 |
| `_prepare_chat_execution_profile` | definition | `orchestration.control.RunControlCommands.prepare_chat_execution_profile` | P4 완료 | 0 |
| `_prepare_chat_scope_decision` | definition | `orchestration.control.RunControlCommands.prepare_chat_scope_decision` | P4 완료 | 0 |
| `_prepare_result_revision_run` | definition | `planning.intake.PlanningIntake.prepare_revision_run` | P3 완료 | 0 |
| `_prepare_task_for_dispatch` | definition | `execution.flow.ExecutionFlow.prepare_task_for_dispatch` | P4 완료 | 0 |
| `_prepare_tasks` | definition | `execution.preparation.TaskExecutionPreparation.prepare` | P4 완료 | 0 |
| `_prepare_verification_command` | definition | `execution.verification_commands.VerificationCommands.prepare_verification_command` | P4 완료 | 7 |
| `_project_chat_action_workflow` | definition | `orchestration.control.RunControlCommands.project_chat_action_workflow` | P4 완료 | 0 |
| `_project_chat_actions` | definition | `orchestration.control.RunControlCommands.project_chat_actions` | P4 완료 | 0 |
| `_project_chat_decisions` | definition | `orchestration.control.RunControlCommands.project_chat_decisions` | P4 완료 | 0 |
| `_project_chat_fingerprint` | definition | `queries.scope_proposals.ScopeProposalQueries.fingerprint` | P4 완료 | 0 |
| `_project_chat_records` | definition | `orchestration.control.RunControlCommands.project_chat_records` | P4 완료 | 0 |
| `_promote_automatic_model` | definition | `execution.profile_workflows.ExecutionProfiles.promote_automatic_model` | P4 완료 | 0 |
| `_prompt` | definition | `execution.task_prompts.task_prompt_from_state` | P5 완료 | 0 |
| `_protect_archive_commits` | definition | `integration.archive_flow.ArchiveFlow.protect_archive_commits` | P5 완료 | 0 |
| `_protected_greenfield_bootstrap` | definition | `planning.plan_review.protected_greenfield_bootstrap` | P5 완료 | 0 |
| `_provider_availability` | definition | `pipeline_bootstrap → execution.provider_choices.ProviderAvailability` | P2 완료 | 0 |
| `_provider_choice_queries` | definition | `pipeline_bootstrap → execution.provider_choices.ProviderChoiceQueries` | P2 완료 | 0 |
| `_provider_choices` | definition | `execution.provider_choices.ProviderChoiceQueries.choices` | P2 완료 | 0 |
| `_provider_command_failure_message` | alias | `execution.ProviderRunner.failure_message` | P5 완료 | 0 |
| `_provider_error` | definition | `execution.provider_runtime.translate_provider_error` | P5 완료 | 0 |
| `_provider_invocation` | definition | `pipeline_provider_bootstrap → execution.ProviderInvocation` | P3 완료 | 0 |
| `_provider_runner` | definition | `pipeline_provider_bootstrap → execution.ProviderRunner` | P3 완료 | 0 |
| `_provider_status_executable` | definition | `execution.provider_connection.ProviderConnectionProbes.executable` | P2 완료 | 0 |
| `_public_planning_preview` | definition | `planning.PlanningPreviewWorkflow.public` | P4 완료 | 0 |
| `_push` | definition | `integration.main_apply_flow.MainApplyFlow.push_main` | P5 완료 | 0 |
| `_push_preflight` | definition | `integration.main_apply_flow.MainApplyFlow.push_preflight` | P5 완료 | 0 |
| `_queue_task_execution_profile` | definition | `execution.profile_workflows.ExecutionProfiles.queue_task_execution_profile` | P4 완료 | 0 |
| `_quota_fallback_matches` | definition | `execution.profile_workflows.ExecutionProfiles.quota_fallback_matches` | P4 완료 | 0 |
| `_quota_fallback_service` | definition | `execution.profile_workflows.ExecutionProfiles.quota` | P4 완료 | 0 |
| `_raise_existing_recovery_operation` | alias | `integration.raise_existing_recovery_operation` | P4 완료 | 0 |
| `_raise_if_stopped` | definition | `execution.lifecycle.raise_if_stopped` | P5 완료 | 0 |
| `_read_task_log_tail` | definition | `orchestration.queries.RunQueries.read_log_tail` | P5 완료 | 0 |
| `_ready_tasks` | alias | `execution.ready_tasks` | P4 완료 | 1 |
| `_reconcile_recovery_operation` | definition | `integration.recovery.RecoveryWorkflow.reconcile` | P5 완료 | 0 |
| `_record_execution_chat` | definition | `execution.control_messages.ExecutionMessages.record` | P4 완료 | 0 |
| `_record_group_result` | definition | `execution.results.record_group_result` | P5 완료 | 0 |
| `_record_planning_progress` | definition | `planning.invocation.record_planning_progress` | P5 완료 | 0 |
| `_record_retry_wait` | definition | `pipeline_bootstrap.record_retry_wait` | P4 완료 | 0 |
| `_record_review` | definition | `execution.task_workflows.TaskWorkflows.record_review` | P4 완료 | 0 |
| `_record_stop_checkpoint` | definition | `execution.lifecycle.ExecutionControlService.record_checkpoint` | P5 완료 | 0 |
| `_record_task_execution_profile` | definition | `execution.task_workflows.TaskWorkflows.record_task_execution_profile` | P4 완료 | 0 |
| `_record_task_progress` | definition | `execution.task_workflows.TaskWorkflows.record_task_progress` | P4 완료 | 0 |
| `_record_task_result` | definition | `execution.task_workflows.TaskWorkflows.record_task_result` | P4 완료 | 2 |
| `_record_task_scope_check` | definition | `execution.task_evidence.TaskScopeInspector.record_check` | P5 완료 | 0 |
| `_record_task_start_commit` | definition | `execution.task_workflows.TaskWorkflows.record_task_start_commit` | P4 완료 | 0 |
| `_record_verification_failure` | definition | `integration.verification_flow.VerificationFlow.record_verification_failure` | P4 완료 | 0 |
| `_recovery_operation_digest` | alias | `integration.recovery_operation_digest` | P5 완료 | 0 |
| `_recovery_operation_payload` | definition | `integration.recovery.RecoveryWorkflow.payload` | P5 완료 | 0 |
| `_recovery_plan` | definition | `integration.recovery_flow.RecoveryFlow.recovery_plan` | P4 완료 | 0 |
| `_recovery_preview_input` | definition | `integration.recovery_flow.RecoveryFlow.recovery_preview_input` | P4 완료 | 0 |
| `_recovery_workflow` | definition | `integration.recovery_flow.RecoveryFlow.recovery_workflow` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_refresh_stored_plan_tasks` | definition | `planning.plan_files.PlanFiles.refresh_tasks` | P4 완료 | 0 |
| `_refresh_task_code_style_evidence` | alias | `execution.refresh_task_code_style_evidence` | P4 완료 | 1 |
| `_repair_task_from_chat` | definition | `orchestration.control.RunControlCommands.repair_task_locked` | P4 완료 | 0 |
| `_repair_verification_failure` | definition | `integration.verification_flow.VerificationFlow.repair_verification_failure` | P4 완료 | 4 |
| `_replace_tech_stack_decision` | definition | `planning.bootstrap.replace_tech_stack_decision` | P3 완료 | 0 |
| `_replan_recovery_tasks` | definition | `integration.recovery_flow.RecoveryFlow.replan_recovery_tasks` | P4 완료 | 0 |
| `_replayed_recovery_result` | definition | `integration.recovery_flow.RecoveryFlow.replayed_recovery_result` | P4 완료 | 0 |
| `_require_confirmed_plan` | definition | `execution.policy_lifecycle.ExecutionPolicyLifecycle.require_confirmed_plan` | P4 완료 | 0 |
| `_require_confirmed_profiles` | definition | `execution.policy_lifecycle.ExecutionPolicyLifecycle.require_confirmed_profiles` | P4 완료 | 0 |
| `_require_integration_conflict` | alias | `integration.require_integration_conflict` | P5 완료 | 0 |
| `_require_manual_task_version` | definition | `execution.task_workflows.TaskWorkflows.require_manual_task_version` | P4 완료 | 0 |
| `_require_waiting_manual_workspace` | definition | `execution.task_workflows.TaskWorkflows.require_waiting_manual_workspace` | P4 완료 | 0 |
| `_resolve_executable` | alias | `execution.provider_connection.ProviderConnectionProbes.resolve_executable` | P4 완료 | 36 |
| `_resolved_execution_policy` | definition | `execution.policy_lifecycle.ExecutionPolicyLifecycle.resolved_execution_policy` | P4 완료 | 0 |
| `_restore_legacy_no_commit_retry_action` | definition | `execution.task_workflows.TaskWorkflows.restore_legacy_no_commit_retry_action` | P4 완료 | 0 |
| `_restore_verification_repair_stop` | definition | `integration.verification_flow.VerificationFlow.restore_verification_repair_stop` | P4 완료 | 0 |
| `_result_planning_chat_available` | definition | `planning.messages.PlanningMessages.result_available` | P3 완료 | 0 |
| `_result_revision_available_paths` | alias | `planning.result_revision_available_paths` | P5 완료 | 0 |
| `_result_revision_context` | alias | `planning.result_revision_context` | P5 완료 | 0 |
| `_result_revision_evidence` | alias | `planning.result_revision_evidence` | P5 완료 | 0 |
| `_result_revision_fingerprint` | definition | `planning.proposals.ResultRevisionAI.fingerprint` | P3 완료 | 0 |
| `_result_revision_retry_instruction` | definition | `execution.task_workflows.TaskWorkflows.result_revision_retry_instruction` | P4 완료 | 0 |
| `_result_revisions` | definition | `pipeline_planning_bootstrap → planning.ResultRevisionWorkflow` | P3 완료 | 0 |
| `_result_workspace` | definition | `integration.workspace_flows.WorkspaceFlows.result_workspace` | P5 완료 | 0 |
| `_resume` | definition | `execution.flow.ExecutionFlow.resume` | P4 완료 | 7 |
| `_retry_task_contract_digest` | alias | `execution.retry_task_contract_digest` | P4 완료 | 0 |
| `_review_prompt` | definition | `execution.task_workflows.TaskWorkflows.review_prompt` | P4 완료 | 0 |
| `_reviewer_provider_is_compatible` | definition | `execution.provider_choices.ProviderAvailability.reviewer_compatible` | P4 완료 | 0 |
| `_revision_prompt` | definition | `execution.task_workflows.TaskWorkflows.revision_prompt` | P4 완료 | 0 |
| `_run_deletion_conflict_worktree` | definition | `integration.workspace_flows.WorkspaceFlows.run_deletion_conflict_worktree` | P5 완료 | 0 |
| `_run_deletion_targets` | definition | `integration.workspace_flows.WorkspaceFlows.run_deletion_targets` | P5 완료 | 0 |
| `_run_deletion_verification_worktree` | definition | `integration.workspace_flows.WorkspaceFlows.run_deletion_verification_worktree` | P5 완료 | 0 |
| `_run_execution_control` | definition | `queries.control.RunControlQueries.execution_control` | P2 완료 | 0 |
| `_run_executor` | definition | `execution.task_workflows.TaskWorkflows.run_executor` | P4 완료 | 6 |
| `_run_pinned_verification` | definition | `integration.verification_flow.VerificationFlow.run_pinned_verification` | P4 완료 | 0 |
| `_run_planning_chat_turn` | definition | `planning.ai.PlanningAI.chat_turn` | P3 완료 | 1 |
| `_run_planning_chat_turn_with_policy` | definition | `planning.chat.PlanningChatRunner.run` | P3 완료 | 0 |
| `_run_provider_command` | endpoint | `execution.provider_runtime.ProviderRuntime.run` | P4 완료 | 3 |
| `_run_review` | definition | `execution.task_workflows.TaskWorkflows.run_review` | P4 완료 | 0 |
| `_run_review_cycles` | definition | `execution.task_workflows.TaskWorkflows.run_review_cycles` | P4 완료 | 1 |
| `_run_summary_queries` | definition | `pipeline_bootstrap → queries.RunSummaryQueries` | P2 완료 | 0 |
| `_run_task` | definition | `execution.task_workflows.TaskWorkflows.run_task` | P4 완료 | 3 |
| `_run_task_attempt` | definition | `execution.task_workflows.TaskWorkflows.run_task_attempt` | P4 완료 | 3 |
| `_run_task_batch` | definition | `execution.flow.ExecutionFlow.run_task_batch` | P4 완료 | 4 |
| `_run_task_verification` | definition | `execution.task_workflows.TaskWorkflows.run_task_verification` | P4 완료 | 5 |
| `_run_verification_commands` | definition | `integration.verification_flow.VerificationFlow.run_verification_commands` | P4 완료 | 1 |
| `_run_worktree_root` | definition | `integration.workspace_access.WorkspaceAccess.run_worktree_root` | 기존 구현 / P5 연결 제거 완료 | 1 |
| `_safe_main_remote_error` | definition | `integration.main_changes.MainChangeService.safe_remote_error` | P5 완료 | 0 |
| `_save_task_execution_profile_locked` | definition | `execution.profile_workflows.ExecutionProfiles.save_task_execution_profile_locked` | P4 완료 | 0 |
| `_save_task_progress` | definition | `execution.task_workflows.TaskWorkflows.save_task_progress` | P4 완료 | 0 |
| `_scope_approval_queries` | definition | `orchestration.scope_approval.ScopeApprovalActions.scope_approval_queries` | P4 완료 | 0 |
| `_scope_approval_result` | definition | `orchestration.scope_approval.ScopeApprovalActions.scope_approval_result` | P4 완료 | 0 |
| `_scope_review_paths_allowed` | definition | `execution.task_evidence.scope_review_paths_allowed` | P5 완료 | 0 |
| `_send_execution_planning_message` | definition | `orchestration.planning.PlanningCommands.send_execution_message` | P3 완료 | 0 |
| `_set_active_execution_task` | definition | `execution.lifecycle.ExecutionControlService.set_active_task` | P5 완료 | 0 |
| `_shared_main_push_recovery_source` | definition | `integration.workspace_access.WorkspaceAccess.shared_main_push_recovery_source` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_shared_run_branch_name` | alias | `integration.shared_run_branch_name` | P5 완료 | 0 |
| `_shared_run_worktree_path` | definition | `integration.layout.WorkspaceLayout.shared_path` | P5 완료 | 0 |
| `_shared_workspace_boundary` | definition | `integration.workspace_access.WorkspaceAccess.shared_workspace_boundary` | 기존 구현 / P5 연결 제거 완료 | 1 |
| `_snapshot_planning_source` | alias | `planning.documents.snapshot_planning_source` | P5 완료 | 0 |
| `_snapshot_planning_sources` | definition | `planning.documents.snapshot_planning_sources` | P3 완료 | 0 |
| `_step` | definition | `execution.operation_lifecycle.RunStepLifecycle` | P1 | 0 |
| `_stop_signal` | definition | `execution.lifecycle.make_stored_stop_signal` | P5 완료 | 1 |
| `_stored_path_values` | definition | `planning.plan_files.PlanFiles.stored_path_values` | P2 완료 | 0 |
| `_summary_attention_reasons` | alias | `run_queries.summary_attention_reasons` | P5 완료 | 0 |
| `_summary_execution_control` | definition | `queries.control.RunControlQueries.summary_control` | P2 완료 | 0 |
| `_task_action` | definition | `execution.task_workflows.TaskWorkflows.task_action` | P4 완료 | 0 |
| `_task_action_runner` | definition | `execution.task_workflows.TaskWorkflows.actions` | P4 완료 | 0 |
| `_task_activity_recorder` | definition | `execution.task_workflows.TaskWorkflows.activity` | P4 완료 | 0 |
| `_task_cancellation` | definition | `execution.task_workflows.TaskWorkflows.task_cancellation` | P4 완료 | 0 |
| `_task_dispatcher` | definition | `execution.flow.ExecutionFlow.task_dispatcher` | P4 완료 | 0 |
| `_task_execution_profile_snapshot` | alias | `execution.task_execution_profile_snapshot` | P4 완료 | 0 |
| `_task_execution_prompt` | definition | `execution.task_workflows.TaskWorkflows.task_execution_prompt` | P4 완료 | 0 |
| `_task_has_recorded_implementation` | definition | `execution.task_workflows.TaskWorkflows.task_has_recorded_implementation` | P4 완료 | 0 |
| `_task_path_matches` | alias | `execution.scope_path_matches` | P5 완료 | 0 |
| `_task_plan_draft` | alias | `planning.conversation.task_plan_draft` | P4 완료 | 0 |
| `_task_profile_service` | definition | `execution.profile_workflows.ExecutionProfiles.service` | P4 완료 | 0 |
| `_task_profile_validator` | definition | `execution.profile_workflows.ExecutionProfiles.validator` | P4 완료 | 0 |
| `_task_recovery_capability` | definition | `execution.retry_guidance.TaskRetryGuidance.capability` | P4 완료 | 1 |
| `_task_recovery_runner` | definition | `execution.task_workflows.TaskWorkflows.recovery` | P4 완료 | 0 |
| `_task_retry_context` | definition | `execution.retry_guidance.TaskRetryGuidance.context` | P4 완료 | 1 |
| `_task_retry_guidance` | definition | `execution.task_workflows.TaskWorkflows.retry` | P4 완료 | 0 |
| `_task_scope_contract_digest` | alias | `execution.scope_contract_digest` | P4 완료 | 0 |
| `_task_scope_exclusions` | definition | `execution.task_evidence.TaskScopeInspector.exclusions` | P5 완료 | 0 |
| `_task_scope_inspector` | definition | `execution.task_workflows.TaskWorkflows.scope_inspector` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_task_scope_review` | definition | `execution.task_workflows.TaskWorkflows.task_scope_review` | P4 완료 | 1 |
| `_task_stop_check` | definition | `execution.task_workflows.TaskWorkflows.task_stop_check` | P4 완료 | 0 |
| `_task_verification_failure_fingerprint` | definition | `execution.task_workflows.TaskWorkflows.task_verification_failure_fingerprint` | P4 완료 | 0 |
| `_task_verification_service` | definition | `execution.task_workflows.TaskWorkflows.verification` | P4 완료 | 0 |
| `_task_verification_timed_out` | definition | `execution.retry_guidance.task_verification_timed_out` | P4 완료 | 0 |
| `_terminate_agent_process` | alias | `execution.ProviderRunner.terminate_process` | P5 완료 | 3 |
| `_timeout_expired_output` | alias | `execution.ProviderRunner.timeout_expired_output` | P5 완료 | 0 |
| `_uses_shared_workspace` | alias | `integration.uses_shared_workspace` | P5 완료 | 2 |
| `_validate_chat_control_target` | definition | `orchestration.scope_approval.ScopeApprovalActions.validate_chat_control_target` | P4 완료 | 0 |
| `_validate_effort_execution_snapshot` | definition | `execution.policy_lifecycle.ExecutionPolicyLifecycle.validate_effort_execution_snapshot` | P4 완료 | 0 |
| `_validate_planning_apply_replay` | alias | `planning.apply_requests.validate_planning_apply_replay` | P5 완료 | 0 |
| `_validate_planning_preview_payload` | alias | `planning.validate_planning_preview_payload` | P5 완료 | 0 |
| `_validate_reasoning_effort` | alias | `execution.validate_reasoning_effort` | P5 완료 | 0 |
| `_validate_recovery_replan_resume` | definition | `integration.recovery_flow.RecoveryFlow.validate_recovery_replan_resume` | P4 완료 | 0 |
| `_validate_task_change_scope` | definition | `execution.task_workflows.TaskWorkflows.validate_task_change_scope` | P4 완료 | 3 |
| `_validate_task_model_overrides` | definition | `execution.profile_workflows.ExecutionProfiles.validate_task_model_overrides` | P4 완료 | 0 |
| `_validate_task_profile_override_targets` | alias | `execution.validate_task_profile_override_targets` | P4 완료 | 0 |
| `_validate_task_reasoning_overrides` | definition | `execution.profile_workflows.ExecutionProfiles.validate_task_reasoning_overrides` | P4 완료 | 0 |
| `_validate_tech_stack_apply` | alias | `planning.apply_requests.validate_tech_stack_apply` | P5 완료 | 0 |
| `_validate_tech_stack_apply_replay` | alias | `planning.apply_requests.validate_tech_stack_apply_replay` | P5 완료 | 0 |
| `_validated_next_execution_profile` | definition | `execution.profile_workflows.ExecutionProfiles.validated_next_execution_profile` | P4 완료 | 0 |
| `_validated_plan_draft` | definition | `planning.PlanDraftValidator.validate` | P3 완료 | 0 |
| `_validated_planning_plan` | definition | `planning.ai.PlanningAI.validate_plan` | P3 완료 | 0 |
| `_verification_build_output_access_denied` | alias | `execution.VerificationRunner.build_output_access_denied` | P5 완료 | 0 |
| `_verification_command_timeout` | definition | `execution.verification_runner.VerificationRunner.command_timeout` | P5 완료 | 0 |
| `_verification_failure_is_repairable` | definition | `integration.verification_flow.VerificationFlow.verification_failure_is_repairable` | P4 완료 | 0 |
| `_verification_output_file_locked` | alias | `execution.VerificationRunner.output_file_locked` | P5 완료 | 0 |
| `_verification_repair_workflow` | definition | `orchestration.control.RunControlCommands.verification_repair_workflow` | P4 완료 | 0 |
| `_verification_resume_stage` | definition | `execution.verification_commands.VerificationCommands.verification_resume_stage` | P4 완료 | 0 |
| `_verification_worktree_path` | definition | `integration.workspace_access.WorkspaceAccess.verification_worktree_path` | P4 완료 | 0 |
| `_verify_and_repair` | definition | `orchestration.control.RunControlCommands.verify_and_repair` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_verify_before_merge` | definition | `integration.verification_flow.VerificationFlow.verify_before_merge` | P4 완료 | 1 |
| `_verify_bootstrap_spec_current` | definition | `planning.bootstrap.BootstrapPlanner.verify_current` | P4 완료 | 0 |
| `_verify_legacy_merged_run` | definition | `integration.verification_flow.VerificationFlow.verify_legacy_merged_run` | P4 완료 | 0 |
| `_verify_locked` | definition | `integration.verification_flow.VerificationFlow.verify_locked` | 기존 구현 / P5 연결 제거 완료 | 4 |
| `_verify_shared_workspace` | definition | `integration.verification_flow.VerificationFlow.verify_shared_workspace` | P4 완료 | 1 |
| `_waiting_for_user_checks` | definition | `execution.flow.ExecutionFlow.waiting_for_user_checks` | P4 완료 | 0 |
| `_with_effort_mode_guidance` | definition | `execution.task_workflows.TaskWorkflows.with_effort_mode_guidance` | P4 완료 | 0 |
| `_with_project_dotnet_guidance` | definition | `execution.task_workflows.TaskWorkflows.with_project_dotnet_guidance` | P4 완료 | 0 |
| `_with_task_execution_efficiency_guidance` | alias | `execution.with_task_execution_efficiency_guidance` | P4 완료 | 0 |
| `_with_task_worktree_contract` | alias | `execution.with_task_worktree_contract` | P4 완료 | 0 |
| `_workspace_inspector` | definition | `integration.workspace_access.WorkspaceAccess.inspector` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_workspace_layout` | definition | `integration.workspace_access.WorkspaceAccess.layout` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_workspace_lifecycle` | definition | `integration.workspace_flows.WorkspaceFlows.lifecycle` | P5 완료 | 0 |
| `_workspace_location` | definition | `integration.layout.WorkspaceLayout.location` | P5 완료 | 0 |
| `_workspace_state` | definition | `integration.workspace_access.WorkspaceAccess.workspace_state` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_workspace_status` | definition | `integration.workspace_flows.WorkspaceFlows.workspace_status` | P5 완료 | 1 |
| `_worktree_is_clean` | definition | `integration.workspace_access.WorkspaceAccess.worktree_is_clean` | P4 완료 | 0 |
| `_worktree_managed_state_roots` | definition | `integration.workspace_access.WorkspaceAccess.worktree_managed_state_roots` | 기존 구현 / P5 연결 제거 완료 | 0 |
| `_write_plan_result` | definition | `planning.plan_files.PlanFiles.write_result` | P4 완료 | 0 |

## 테스트 hook 이전 경계

기준 테스트에는 private callable을 대체하는 AST 후보가 **360곳/57개 이름** 있다.
위 표의 마지막 열이 57개 이름 모두의 이전 대상이다. 이 수치는 텍스트·구문 기반 후보 수이며
실제 실행 횟수나 실패 개수가 아니다. 0인 행도 외부 사용/동적 호출 여부 확인 없이 삭제하지 않는다.

- P1: credential 생성 함수를 패치하는 fixture는 `pipeline_bootstrap.current_*`로 옮겼다.
  scope의 nesting/오류 정리와 live 자원 port는 제한된 별도 경계 검사로 확인했다.
- `_step`/`_planning_effort_scope`의 호출은 같은 instance callable로 유지한다. 새 기능 테스트는
  `RunStepLifecycle`/`PlanningPolicyScope`의 기록·AI port를 주입하고 최종 상태/오류/receipt를 확인한다.
- P2: `_resolve_executable`/`_claude_auth_status` fixture는 인스턴스별 `ProviderConnectionProbes`와
  static `execution.provider_connection` 입력으로 이전했다. 연결 집합/가용성 fake는 실제 기능 owner로
  옮겼다. 사용이 끝난 12개 private 연결을 제거했으며 관련 테스트는 직접 owner를 사용한다.
- `_agent_command`/`_available_agent` 등 남은 실행 hook은 P3/P4 소비자 이전 때 같은 가용성/command
  port로 정리한다. 현재 facade의 임시 연결을 제품 확장 계약으로 보존하지 않는다.
- P3: `_build_plan`/`_invoke_planning_agent`는 `PlanningAI`, provider 호출은 요청별 `ProviderRuntime`,
  profile·계획 적용·메시지/색인 관련 fixture는 해당 owner로 옮겼다. 새 runtime/phase 객체는
  설정 DTO와 달리 호출 경계를 주입할 수 있는 객체이며 같은 인스턴스를 기획/실행이 공유한다.
- `_invoke_agent`/`_execute` 등 아직 이전하지 않은 fixture는 P4 owner의 AI·기록·phase port로 옮긴다.
  실패/재시도/호출 순서 assertion을 유지하고 facade에는 공개 API 계약 검사를 남긴다.
- port 생성/조회 자체를 재현하는 테스트를 쌓지 않는다. 현재 관련 테스트가 같은 의미를 보장하면 재사용한다.

## 자원·수명 계약

| 자원 | 실제 생성·소유 | P1 이후 접근/재할당 의미 |
|---|---|---|
| Config·repo·agents·GitWorkspace·StateStore | bootstrap이 Pipeline마다 한 번 구성 | 명시적 facade property가 같은 holder를 참조. config 교체로 다른 자원을 자동 재구성하지 않음 |
| SDK | 호출 호스트가 소유, bootstrap은 빌린 참조만 보관 | 생성/close 없음. 기존 `_codex_sdk` 재할당은 같은 참조를 갱신 |
| credential snapshot | bootstrap에서 요청별 한 번 고정 | worker thread/후속 요청의 ContextVar 변경으로 교체하지 않음 |
| AccountUsageCache·RLock | Pipeline별 한 개 | 기존 facade 필드는 동일 객체 alias. 별도 feature lock을 만들지 않음 |
| Planning ContextVar | Pipeline별 한 개 | PlanningPolicyScope와 기존 기획 invocation이 동일 객체 사용. 중첩 request 재사용, finally token 복원 |
| StateStore notification callback | 최초 repo/deploy 설정에 고정 | config/repo 교체로 기존 callback의 project key를 바꾸지 않음 |
| 공통 제어/단계/policy 기록 port | bootstrap에서 제한된 callable로 구성 | 호출 시 현재 store/config/git/agents/SDK 조회. 전체 holder를 feature에 전달하지 않음 |
| StoredStopSignal | 실행 제어 모듈, control loader만 보관 | 생성 당시 store의 bound loader 유지. 다른 store로 교체해도 기존 실행의 중단 신호 유지 |
| 검증 attempt·결과 receipt | RunStepLifecycle | begin/save→실행→오류/중단/stale 또는 성공/save 순서 유지. 호출자가 연 session/lock을 바꾸지 않음 |

## 잠금·phase 진입 경계

기준 AST에서 직접 lock context를 여는 메서드는 아래와 같다. 표는 **직접 취득 위치**이며
내부 기능/StateStore의 잠금까지 전부 열거했다는 뜻은 아니다. P1은 기존 잠금 위치/순서를 변경하지 않았다.
공통 RunStepLifecycle은 verification control 갱신 시 기존 control lock만 취득하고 바깥 run lock을 다시 잡지 않는다.
ExecutionControlService session은 control ownership을 기록하며 장기 run lock을 대체하지 않는다.

| 현재 진입점/phase | 직접 잠금 호출 |
|---|---|
| `_record_execution_chat` | `self.store.planning_chat_lock(run_id)` |
| `submit_external_plan` | `self.store.planning_chat_lock(run_id, 'submit-external-plan')` |
| `propose_result_revision` | `self.store.revision_proposals_lock(run_id)` |
| `create_result_revision_request` | `self.store.revision_requests_lock(run_id)` |
| `run_planning` | `self.store.lock(run_id, 'planning')` |
| `send_planning_message` | `self.store.lock(run_id, 'planning-message')` |
| `request_direction_change` | `self.store.planning_chat_lock(run_id)` |
| `_send_execution_planning_message` | `self.store.planning_chat_lock(run_id)` |
| `preview_planning_apply` | `self.store.planning_chat_lock(run_id, 'planning-preview')` |
| `apply_planning_preview` | `self.store.lock(run_id, 'planning-preview-apply')`; `self.store.planning_chat_lock(run_id)` |
| `request_planning_conversation_apply` | `self.store.lock(run_id, 'planning-apply')`; `self.store.planning_chat_lock(run_id)` |
| `apply_planning_conversation` | `self.store.lock(run_id, 'planning-apply')`; `self.store.planning_chat_lock(run_id)` |
| `confirm_tech_stack` | `self.store.lock(run_id, 'tech-stack-confirm')` |
| `configure_bootstrap_agent_instructions` | `self.store.lock(run_id, 'bootstrap-agent-instructions')` |
| `generate_feature_plan` | `self.store.lock(run_id, 'generate-feature-plan')`; `self.store.planning_chat_lock(run_id)` |
| `_apply_queued_changes_after_batch` | `self.store.planning_chat_lock(state.id)` |
| `recovery_plan` | `self.store.lock(run_id, 'recovery-preview')` |
| `apply_recovery` | `self.store.lock(run_id, 'recovery-apply')`; `self.store.planning_chat_lock(run_id)` |
| `begin_planning_request` | `self.store.request_control_lock(run_id)` |
| `finish_planning_request` | `self.store.request_control_lock(run_id)`; `self.store.planning_chat_lock(run_id)`; `self.store.lock(run_id, 'interrupt-chat')` |
| `interrupt_planning` | `self.store.lock(run_id, 'interrupt-planning')` |
| `update_main` | `self.store.project_git_lock('update-main')` |
| `main_changes` | `self.store.project_git_lock('inspect-main-changes')` |
| `main_change_diff` | `self.store.project_git_lock('inspect-main-change-diff')` |
| `commit_main_changes` | `self.store.project_git_lock('commit-main-changes')` |
| `push_main_commits` | `self.store.project_git_lock('push-main-commits')` |
| `commit_and_push_main_changes` | `self.store.project_git_lock('commit-and-push-main-changes')` |
| `set_effort_mode` | `self.store.lock(run_id, 'set-effort-mode')` |
| `apply_effort_mode_to_plan` | `self.store.lock(run_id, 'apply-effort-mode')`; `self.store.planning_chat_lock(run_id)` |
| `archive_run` | `self.store.project_git_lock('run-archive')`; `self.store.lock(run_id, 'run-archive')`; `self.store.planning_chat_lock(run_id)` |
| `retry_archive_cleanup` | `self.store.project_git_lock('archive-cleanup')`; `self.store.lock(run_id, 'archive-cleanup')` |
| `delete_run` | `self.store.lock(run_id, 'run-delete')` |
| `cleanup_workspace` | `self.store.lock(run_id, 'workspace-clear')` |
| `exclude_tasks` | `self.store.lock(run_id, 'exclude-tasks')` |
| `update_plan` | `self.store.lock(run_id, 'update-plan')` |
| `update_task_execution_profile` | `self.store.lock(run_id, 'update-task-execution-profile')`; `self.store.planning_chat_lock(run_id)` |
| `_queue_task_execution_profile` | `self.store.planning_chat_lock(run_id)` |
| `confirm_plan` | `self.store.lock(run_id, 'confirm-plan')` |
| `execute` | `self.store.lock(run_id, 'execute')` |
| `resume` | `self.store.lock(run_id, 'resume')` |
| `approve_task_scope` | `self.store.request_control_lock(run_id)` |
| `_decide_scope_consent` | `self.store.planning_chat_lock(run_id)`; `self.store.request_control_lock(run_id)` |
| `_prepare_chat_scope_decision` | `self.store.request_control_lock(run_id)` |
| `_apply_chat_scope_approval` | `self.store.lock(run_id, 'retry-task')`; `self.store.planning_chat_lock(run_id)`; `self.store.request_control_lock(run_id)` |
| `_prepare_chat_execution_profile` | `self.store.request_control_lock(run_id)` |
| `_generate_project_chat_decision` | `self.store.planning_chat_lock(run_id)` |
| `perform_project_chat` | `self.store.request_control_lock(run_id)` |
| `_execute_project_chat_action` | `self.store.lock(run_id, lock_operation)` |
| `_perform_chat_execution_profile` | `self.store.lock(run_id, 'update-task-execution-profile')`; `self.store.planning_chat_lock(run_id)` |
| `request_chat_control` | `self.store.request_control_lock(run_id)` |
| `cancel_chat_control` | `self.store.request_control_lock(run_id)` |
| `_repair_task_from_chat` | `self.store.lock(run_id, 'retry-task')`; `self.store.planning_chat_lock(run_id)`; `self.store.revision_requests_lock(run_id)` |
| `retry_task` | `self.store.lock(run_id, 'retry-task')` |
| `execute_task` | `self.store.lock(run_id, 'execute-task')` |
| `_execute` | `self.store.planning_chat_lock(result.id)` |
| `set_manual_task_deferred` | `self.store.lock(run_id, operation)`; `self.store.planning_chat_lock(run_id)` |
| `record_user_check` | `self.store.lock(run_id, 'record-user-check')` |
| `complete_manual_verification` | `self.store.lock(run_id, 'complete-task')`; `self.store.planning_chat_lock(run_id)` |
| `handoff_manual_task_to_ai` | `self.store.lock(run_id, 'execute-task')`; `self.store.planning_chat_lock(run_id)` |
| `complete_task` | `self.store.lock(run_id, 'complete-task')` |
| `merge` | `self.store.project_git_lock('merge')`; `self.store.lock(run_id, 'merge')` |
| `recover_main_apply` | `self.store.project_git_lock('recover-main-apply')`; `self.store.lock(run_id, 'recover-main-apply')` |
| `retry_main_push` | `self.store.project_git_lock('retry-main-push')`; `self.store.lock(run_id, 'retry-main-push')` |
| `register_result_artifact` | `self.store.lock(run_id, 'register_result')` |
| `launch_result_artifact` | `self.store.lock(run_id, 'launch_result')` |
| `verify` | `self.store.lock(run_id, 'verify')`; `self.store.planning_chat_lock(run_id)` |
| `_finish_verification_repair` | `self.store.planning_chat_lock(run_id)` |
| `_verify_and_repair` | `self.store.lock(run_id, 'verify-and-repair')` |
| `prepare_conflict_resolution` | `self.store.lock(run_id, 'conflict-resolution-prepare')` |
| `apply_conflict_resolution` | `self.store.lock(run_id, 'conflict-resolution-apply')` |
| `push` | `self.store.project_git_lock('push')`; `self.store.lock(run_id, 'push')` |
| `deploy` | `self.store.lock(run_id, 'deploy')` |
| `_step` | `self.store.execution_control_lock(state.id)` |
| `record_task_diagnosis` | `self.store.lock(run_id, 'record-task-diagnosis')`; `self.store.planning_chat_lock(run_id)` |
| `save_task_retry_instruction` | `self.store.lock(run_id, 'retry-instruction-save')`; `self.store.revision_requests_lock(run_id)` |

| 내부 phase | 실제 호출자와 진입 조건 |
|---|---|
| `_main_changes_locked` | `update_main`/`main_changes`의 project Git lock 안에서 기존 조회·갱신 preflight 후 호출 |
| `_save_task_execution_profile_locked` | `update_task_execution_profile` 및 `_perform_chat_execution_profile`의 run/chat lock 안에서 호출. 채팅은 기존 대상/revision 재검증 유지 |
| `_execute_task_locked` | `execute_task`의 run lock과 execution session 안에서 호출. stage/plan/profile 검증을 중복 공개 호출로 옮기지 않음 |
| `_verify_locked` | `verify`, 관제의 `_execute_project_chat_action`, `_verification_repair_workflow`가 이미 확보한 run lock/session 안에서 호출. 복구는 `_verify_and_repair`가 바깥 경계를 소유 |

`*_locked` phase의 기존 호출자는 같은 명령 객체 안으로 함께 이전한다. `request_stop`/실행 제어는
기존 별도 control/operation lock을 유지하며 장기 실행의 run lock을 기다리는 공통 decorator로 묶지 않는다.
PlanningPolicyScope는 기록 adapter의 기존 prepare/finish 잠금을 그대로 사용하고 scope 전체에 새 잠금을 추가하지 않는다.

## module-level 호환 이름

| 이름 | 동작/값 owner와 유지 방식 |
|---|---|
| `ApprovalRequired` | `errors.ApprovalRequired`; facade는 동일 클래스를 re-export |
| `_StoredStopSignal` | `execution.lifecycle.StoredStopSignal`; facade 내부 annotation용 alias. 생성은 `make_stored_stop_signal` |
| `RUN_DELETION_TIMEOUT_SECONDS` | P5 `integration.deletion`의 삭제 경계로 이전 후 facade 값 호환 |
| `PROVIDER_AUTH_STATUS_TIMEOUT_SECONDS` | P2 `execution.provider_connection`으로 이전, facade 호환 re-export |
| `TASK_LOG_DISPLAY_LIMIT_BYTES` | P2 `orchestration.queries`로 이전, facade 호환 re-export |
| `TASK_AUTOMATIC_RECOVERY_LIMIT` | P4 task recovery owner로 이전 |
| `EXECUTION_RUN_LOCK_OPERATIONS` | P3 `execution.lifecycle`로 이전, facade 호환 re-export. 기획/실행이 같은 값 사용 |
| `NEW_SELECTION_EXCLUDED_PROVIDER_IDS` | P2 `execution.provider_choices`로 이전, facade 호환 re-export |
| import한 기존 오류·상수·타입 | 소유 모듈의 동일 객체 유지; src/tests의 16개 사용 이름을 계약 검사로 고정 |

순수 함수·상수의 이름과 위치 변경은 해당 소비자를 이전하는 단계에서만 수행한다.
P1에서 무관한 미사용 이름이나 다른 작업의 변경을 정리하지 않는다.
