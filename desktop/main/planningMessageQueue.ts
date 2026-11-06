import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { RpcMethod, RpcParams } from "../shared/rpc";
import type { PlanningRequestOwner } from "../shared/planningRequests";
import { planningRequestFor } from "../shared/planningRequests";
import type { PlanningMessageQueueSnapshot, QueuedMessageChange, QueuedMessageInput, QueuedPlanningMessage } from "../shared/planningMessageQueue";
import { chatControlParams, chatExecutionIntent, type ChatControlRun } from "../shared/chatExecution";
import type { PlanningRequests } from "./planningRequests";
import type { ChatControls } from "./chatControls";

interface Bridge { request<T>(method: RpcMethod, params: RpcParams): Promise<T> }
const MAX_MESSAGES = 100;
const MAX_TEXT = 64 * 1024;
const sameConversation = (a: QueuedMessageInput, b: { projectName: string; runId: string }) =>
  a.projectName === b.projectName && a.runId === b.runId;

function validInput(value: unknown): value is QueuedMessageInput {
  if (!value || typeof value !== "object") return false;
  const input = value as Partial<QueuedMessageInput>;
  return [input.id, input.projectName, input.runId, input.text, input.message].every(field =>
    typeof field === "string" && field.trim().length > 0 && field.length <= MAX_TEXT)
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(input.id || "")
    && (input.taskId === undefined || typeof input.taskId === "string")
    && (input.afterRequestId === undefined || typeof input.afterRequestId === "string")
    && (input.executionMode === undefined || input.executionMode === "project" && Boolean(input.controlTarget))
    && (input.controlTarget === undefined || Boolean(input.controlTarget && Number.isSafeInteger(input.controlTarget.planRevision)
      && [input.controlTarget.executionId, input.controlTarget.scope, input.controlTarget.taskId, input.controlTarget.attemptId, input.controlTarget.invocationId]
        .every(field => typeof field === "string" && field.length <= 500)))
    && Boolean(input.profile && [input.profile.planningAgentId, input.profile.planningModel, input.profile.planningReasoningEffort]
      .every(field => typeof field === "string" && field.length <= 500));
}

function copyInput(input: QueuedMessageInput): QueuedMessageInput {
  return { id: input.id, projectName: input.projectName, runId: input.runId, text: input.text, message: input.message,
    ...(input.executionMode === "project" ? { executionMode: "project" as const } : {}),
    ...(input.taskId ? { taskId: input.taskId } : {}), ...(input.afterRequestId ? { afterRequestId: input.afterRequestId } : {}),
    ...(input.controlTarget ? { controlTarget: { planRevision: input.controlTarget.planRevision, executionId: input.controlTarget.executionId,
      scope: input.controlTarget.scope, taskId: input.controlTarget.taskId, attemptId: input.controlTarget.attemptId,
      invocationId: input.controlTarget.invocationId } } : {}),
    profile: { planningAgentId: input.profile.planningAgentId, planningModel: input.profile.planningModel,
      planningReasoningEffort: input.profile.planningReasoningEffort } };
}

function validStored(value: unknown): value is QueuedPlanningMessage {
  if (!validInput(value)) return false;
  const item = value as Partial<QueuedPlanningMessage>;
  return ["queued", "paused", "sending", "sent", "failed", "uncertain"].includes(item.status || "")
    && Number.isSafeInteger(item.revision) && (item.revision || 0) > 0 && Number.isFinite(item.createdAt)
    && typeof item.error === "string" && typeof item.waitForRequestId === "string";
}

/** A local outbox. Only existing Python APIs decide whether a queued request may execute. */
export class PlanningMessageQueue {
  private items: QueuedPlanningMessage[] = [];
  private error = "";
  private writable = true;
  private timer?: ReturnType<typeof setTimeout>;
  private readonly unsubscribe: () => void;
  private readonly unsubscribeControl: () => void;
  private closed = false;

  constructor(private readonly path: string, private readonly owners: PlanningRequests,
    private readonly bridge: Bridge, private readonly controls: ChatControls) {
    try {
      if (existsSync(path)) {
        const data: unknown = JSON.parse(readFileSync(path, "utf8"));
        if (!data || typeof data !== "object" || !("version" in data) || data.version !== 1
          || !("items" in data) || !Array.isArray(data.items) || data.items.length > MAX_MESSAGES
          || !data.items.every(validStored)
          || new Set(data.items.map(item => item.id)).size !== data.items.length) throw new Error("예약 메시지 파일 형식을 확인할 수 없습니다.");
        this.items = data.items.map((item: QueuedPlanningMessage) => ({ ...copyInput(item), createdAt: item.createdAt,
          status: item.status === "sending" ? "uncertain" : item.status === "queued" ? "paused" : item.status,
          error: item.status === "sending" ? "앱 종료 전 전송 결과를 확인해 주세요. 자동으로 다시 보내지 않습니다."
            : item.status === "queued" ? "앱이 다시 시작되어 예약이 일시 정지되었습니다." : item.error,
          waitForRequestId: "", revision: item.revision + 1 }));
      }
    } catch (error) {
      this.writable = false;
      this.error = `예약 목록을 읽지 못했습니다. ${error instanceof Error ? error.message : String(error)}`;
    }
    this.unsubscribe = owners.onFinished(owner => this.finished(owner));
    this.unsubscribeControl = controls.onFinished(() => this.kick());
  }

