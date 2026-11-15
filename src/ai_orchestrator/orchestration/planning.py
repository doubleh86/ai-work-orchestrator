"""Planning entry points own validation, locks and request ordering."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import replace, dataclass
from pathlib import Path
from typing import Callable, ContextManager, Sequence, Protocol
from .planning_routing import PlanningMessageRouter
from ..codex_sdk import CodexSdkError
from ..config import AgentConfig
from ..document_index import PlanningSourceIndex
from ..errors import PipelineError
from ..git import GitError
from ..models import (
    RunLockStatus,
    BootstrapSpec,
    EffortMode,
    PlanningMode,
    ProfileSource,
    RunState,
    RunStep,
    Stage,
    TaskStatus,
    TechStackDecisionStatus,
    UserCheck,
    WorkspaceLocation,
    utc_now,
)
from ..persistence.run_lookup import RunLookup
from ..planner import PlanningError, read_planning_document, validate_task_graph
from ..planning import PlanDraftValidator, PlanningPreviewWorkflow, ResultRevisionWorkflow
from ..planning.ai import PlanningAI
from ..planning.apply_requests import PlanningApplyInput, PlanningApplyWorkflow, normalize_planning_apply_request_id
from ..planning.bootstrap import BootstrapPlanner
from ..planning.conversation import task_plan_draft
from ..planning.direction_changes import DirectionChangeIntake
from ..planning.initialization import PlanningRepositoryContext, external_plan_input
from ..planning.intake import PlanningIntake
from ..planning.lifecycle import PlanningLifecycle
from ..planning.messages import PlanningMessages
from ..planning.plan_files import PlanFiles
from ..planning.plan_review import PlanConfirmation, TaskPlanExclusion, protected_greenfield_bootstrap
from ..planning.preview_apply import PlanningPreviewApplication
from ..planning.profiles import PlanningProfiles
from ..planning.source_indexes import PlanningSourceIndexes
from ..repository_maturity import inspect_repository_maturity
from ..run_queries import user_checks


class PlanningInitializeEffort(Protocol):
    def __call__(self, state: RunState, mode: str, *, recover_unpublished: bool = False) -> object: ...


class PlanningChatLock(Protocol):
    def __call__(self, run_id: str, operation: str = "planning-chat") -> ContextManager[object]: ...


@dataclass(frozen=True, slots=True)
class PlanningCommandRecords:
    load: Callable[[str], RunState]
    save: Callable[[RunState], None]
    save_chat: Callable[[RunState], None]
    state_path: Callable[[str], Path]
    run_dir: Callable[[str], Path]
    run_lock: Callable[[str, str], ContextManager[object]]
    chat_lock: PlanningChatLock
    revision_proposals_lock: Callable[[str], ContextManager[object]]
    revision_requests_lock: Callable[[str], ContextManager[object]]
    inspect_chat_lock: Callable[[str], RunLockStatus]
    save_preview_progress: Callable[[str, dict[str, object]], None]
    initialize_effort: PlanningInitializeEffort


@dataclass
class PlanningCommands:
    records: PlanningCommandRecords
    intake: PlanningIntake
    ai: PlanningAI
    lifecycle: PlanningLifecycle
    messages: PlanningMessages
    profiles: PlanningProfiles
    lookup: RunLookup
    files: PlanFiles
    repository: Callable[[], Path]
    main_branch: Callable[[], str]
    workspace_location: Callable[[], WorkspaceLocation]
    read_head: Callable[[], str]
    ensure_git_ready: Callable[[], None]
    ensure_verification: Callable[[RunState], None]
    execution_capabilities: Callable[[], list[str]]
    configured_agents: Callable[[], tuple[AgentConfig, ...]]
    tool_connections: Callable[[], list[dict[str, object]]]
    repository_context: Callable[[], PlanningRepositoryContext]
    source_indexes: Callable[[], PlanningSourceIndexes]
    result_revisions: Callable[[], ResultRevisionWorkflow]
    previews: Callable[[], PlanningPreviewWorkflow]
    preview_application: Callable[[], PlanningPreviewApplication]
    apply_workflow: Callable[[], PlanningApplyWorkflow]
    message_router: Callable[[], PlanningMessageRouter]
    draft_validator: Callable[[], PlanDraftValidator]
    confirmation: Callable[[], PlanConfirmation]
    exclusion: Callable[[], TaskPlanExclusion]
    bootstrap: Callable[[], BootstrapPlanner]

    def external_planning_context(self) -> dict[str, object]:
        self.ensure_git_ready()
        assessment = inspect_repository_maturity(self.repository())
        return {
            "base_commit": self.read_head(),
            "main_branch": self.main_branch(),
            "repository_maturity": assessment.kind.value,
            "execution_capabilities": self.execution_capabilities(),
            "tool_connections": self.tool_connections(),
        }

    def submit_external_plan(
        self, run_id: str, *, expected_base_commit: str, summary: str, requirements: str,
        task_drafts: list[dict[str, object]], server_work: bool = False, user_checks: tuple[UserCheck, ...] = (),
    ) -> RunState:
        """Validate and persist a plan supplied by a client without running Planning AI."""
        summary, requirements, submission_digest = external_plan_input(
            run_id, expected_base_commit=expected_base_commit, summary=summary, requirements=requirements,
            task_drafts=task_drafts, server_work=server_work, user_checks=user_checks,
        )
        with self.records.chat_lock(run_id, "submit-external-plan"):
            if self.records.state_path(run_id).is_file():
                saved = self.records.load(run_id)
                if saved.external_plan_digest != submission_digest:
                    raise PipelineError("같은 외부 기획 ID에 다른 계획을 저장할 수 없습니다.")
                return saved
            self.ensure_git_ready()
            self.check_base(expected_base_commit)
            state = self.repository_context().external(
                run_id, expected_base_commit=expected_base_commit, summary=summary, requirements=requirements,
                submission_digest=submission_digest, server_work=server_work, user_checks=user_checks,
                main_branch=self.main_branch, workspace_location=self.workspace_location,
            )
            plan = self.draft_validator().validate(
                state, task_drafts, initial_effort_mode=EffortMode.BALANCED,
                execution_agents=tuple(agent for agent in self.configured_agents() if not agent.manual_only),
            )
            self.check_base(expected_base_commit)
            self.ensure_verification(state)
            state.begin_step(RunStep.PLANNING)
            state.transition(Stage.REVIEWED, "external plan contract validated")
            state.tasks = plan.tasks
            state.refresh_task_readiness()
            state.revise_plan()
            snapshot = self.records.run_dir(run_id) / "planning-document.md"
            snapshot.write_text(requirements, encoding="utf-8")
            state.spec_snapshot_path = str(snapshot)
            self.files.write_result(state, plan)
            state.complete_step(RunStep.PLANNING)
            state.transition(Stage.PLANNED, "external plan submitted for user review")
            self.records.initialize_effort(state, EffortMode.BALANCED.value, recover_unpublished=True)
            return state

    def start(
        self,
        spec_path: str | Path,
        *,
        planning_agent_id: str = "",
        planning_model: str = "",
        planning_reasoning_effort: str = "",
        planning_mode: PlanningMode | str = PlanningMode.AUTO,
        planning_request: str = "",
        effort_mode: EffortMode | str = EffortMode.BALANCED,
        planning_profile_source: ProfileSource | str | None = None,
    ) -> RunState:
        state = self.prepare_planning(
            spec_path,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
            planning_mode=planning_mode,
            planning_request=planning_request,
            effort_mode=effort_mode,
            planning_profile_source=planning_profile_source,
        )
        return self.run_planning(state.id)

    def prepare_planning(
        self,
        spec_path: str | Path,
        *,
        planning_agent_id: str = "",
        planning_model: str = "",
        planning_reasoning_effort: str = "",
        planning_mode: PlanningMode | str = PlanningMode.AUTO,
        planning_request: str = "",
        prepared_source_index: PlanningSourceIndex | None = None,
        repository_intent: str | None = None,
        revision_source_run_id: str = "",
        revision_request_id: str = "",
        revision_request_text: str = "",
        revision_source_task_ids: Sequence[str] = (),
        revision_source_paths: Sequence[str] = (),
        effort_mode: EffortMode | str = EffortMode.BALANCED,
        planning_profile_source: ProfileSource | str | None = None,
        reserved_run_id: str = "",
    ) -> RunState:
        return self.intake.prepare(
            spec_path,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
            planning_mode=planning_mode,
            planning_request=planning_request,
            prepared_source_index=prepared_source_index,
            repository_intent=repository_intent,
            revision_source_run_id=revision_source_run_id,
            revision_request_id=revision_request_id,
            revision_request_text=revision_request_text,
            revision_source_task_ids=revision_source_task_ids,
            revision_source_paths=revision_source_paths,
            effort_mode=effort_mode,
            planning_profile_source=planning_profile_source,
            reserved_run_id=reserved_run_id,
        )

    def result_revision_requests(self, run_id: str) -> dict[str, object]:
        return self.result_revisions().requests(run_id)

    def propose_result_revision(self, run_id: str, *, proposal_id: str, text: str, focus_task_id: str = "") -> dict[str, object]:
        try:
            normalized_id = str(uuid.UUID(proposal_id))
        except (ValueError, AttributeError) as exc:
            raise PipelineError("AI 수정 제안 ID가 올바르지 않습니다.") from exc
        instruction = text.strip()
        if len(instruction) > 8000:
            raise PipelineError("수정할 내용은 8000자 이하로 입력해 주세요.")
        with self.records.revision_proposals_lock(run_id):
            return self.result_revisions().propose(run_id, normalized_id, instruction, focus_task_id)

    def create_result_revision_request(
        self, run_id: str, *, request_id: str, text: str, task_ids: Sequence[str], paths: Sequence[str], proposal_id: str = ""
    ) -> dict[str, object]:
        try:
            normalized_request_id = str(uuid.UUID(request_id))
        except (ValueError, AttributeError) as exc:
            raise PipelineError("수정 요청 ID가 올바르지 않습니다.") from exc
        normalized_text = text.strip()
        if (not normalized_text and not proposal_id) or len(normalized_text) > 8000:
            raise PipelineError("수정 요청을 1~8000자로 입력해 주세요.")
        selected_task_ids = list(dict.fromkeys(task_ids))
        selected_paths = list(dict.fromkeys(paths))
        with self.records.revision_requests_lock(run_id):
            return self.result_revisions().create(
                        run_id, normalized_request_id, normalized_text, selected_task_ids, selected_paths, proposal_id,
                    )

    def run_planning(self, run_id: str) -> RunState:
        with self.records.run_lock(run_id, "planning"):
            state = self.records.load(run_id)
            if state.stage != Stage.REVIEWED or state.active_step != RunStep.PLANNING:
                raise PipelineError(f"run {run_id} is not prepared for Planning")
            try:
                document = Path(state.spec_snapshot_path).read_text(encoding="utf-8")
                source_index = self.source_indexes().snapshot(state)
                plan = self.ai.build_plan(state, document, source_index=source_index)
                return self.lifecycle.apply_plan(state, plan)
            except (PlanningError, OSError) as exc:
                state.fail_step(RunStep.PLANNING, f"planning failed: {exc}")
                self.records.save(state)
                raise

    def clarify(self, run_id: str, answers_path: str | Path) -> RunState:
        answers = read_planning_document(answers_path)
        return self.clarify_text(run_id, answers)

    def clarify_text(
        self,
        run_id: str,
        answers: str,
        *,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        answers = answers.strip()
        if not answers:
            raise PipelineError("clarification answer must not be empty")
        return self.apply_planning_conversation(
            run_id,
            message=answers,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )

    def send_planning_message(
        self,
        run_id: str,
        message: str,
        *,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        message = message.strip()
        if not message:
            raise PipelineError("planning message must not be empty")
        routed = self.message_router().route(
            run_id, message, planning_agent_id=planning_agent_id, planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )
        if routed is not None:
            return routed
        with self.records.run_lock(run_id, "planning-message"):
            state = self.records.load(run_id)
            if state.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED}:
                raise PipelineError(
                    f"run {run_id} is at '{state.stage.value}', expected '{Stage.NEEDS_CLARIFICATION.value}' or '{Stage.PLANNED.value}'"
                )
            active_agent = self.profiles.configure(
                state, planning_agent_id=planning_agent_id, planning_model=planning_model, planning_reasoning_effort=planning_reasoning_effort
            )
            self.messages.append_user(state, message)
            state.begin_step(RunStep.PLANNING)
            state.add_event("planning", "planning chat message received")
            self.records.save(state)
            try:
                response = self.ai.chat_turn(state, active_agent, message)
            except (PipelineError, PlanningError, OSError) as exc:
                state.complete_step(RunStep.PLANNING)
                state.add_event("planning", f"planning chat response failed: {exc}")
                self.records.save(state)
                raise
            self.messages.append_assistant(state, response)
            state.complete_step(RunStep.PLANNING)
            state.add_event("planning", "planning chat response received")
            self.records.save(state)
            return state

    def request_direction_change(self, run_id: str, *, request_id: str, text: str) -> RunState:
        normalized_id = normalize_planning_apply_request_id(request_id)
        instruction = text.strip()
        if not instruction or len(instruction) > 4000:
            raise PipelineError("방향 수정 내용은 1~4000자로 입력해 주세요.")
        with self.records.chat_lock(run_id):
            state = self.records.load(run_id)
            return DirectionChangeIntake(self.messages.append_user, self.records.save_chat).accept(
                state, normalized_id, instruction,
            )

    def planning_apply_preview(self, run_id: str) -> dict[str, object] | None:
        return self.previews().read(run_id)

    def planning_preview_status(self, run_id: str) -> dict[str, object]:
        return self.previews().status(run_id)

    def preview_planning_apply(self, run_id: str, *, request_id: str) -> dict[str, object]:
        request_id = normalize_planning_apply_request_id(request_id)
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", request_id):
            raise PipelineError("Planning 미리보기 요청 ID가 올바르지 않습니다.")
        with self.records.chat_lock(run_id, "planning-preview"):
            state = self.records.load(run_id)
            lock = self.records.inspect_chat_lock(run_id)
            progress: dict[str, object] = {
                "request_id": request_id, "owner_pid": os.getpid(), "started_at": lock.acquired_at,
                "fingerprint": self.previews().fingerprint(state), "phase": "generating", "updated_at": utc_now(), "error": "",
                "phase_started_at": lock.acquired_at, "last_activity_at": "",
            }
            self.records.save_preview_progress(run_id, progress)
            try:
                preview = self.previews().create(run_id, request_id=request_id)
            except (PipelineError, PlanningError, OSError, ValueError, GitError, CodexSdkError) as exc:
                progress.update(phase="failed", updated_at=utc_now(), error=str(exc))
                self.records.save_preview_progress(run_id, progress)
                raise
            progress.update(phase="ready", updated_at=utc_now())
            self.records.save_preview_progress(run_id, progress)
            return preview

    def apply_planning_preview(self, run_id: str, *, preview_id: str, fingerprint: str, candidate_digest: str) -> dict[str, object]:
        with self.records.run_lock(run_id, "planning-preview-apply"), self.records.chat_lock(run_id):
            return self.preview_application().apply_locked(run_id, preview_id=preview_id, fingerprint=fingerprint, candidate_digest=candidate_digest)

    def request_planning_conversation_apply(
        self,
        run_id: str,
        *,
        request_id: str,
        expected_revision: int,
        conversation_revision: int,
        control_message: str = "",
        answer_message: str = "",
        expected_tech_stack_revision: int | None = None,
        retry_failed: bool = False,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        workflow = self.apply_workflow()
        request = PlanningApplyInput(
            request_id=request_id, expected_revision=expected_revision, conversation_revision=conversation_revision,
            control_message=control_message, answer_message=answer_message, expected_tech_stack_revision=expected_tech_stack_revision,
            retry_failed=retry_failed, planning_agent_id=planning_agent_id, planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )
        prepared = workflow.prepare(run_id, request)
        if prepared.replayed:
            return prepared.state
        if prepared.execution_active:
            with self.records.chat_lock(run_id):
                return workflow.queue(run_id, prepared.request)
        with self.records.run_lock(run_id, "planning-apply"), self.records.chat_lock(run_id):
            return workflow.apply(run_id, prepared.request)

    def apply_planning_conversation(
        self,
        run_id: str,
        *,
        message: str = "",
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        message = message.strip()
        current = self.records.load(run_id)
        if current.stage in {Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE} and current.tasks:
            with self.records.run_lock(run_id, "planning-apply"), self.records.chat_lock(run_id):
                state = self.records.load(run_id)
                self.profiles.configure(
                    state,
                    planning_agent_id=planning_agent_id,
                    planning_model=planning_model,
                    planning_reasoning_effort=planning_reasoning_effort,
                )
                if message:
                    self.messages.append_user(state, message)
                follow_up = self.messages.follow_up(state)
                if follow_up not in state.planning_follow_up_requests:
                    state.planning_follow_up_requests.append(follow_up)
                self.records.save_chat(state)
                return self.lifecycle.apply_pending(state)
        with self.records.run_lock(run_id, "planning-apply"):
            state = self.records.load(run_id)
            if state.stage == Stage.FAILED:
                if state.failed_step != RunStep.PLANNING:
                    raise PipelineError(f"run {run_id} did not fail during planning")
            elif state.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED}:
                raise PipelineError(
                    f"run {run_id} is at '{state.stage.value}', expected '{Stage.NEEDS_CLARIFICATION.value}' or '{Stage.PLANNED.value}'"
                )
            self.profiles.configure(
                state, planning_agent_id=planning_agent_id, planning_model=planning_model, planning_reasoning_effort=planning_reasoning_effort
            )
            if message:
                self.messages.append_user(state, message)
            return self.lifecycle.apply_conversation(state, event_message="planning apply requested")

    def confirm_tech_stack(self, run_id: str, *, option_id: str, expected_revision: int) -> RunState:
        option_id = option_id.strip()
        if not option_id:
            raise PipelineError("technology stack option id must not be empty")
        with self.records.run_lock(run_id, "tech-stack-confirm"):
            state = self.records.load(run_id)
            if state.repository_intent != "new_project":
                raise PipelineError("technology stack decisions are only available for new project Planning")
            if state.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED}:
                raise PipelineError(f"run {run_id} is at '{state.stage.value}', expected Planning review")
            decision = state.current_tech_stack_decision()
            if decision is None:
                raise PipelineError("technology stack options are not ready")
            if decision.revision != expected_revision:
                raise PipelineError(
                    f"기술 구성 후보가 변경되었습니다. 현재 revision {decision.revision}을 확인한 뒤 다시 선택해 주세요."
                )
            selected = next((option for option in decision.options if option.option_id == option_id), None)
            if selected is None:
                raise PipelineError(f"unknown technology stack option: {option_id}")
            if decision.status == TechStackDecisionStatus.CONFIRMED:
                if decision.selected_option_id == option_id:
                    return state
                raise PipelineError("확정된 기술 구성을 바꾸려면 Planning 대화에서 새 후보를 만들어 주세요.")
            if not state.tech_stack_confirmation_allowed():
                raise PipelineError("기술 선택에 필요한 질문에 먼저 답해 주세요.")
            selection_message = f"기술 구성 revision {decision.revision}에서 '{selected.label}'({selected.option_id})을 선택했습니다."
            if decision.status == TechStackDecisionStatus.QUESTIONS_REQUIRED:
                decision.answers.append(selection_message)
                state.add_event("planning", f"candidate selection answered {len(state.planning_questions)} technology choice questions")
                state.planning_questions = []
            decision.status = TechStackDecisionStatus.CONFIRMED
            decision.selected_option_id = option_id
            decision.confirmed_at = utc_now()
            decision.confirmed_by = "user"
            state.greenfield_phase = "stack_confirmed"
            self.messages.append_user(
                state,
                selection_message,
            )
            state.add_event("planning", f"technology stack decision revision {decision.revision} confirmed")
            self.records.save(state)
            return state

    def preview_bootstrap(self, run_id: str) -> BootstrapSpec:
        state = self.records.load(run_id)
        if state.bootstrap_spec is None:
            raise PipelineError("기본 구조 계획이 아직 준비되지 않았습니다.")
        return state.bootstrap_spec

    def configure_bootstrap_agent_instructions(
        self,
        run_id: str,
        *,
        create: bool,
        expected_revision: int,
        expected_digest: str,
    ) -> RunState:
        with self.records.run_lock(run_id, "bootstrap-agent-instructions"):
            state = self.records.load(run_id)
            if state.stage != Stage.PLANNED or state.greenfield_phase != "bootstrap_ready":
                raise PipelineError("기본 구조 실행 전 계획 확인 단계에서만 프로젝트 작업 지침을 변경할 수 있습니다.")
            decision = state.current_tech_stack_decision()
            spec = state.bootstrap_spec
            if decision is None or spec is None or decision.revision != expected_revision or spec.decision_revision != expected_revision:
                raise PipelineError("기술 구성 결정이 변경되었습니다. 최신 초기화 계획을 확인한 뒤 다시 선택해 주세요.")
            if spec.digest != expected_digest:
                raise PipelineError("초기화 계획이 변경되었습니다. 최신 미리보기를 확인한 뒤 다시 선택해 주세요.")
            target_mode = self.bootstrap().configure_agent_instructions(spec, state.tasks, create=create)
            if target_mode is None:
                return state
            state.revise_plan()
            state.add_event("planning", f"bootstrap AGENTS.md mode changed to {target_mode}")
            self.files.refresh_tasks(state)
            self.records.save(state)
            return state

    def generate_feature_plan(self, run_id: str) -> RunState:
        with self.records.run_lock(run_id, "generate-feature-plan"), self.records.chat_lock(run_id):
            state = self.records.load(run_id)
            return self.lifecycle.generate_features(state, suppress_errors=False)

    def refresh_planning_index(self, source_root: str | Path, *, base_commit: str = "") -> PlanningSourceIndex:
        return self.source_indexes().refresh(source_root, base_commit=base_commit)

    def exclude_tasks(self, run_id: str, task_ids: list[str]) -> RunState:
        selected_ids = list(dict.fromkeys(task_ids))
        if not selected_ids:
            raise PipelineError("no tasks selected for exclusion")
        with self.records.run_lock(run_id, "exclude-tasks"):
            state = self.lookup.at(run_id, {Stage.PLANNED})
            return self.exclusion().exclude_locked(state, selected_ids)

    def update_plan(self, run_id: str, task_drafts: list[dict[str, object]], *, expected_revision: int | None = None) -> RunState:
        with self.records.run_lock(run_id, "update-plan"):
            state = self.lookup.at(run_id, {Stage.PLANNED})
            if expected_revision is not None and state.plan_revision != expected_revision:
                raise PipelineError("편집하려던 계획이 변경됐습니다. 최신 계획을 다시 확인해 주세요.")
            protected_bootstrap = protected_greenfield_bootstrap(state)
            if any(task.status != TaskStatus.PENDING and task is not protected_bootstrap for task in state.tasks):
                raise PipelineError("task plan cannot be edited after execution has started")
            if protected_bootstrap is not None:
                incoming = next(
                    (draft for draft in task_drafts if str(draft.get("id", "")) == protected_bootstrap.id),
                    None,
                )
                if incoming is None:
                    raise PipelineError("검증된 project-bootstrap Task는 기능 계획에서 삭제할 수 없습니다.")
                protected_draft = task_plan_draft(protected_bootstrap)
                if any(incoming.get(key) != value for key, value in protected_draft.items()):
                    raise PipelineError("검증된 project-bootstrap Task는 수정할 수 없습니다.")
            plan = self.draft_validator().validate(state, task_drafts)
            state.tasks = [
                protected_bootstrap if protected_bootstrap is not None and task.id == protected_bootstrap.id else task
                for task in plan.tasks
            ]
            state.tasks = validate_task_graph(state.tasks)
            state.refresh_task_readiness()
            state.revise_plan()
            self.files.write_result(state, plan)
            state.add_event("planning", f"task plan revision {state.plan_revision} saved for review")
            self.records.save(state)
            return state

    def confirm_plan(self, run_id: str, *, expected_revision: int | None = None, expected_bootstrap_digest: str = "") -> RunState:
        with self.records.run_lock(run_id, "confirm-plan"):
            state = self.lookup.at(run_id, {Stage.PLANNED})
            plan = self.confirmation().prepare(
                state,
                run_id,
                expected_revision=expected_revision,
                expected_bootstrap_digest=expected_bootstrap_digest,
            )
            state.approve_plan()
            self.files.write_result(state, plan)
            state.add_event("planning", f"task plan revision {state.plan_revision} confirmed")
            self.records.save(state)
            return state

    def check_base(self, expected_base_commit: str) -> None:
        head = self.read_head()
        if head != expected_base_commit:
            raise PipelineError("계획의 기준 커밋이 현재 저장소와 다릅니다. 계획 컨텍스트를 다시 조회해 주세요.")

    def send_execution_message(
            self, run_id: str, message: str, *, planning_agent_id: str | None, planning_model: str | None, planning_reasoning_effort: str | None
        ) -> RunState:
            with self.records.chat_lock(run_id):
                state = self.records.load(run_id)
                if not (self.messages.execution_available(state) or self.messages.result_available(state)):
                    raise PipelineError(f"run {run_id} is at '{state.stage.value}', expected '{Stage.EXECUTING.value}' or an active execution start")
                active_agent = self.profiles.configure(
                    state, planning_agent_id=planning_agent_id, planning_model=planning_model, planning_reasoning_effort=planning_reasoning_effort
                )
                if state.archive is not None:
                    active_agent = replace(active_agent, review_sandbox_mode="read-only", review_approval_mode="deny-all")
                self.messages.append_user(state, message)
                state.add_event("planning", "execution planning chat message received")
                self.records.save_chat(state)
                try:
                    response = self.ai.chat_turn(state, active_agent, message, persist_state=self.records.save_chat)
                except (PipelineError, PlanningError, OSError) as exc:
                    state.add_event("planning", f"execution planning chat response failed: {exc}")
                    self.records.save_chat(state)
                    raise
                self.messages.append_assistant(state, response)
                state.add_event("planning", "execution planning chat response received")
                self.records.save_chat(state)
                return state
