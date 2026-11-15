"""Bootstrap specifications, instruction previews and path protection."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from ..errors import PipelineError
from ..greenfield_instructions import (
    TEMPLATE_VERSION as GREENFIELD_AGENTS_TEMPLATE_VERSION,
    content_digest as greenfield_content_digest,
    render_greenfield_agents,
)
from ..models import (
    BootstrapAgentInstructions, BootstrapPathState, BootstrapSpec, PlanningMessageRole, RunState, TechStackDecision,
    TaskStatus, TechStackDecisionStatus, WorkTask,
)
from .contracts import Plan
from .validation import task_path_matches


BOOTSTRAP_SNAPSHOT_EXCLUDED_DIRECTORIES = frozenset({".git", ".ai-orchestrator", ".ai_auto_work"})
BOOTSTRAP_SNAPSHOT_MAX_PATHS = 10_000
BOOTSTRAP_AGENTS_PATH = "AGENTS.md"
BOOTSTRAP_AGENTS_ACCEPTANCE = "root AGENTS.md에 확정한 기술 구성과 검증 명령을 기록한다."


def bootstrap_spec_digest(spec: BootstrapSpec) -> str:
    payload = {
        "decision_id": spec.decision_id,
        "decision_revision": spec.decision_revision,
        "target_root": spec.target_root,
        "planned_paths": spec.planned_paths,
        "steps": spec.steps,
        "required_tools": spec.required_tools,
        "verify_commands": spec.verify_commands,
        "excluded_external_actions": spec.excluded_external_actions,
        "path_snapshot": [asdict(item) for item in spec.path_snapshot],
        "agent_instructions": asdict(spec.agent_instructions) if spec.agent_instructions is not None else None,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def bootstrap_path_snapshot(root: Path, planned_paths: list[str]) -> list[BootstrapPathState]:
    if not planned_paths:
        raise PipelineError("기본 구조 Task에 예상 변경 경로가 없습니다.")
    entries: list[BootstrapPathState] = []
    try:
        for current, directories, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            traversable_directories: list[str] = []
            for directory in sorted(directories):
                if directory.casefold() in BOOTSTRAP_SNAPSHOT_EXCLUDED_DIRECTORIES:
                    continue
                directory_path = current_path / directory
                relative_directory = directory_path.relative_to(root).as_posix()
                directory_is_junction = getattr(directory_path, "is_junction", lambda: False)
                if directory_path.is_symlink() or directory_is_junction():
                    if any(task_path_matches(relative_directory, rule) for rule in planned_paths):
                        entries.append(BootstrapPathState(relative_directory, "symlink", os.readlink(directory_path)))
                    continue
                traversable_directories.append(directory)
            directories[:] = traversable_directories
            relative_current = current_path.relative_to(root).as_posix()
            if relative_current != "." and any(task_path_matches(relative_current, rule) for rule in planned_paths):
                entries.append(BootstrapPathState(relative_current, "directory"))
            if len(entries) > BOOTSTRAP_SNAPSHOT_MAX_PATHS:
                raise PipelineError(
                    f"기본 구조 예상 경로가 {BOOTSTRAP_SNAPSHOT_MAX_PATHS:,}개를 넘어 안전하게 검사할 수 없습니다. 경로 범위를 좁혀 주세요."
                )
            for name in sorted(files):
                path = current_path / name
                relative_path = path.relative_to(root).as_posix()
                if not any(task_path_matches(relative_path, rule) for rule in planned_paths):
                    continue
                if path.is_symlink():
                    entries.append(BootstrapPathState(relative_path, "symlink", os.readlink(path)))
                else:
                    entries.append(BootstrapPathState(relative_path, "file", file_sha256(path)))
                if len(entries) > BOOTSTRAP_SNAPSHOT_MAX_PATHS:
                    raise PipelineError(
                        f"기본 구조 예상 경로가 {BOOTSTRAP_SNAPSHOT_MAX_PATHS:,}개를 넘어 안전하게 검사할 수 없습니다. 경로 범위를 좁혀 주세요."
                    )
    except OSError as exc:
        raise PipelineError(f"기본 구조 예상 경로를 확인하지 못했습니다: {exc}") from exc
    return entries


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class BootstrapPlanner:
    repo: Path

    def build(self, state: RunState, task: WorkTask) -> BootstrapSpec:
        decision = state.current_tech_stack_decision()
        if decision is None or decision.status != TechStackDecisionStatus.CONFIRMED:
            raise PipelineError("기술 구성을 확정한 뒤 기본 구조 계획을 적용해 주세요.")
        selected = next((option for option in decision.options if option.option_id == decision.selected_option_id), None)
        if selected is None:
            raise PipelineError("확정된 기술 구성 후보를 찾을 수 없습니다. 후보를 다시 생성해 주세요.")
        root = self.repo.resolve()
        components = selected.components
        stack_items = list(
            dict.fromkeys(
                [
                    selected.label,
                    *components.languages,
                    *components.runtimes,
                    *components.application_frameworks,
                    *components.ui_frameworks,
                ]
            )
        )
        agents_path = root / BOOTSTRAP_AGENTS_PATH
        if agents_path.is_file():
            agent_instructions = BootstrapAgentInstructions(
                mode="preserve_existing",
                template_version=GREENFIELD_AGENTS_TEMPLATE_VERSION,
                content_digest=file_sha256(agents_path),
            )
        else:
            template_verify_commands = [list(command) for command in task.verify_commands]
            if state.code_style_snapshot is not None:
                template_verify_commands.extend(
                    list(check.argv) for check in state.code_style_snapshot.checks if check.configured
                )
            rendered_agents = render_greenfield_agents(
                purpose=state.planning_request or state.summary,
                stack_items=stack_items,
                planned_paths=task.expected_paths,
                verify_commands=template_verify_commands,
            )
            task_path_injected = BOOTSTRAP_AGENTS_PATH not in task.expected_paths
            task_acceptance_injected = BOOTSTRAP_AGENTS_ACCEPTANCE not in task.acceptance_criteria
            agent_instructions = BootstrapAgentInstructions(
                mode="create_from_template",
                template_version=GREENFIELD_AGENTS_TEMPLATE_VERSION,
                rendered_content=rendered_agents,
                content_digest=greenfield_content_digest(rendered_agents),
                task_path_injected=task_path_injected,
                task_acceptance_injected=task_acceptance_injected,
            )
            if task_path_injected:
                task.expected_paths.append(BOOTSTRAP_AGENTS_PATH)
            if task_acceptance_injected:
                task.acceptance_criteria.append(BOOTSTRAP_AGENTS_ACCEPTANCE)
        planned_paths = list(dict.fromkeys(task.expected_paths))
        monitored_paths = list(dict.fromkeys([*planned_paths, agent_instructions.path]))
        path_snapshot = bootstrap_path_snapshot(root, monitored_paths)
        required_tools = list(
            dict.fromkeys(
                [
                    *components.languages,
                    *components.runtimes,
                    *components.package_and_build_tools,
                    *components.test_tools,
                ]
            )
        )
        result = BootstrapSpec(
            decision_id=decision.decision_id,
            decision_revision=decision.revision,
            target_root=str(root),
            planned_paths=planned_paths,
            steps=list(task.acceptance_criteria) or [task.title],
            required_tools=required_tools,
            verify_commands=[list(command) for command in task.verify_commands],
            excluded_external_actions=["remote_repository_changes", "deployment", "global_tool_installation"],
            path_snapshot=path_snapshot,
            digest="",
            agent_instructions=agent_instructions,
        )
        result.digest = bootstrap_spec_digest(result)
        return result

    def verify_current(self, state: RunState) -> None:
        if state.repository_intent != "new_project" or state.greenfield_phase != "bootstrap_ready":
            return
        spec = state.bootstrap_spec
        if spec is None:
            raise PipelineError("기본 구조 실행 명세가 없습니다. Planning 대화를 다시 적용해 주세요.")
        decision = state.current_tech_stack_decision()
        if (
            decision is None
            or decision.status != TechStackDecisionStatus.CONFIRMED
            or decision.decision_id != spec.decision_id
            or decision.revision != spec.decision_revision
        ):
            raise PipelineError("기술 구성 결정이 기본 구조 명세 생성 후 변경되었습니다. 계획을 다시 적용해 주세요.")
        root = self.repo.resolve()
        if Path(spec.target_root).expanduser().resolve() != root:
            raise PipelineError("기본 구조 대상 폴더가 현재 프로젝트와 다릅니다. 계획을 다시 적용해 주세요.")
        monitored_paths = list(spec.planned_paths)
        if spec.agent_instructions is not None and spec.agent_instructions.path not in monitored_paths:
            monitored_paths.append(spec.agent_instructions.path)
        current = bootstrap_path_snapshot(root, monitored_paths)
        expected_by_path = {item.relative_path: item for item in spec.path_snapshot}
        current_by_path = {item.relative_path: item for item in current}
        changed = sorted(
            path
            for path in expected_by_path.keys() | current_by_path.keys()
            if expected_by_path.get(path) != current_by_path.get(path)
        )
        if changed:
            visible = ", ".join(changed[:20])
            suffix = f" 외 {len(changed) - 20}개" if len(changed) > 20 else ""
            raise PipelineError(
                "기본 구조 계획을 만든 뒤 예상 경로가 변경되었습니다. 기존 파일을 덮어쓰지 않도록 실행을 중단했습니다. "
                f"변경 경로: {visible}{suffix}. Planning 대화에서 계획을 다시 적용해 주세요."
            )

    def configure_agent_instructions(
        self, spec: BootstrapSpec, tasks: list[WorkTask], *, create: bool,
    ) -> str | None:
        instructions = spec.agent_instructions
        if instructions is None:
            raise PipelineError("프로젝트 작업 지침 미리보기가 없는 이전 계획입니다. Planning 대화에서 계획을 다시 적용해 주세요.")
        if instructions.mode == "preserve_existing":
            raise PipelineError("기존 AGENTS.md는 자동 변경하거나 생성 제외할 수 없습니다.")
        target_mode = "create_from_template" if create else "skip_by_user"
        if instructions.mode == target_mode:
            return None
        task = next((item for item in tasks if item.id == "project-bootstrap"), None)
        if task is None or task.status != TaskStatus.PENDING:
            raise PipelineError("실행 전 project-bootstrap Task를 찾을 수 없습니다. 계획을 다시 확인해 주세요.")
        if create:
            if instructions.task_path_injected and instructions.path not in task.expected_paths:
                task.expected_paths.append(instructions.path)
            if instructions.task_acceptance_injected and BOOTSTRAP_AGENTS_ACCEPTANCE not in task.acceptance_criteria:
                task.acceptance_criteria.append(BOOTSTRAP_AGENTS_ACCEPTANCE)
        else:
            if instructions.task_path_injected:
                remaining_paths = [path for path in task.expected_paths if path != instructions.path]
                if not remaining_paths:
                    raise PipelineError("AGENTS.md를 제외하면 기본 구조 Task의 예상 변경 경로가 남지 않습니다. Planning 계획을 보완해 주세요.")
                task.expected_paths = remaining_paths
            if instructions.task_acceptance_injected:
                task.acceptance_criteria = [criterion for criterion in task.acceptance_criteria if criterion != BOOTSTRAP_AGENTS_ACCEPTANCE]
        instructions.mode = target_mode
        spec.planned_paths = list(dict.fromkeys(task.expected_paths))
        spec.steps = list(task.acceptance_criteria) or [task.title]
        monitored_paths = list(dict.fromkeys([*spec.planned_paths, instructions.path]))
        spec.path_snapshot = bootstrap_path_snapshot(self.repo.resolve(), monitored_paths)
        spec.digest = bootstrap_spec_digest(spec)
        return target_mode


def replace_tech_stack_decision(state: RunState, plan: Plan, *, repo: Path) -> None:
    current = state.current_tech_stack_decision()
    revision = max((decision.revision for decision in state.tech_stack_decisions), default=0) + 1
    if current is not None:
        current.status = TechStackDecisionStatus.SUPERSEDED
    answers = [
        message.text.strip()
        for message in state.planning_messages
        if message.role == PlanningMessageRole.USER and message.text.strip()
    ]
    state.tech_stack_decisions.append(
        TechStackDecision(
            decision_id=current.decision_id if current is not None else f"tech-stack-{state.id}",
            revision=revision,
            status=(
                TechStackDecisionStatus.QUESTIONS_REQUIRED
                if plan.questions
                else TechStackDecisionStatus.OPTIONS_READY
            ),
            project_root=str(repo.resolve()),
            requirement_sources=list(plan.source_paths),
            answers=answers,
            options=deepcopy(plan.tech_stack_options),
        )
    )
