import type { RpcMethod, RpcParams } from "../../shared/rpc";
import type { RunState } from "./types";
import { type ChatExecutionIntent } from "./chatTaskRecovery";
import { chatControlParams } from "../../shared/chatExecution";

export type ChatExecutionPhase = "stopping" | "repairing" | "verifying" | "thinking" | "working";

export function chatExecutionErrorReported(run: RunState, previousMessageCount: number, submittedText: string, error: string): boolean {
  const normalize = (value: string) => value.replace(/\s+/gu, " ").trim();
  const messages = run.planning_messages.slice(previousMessageCount);
  const submitted = messages.findIndex(message => message.role === "user" && message.text === submittedText);
  if (submitted < 0) return false;
  const cause = normalize(error);
  for (const message of messages.slice(submitted + 1)) {
    if (message.role === "user") break;
    const detail = normalize(message.text).replace(/^(?:복구를 진행하지 못했습니다|중지 요청을 처리하지 못했습니다|요청을 진행하지 못했습니다)\.\s*/u, "");
    if (detail && (cause === detail || cause.endsWith(`: ${detail}`))) return true;
  }
  return false;
}

export async function controlExecutionFromChat(options: {
  projectName: string; run: RunState; taskId?: string; message: string; requestId: string; intent: ChatExecutionIntent;
  profile?: { planningAgentId: string; planningModel: string; planningReasoningEffort: string };
  request<T>(method: RpcMethod, params: RpcParams): Promise<T>;
  isCurrent(): boolean;
  onRun(run: RunState): void;
  onPhase(phase: ChatExecutionPhase): void;
  wait?: () => Promise<void>;
  now?: () => number;
}): Promise<RunState | undefined> {
  const { projectName, message, requestId, intent, request, onRun, onPhase } = options;
  const run = options.run, control = run.execution_control;
  const params = chatControlParams(projectName, run, message, requestId, intent, options.taskId);
  onPhase(intent === "project" ? "thinking" : control?.can_stop || intent === "stop" ? "stopping" : "repairing");
  const result = await request<RunState>("runs.controlChat", { ...params, ...(options.profile ? { profile: options.profile } : {}) });
  if (result.id !== run.id) throw new Error("조회한 작업 그룹이 요청 대상과 다릅니다.");
  onRun(result);
  return result;
}
