from __future__ import annotations

from typing import Any

from ..code_style import CodeStyleSnapshot, CodeStyleTaskEvidence
from ..progress import ProgressObservation
from .common import (
    ArchiveCleanupStatus,
    ConflictResolutionStatus,
    DirectionChangeStatus,
    Event,
    ExecutionWorkspaceMode,
    LEGACY_STATE_SCHEMA_VERSION,
    PlanningApplyStatus,
    PlanningMessageRole,
    PlanningMode,
    ProfileSource,
    RepositoryMaturityKind,
    ReviewStatus,
    RiskLevel,
    RunStep,
    Stage,
    TaskAction,
    TaskReadiness,
    TaskStatus,
    TechStackDecisionStatus,
    UserCheckOutcome,
    UserNotificationEvent,
    WorkspaceLocationSource,
    utc_now,
)
from .execution import (
    GroupResultRecord,
    ResultFileChange,
    TaskActionResult,
    TaskResultRecord,
    UserCheck,
    UserCheckResult,
    WorkTask,
)
from .integration import (
    ArchiveCleanupTarget,
    ConflictResolutionCandidate,
    IntegrationConflict,
    IntegrationConflictFile,
    PushReceipt,
    RecoveryTask,
    RunArchive,
    VerificationAttempt,
    WorkspaceLocation,
    conflict_source_key,
)
from .planning import (
    BootstrapAgentInstructions,
    BootstrapPathState,
    BootstrapSpec,
    DirectionChangeRequest,
    PlanningApplyRequest,
    PlanningMessage,
    RepositoryMaturityAssessment,
    RepositoryMaturityEvidence,
    TechStackComponents,
    TechStackDecision,
    TechStackOption,
)


