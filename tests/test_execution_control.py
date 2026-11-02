from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.git import run_command
from ai_orchestrator.models import ExecutionControlRecord, RunState, RunStep, Stage, TaskAction, TaskStatus, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError


def pipeline_at(root: Path) -> Pipeline:
    repo = root / "repo"
    repo.mkdir()
    return Pipeline(
        Config(
            path=root / "orchestrator.toml",
            project=ProjectConfig(repo=repo),
            execution=ExecutionConfig(),
            agents=(),
        )
    )


def test_stop_request_targets_one_active_parallel_task(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    execution_id = str(uuid.uuid4())
    first_attempt = str(uuid.uuid4())
    first_invocation = str(uuid.uuid4())
    second_attempt = str(uuid.uuid4())
    second_invocation = str(uuid.uuid4())
    pipeline.store.save_execution_control(
        ExecutionControlRecord(
            run_id="run-1",
            execution_id=execution_id,
            scope="task",
            owner_pid=123,
            task_id="task-2",
            attempt_id=second_attempt,
            invocation_id=second_invocation,
            active_targets={
                "task-1": {"task_title": "First", "action": "execute", "attempt_id": first_attempt, "invocation_id": first_invocation},
                "task-2": {"task_title": "Second", "action": "execute", "attempt_id": second_attempt, "invocation_id": second_invocation},
            },
        )
    )

    operation = pipeline.request_stop(
        "run-1",
        request_id=str(uuid.uuid4()),
        execution_id=execution_id,
        scope="task",
        task_id="task-1",
        attempt_id=first_attempt,
        invocation_id=first_invocation,
    )

    control = pipeline.store.load_execution_control("run-1")
    assert operation.phase == "stopping"
    assert control is not None
    assert control.dispatch_paused is True
    assert control.task_id == "task-1"
    assert control.active_targets["task-2"]["invocation_id"] == second_invocation


def test_stop_request_rejects_changed_invocation(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    execution_id = str(uuid.uuid4())
    pipeline.store.save_execution_control(
        ExecutionControlRecord(
            run_id="run-1",
            execution_id=execution_id,
            scope="task",
            owner_pid=123,
            active_targets={
                "task-1": {"task_title": "First", "action": "execute", "attempt_id": "current", "invocation_id": "current"}
            },
        )
    )

    operation = pipeline.request_stop(
        "run-1",
        request_id=str(uuid.uuid4()),
        execution_id=execution_id,
        scope="task",
        task_id="task-1",
        attempt_id="old",
        invocation_id="old",
    )

    assert operation.status == "failed"
    assert operation.phase == "target_changed"


def test_verification_repair_classifier_excludes_environment_failures() -> None:
    assert Pipeline._verification_failure_is_repairable(PipelineError("통합 검증 명령이 실패했습니다: npm test"))
    assert not Pipeline._verification_failure_is_repairable(PipelineError("통합 검증 명령이 제한시간을 초과했습니다: npm test"))
    assert not Pipeline._verification_failure_is_repairable(PipelineError(".NET SDK 환경 오류"))


@pytest.mark.parametrize(
    ("output", "locked"),
    [
        ('targets(1,1): error MSB3021: The process cannot access the file because it is being used by another process.', True),
        ('error MSB3027: Exceeded retry count. The file is locked by: "ExampleServer (123)"', True),
        ('error MSB3021: 다른 프로세스가 파일을 사용 중이기 때문에 프로세스가 액세스할 수 없습니다.', True),
        ('오류 MSB3027: 파일이 다음 프로세스에 의해 잠겨 있습니다: ExampleServer (123)', True),
        ('error MSB3021: Access to the path is denied.', False),
        ('error MSB3027: Exceeded retry count. Failed.', False),
        ('warning MSB3026: The file is locked by: "ExampleServer (123)"\nerror CS1002: ; expected', False),
        ('error CS1002: ; expected\nTest name: file is locked by another process', False),
    ],
)
def test_verification_file_lock_requires_explicit_copy_error_evidence(output: str, locked: bool) -> None:
    assert Pipeline._verification_output_file_locked(("dotnet", "test"), output) is locked
    assert Pipeline._verification_output_file_locked(("npm", "test"), output) is False


def test_file_lock_stops_auto_repair_preserves_evidence_and_allows_full_retry(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    commands = (("dotnet", "build", "Example.sln"), ("dotnet", "test", "Example.sln"))
    task = WorkTask(id="completed", title="Completed work", capabilities=["general"], status=TaskStatus.COMPLETED,
                    completed_commit="preserved-commit", verify_commands=[list(command) for command in commands])
    state = RunState(id="file-lock-run", spec_path="plan.md", spec_digest="abc", repo_path=str(pipeline.repo),
                     main_branch="main", stage=Stage.READY_TO_MERGE, tasks=[task])
    pipeline.store.save(state)
    locked_output = 'error MSB3027: Exceeded retry count. The file is locked by: "ExampleServer (123)"'
    invocations: list[tuple[str, ...]] = []
    locked = True

    def command_result(command: tuple[str, ...], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        invocations.append(tuple(command))
        failed = locked and command[1] == "test"
        return subprocess.CompletedProcess(command, 1 if failed else 0, "build/test output", locked_output if failed else "")

    def verify_workspace(current: RunState, selected: tuple[tuple[str, ...], ...]) -> RunState:
        pipeline._run_verification_commands(current, pipeline.repo, selected)
        current.transition(Stage.VERIFIED, "test workspace verified")
        pipeline.store.save(current)
        return current

    request_id = str(uuid.uuid4())
    with (
        patch.object(pipeline, "_verify_before_merge", side_effect=verify_workspace),
        patch.object(pipeline, "_verify_shared_workspace", side_effect=verify_workspace),
        patch.object(pipeline, "_prepare_verification_command", side_effect=lambda command, *_: command),
        patch("ai_orchestrator.pipeline.run_command", side_effect=command_result),
        patch.object(pipeline, "_repair_verification_failure") as repair,
    ):
        with pytest.raises(PipelineError, match="실행 중인 앱"):
            pipeline.verify_and_repair(state.id, request_id=request_id)
        failed = pipeline.store.load(state.id)
        assert failed.stage == Stage.FAILED and failed.failed_step == RunStep.VERIFY
        assert failed.tasks[0].status == TaskStatus.COMPLETED and failed.tasks[0].completed_commit == "preserved-commit"
        assert failed.verification_repair_count == 0
        attempt = failed.verification_attempts[-1]
        assert attempt.failure_phase == "file_lock" and attempt.failed_command == list(commands[1])
        assert attempt.passed_commands == [list(commands[0])]
        assert attempt.candidate_task_ids == [] and attempt.failed_task_id == ""
        assert "파일 잠금" in attempt.attribution_reason
        saved_log = Path(attempt.log_path).read_text(encoding="utf-8")
        assert locked_output in saved_log and "build/test output" in saved_log
        operation = pipeline.store.load_operation(state.id, request_id)
        assert operation is not None and operation.status == "failed" and operation.error_code == "verification_not_repairable"
        repair.assert_not_called()
        locked = False
        retried = pipeline.verify(state.id)
        assert retried.stage == Stage.VERIFIED and retried.failure_message == ""
        assert retried.verification_attempts[-1].passed_commands == [list(command) for command in commands]
        assert invocations == [*commands, *commands], "retry must run the original complete commands without skipping build"
        repair.assert_not_called()


class EventSignal:
    def __init__(self) -> None:
        self.event = threading.Event()

    def is_set(self) -> bool:
        return self.event.is_set()


def test_noninteractive_command_honors_user_stop(tmp_path: Path) -> None:
    signal = EventSignal()
    timer = threading.Timer(0.15, signal.event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ExecutionStopped):
            run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                tmp_path,
                non_interactive=True,
                timeout_seconds=10,
                cancel_signal=signal,
            )
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5


def test_group_resume_queues_stopped_task_from_preserved_work(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    task = WorkTask(
        id="task-1",
        title="Stopped task",
        capabilities=["general"],
        status=TaskStatus.STOPPED,
        failed_action=TaskAction.REVIEW,
        stop_request_id=str(uuid.uuid4()),
    )
    state = RunState(
        id="run-1",
        spec_path="plan.md",
        spec_digest="abc",
        repo_path=str(pipeline.repo),
        main_branch="main",
        stage=Stage.EXECUTING,
        tasks=[task],
    )
    pipeline.store.save(state)

    with patch.object(pipeline, "_execute", side_effect=lambda current, *, manual, recover_saved_profiles: current) as execute:
        resumed = pipeline._resume(state.id, manual=False)

    assert resumed.tasks[0].status == TaskStatus.PENDING
    assert resumed.tasks[0].failed_action == TaskAction.REVIEW
    execute.assert_called_once()
    assert execute.call_args.kwargs == {"manual": False, "recover_saved_profiles": True}


def test_verification_repair_stop_is_recorded_as_interrupted(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    state = RunState(
        id="run-1",
        spec_path="plan.md",
        spec_digest="abc",
        repo_path=str(pipeline.repo),
        main_branch="main",
        stage=Stage.READY_TO_MERGE,
    )
    pipeline.store.save(state)
    request_id = str(uuid.uuid4())

    with (
        patch.object(pipeline, "_verify_locked", side_effect=PipelineError("통합 검증 명령이 실패했습니다: test")),
        patch.object(
            pipeline,
            "_repair_verification_failure",
            side_effect=ExecutionStopped("사용자 요청에 따라 중지했습니다.", request_id=""),
        ),
    ):
        result = pipeline.verify_and_repair(state.id, request_id=request_id)

    operation = pipeline.store.load_operation(state.id, request_id)
    assert result.verification_progress_phase == "stopped"
    assert operation is not None
    assert operation.status == "interrupted"
    assert operation.error_code == "user_stopped"
