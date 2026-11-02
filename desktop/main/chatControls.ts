import { randomUUID } from "node:crypto";
import type { RpcMethod, RpcParams } from "../shared/rpc";
import type { ChatControlView } from "../shared/chatControls";

interface Operation { phase: string; status: string; error: string }
interface Advance { operation: Operation; next_action: "stop" | "repair" | "verify" | "decide" | "act" | "none"; params: RpcParams }
interface Bridge { request<T>(method: RpcMethod, params: RpcParams): Promise<T> }
interface Request { view: ChatControlView; digest: string; promise?: Promise<unknown> }

/** Keeps an accepted command alive across renderer navigation/reload, never across app restarts. */
export class ChatControls {
  private readonly sessionId = randomUUID();
  private readonly items = new Map<string, Request>();
  private readonly listeners = new Set<() => void>();
  constructor(private readonly bridge: Bridge, private readonly wait = () => new Promise<void>(resolve => setTimeout(resolve, 500)),
    private readonly planning: Bridge = bridge) {}

  snapshot(): ChatControlView[] { return [...this.items.values()].map(item => ({ ...item.view })); }
  onFinished(listener: () => void): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener); }

  start(params: RpcParams): Promise<unknown> {
    const requestId = String(params.requestId || ""), key = JSON.stringify([params.projectName, params.runId, requestId]);
    const digest = JSON.stringify(params), existing = this.items.get(key);
    if (existing) {
      if (existing.digest !== digest) return Promise.reject(new Error("같은 요청 ID를 다른 명령에 사용할 수 없습니다."));
      return existing.promise!;
    }
    const item: Request = { digest, view: { projectName: String(params.projectName || ""), runId: String(params.runId || ""),
      requestId, intent: String(params.intent || ""), phase: "accepted", status: "running", error: "", startedAt: Date.now() } };
    this.items.set(key, item);
    item.promise = this.drive(params, item).finally(() => { for (const listener of this.listeners) listener(); });
    for (const [oldKey, old] of this.items) if (this.items.size > 40 && old.view.status !== "running") this.items.delete(oldKey);
    return item.promise;
  }

  private async drive(params: RpcParams, item: Request): Promise<unknown> {
    const scope = { projectName: item.view.projectName, runId: item.view.runId, requestId: item.view.requestId };
    try {
      await this.bridge.request("runs.requestChatControl", { ...params, sessionId: this.sessionId });
      while (true) {
        const next = await this.bridge.request<Advance>("runs.advanceChatControl", scope);
        item.view.phase = next.operation.phase; item.view.status = next.operation.status; item.view.error = next.operation.error;
        if (next.operation.status !== "running") {
          if (next.operation.status === "failed") throw new Error(next.operation.error || "복구를 진행하지 못했습니다.");
          return this.bridge.request("runs.get", { projectName: scope.projectName, runId: scope.runId });
        }
        if (next.next_action !== "none") {
          item.view.phase = next.next_action === "stop" ? "stopping" : next.next_action === "repair" ? "repairing" : "verifying";
          const methods: Record<Exclude<Advance["next_action"], "none">, RpcMethod> = {
            stop: "runs.requestStop", repair: "tasks.repairFromChat", verify: "runs.verifyAndRepair",
            decide: "runs.decideProjectChat", act: "runs.performProjectChat",
          };
          const target = next.next_action === "decide" ? this.planning : this.bridge;
          item.view.phase = next.next_action === "decide" ? "deciding" : next.next_action === "act" ? "acting" : item.view.phase;
          await target.request(methods[next.next_action], { projectName: scope.projectName, runId: scope.runId, ...next.params });
        } else await this.wait();
      }
    } catch (error) {
      item.view.error = error instanceof Error ? error.message : String(error);
      try {
        const final = await this.bridge.request<Advance>("runs.advanceChatControl", { ...scope, suspend: true });
        item.view.phase = final.operation.phase; item.view.status = final.operation.status;
      } catch { item.view.phase = "confirmation_required"; item.view.status = "partial"; }
      throw error;
    }
  }
}