def _effort_baseline(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("effort baseline reasoning must be a string or null")
    return value


def _review_policy_added(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("review policy added must be a boolean")
    return value


def _model_escalation_index(value: object) -> int:
    if type(value) is not int or value < -1:
        raise ValueError("model escalation result index must be an integer >= -1")
    return value


def _integration_conflict_from_dict(raw: dict[str, Any]) -> IntegrationConflict:
    candidate_raw = raw.get("candidate")
    return IntegrationConflict(
        id=str(raw["id"]),
        verification_attempt_id=str(raw.get("verification_attempt_id", "")),
        main_head=str(raw.get("main_head", "")),
        work_head=str(raw.get("work_head", "")),
        merge_base_heads=[str(value) for value in raw.get("merge_base_heads", [])],
        files=[IntegrationConflictFile(**item) for item in raw.get("files", [])],
        fingerprint=str(raw.get("fingerprint", "")),
        detected_at=str(raw.get("detected_at", "")),
        abort_status=str(raw.get("abort_status", "pending")),
        abort_error=str(raw.get("abort_error", "")),
        resolution_status=ConflictResolutionStatus(raw.get("resolution_status", ConflictResolutionStatus.UNRESOLVED.value)),
        candidate=(ConflictResolutionCandidate(**candidate_raw) if isinstance(candidate_raw, dict) else None),
        error=str(raw.get("error", "")),
    )


def _task_action_result_from_dict(raw: dict[str, Any]) -> TaskActionResult:
    values = dict(raw)
    values["code_style_evidence"] = CodeStyleTaskEvidence.from_dict(raw.get("code_style_evidence"))
    return TaskActionResult(**values)


def _result_files_from_dict(raw: dict[str, Any]) -> list[ResultFileChange]:
    return [ResultFileChange(path=str(item["path"]), change=str(item["change"])) for item in raw.get("files", [])]


def _task_result_from_dict(raw: dict[str, Any]) -> TaskResultRecord:
    return TaskResultRecord(
        baseline_commit=str(raw.get("baseline_commit", "")), result_commit=str(raw.get("result_commit", "")),
        captured_at=str(raw.get("captured_at", "")), files_state=str(raw.get("files_state", "unavailable")),
        files=_result_files_from_dict(raw), error=str(raw.get("error", "")), self_report=str(raw.get("self_report", "")),
        verification_status=str(raw.get("verification_status", "unverified")),
        passed_commands=[list(command) for command in raw.get("passed_commands", [])],
        manual_verification_note=str(raw.get("manual_verification_note") or ""),
    )


def _group_result_from_dict(raw: dict[str, Any]) -> GroupResultRecord:
    return GroupResultRecord(
        verification_attempt_id=str(raw.get("verification_attempt_id", "")), main_commit=str(raw.get("main_commit", "")),
        result_commit=str(raw.get("result_commit", "")), captured_at=str(raw.get("captured_at", "")),
        files_state=str(raw.get("files_state", "unavailable")), files=_result_files_from_dict(raw),
        error=str(raw.get("error", "")),
    )


def decode_run_state_fields(raw: dict[str, Any]) -> dict[str, Any]:
    conflict_raw = raw.get("integration_conflict")
    integration_conflict = _integration_conflict_from_dict(conflict_raw) if isinstance(conflict_raw, dict) else None
    recovery_tasks = []
    for item in raw.get("recovery_tasks", []):
        if not isinstance(item, dict) or not isinstance(item.get("conflict"), dict):
            continue
        recovery_tasks.append(
            RecoveryTask(
                id=str(item.get("id", "")),
                kind=str(item.get("kind", "conflict_resolution")),
                source_key=str(item.get("source_key", "")),
                conflict=_integration_conflict_from_dict(item["conflict"]),
                title=str(item.get("title", "최신 Main 통합 충돌 해결")),
                operation_request_ids=[str(value) for value in item.get("operation_request_ids", [])],
                verification_attempt_ids=[str(value) for value in item.get("verification_attempt_ids", [])],
                created_at=str(item.get("created_at", "")),
                superseded_by=str(item.get("superseded_by", "")),
            )
        )
    if integration_conflict is not None:
        matching = next((task for task in recovery_tasks if task.conflict.id == integration_conflict.id), None)
        if matching is None:
            matching = RecoveryTask(
                id=f"recovery-{integration_conflict.fingerprint[:16] or integration_conflict.id.removeprefix('conflict-')}",
                kind="conflict_resolution",
                source_key=conflict_source_key(integration_conflict),
                conflict=integration_conflict,
                verification_attempt_ids=([integration_conflict.verification_attempt_id] if integration_conflict.verification_attempt_id else []),
                created_at=integration_conflict.detected_at,
            )
            recovery_tasks.append(matching)
        integration_conflict = matching.conflict
    return dict(
        id=raw["id"],
        spec_path=raw["spec_path"],
        spec_digest=raw["spec_digest"],
        repo_path=raw["repo_path"],
        main_branch=raw["main_branch"],
        stage=Stage(raw["stage"]),
        schema_version=int(raw.get("schema_version", LEGACY_STATE_SCHEMA_VERSION)),
        workspace_mode=ExecutionWorkspaceMode(raw.get("workspace_mode", ExecutionWorkspaceMode.ISOLATED.value)),
        workspace_location=(
            WorkspaceLocation(
                root=str(raw["workspace_location"]["root"]),
                source=WorkspaceLocationSource(raw["workspace_location"]["source"]),
                layout_version=int(raw["workspace_location"].get("layout_version", 2)),
                notice_code=str(raw["workspace_location"].get("notice_code", "")),
            )
            if isinstance(raw.get("workspace_location"), dict) and raw["workspace_location"].get("root")
            else None
        ),
        execution_branch=raw.get("execution_branch", ""),
        execution_worktree=raw.get("execution_worktree", ""),
        base_commit=raw.get("base_commit", ""),
        verified_task_heads={str(task_id): str(commit) for task_id, commit in raw.get("verified_task_heads", {}).items()},
        verified_main_head=raw.get("verified_main_head", ""),
        verified_integration_head=raw.get("verified_integration_head", ""),
        pushed_work_branch_head=raw.get("pushed_work_branch_head", ""),
        push_receipts=[
            PushReceipt(
                scope=str(item.get("scope", "")),
                remote=str(item.get("remote", "")),
                branch=str(item.get("branch", "")),
                local_commit=str(item.get("local_commit", "")),
                remote_commit=str(item.get("remote_commit", "")),
                operation_request_id=str(item.get("operation_request_id", "")),
                pushed_at=str(item.get("pushed_at", "")),
            )
            for item in raw.get("push_receipts", [])
            if isinstance(item, dict)
        ],
        verification_attempts=[VerificationAttempt(**item) for item in raw.get("verification_attempts", [])],
        group_result_history=[_group_result_from_dict(item) for item in raw.get("group_result_history", [])],
        integration_conflict=integration_conflict,
        recovery_tasks=recovery_tasks,
        archive=_archive_from_dict(raw),
        verification_policy_version=int(raw.get("verification_policy_version", 1)),
        task_verify_command_timeout_seconds=int(raw.get("task_verify_command_timeout_seconds", 0)),
        task_verify_total_timeout_seconds=int(raw.get("task_verify_total_timeout_seconds", 0)),
        integration_verify_command_timeout_seconds=int(raw.get("integration_verify_command_timeout_seconds", 0)),
        integration_verify_total_timeout_seconds=int(raw.get("integration_verify_total_timeout_seconds", 0)),
        verification_repair_limit=int(raw.get("verification_repair_limit", 2)),
        verification_repair_count=int(raw.get("verification_repair_count", 0)),
        verification_repair_head=str(raw.get("verification_repair_head", "")),
        verification_repair_main_head=str(raw.get("verification_repair_main_head", "")),
        verification_repair_task_heads={
            str(key): str(value)
            for key, value in dict(raw.get("verification_repair_task_heads") or {}).items()
        },
        verification_progress_phase=raw.get("verification_progress_phase", ""),
        verification_progress_detail=raw.get("verification_progress_detail", ""),
        verification_progress_current=int(raw.get("verification_progress_current", 0)),
        verification_progress_total=int(raw.get("verification_progress_total", 0)),
        verification_started_at=raw.get("verification_started_at", ""),
        verification_progress_updated_at=raw.get("verification_progress_updated_at", ""),
        active_step=(RunStep(raw["active_step"]) if raw.get("active_step") else None),
        failed_step=(RunStep(raw["failed_step"]) if raw.get("failed_step") else None),
        failure_message=raw.get("failure_message", ""),
        spec_snapshot_path=raw.get("spec_snapshot_path", ""),
        server_work=raw.get("server_work", False),
        summary=raw.get("summary", ""),
        planning_questions=list(raw.get("planning_questions", [])),
        planning_agent_id=raw.get("planning_agent_id", ""),
        planning_provider_id=raw.get("planning_provider_id", ""),
        planning_model=raw.get("planning_model", ""),
        planning_reasoning_effort=raw.get("planning_reasoning_effort", ""),
        planning_profile_source=ProfileSource(raw.get("planning_profile_source", ProfileSource.LEGACY.value)),
        planning_effort_baseline_reasoning=_effort_baseline(raw.get("planning_effort_baseline_reasoning")),
        active_policy_id=raw.get("active_policy_id", ""),
        active_execution_request_id=raw.get("active_execution_request_id", ""),
        planning_claude_session_id=raw.get("planning_claude_session_id", ""),
        planning_mode=PlanningMode(raw.get("planning_mode", PlanningMode.AUTO.value)),
        planning_request=raw.get("planning_request", ""),
        external_plan_digest=str(raw.get("external_plan_digest") or ""),
        user_check_plan=[UserCheck(
            id=item["id"], title=item["title"], instructions=item["instructions"],
            acceptance_criteria=tuple(item["acceptance_criteria"]), after_task_id=item.get("after_task_id", ""),
            blocks_task_ids=tuple(item.get("blocks_task_ids", ())), required_for_integration=item.get("required_for_integration", False),
        ) for item in raw.get("user_check_plan", [])],
        user_check_results={check_id: [UserCheckResult(
            item["reference_commit"], UserCheckOutcome(item["outcome"]), item["note"], item["recorded_at"],
        ) for item in results] for check_id, results in raw.get("user_check_results", {}).items()},
        revision_source_run_id=str(raw.get("revision_source_run_id", "")),
        revision_request_id=str(raw.get("revision_request_id", "")),
        revision_request_text=str(raw.get("revision_request_text", "")),
        revision_source_task_ids=[str(value) for value in raw.get("revision_source_task_ids", [])],
        revision_source_paths=[str(value) for value in raw.get("revision_source_paths", [])],
        planning_attempts=int(raw.get("planning_attempts", 0)),
        structured_plan_path=raw.get("structured_plan_path", ""),
        clarification_paths=list(raw.get("clarification_paths", [])),
        planning_messages=[
            PlanningMessage(role=PlanningMessageRole(item["role"]), text=item["text"], at=item.get("at", ""))
            for item in raw.get("planning_messages", [])
        ],
        planning_follow_up_requests=[str(item) for item in raw.get("planning_follow_up_requests", []) if str(item).strip()],
        planning_conversation_revision=int(raw.get("planning_conversation_revision", len(raw.get("planning_messages", [])))),
        planning_applied_conversation_revision=int(raw.get("planning_applied_conversation_revision", 0)),
        planning_apply_requests=_planning_apply_requests_from_dict(raw),
        direction_change_requests=_direction_change_requests_from_dict(raw),
        repository_maturity=_repository_maturity_from_dict(raw),
        code_style_snapshot=CodeStyleSnapshot.from_dict(raw.get("code_style_snapshot")),
        repository_intent=str(raw.get("repository_intent", "")),
        greenfield_phase=str(raw.get("greenfield_phase", "")),
        tech_stack_decisions=_tech_stack_decisions_from_dict(raw),
        bootstrap_spec=_bootstrap_spec_from_dict(raw),
        plan_revision=int(raw.get("plan_revision", 0)),
        plan_approved_revision=int(raw.get("plan_approved_revision", 0)),
        tasks=[
            _work_task_from_dict(item)
            for item in raw.get("tasks", [])
        ],
        events=[Event(**item) for item in raw.get("events", [])],
        notification_events=[UserNotificationEvent(**item) for item in raw.get("notification_events", [])],
        created_at=raw.get("created_at", utc_now()),
        updated_at=raw.get("updated_at", utc_now()),
    )


def decode_run_summary_fields(raw: dict[str, Any]) -> dict[str, Any]:
    tasks = raw.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("run tasks must be an array")
    completed_values = {TaskStatus.COMPLETED.value, TaskStatus.MERGED.value}
    return dict(
        id=str(raw["id"]),
        summary=str(raw.get("summary", "")),
        stage=Stage(raw["stage"]),
        updated_at=str(raw.get("updated_at", "")),
        created_at=str(raw.get("created_at", "")),
        task_count=len(tasks),
        completed_task_count=sum(isinstance(task, dict) and task.get("status") in completed_values for task in tasks),
        archived=isinstance(raw.get("archive"), dict),
        archived_at=str(raw.get("archive", {}).get("archived_at", "")) if isinstance(raw.get("archive"), dict) else "",
        cleanup_status=str(raw.get("archive", {}).get("cleanup_status", "")) if isinstance(raw.get("archive"), dict) else "",
        failed_task_count=sum(isinstance(task, dict) and task.get("status") == TaskStatus.FAILED.value for task in tasks),
        waiting_task_count=sum(isinstance(task, dict) and task.get("status") == TaskStatus.WAITING.value for task in tasks),
        plan_is_approved=(
            int(raw.get("plan_revision", 0)) == 0
            or int(raw.get("plan_approved_revision", 0)) == int(raw.get("plan_revision", 0))
        ),
    )


def _archive_from_dict(raw: dict[str, Any]) -> RunArchive | None:
    return (
        RunArchive(
            archived_at=str(raw["archive"].get("archived_at", "")),
            source_revision=str(raw["archive"].get("source_revision", "")),
            snapshot_path=str(raw["archive"].get("snapshot_path", "")),
            manifest_path=str(raw["archive"].get("manifest_path", "")),
            summary_path=str(raw["archive"].get("summary_path", "")),
            fingerprint=str(raw["archive"].get("fingerprint", "")),
            cleanup_status=ArchiveCleanupStatus(
                raw["archive"].get("cleanup_status", ArchiveCleanupStatus.PENDING.value)
            ),
            cleanup_request_id=str(raw["archive"].get("cleanup_request_id", "")),
            cleanup_targets=[
                ArchiveCleanupTarget(
                    id=str(item.get("id", "")),
                    recorded_path=str(item.get("recorded_path", "")),
                    expected_head=str(item.get("expected_head", "")),
                    status=str(item.get("status", "pending")),
                    error=str(item.get("error", "")),
                    archive_ref=str(item.get("archive_ref", "")),
                )
                for item in raw["archive"].get("cleanup_targets", [])
                if isinstance(item, dict)
            ],
        )
        if isinstance(raw.get("archive"), dict)
        else None
    )


def _planning_apply_requests_from_dict(raw: dict[str, Any]) -> list[PlanningApplyRequest]:
    return [
        PlanningApplyRequest(
            request_id=str(item["request_id"]),
            conversation_revision=int(item.get("conversation_revision", 0)),
            plan_revision=int(item.get("plan_revision", 0)),
            context_snapshot=str(item.get("context_snapshot", "")),
            answer_message=str(item.get("answer_message", "")),
            answer_conversation_revision=int(item.get("answer_conversation_revision", 0)),
            tech_stack_revision=int(item.get("tech_stack_revision", 0)),
            status=PlanningApplyStatus(item.get("status", PlanningApplyStatus.QUEUED.value)),
            created_at=str(item.get("created_at", "")),
            completed_at=str(item.get("completed_at", "")),
            added_tasks=int(item.get("added_tasks", 0)),
            updated_tasks=int(item.get("updated_tasks", 0)),
            excluded_tasks=int(item.get("excluded_tasks", 0)),
            unchanged_tasks=int(item.get("unchanged_tasks", 0)),
            error_code=str(item.get("error_code", "")),
            error=str(item.get("error", "")),
        )
        for item in raw.get("planning_apply_requests", [])
        if isinstance(item, dict) and str(item.get("request_id", "")).strip()
    ]


def _direction_change_requests_from_dict(raw: dict[str, Any]) -> list[DirectionChangeRequest]:
    return [
        DirectionChangeRequest(
            request_id=str(item["request_id"]), text=str(item["text"]),
            task_id=str(item.get("task_id", "")), task_title=str(item.get("task_title", "")),
            status=DirectionChangeStatus(item.get("status", DirectionChangeStatus.RECEIVED.value)),
            next_step=str(item.get("next_step", "")), preview_id=str(item.get("preview_id", "")),
            error=str(item.get("error", "")), created_at=str(item.get("created_at", "")),
            updated_at=str(item.get("updated_at", "")),
        )
        for item in raw.get("direction_change_requests", [])
        if isinstance(item, dict) and str(item.get("request_id", "")).strip()
    ]


def _repository_maturity_from_dict(raw: dict[str, Any]) -> RepositoryMaturityAssessment | None:
    return (
        RepositoryMaturityAssessment(
            kind=RepositoryMaturityKind(raw["repository_maturity"].get("kind", RepositoryMaturityKind.AMBIGUOUS.value)),
            evidence=[
                RepositoryMaturityEvidence(
                    relative_path=str(item.get("relative_path", "")),
                    evidence_kind=str(item.get("evidence_kind", "unknown")),
                    stack_hints=[str(value) for value in item.get("stack_hints", [])],
                )
                for item in raw["repository_maturity"].get("evidence", [])
                if isinstance(item, dict)
            ],
            ignored_roots=[str(value) for value in raw["repository_maturity"].get("ignored_roots", [])],
            detected_application_roots=[
                str(value) for value in raw["repository_maturity"].get("detected_application_roots", [])
            ],
            diagnostics=[str(value) for value in raw["repository_maturity"].get("diagnostics", [])],
            inspected_file_count=int(raw["repository_maturity"].get("inspected_file_count", 0)),
            truncated=bool(raw["repository_maturity"].get("truncated", False)),
        )
        if isinstance(raw.get("repository_maturity"), dict)
        else None
    )


def _tech_stack_decisions_from_dict(raw: dict[str, Any]) -> list[TechStackDecision]:
    return [
        TechStackDecision(
            decision_id=str(item.get("decision_id", "")),
            revision=int(item.get("revision", 0)),
            status=TechStackDecisionStatus(item.get("status", TechStackDecisionStatus.QUESTIONS_REQUIRED.value)),
            project_root=str(item.get("project_root", "")),
            requirement_sources=[str(value) for value in item.get("requirement_sources", [])],
            answers=[str(value) for value in item.get("answers", [])],
            options=[
                TechStackOption(
                    option_id=str(option.get("option_id", "")),
                    label=str(option.get("label", "")),
                    recommendation_rank=int(option.get("recommendation_rank", 0)),
                    components=TechStackComponents(
                        languages=[str(value) for value in option.get("components", {}).get("languages", [])],
                        runtimes=[str(value) for value in option.get("components", {}).get("runtimes", [])],
                        application_frameworks=[
                            str(value) for value in option.get("components", {}).get("application_frameworks", [])
                        ],
                        ui_frameworks=[str(value) for value in option.get("components", {}).get("ui_frameworks", [])],
                        persistence=[str(value) for value in option.get("components", {}).get("persistence", [])],
                        package_and_build_tools=[
                            str(value) for value in option.get("components", {}).get("package_and_build_tools", [])
                        ],
                        test_tools=[str(value) for value in option.get("components", {}).get("test_tools", [])],
                        style_and_analysis=[str(value) for value in option.get("components", {}).get("style_and_analysis", [])],
                        packaging_and_deployment=[
                            str(value) for value in option.get("components", {}).get("packaging_and_deployment", [])
                        ],
                    ),
                    version_policy=[str(value) for value in option.get("version_policy", [])],
                    requirement_fit=[str(value) for value in option.get("requirement_fit", [])],
                    tradeoffs=[str(value) for value in option.get("tradeoffs", [])],
                    unresolved_constraints=[str(value) for value in option.get("unresolved_constraints", [])],
                    required_external_dependencies=[
                        str(value) for value in option.get("required_external_dependencies", [])
                    ],
                )
                for option in item.get("options", [])
                if isinstance(option, dict) and isinstance(option.get("components"), dict)
            ],
            selected_option_id=str(item.get("selected_option_id", "")),
            confirmed_at=str(item.get("confirmed_at", "")),
            confirmed_by=str(item.get("confirmed_by", "")),
            created_at=str(item.get("created_at", "")),
        )
        for item in raw.get("tech_stack_decisions", [])
        if isinstance(item, dict)
    ]


def _bootstrap_spec_from_dict(raw: dict[str, Any]) -> BootstrapSpec | None:
    return (
        BootstrapSpec(
            decision_id=str(raw["bootstrap_spec"].get("decision_id", "")),
            decision_revision=int(raw["bootstrap_spec"].get("decision_revision", 0)),
            target_root=str(raw["bootstrap_spec"].get("target_root", "")),
            planned_paths=[str(value) for value in raw["bootstrap_spec"].get("planned_paths", [])],
            steps=[str(value) for value in raw["bootstrap_spec"].get("steps", [])],
            required_tools=[str(value) for value in raw["bootstrap_spec"].get("required_tools", [])],
            verify_commands=[list(command) for command in raw["bootstrap_spec"].get("verify_commands", [])],
            excluded_external_actions=[
                str(value) for value in raw["bootstrap_spec"].get("excluded_external_actions", [])
            ],
            path_snapshot=[
                BootstrapPathState(
                    relative_path=str(item.get("relative_path", "")),
                    entry_kind=str(item.get("entry_kind", "")),
                    content_digest=str(item.get("content_digest", "")),
                )
                for item in raw["bootstrap_spec"].get("path_snapshot", [])
                if isinstance(item, dict)
            ],
            digest=str(raw["bootstrap_spec"].get("digest", "")),
            agent_instructions=(
                BootstrapAgentInstructions(
                    mode=str(raw["bootstrap_spec"]["agent_instructions"].get("mode", "preserve_existing")),
                    path=str(raw["bootstrap_spec"]["agent_instructions"].get("path", "AGENTS.md")),
                    template_version=str(raw["bootstrap_spec"]["agent_instructions"].get("template_version", "1")),
                    rendered_content=str(raw["bootstrap_spec"]["agent_instructions"].get("rendered_content", "")),
                    content_digest=str(raw["bootstrap_spec"]["agent_instructions"].get("content_digest", "")),
                    task_path_injected=bool(raw["bootstrap_spec"]["agent_instructions"].get("task_path_injected", False)),
                    task_acceptance_injected=bool(
                        raw["bootstrap_spec"]["agent_instructions"].get("task_acceptance_injected", False)
                    ),
                )
                if isinstance(raw["bootstrap_spec"].get("agent_instructions"), dict)
                else None
            ),
            verified_integration_head=str(raw["bootstrap_spec"].get("verified_integration_head", "")),
            verified_at=str(raw["bootstrap_spec"].get("verified_at", "")),
            feature_plan_attempts=int(raw["bootstrap_spec"].get("feature_plan_attempts", 0)),
            feature_plan_error=str(raw["bootstrap_spec"].get("feature_plan_error", "")),
            created_at=str(raw["bootstrap_spec"].get("created_at", "")),
        )
        if isinstance(raw.get("bootstrap_spec"), dict)
        else None
    )


def _work_task_from_dict(raw: dict[str, Any]) -> WorkTask:
    return WorkTask(
        id=raw["id"],
        title=raw["title"],
        capabilities=list(raw.get("capabilities", [])),
        description=raw.get("description", ""),
        implementation_notes=list(raw.get("implementation_notes", [])),
        acceptance_criteria=list(raw.get("acceptance_criteria", [])),
        dependencies=list(raw.get("dependencies", [])),
        is_prerequisite=raw.get("is_prerequisite", False),
        conflict_dependencies=list(raw.get("conflict_dependencies", [])),
        conflict_group=list(raw.get("conflict_group", [])),
        action_results=[_task_action_result_from_dict(result) for result in raw.get("action_results", [])],
        result_history=[_task_result_from_dict(result) for result in raw.get("result_history", [])],
        expected_paths=list(raw.get("expected_paths", [])),
        forbidden_paths=list(raw.get("forbidden_paths", [])),
        verify_commands=[list(command) for command in raw.get("verify_commands", [])],
        risk_level=RiskLevel(raw.get("risk_level", RiskLevel.MEDIUM)),
        readiness=TaskReadiness(raw.get("readiness", TaskReadiness.READY)),
        blocked_by=list(raw.get("blocked_by", [])),
        agent_id=raw.get("agent_id", ""),
        provider_id=raw.get("provider_id", ""),
        model=raw.get("model", ""),
        reasoning_effort=raw.get("reasoning_effort", ""),
        profile_source=ProfileSource(raw.get("profile_source", ProfileSource.LEGACY.value)),
        effort_baseline_reasoning=_effort_baseline(raw.get("effort_baseline_reasoning")),
        effective_model=raw.get("effective_model", ""),
        effective_reasoning_effort=raw.get("effective_reasoning_effort", ""),
        reviewer_agent_id=raw.get("reviewer_agent_id", ""),
        reviewer_provider_id=raw.get("reviewer_provider_id", ""),
        reviewer_model=raw.get("reviewer_model", ""),
        review_policy_added=_review_policy_added(raw.get("review_policy_added", False)),
        routing_reason=raw.get("routing_reason", ""),
        routing_confidence=float(raw.get("routing_confidence", 0.0)),
        model_selection_reason=raw.get("model_selection_reason", ""),
        model_escalation_policy_id=raw.get("model_escalation_policy_id", ""),
        model_escalation_result_index=_model_escalation_index(raw.get("model_escalation_result_index", -1)),
        status=TaskStatus(raw.get("status", TaskStatus.PENDING)),
        review_status=ReviewStatus(raw.get("review_status", ReviewStatus.NOT_REQUIRED)),
        review_cycles=int(raw.get("review_cycles", 0)),
        review_summary=raw.get("review_summary", ""),
        review_findings=list(raw.get("review_findings", [])),
        last_review_commit=raw.get("last_review_commit", ""),
        branch=raw.get("branch", ""),
        worktree=raw.get("worktree", ""),
        started_commit=raw.get("started_commit", ""),
        completed_commit=raw.get("completed_commit", ""),
        prompt_path=raw.get("prompt_path", ""),
        log_path=raw.get("log_path", ""),
        error=raw.get("error", ""),
        active_action=(TaskAction(raw["active_action"]) if raw.get("active_action") else None),
        failed_action=(TaskAction(raw["failed_action"]) if raw.get("failed_action") else None),
        attempt_count=int(raw.get("attempt_count", 0)),
        last_attempt_id=raw.get("last_attempt_id", ""),
        last_attempt_started_at=raw.get("last_attempt_started_at", ""),
        last_attempt_finished_at=raw.get("last_attempt_finished_at", ""),
        active_invocation_id=raw.get("active_invocation_id", ""),
        stop_request_id=raw.get("stop_request_id", ""),
        stopped_at=raw.get("stopped_at", ""),
        progress_phase=raw.get("progress_phase", ""),
        progress_detail=raw.get("progress_detail", ""),
        progress_updated_at=raw.get("progress_updated_at", ""),
        progress_observation=(ProgressObservation(**raw["progress_observation"]) if isinstance(raw.get("progress_observation"), dict) else None),
    )
