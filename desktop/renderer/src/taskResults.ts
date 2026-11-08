import type { TaskResultRecord, WorkTask } from "./types";

export function currentTaskResult(task: WorkTask): TaskResultRecord | undefined {
  if (!["completed", "merged"].includes(task.status) || !task.completed_commit) return undefined;
  const result = task.result_history?.at(-1);
  return result?.result_commit === task.completed_commit ? result : undefined;
}
