import type { DesktopApi } from "../../shared/rpc";
import type { RunState } from "./types";
import { activeTechStackDecision } from "./techStackDecision";
import { greenfieldRetry } from "./greenfieldFlow";

interface GreenfieldActionContext {
  projectName: string;
  run: RunState;
  request: DesktopApi["request"];
  requestId: string;
  profile: Record<string, unknown>;
  onUpdate(run: RunState): void;
}

export async function requestGreenfieldPlan(context: GreenfieldActionContext, answer = ""): Promise<RunState> {
  const { run, projectName, request, onUpdate } = context;
  const retry = greenfieldRetry(run);
  const sameAnswer = retry && (retry.answer_message || "") === answer.trim();
  const updated = await request<RunState>("runs.applyPlanningConversation", {
    projectName, runId: run.id,
    requestId: sameAnswer ? retry.request_id : context.requestId,
    expectedRevision: sameAnswer ? retry.plan_revision : run.plan_revision,
    conversationRevision: sameAnswer ? retry.conversation_revision : run.planning_conversation_revision,
    expectedTechStackRevision: activeTechStackDecision(run.tech_stack_decisions)?.revision || 0,
    answer: answer.trim(), retryFailed: Boolean(sameAnswer), ...context.profile,
  });
  onUpdate(updated);
  return updated;
}

export async function confirmGreenfieldOption(context: GreenfieldActionContext, optionId: string, revision: number): Promise<RunState> {
  const confirmed = await context.request<RunState>("runs.confirmTechStack", {
    projectName: context.projectName, runId: context.run.id, optionId, expectedRevision: revision,
  });
  context.onUpdate(confirmed);
  if (confirmed.bootstrap_spec || confirmed.tasks.length) return confirmed;
  return requestGreenfieldPlan({ ...context, run: confirmed });
}

export async function confirmGreenfieldExecution(context: GreenfieldActionContext): Promise<RunState> {
  const { run, projectName, request } = context;
  if (run.repository_intent !== "new_project" || !["bootstrap_ready", "feature_plan_ready"].includes(run.greenfield_phase || "")) {
    throw new Error("현재 단계의 계획과 검증 결과를 다시 확인해 주세요.");
  }
  if (run.stage !== "planned" || !run.tasks.length) throw new Error("실행 전 계획을 확인해 주세요.");
  if (run.greenfield_phase === "bootstrap_ready" && !run.bootstrap_spec?.digest) throw new Error("검토할 기본 구조 계획이 없습니다.");
  if (run.greenfield_phase === "feature_plan_ready" && !run.bootstrap_spec?.verified_integration_head) throw new Error("기본 구조 검증 결과를 먼저 확인해 주세요.");
  const confirmed = await request<RunState>("runs.confirmPlan", {
    projectName, runId: run.id, expectedRevision: run.plan_revision,
    ...(run.greenfield_phase === "bootstrap_ready" ? { bootstrapDigest: run.bootstrap_spec?.digest } : {}),
  });
  context.onUpdate(confirmed);
  return confirmed;
}
