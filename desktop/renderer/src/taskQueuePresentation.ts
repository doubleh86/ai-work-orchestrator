import type { RunExecutionSituation, WorkTask } from "./types";

export type TaskQueueHold = "plan_confirmation" | "group_turn" | "group_resume" | "none";

export function pendingTaskActionIsAllowed(primaryMethod: string | undefined, stage: string): boolean {
  return primaryMethod === "runs.execute" || (primaryMethod === "runs.resume" && stage === "executing");
}

export function taskRetryIsAllowed(primaryMethod: string | undefined, failedStep: string | null): boolean {
  return primaryMethod === "runs.resume" && failedStep === "agent_execution";
}

export function blockedTaskFailureAction(taskStatus: string, taskRetryAllowed: boolean): { label: string; reason: string } | undefined {
  if (taskStatus !== "failed" || taskRetryAllowed) return undefined;
  return {
    label: "그룹 복원 필요",
    reason: "이 실패 단계는 개별 작업 재시도를 지원하지 않습니다. 상단 복구 안내를 확인하세요.",
  };
}

export function taskQueueHold(
  task: WorkTask,
  planConfirmed: boolean,
  taskActionsAllowed: boolean,
  executionSituation: RunExecutionSituation | undefined,
): TaskQueueHold {
  if (task.status !== "pending") return "none";
  if (!planConfirmed) return "plan_confirmation";
  if (taskActionsAllowed || task.readiness === "blocked") return "none";
  if (["running", "preparing"].includes(executionSituation || "")) return "group_turn";
  if (executionSituation === "resumable") return "group_resume";
  return "none";
}
