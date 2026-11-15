"""Validate a verified bootstrap and the feature plan built from it."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from ..errors import PipelineError
from ..models import BootstrapSpec, RunState, Stage, TaskStatus, TechStackDecision, TechStackDecisionStatus, WorkTask
from .contracts import Plan, PlanningError
from .validation import validate_task_graph


@dataclass(frozen=True, slots=True)
class FeaturePlanningBaseline:
    spec: BootstrapSpec
    decision: TechStackDecision
    bootstrap: WorkTask


def feature_planning_baseline(state: RunState) -> FeaturePlanningBaseline:
    if state.repository_intent != "new_project":
        raise PipelineError("새 프로젝트 기준선에만 기능 계획을 생성할 수 있습니다.")
    if state.stage != Stage.VERIFIED or state.greenfield_phase not in {
        "feature_planning_ready",
        "feature_planning",
    }:
        raise PipelineError("검증된 기본 구조의 기능 Planning 준비 상태에서만 실행할 수 있습니다.")
    spec = state.bootstrap_spec
    decision = state.current_tech_stack_decision()
    bootstrap = next((task for task in state.tasks if task.id == "project-bootstrap"), None)
    if spec is None or not spec.verified_integration_head or not spec.verified_at:
        raise PipelineError("검증된 기본 구조 snapshot을 찾을 수 없습니다.")
    if (
        decision is None
        or decision.status != TechStackDecisionStatus.CONFIRMED
        or decision.decision_id != spec.decision_id
        or decision.revision != spec.decision_revision
    ):
        raise PipelineError("기술 구성 결정이 검증된 기본 구조 snapshot과 일치하지 않습니다.")
    if bootstrap is None or bootstrap.status not in {TaskStatus.COMPLETED, TaskStatus.MERGED}:
        raise PipelineError("완료된 project-bootstrap Task를 찾을 수 없습니다.")
    return FeaturePlanningBaseline(spec, decision, bootstrap)


def feature_planning_context(baseline: FeaturePlanningBaseline) -> str:
    spec, decision = baseline.spec, baseline.decision
    return (
        "검증된 신규 프로젝트 기준선에서 제품 기능 구현 계획을 생성하세요. "
        "아래 snapshot은 이 작업 그룹에서 확정·검증됐으며 변경할 수 없습니다. "
        "project-bootstrap을 다시 만들거나 depends_on에 넣지 말고 제품 기능 Task만 반환하세요. "
        "기능 root와 bootstrap의 의존성은 오케스트레이터가 추가합니다.\n"
        + json.dumps(
            {
                "verified_integration_head": spec.verified_integration_head,
                "verified_at": spec.verified_at,
                "technology_decision": asdict(decision),
                "bootstrap_spec": {
                    "decision_id": spec.decision_id,
                    "decision_revision": spec.decision_revision,
                    "target_root": spec.target_root,
                    "planned_paths": spec.planned_paths,
                    "required_tools": spec.required_tools,
                    "verify_commands": spec.verify_commands,
                    "digest": spec.digest,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def feature_plan_tasks(plan: Plan, baseline: FeaturePlanningBaseline) -> list[WorkTask]:
    bootstrap = baseline.bootstrap
    if plan.questions:
        raise PlanningError("기능 계획에 추가 확인이 필요합니다: " + " / ".join(plan.questions))
    if not plan.tasks:
        raise PlanningError("검증된 기본 구조 뒤에 실행할 기능 Task가 없습니다.")
    if any(task.id == bootstrap.id for task in plan.tasks):
        raise PlanningError("기능 계획은 project-bootstrap Task를 다시 만들 수 없습니다.")
    for task in plan.tasks:
        if not task.dependencies:
            task.dependencies = [bootstrap.id]
    return validate_task_graph([bootstrap, *plan.tasks])
