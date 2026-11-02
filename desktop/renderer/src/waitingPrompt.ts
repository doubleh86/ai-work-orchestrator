import type { RunState } from "./types";

export function waitingPromptAction(run: RunState): "retry" | "resume" | "verify" | "operations" | null {
  const prompt = run.waiting_prompt;
  const control = run.execution_control;
  if (!prompt || !prompt.source_key || run.archive || run.active_step || control?.lock_state !== "unlocked"
    || control.dispatch_paused || ["stopping", "stopped", "confirmation_required"].includes(control.stop_phase)
    || ["running", "preparing", "status_unknown", "unavailable"].includes(control.situation)
    || run.tasks.some((task) => task.active_action || ["running", "reviewing", "revising"].includes(task.status))) return null;
  if (prompt.action === "retry" && prompt.kind === "retry" && run.stage === "failed" && run.failed_step === "agent_execution"
    && control.action === "resume" && run.tasks.some((task) => task.id === prompt.task_id && task.status === "failed")) return "retry";
  if (prompt.action === "resume" && prompt.kind === "resume" && run.stage === "executing"
    && control.action === "resume" && control.situation === "resumable"
    && !run.tasks.some((task) => ["failed", "waiting", "stopped"].includes(task.status))
    && run.tasks.some((task) => task.id === prompt.next_task_id && task.status === "pending" && task.readiness === "ready")) return "resume";
  if (prompt.action === "verify" && prompt.kind === "verification" && run.stage === "ready_to_merge"
    && run.tasks.every((task) => ["completed", "merged"].includes(task.status))
    && run.integration_control?.status === "needs_verification" && run.integration_control.can_verify) return "verify";
  if (prompt.action === "operations" && prompt.kind === "main_review" && ["verified", "work_branch_pushed"].includes(run.stage)
    && run.integration_control?.status === "verified") return "operations";
  return null;
}

export async function readWaitingPromptAction(
  read: () => Promise<RunState>, sourceKey: string,
): Promise<{ run: RunState; action: ReturnType<typeof waitingPromptAction> }> {
  const run = await read();
  return { run, action: run.waiting_prompt?.source_key === sourceKey ? waitingPromptAction(run) : null };
}
