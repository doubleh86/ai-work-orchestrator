export type ChatExecutionIntent = "stop" | "repair" | "stop_repair" | "project";

export interface ChatControlRun {
  project_chat_available?: boolean;
  id: string;
  plan_revision: number;
  planning_conversation_revision?: number;
  archive?: object | null;
  tasks: { id: string; status: string; active_action?: string | null; last_attempt_id?: string; active_invocation_id?: string }[];
  execution_control?: { can_stop: boolean; stop_scope: string; execution_id: string; active_attempt_id: string; active_invocation_id: string };
}

export function chatControlParams(projectName: string, run: ChatControlRun, message: string, requestId: string,
  intent: ChatExecutionIntent, taskId?: string) {
  const control = run.execution_control;
  const active = run.tasks.filter(task => task.active_action || ["running", "reviewing", "revising"].includes(task.status));
  const failures = run.tasks.filter(task => ["failed", "stopped"].includes(task.status));
  const candidates = active.length ? active : failures;
  const target = taskId ? run.tasks.find(task => task.id === taskId) : intent !== "project" && candidates.length === 1 ? candidates[0] : undefined;
  if (taskId && !target) throw new Error("요청한 작업을 찾지 못했습니다.");
  if (intent !== "project" && control?.stop_scope === "task" && control.can_stop && !target) throw new Error("중지할 작업을 하나로 특정하지 못했습니다.");
  return { projectName, runId: run.id, requestId, message, intent,
    expected: { planRevision: run.plan_revision, conversationRevision: run.planning_conversation_revision || 0,
      executionId: control?.execution_id || "", scope: control?.stop_scope || "", taskId: target?.id || "",
      attemptId: target?.last_attempt_id || control?.active_attempt_id || "",
      invocationId: target?.active_invocation_id || control?.active_invocation_id || "" } };
}

// Require an explicit request, not a status question or a quoted suggestion.
export function chatExecutionIntent(message: string, run?: ChatControlRun): ChatExecutionIntent | undefined {
  const direct = explicitChatExecutionIntent(message);
  if (run && !run.archive && run.tasks?.length === 0) return direct === "stop" && run.execution_control?.can_stop ? "stop" : undefined;
  if (run?.project_chat_available && !run.archive && run.tasks.length) return direct === "stop" ? "stop" : "project";
  return direct;
}

function explicitChatExecutionIntent(message: string): ChatExecutionIntent | undefined {
  const text = message.trim().replace(/[.!。！]+$/u, "").replace(/\s+/gu, " ");
  if (/Task\s*(?:수정|변경)|(?:계획|완료\s*조건|검증\s*명령|범위)(?:을|를)?\s*(?:수정|변경)/iu.test(text)) return;
  if (/(?:하면|되면|나면)|나중에|내일|모레|다음에|이따/u.test(text)) return;
  if (!text || text.length > 1800 || /["“”‘’`]|(?:라고|라는|방법|어떻게|왜|가능|할 수|줄 수)|(?:하지|추지|치지|리지)\s*(?:마|말)|하지 않|말고|생략|삭제|건너뛰|무시|(?:merge|push|deploy|reset)\b|배포|병합|푸시/iu.test(text)) return;
  const politeRequest = /(?:해\s*줄래(?:요)?|해\s*주실래요|해\s*주시겠어요)[?？]?$/u.test(text);
  if (!politeRequest && /[?？]|(?:나요|까요|할까|되나|니|냐|같아|같아요)$/u.test(text)) return;
  const request = politeRequest || /(?:해\s*(?:줘|주세요)|해|줘|주세요|하자|멈춰|멈추자|부탁(?:해|해요|드립니다)|진행|시작|중지|중단|복구|재시도|재실행)$/u.test(text);
  if (!request) return;
  const command = text.replace(/(중지|중단|복구|수정|재시도|재실행)(?:을|를)\s*/gu, "$1");
  const stop = /멈(?:춰|추(?:고|자|세요))|(?:중지|중단)(?:\s*해|하(?:고|자)|\s*(?:후|부탁))|(?:중지|중단)$/u.test(command);
  const repair = /고쳐|고치(?:고|자)|(?:복구|수정|재시도|재실행)(?:\s*해|하(?:고|자|여)|\s*(?:후|부탁)|\s*(?:진행|시작)(?:해|하(?:고|자)|$))|(?:복구|재시도|재실행)$|문제(?:를)?\s*해결(?:해|하(?:고|자)|$)/u.test(command);
  return stop ? repair ? "stop_repair" : "stop" : repair ? "repair" : undefined;
}
