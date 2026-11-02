import tempfile
import unittest
from pathlib import Path

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import (
    ConflictResolutionCandidate,
    ConflictResolutionStatus,
    IntegrationConflict,
    RunState,
    RunStep,
    Stage,
    TaskAction,
    TaskStatus,
    WorkTask,
)
from ai_orchestrator.pipeline import Pipeline


class NotificationEventTest(unittest.TestCase):
    def pipeline(self, root: Path, *, deployment: bool = False) -> Pipeline:
        return Pipeline(
            Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(deploy_command=("deploy",) if deployment else ()),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
        )

    def state(self, root: Path, stage: Stage = Stage.READY_TO_MERGE) -> RunState:
        return RunState(
            id="run-1",
            spec_path="plan.md",
            spec_digest="digest",
            repo_path=str(root),
            main_branch="main",
            stage=stage,
            summary="알림 구현",
            plan_revision=2,
            plan_approved_revision=2,
            tasks=[
                WorkTask(
                    id="task-1",
                    title="알림 API",
                    capabilities=["general"],
                    status=TaskStatus.COMPLETED,
                    completed_commit="a" * 40,
                    last_attempt_finished_at="2026-09-11T00:00:01+00:00",
                )
            ],
            updated_at="2026-09-11T00:00:02+00:00",
        )

    def test_state_save_persists_stable_task_and_attention_events_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = self.pipeline(root)
            state = self.state(root)

            pipeline.store.save(state)
            pipeline.store.save(state)
            result = pipeline.notifications()

            self.assertEqual([item["summary_code"] for item in result["items"]], ["task_completed", "integration_verification_required"])
            self.assertFalse(result["items"][0]["os_eligible"])
            self.assertEqual(len({item["source_key"] for item in result["items"]}), 2)
            restored = pipeline.store.load(state.id)
            self.assertEqual(len(restored.notification_events), 2)

    def test_retried_task_failure_uses_attempt_identity_without_copying_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = self.pipeline(root)
            state = self.state(root, Stage.FAILED)
            task = state.tasks[0]
            task.status = TaskStatus.FAILED
            task.failed_action = TaskAction.EXECUTE
            task.last_attempt_id = "attempt-1"
            task.error = "secret diagnostic must not be copied"
            state.failed_step = RunStep.AGENT_EXECUTION
            state.failure_message = task.error
            pipeline.store.save(state)

            state.resume_to(Stage.EXECUTING, "retry")
            task.status = TaskStatus.FAILED
            task.last_attempt_id = "attempt-2"
            task.last_attempt_finished_at = "2026-09-11T00:00:03+00:00"
            state.fail_step(RunStep.AGENT_EXECUTION, task.error)
            pipeline.store.save(state)
            items = pipeline.notifications()["items"]
            failures = [item for item in items if item["summary_code"] == "task_failed"]

            self.assertEqual(len(failures), 2)
            self.assertNotEqual(failures[0]["event_id"], failures[1]["event_id"])
            self.assertNotIn("secret", str(failures))

    def test_conflict_candidate_replaces_generic_failure_with_review_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = self.pipeline(root)
            state = self.state(root, Stage.FAILED)
            state.failed_step = RunStep.VERIFY
            state.integration_conflict = IntegrationConflict(
                id="conflict-1",
                verification_attempt_id="verify-1",
                main_head="a" * 40,
                work_head="b" * 40,
                merge_base_heads=["c" * 40],
                files=[],
                fingerprint="fingerprint",
                resolution_status=ConflictResolutionStatus.CANDIDATE_READY,
                candidate=ConflictResolutionCandidate(
                    id="candidate-1",
                    request_id="request-1",
                    revision=2,
                    status="candidate_ready",
                    created_at="2026-09-11T00:00:04+00:00",
                ),
            )
            pipeline.store.save(state)
            items = pipeline.notifications()["items"]

            candidate = next(item for item in items if item["summary_code"] == "conflict_candidate_ready")
            self.assertEqual((candidate["target_kind"], candidate["target_id"]), ("conflict", "conflict-1"))
            self.assertEqual(candidate["request_id"], "request-1")

    def test_cursor_pages_events_without_marking_them_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = self.pipeline(root)
            state = self.state(root)
            pipeline.store.save(state)

            first = pipeline.notifications(limit=1)
            second = pipeline.notifications(after_cursor=first["next_cursor"], limit=1)

            self.assertTrue(first["has_more"])
            self.assertFalse(second["has_more"])
            self.assertNotEqual(first["items"][0]["event_id"], second["items"][0]["event_id"])


if __name__ == "__main__":
    unittest.main()