  snapshot(): PlanningMessageQueueSnapshot {
    return { items: this.items.map(item => ({ ...item, ...copyInput(item) })), error: this.error };
  }

  enqueue(input: QueuedMessageInput): PlanningMessageQueueSnapshot {
    if (!validInput(input)) throw new Error("예약할 대화·메시지·AI 설정을 확인해 주세요.");
    input = copyInput(input);
    const existing = this.items.find(item => item.id === input.id);
    if (existing) {
      if (!sameConversation(existing, input) || existing.text !== input.text || existing.message !== input.message
        || existing.taskId !== input.taskId || existing.executionMode !== input.executionMode || JSON.stringify(existing.controlTarget) !== JSON.stringify(input.controlTarget)
        || JSON.stringify(existing.profile) !== JSON.stringify(input.profile))
        throw new Error("동일한 예약 ID에 다른 메시지를 등록할 수 없습니다.");
      return this.snapshot();
    }
    const items = this.items.filter(item => item.status !== "sent").concat(this.items.filter(item => item.status === "sent").slice(-20));
    if (items.length >= MAX_MESSAGES) throw new Error("예약 메시지가 너무 많습니다. 기존 예약을 정리해 주세요.");
    const owner = this.owners.snapshot();
    const active = planningRequestFor(owner, input.projectName, input.runId);
    const previous = input.afterRequestId ? owner.recent.find(item => item.requestId === input.afterRequestId) : undefined;
    const priorUnknown = Boolean(input.afterRequestId && active?.requestId !== input.afterRequestId && !previous);
    const blocked = priorUnknown || active?.phase === "confirmation_required" || previous && sameConversation(input, previous) && previous.phase !== "succeeded"
      || items.some(item => sameConversation(item, input) && ["paused", "failed", "uncertain"].includes(item.status));
    this.commit([...items, { ...input, status: blocked ? "paused" : "queued", createdAt: Date.now(), revision: 1,
      error: blocked ? "앞선 답변이나 예약 상태를 확인한 뒤 다시 예약해 주세요." : "", waitForRequestId: owner.active?.requestId || "" }]);
    this.kick();
    return this.snapshot();
  }

  change(change: QueuedMessageChange): PlanningMessageQueueSnapshot {
    if (!change || typeof change !== "object") throw new Error("예약 변경 내용을 확인해 주세요.");
    const item = this.items.find(candidate => candidate.id === change.id && sameConversation(candidate, change));
    if (!item || item.revision !== change.revision) throw new Error("예약이 변경됐습니다. 최신 목록을 확인해 주세요.");
    if (["sending", "sent"].includes(item.status)) throw new Error("이미 전송을 시작했습니다. 답변 중단을 사용해 주세요.");
    let next: QueuedPlanningMessage | undefined;
    if (change.action === "resume") {
      if (item.status === "uncertain") throw new Error("이전 전송 결과를 대화에서 확인해 주세요. 입력창으로 가져와 다시 보낼 수 있습니다.");
      next = { ...item, status: "queued", revision: item.revision + 1, error: "", waitForRequestId: planningRequestFor(this.owners.snapshot(), item.projectName, item.runId)?.requestId || "" };
    } else if (change.action !== "cancel") throw new Error("지원하지 않는 예약 변경입니다.");
    this.commit(this.items.flatMap(candidate => candidate.id === item.id ? next ? [next] : [] : [candidate]));
    this.kick();
    return this.snapshot();
  }

  close(): void { this.closed = true; this.unsubscribe(); this.unsubscribeControl(); if (this.timer) clearTimeout(this.timer); }

  private commit(items: QueuedPlanningMessage[]): void {
    if (!this.writable) throw new Error(this.error || "예약 저장소를 사용할 수 없습니다.");
    const temporary = `${this.path}.${randomUUID()}.tmp`;
    try {
      mkdirSync(dirname(this.path), { recursive: true });
      writeFileSync(temporary, JSON.stringify({ version: 1, items }), { encoding: "utf8", mode: 0o600 });
      renameSync(temporary, this.path);
    } finally { if (existsSync(temporary)) unlinkSync(temporary); }
    this.items = items;
    this.error = "";
  }

