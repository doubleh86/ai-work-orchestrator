import { randomUUID } from "node:crypto";
import type { RpcMethod, RpcParams } from "../shared/rpc";
import type { PlanningRequestKind, PlanningRequestOwner, PlanningRequestsSnapshot } from "../shared/planningRequests";
import { PLANNING_REQUEST_METHODS } from "../shared/planningRequests";

export const PLANNING_OWNER_METHODS = new Set<RpcMethod>(PLANNING_REQUEST_METHODS);
interface Bridge {
  request<T>(method: RpcMethod, params: RpcParams): Promise<T>;
  restartPlanning(): Promise<void>;
}
interface OwnedRequest {
  owner: PlanningRequestOwner; settled: boolean; registered: Promise<void>; registrationSaved: boolean; generation: number;
  interruption?: { promise: Promise<void>; resolve(): void; reject(error: unknown): void };
  completion?: "succeeded" | "failed";
}

/** One Planning bridge slot, independent of renderer selection and lifetime. */
export class PlanningRequests {
  private active?: OwnedRequest;
  private recent: PlanningRequestOwner[] = [];
  private generation = 0;
  private readonly listeners = new Set<(owner: PlanningRequestOwner) => void>();
  constructor(private readonly bridge: Bridge) {}

  onFinished(listener: (owner: PlanningRequestOwner) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  snapshot(): PlanningRequestsSnapshot {
    return { active: this.active ? { ...this.active.owner } : undefined, recent: this.recent.map(item => ({ ...item })) };
  }

  async request<T>(method: RpcMethod, params: RpcParams): Promise<T> {
    if (!PLANNING_OWNER_METHODS.has(method)) return this.bridge.request<T>(method, params);
    if (this.active) throw new Error(`planning_capacity_busy: 다른 대화에서 AI가 응답 중입니다 · ${this.active.owner.projectName}`);
    const owner: PlanningRequestOwner = {
      projectName: String(params.projectName || ""), runId: String(params.runId || ""),
      requestId: method !== "runs.decideProjectChat" && typeof params.requestId === "string" ? params.requestId : randomUUID(),
      kind: method === "runs.sendPlanningMessage" || method === "runs.decideProjectChat" ? "chat" : method === "runs.runPlanning" || method === "runs.start" ? "plan" : "replan",
      method, phase: "accepted", startedAt: Date.now(), error: "",
    };
    const current: OwnedRequest = { owner, settled: false, registered: Promise.resolve(), registrationSaved: false, generation: this.generation };
    this.active = current;
    try {
      if (owner.runId) {
        current.registered = this.bridge.request<{ kind: PlanningRequestKind }>("runs.beginPlanningRequest", {
          projectName: owner.projectName, runId: owner.runId, requestId: owner.requestId, kind: owner.kind,
          message: method === "runs.sendPlanningMessage" ? params.message : "",
        }).then(result => { owner.kind = result.kind; current.registrationSaved = true; });
        await current.registered;
      }
      if (owner.phase === "stopping") throw new Error("기획 요청을 중단했습니다.");
      owner.phase = "running";
      const result = await this.bridge.request<T>(method, params);
      current.settled = true;
      current.completion = "succeeded";
      if (!this.isStopping(current)) {
        current.completion = "failed";
        await this.finish(current, "succeeded");
      }
      return result;
    } catch (error) {
      current.settled = true;
      if (current.owner.phase === "confirmation_required") throw error;
      if (current.interruption && (this.isStopping(current) || current.owner.phase === "interrupted")) {
        await current.interruption.promise;
        if (method !== "runs.sendPlanningMessage") throw new Error("request_interrupted: 사용자가 AI 요청을 중단했습니다.");
        return this.bridge.request<T>("runs.get", { projectName: owner.projectName, runId: owner.runId });
      }
      if (!this.isStopping(current)) {
        owner.error = error instanceof Error ? error.message : String(error);
        await this.finish(current, "failed");
      }
      throw error;
    }
  }

  private isStopping(current: OwnedRequest): boolean { return current.owner.phase === "stopping"; }

  async interrupt<T>(projectName: string, runId: string, requestId: string): Promise<T | null> {
    const current = this.active;
    if (!requestId) throw new Error("request_target_required: 중단할 요청 ID가 필요합니다.");
    if (!current || current.owner.projectName !== projectName || current.owner.runId !== runId || current.owner.requestId !== requestId) {
      if (this.recent.some(item => item.projectName === projectName && item.runId === runId && item.requestId === requestId
        && ["succeeded", "interrupted"].includes(item.phase))) return null;
      throw new Error("target_changed: 중단할 대화 요청이 일치하지 않습니다.");
    }
    if (current.owner.phase === "stopping") throw new Error("중단 완료를 확인하고 있습니다.");
    let resolve!: () => void, reject!: (error: unknown) => void;
    const promise = new Promise<void>((done, fail) => { resolve = done; reject = fail; });
    void promise.catch(() => {});
    current.interruption = { promise, resolve, reject };
    current.owner.phase = "stopping";
    try {
      await current.registered;
      if (this.active !== current || current.generation !== this.generation) throw new Error("target_changed: 대화 요청이 변경됐습니다.");
      if (current.settled) { await this.finish(current, current.completion || "interrupted"); resolve(); return null; }
      await this.bridge.restartPlanning();
      this.generation++;
      await this.finish(current, "interrupted");
      resolve();
      return current.owner.runId ? this.bridge.request<T>("runs.get", { projectName, runId }) : null;
    } catch (error) {
      current.owner.phase = "confirmation_required";
      current.owner.error = error instanceof Error ? error.message : String(error);
      reject(error);
      throw error;
    }
  }

  private async finish(current: OwnedRequest, phase: "succeeded" | "failed" | "interrupted"): Promise<void> {
    try {
      if (current.registrationSaved) await this.bridge.request("runs.finishPlanningRequest", {
        projectName: current.owner.projectName, runId: current.owner.runId, requestId: current.owner.requestId,
        phase, error: current.owner.error,
      });
    } catch (error) {
      current.owner.phase = "confirmation_required";
      current.owner.error = error instanceof Error ? error.message : String(error);
      throw error;
    }
    current.owner.phase = phase;
    if (this.active === current) this.active = undefined;
    this.recent = [...this.recent.filter(item => item.requestId !== current.owner.requestId), { ...current.owner }].slice(-30);
    for (const listener of this.listeners) listener({ ...current.owner });
  }
}
