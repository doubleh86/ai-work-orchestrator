import type { RunState } from "./types";
import { taskIsActive } from "./executionActivity";

// This action continues only the successful retry explicitly approved by the user.
// Python rechecks the actual stop, dependency, lock and execution contracts.
export function canContinueTaskRetry(before: RunState, latest: RunState, taskId: string, retryResult: RunState = latest): boolean {
  const control = latest.execution_control;
  if (before.id !== latest.id || latest.archive || latest.plan_revision !== before.plan_revision
    || latest.id !== retryResult.id || latest.plan_revision !== retryResult.plan_revision || latest.stage !== "executing"
    || latest.active_step || control?.action !== "resume" || control.situation !== "resumable" || control.lock_state !== "unlocked"
    || control.dispatch_paused || ["stopping", "stopped", "confirmation_required"].includes(control.stop_phase)
    || latest.tasks.some((task) => taskIsActive(task) || ["failed", "waiting", "stopped"].includes(task.status))
    || !latest.tasks.some((task) => task.status === "pending" && task.readiness === "ready")) return false;
  const previous = before.tasks.find((task) => task.id === taskId);
  const task = latest.tasks.find((item) => item.id === taskId);
  if (previous?.status !== "failed" || !task || task.status !== "completed" || !task.completed_commit || !task.last_attempt_id
    || task.last_attempt_id === previous.last_attempt_id) return false;
  const result = retryResult.tasks.find((item) => item.id === taskId);
  if (result?.status !== "completed" || result.last_attempt_id !== task.last_attempt_id || result.completed_commit !== task.completed_commit) return false;
  const prefix = `task:${taskId}:remaining_tasks_resume_required:${latest.plan_revision}:${task.last_attempt_id}:${task.completed_commit}:`;
  if (latest.waiting_prompt && (latest.waiting_prompt.action !== "resume" || !latest.waiting_prompt.source_key.startsWith(prefix))) return false;
  return before.tasks.filter((item) => ["completed", "merged"].includes(item.status)).every((item) => {
    const current = latest.tasks.find((candidate) => candidate.id === item.id);
    return current?.status === item.status && current.completed_commit === item.completed_commit;
  });
}
