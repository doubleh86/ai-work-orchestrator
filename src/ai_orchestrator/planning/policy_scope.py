"""Keep a per-Pipeline Planning policy with explicit persistence ports."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from ..config import AgentConfig
from ..effort_policy import resolve_reasoning_profile
from ..errors import PipelineError
from ..models import EffortPlanningBinding, EffortPolicyState, EffortProfileSnapshot, ProfileSource, ResolvedEffortPolicy, RunState, utc_now


class PlanningPolicyPath(Protocol):
    def __call__(self, run_id: str, *, archived_chat: bool = False) -> Path: ...


class PlanningPolicyLoad(Protocol):
    def __call__(self, run_id: str, *, archived_chat: bool = False) -> EffortPolicyState: ...


class PlanningPolicyPrepare(Protocol):
    def __call__(
        self, run_id: str, policy: ResolvedEffortPolicy, *, request_id: str, expected_revision: int, purpose: str,
        archived_chat: bool = False,
    ) -> EffortPlanningBinding: ...


class PlanningPolicyFinish(Protocol):
    def __call__(self, run_id: str, request_id: str, *, failed: bool = False, archived_chat: bool = False) -> EffortPlanningBinding: ...


@dataclass(frozen=True, slots=True)
class PlanningPolicyRecords:
    path: PlanningPolicyPath
    load: PlanningPolicyLoad
    prepare: PlanningPolicyPrepare
    finish: PlanningPolicyFinish


@dataclass(frozen=True, slots=True)
class PlanningPolicyScope:
    context: ContextVar[tuple[str, str, ResolvedEffortPolicy] | None]
    records: PlanningPolicyRecords
    default_agent_id: Callable[[], str]
    available_agent: Callable[[str, str], AgentConfig]

    @contextmanager
    def scope(self, state: RunState, *, purpose: str) -> Iterator[ResolvedEffortPolicy | None]:
        active = self.context.get()
        if active is not None and active[0] == state.id:
            yield active[2]
            return
        archive_options = {"archived_chat": True} if state.archive is not None and purpose == "chat" else {}
        if not (self.records.path(state.id, **archive_options).exists() or (
            archive_options and self.records.path(state.id).exists()
        )):
            yield None
            return
        selected = self.records.load(state.id, **archive_options)
        agent_id = state.planning_agent_id or self.default_agent_id()
        if selected.selected_mode is None or not agent_id:
            yield None
            return
        agent = self.available_agent(agent_id, "review")
        reasoning = resolve_reasoning_profile(
            mode=selected.selected_mode, provider_id=agent.provider_id, model=state.planning_model or agent.model,
            reasoning_effort=state.planning_reasoning_effort, profile_source=state.planning_profile_source,
            baseline_reasoning_effort=state.planning_effort_baseline_reasoning,
            purpose="planning",
        )
        if "mode_profile_baseline_missing" in reasoning.unsupported_effects:
            raise PipelineError("Planning effort policy requires the original reasoning profile")
        profile = EffortProfileSnapshot(agent.id, agent.provider_id, reasoning.model, reasoning.reasoning_effort, reasoning.profile_source)
        policy = ResolvedEffortPolicy(
            policy_id=str(uuid.uuid4()), policy_version=3, mode=selected.selected_mode, scope="planning",
            plan_revision=state.plan_revision, planning_profile=profile, task_profiles=(), review_decisions=(),
            manual_exception_ids=("planning",) if state.planning_profile_source == ProfileSource.MANUAL else (),
            unsupported_effects=tuple(f"planning:{item}" for item in reasoning.unsupported_effects), resolved_at=utc_now(),
        )
        request_id = str(uuid.uuid4())
        self.records.prepare(
            state.id, policy, request_id=request_id, expected_revision=selected.revision, purpose=purpose, **archive_options,
        )
        token = self.context.set((state.id, request_id, policy))
        try:
            yield policy
        except BaseException:
            self.records.finish(state.id, request_id, failed=True, **archive_options)
            raise
        else:
            self.records.finish(state.id, request_id, **archive_options)
        finally:
            self.context.reset(token)