  private update(id: string, values: Partial<QueuedPlanningMessage>): void {
    this.commit(this.items.map(item => item.id === id ? { ...item, ...values, revision: item.revision + 1 } : item));
  }

  private finished(owner: PlanningRequestOwner): void {
    if (!this.items.some(item => item.status === "queued" && item.waitForRequestId === owner.requestId)) { this.kick(); return; }
    try {
      this.commit(this.items.map(item => item.status !== "queued" || item.waitForRequestId !== owner.requestId ? item : {
        ...item, revision: item.revision + 1, waitForRequestId: "",
        status: owner.phase !== "succeeded" && sameConversation(item, owner) ? "paused" : "queued",
        error: owner.phase !== "succeeded" && sameConversation(item, owner) ? "앞선 답변이 실패하거나 중단되어 예약을 일시 정지했습니다." : "",
      }));
    } catch (error) { this.error = `예약 상태를 저장하지 못했습니다. ${error instanceof Error ? error.message : String(error)}`; }
    this.kick();
  }

  private kick(): void {
    if (this.closed || this.timer || this.error) return;
    this.timer = setTimeout(() => { this.timer = undefined; void this.drain(); }, 0);
  }

  private async drain(): Promise<void> {
    if (this.closed || this.error) return;
    const item = this.items.find((candidate, index) => candidate.status === "queued"
      && !planningRequestFor(this.owners.snapshot(), candidate.projectName, candidate.runId)
      && !this.controls.snapshot().some(control => sameConversation(candidate, control) && control.status === "running")
      && !this.items.slice(0, index).some(earlier => sameConversation(earlier, candidate) && ["paused", "failed", "uncertain", "sending"].includes(earlier.status)));
    if (!item) return;
    let dispatched = false;
    try {
      // Persist the claim before any asynchronous work; edits and cancellation now reject.
      this.update(item.id, { status: "sending", error: "" });
      this.kick();
      const run = await this.bridge.request<ChatControlRun>("runs.get", { projectName: item.projectName, runId: item.runId });
      if (this.closed) { this.update(item.id, { status: "paused", error: "앱 종료로 예약을 일시 정지했습니다." }); return; }
      if (run.id !== item.runId) throw new Error("예약한 작업 그룹과 조회 결과가 일치하지 않습니다.");
      if (item.executionMode === "project" && (!run.project_chat_available || run.archive))
        throw new Error("예약한 프로젝트의 AI 실행 기능을 현재 사용할 수 없습니다. 입력창으로 가져와 확인해 주세요.");
      const intent = chatExecutionIntent(item.text, item.executionMode === "project" || !run.tasks.length ? run : undefined);
      const latestOwner = planningRequestFor(this.owners.snapshot(), item.projectName, item.runId);
      if (latestOwner) { this.update(item.id, { status: "queued", waitForRequestId: latestOwner.requestId }); return; }
      if (this.controls.snapshot().some(control => sameConversation(item, control) && control.status === "running")) {
        this.update(item.id, { status: "queued", waitForRequestId: "" }); return;
      }
      if (intent && !run.archive) {
        const params = chatControlParams(item.projectName, run, item.text, item.id, intent, item.taskId);
        const target = item.controlTarget;
        const targetKeys = intent === "project" ? ["planRevision", "taskId"] as const : Object.keys(target || {}) as (keyof typeof target)[];
        if (!target || targetKeys.some(key => target[key] !== params.expected[key]))
          throw new Error("예약한 실행 대상이 변경되었습니다. 입력창으로 가져와 현재 작업을 다시 확인해 주세요.");
        dispatched = true;
        await this.controls.start({ ...params, profile: item.profile });
      } else {
        dispatched = true;
        await this.owners.request("runs.sendPlanningMessage", { projectName: item.projectName, runId: item.runId,
          requestId: item.id, message: item.message, ...item.profile });
        const receipt = this.owners.snapshot().recent.find(owner => owner.requestId === item.id);
        if (receipt?.phase !== "succeeded") throw new Error("예약 메시지의 답변이 중단되었습니다. 대화에서 결과를 확인해 주세요.");
      }
      this.update(item.id, { status: "sent", error: "" });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      try {
        this.commit(this.items.map(candidate => candidate.id === item.id ? { ...candidate, revision: candidate.revision + 1,
          status: dispatched ? "uncertain" : "failed", error: message } : candidate.status === "queued" && sameConversation(candidate, item)
            ? { ...candidate, revision: candidate.revision + 1, status: "paused", error: "앞선 예약 메시지를 먼저 확인해 주세요." } : candidate));
      } catch (saveError) { this.error = `전송 상태를 저장하지 못했습니다. ${saveError instanceof Error ? saveError.message : String(saveError)}`; }
    } finally { this.kick(); }
  }
}
