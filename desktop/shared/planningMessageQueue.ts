export interface QueuedMessageInput {
  id: string;
  projectName: string;
  runId: string;
  text: string;
  message: string;
  taskId?: string;
  afterRequestId?: string;
  controlTarget?: Omit<ReturnType<typeof import("./chatExecution").chatControlParams>["expected"], "conversationRevision">;
  executionMode?: "project";
  profile: { planningAgentId: string; planningModel: string; planningReasoningEffort: string };
}
export interface QueuedPlanningMessage extends QueuedMessageInput {
  status: "queued" | "paused" | "sending" | "sent" | "failed" | "uncertain";
  createdAt: number;
  revision: number;
  error: string;
  waitForRequestId: string;
}
export interface QueuedMessageChange {
  projectName: string;
  runId: string;
  id: string;
  revision: number;
  action: "cancel" | "resume";
}
export interface PlanningMessageQueueSnapshot { items: QueuedPlanningMessage[]; error: string }
