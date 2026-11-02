import type { RunState, TaskRetryContext, WorkTask } from "./types";
import type { RpcMethod, RpcParams } from "../../shared/rpc";

import { chatExecutionIntent } from "../../shared/chatExecution";
export { chatExecutionIntent, type ChatExecutionIntent } from "../../shared/chatExecution";

export function chatRequestsTaskRecovery(message: string): boolean {
  return ["repair", "stop_repair"].includes(chatExecutionIntent(message) || "");
}

export function chatRecoveryTask(run: RunState, taskId?: string): WorkTask | undefined {
  if (run.archive || run.active_step) return;
  const stopped = run.stage === "executing" && run.execution_control?.stop_phase === "stopped"
    && run.execution_control.lock_state === "unlocked";
  if (!stopped && (run.stage !== "failed" || run.failed_step !== "agent_execution")) return;
  const failed = run.tasks.filter(task => task.status === (stopped ? "stopped" : "failed"));
  if (failed.length !== 1 || taskId && failed[0].id !== taskId) return;
  if (run.tasks.some(task => task.active_action
    || task.id !== failed[0].id && !["pending", "completed", "merged"].includes(task.status))) return;
  return failed[0];
}

export async function recoverTaskFromChat(options: {
  projectName: string; run: RunState; task: WorkTask; message: string; requestId: string;
  request<T>(method: RpcMethod, params: RpcParams): Promise<T>;
  isCurrent(): boolean;
}): Promise<RunState | undefined> {
  const { projectName, run, task, message, requestId, request, isCurrent } = options;
  const params = { projectName, runId: run.id, taskId: task.id };
  const context = await request<TaskRetryContext>("tasks.retryContext", params);
  if (!isCurrent()) return;
  if (!context.can_save) throw new Error(context.reason || "현재 Task를 복구할 수 없습니다. 상태를 확인해 주세요.");
  if (context.recovery?.can_execute === false) throw new Error("현재 조건에서는 복구할 수 없습니다. 지연 원인과 작업 상태를 확인해 주세요.");
  if (context.task_id !== task.id || !context.fingerprint) throw new Error("복구 대상 확인 응답이 일치하지 않습니다.");
  if (context.plan_revision !== run.plan_revision || context.attempt_id !== (task.last_attempt_id || "")) {
    throw new Error("실패 Task 또는 계획이 변경됐습니다. 최신 상태를 확인한 뒤 다시 요청해 주세요.");
  }
  return request<RunState>("tasks.repairFromChat", {
    ...params, requestId, message, fingerprint: context.fingerprint,
    conversationRevision: run.planning_conversation_revision || 0,
    ...(context.recovery?.fingerprint ? { recoveryFingerprint: context.recovery.fingerprint } : {}),
  });
}
