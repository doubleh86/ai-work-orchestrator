from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import RunExecutionSituation, Stage, TaskStatus, UserCheck
from ai_orchestrator.pipeline import Pipeline, PipelineError
from test_pipeline import git


def test_user_checks_gate_only_their_dependents_and_integration(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "0.1.0"\n', encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Initial")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    pipeline = Pipeline(Config(
        path=tmp_path / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
        agents=(AgentConfig("general", ("general",), (sys.executable, "-c", "pass"), 1),),
    ))
    base = pipeline.git.head(repo)

    def draft(task_id: str, dependencies: list[str]) -> dict[str, object]:
        return {
            "id": task_id, "title": task_id, "description": f"Implement {task_id}", "capabilities": ["general"],
            "depends_on": dependencies, "acceptance_criteria": [f"{task_id} is implemented"],
            "expected_paths": [f"src/{task_id}.txt"], "forbidden_paths": [],
            "verify_commands": [[sys.executable, "-c", "pass"]], "risk_level": "low",
        }

    tasks = [draft("prepare", []), draft("dependent", []), draft("later", ["dependent"]), draft("independent", [])]
    checks = (
        UserCheck("workflow", "수동 흐름 확인", "테스트 환경에서 흐름을 확인한다.", ("흐름 완료",), "prepare", ("dependent",)),
        UserCheck("acceptance", "통합 전 확인", "통합 기준을 확인한다.", ("최종 흐름 완료",), "later", required_for_integration=True),
        UserCheck("optional", "참고 확인", "별도 환경을 확인한다.", ("참고 자료 확인",)),
    )

    def submit(user_checks: tuple[UserCheck, ...]):
        return pipeline.submit_external_plan(
            f"mcp-plan-{uuid.uuid4().hex}", expected_base_commit=base, summary="사용자 확인이 있는 계획", requirements="기획 내용",
            task_drafts=tasks, user_checks=user_checks,
        )

    cycle = UserCheck("cycle", "순환", "확인한다.", ("확인",), "later", ("dependent",))
    with pytest.raises(PipelineError, match="순환 의존성"):
        submit((cycle,))
    with pytest.raises(PipelineError, match="등록되지 않은 작업"):
        submit((UserCheck("missing", "확인", "확인한다.", ("확인",), "absent"),))

    preflight = submit((UserCheck("base-review", "기준 확인", "기준 내용을 확인한다.", ("기준 확인",),
                                  blocks_task_ids=("prepare", "dependent", "independent")),))
    pipeline.confirm_plan(preflight.id, expected_revision=1)
    blocked = pipeline.execute(preflight.id)
    assert blocked.stage == Stage.PLANNED and not blocked.execution_worktree
    assert pipeline.status_with_controls(preflight.id)[1].situation == RunExecutionSituation.WAITING_USER_CHECK

    plan = submit(checks)
    assert plan.user_check_blocked_task_ids() == {"dependent", "later"}
    with pytest.raises(PipelineError, match="등록되지 않은 작업"):
        pipeline.exclude_tasks(plan.id, ["prepare"])

    def record(check_id: str, commit: str, outcome: str, note: str):
        return pipeline.record_user_check(
            plan.id, check_id, expected_revision=plan.plan_revision, expected_commit=commit, outcome=outcome, note=note,
        )

    with pytest.raises(PipelineError, match="confirmed"):
        record("optional", base, "passed", "앱 승인 전")
    pipeline.confirm_plan(plan.id, expected_revision=1)
    with pytest.raises(PipelineError, match="계획이 변경"):
        pipeline.record_user_check(plan.id, "optional", expected_revision=0, expected_commit=base, outcome="passed", note="이전 계획")
    with pytest.raises(PipelineError, match="기준 커밋"):
        record("workflow", base, "passed", "기준 작업 완료 전")

    invoked: list[str] = []

    def implement(_state, task, *_args):
        invoked.append(task.id)
        (Path(task.worktree) / f"src/{task.id}.txt").write_text(task.id, encoding="utf-8")
        return "implemented"

    with patch.object(pipeline, "_invoke_agent", side_effect=implement):
        paused = pipeline.execute(plan.id)
        assert paused.stage == Stage.EXECUTING and paused.failed_step is None and paused.active_step is None
        assert invoked == ["prepare", "independent"]
        assert pipeline.status_with_controls(plan.id)[1].situation == RunExecutionSituation.WAITING_USER_CHECK
        assert [task.blocked_by for task in paused.tasks if task.id == "dependent"] == [["workflow"]]
        anchor = next(task.completed_commit for task in paused.tasks if task.id == "prepare")
        independent = next(task.completed_commit for task in paused.tasks if task.id == "independent")
        assert anchor != independent
        with pytest.raises(PipelineError, match="기준 커밋"):
            record("workflow", independent, "passed", "다른 작업 결과")
        record("workflow", anchor, "failed", "재현됨")
        record("workflow", anchor, "deferred", "테스트 환경 대기")
        assert pipeline.resume(plan.id).stage == Stage.EXECUTING
        assert invoked == ["prepare", "independent"]
        record("workflow", anchor, "passed", "검증 완료")
        replay = record("workflow", anchor, "passed", "검증 완료")
        assert len(replay.user_check_results["workflow"]) == 3
        with pytest.raises(PipelineError, match="통과로 확정"):
            record("workflow", anchor, "failed", "확정된 커밋 재기록")
        assert pipeline.status_with_controls(plan.id)[1].action == "resume"
        finished = pipeline.resume(plan.id)
        assert invoked == ["prepare", "independent", "dependent", "later"]
        assert all(task.status == TaskStatus.COMPLETED for task in finished.tasks)
        assert finished.stage == Stage.EXECUTING
        assert pipeline.status_with_controls(plan.id)[2].reason_code == "user_checks_pending"
        with pytest.raises(PipelineError, match="ready_to_merge"):
            pipeline.verify(plan.id)

    reference = next(task.completed_commit for task in finished.tasks if task.id == "later")
    assert record("acceptance", reference, "passed", "통합 확인 완료").stage == Stage.READY_TO_MERGE
    assert pipeline.verify(plan.id).stage == Stage.VERIFIED
    saved = pipeline.status(plan.id)
    assert saved.user_check_plan == list(checks)
    assert [item["status"] for item in pipeline.planned_user_checks(saved)] == ["passed", "passed", "waiting"]
