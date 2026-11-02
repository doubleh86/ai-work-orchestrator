import type { DesktopApi } from "../../shared/rpc";
import type { RunLockStatus, RunState } from "./types";

export interface RunLockRecoverySnapshot {
  phase: "loading" | "ready" | "acting" | "error";
  run?: RunState;
  lock?: RunLockStatus;
  message: string;
  error: string;
}

export interface RunLockAction {
  kind: "clear" | "stop" | "inspect" | "refresh";
  label: string;
  status: string;
}

export function runLockAction(run: RunState, lock: RunLockStatus): RunLockAction | undefined {
  if (run.id !== lock.run_id) return { kind: "refresh", label: "다시 확인", status: "잠금 대상 확인 필요" };
  const merge = run.main_operations?.merge;
  if (["main_apply_interrupted", "main_apply_recoverable"].includes(run.integration_control?.reason_code || "")
    || merge?.phase === "applying_main" && merge.status === "running" && lock.state !== "active") {
    return { kind: "inspect", label: "원본 상태 확인", status: "원본 반영 중단" };
  }
  if (lock.state === "unlocked") return undefined;
  if (["planning-chat", "planning-preview", "effort-policy"].includes(lock.operation)) {
    return { kind: "refresh", label: "다시 확인", status: "기획·정책 잠금 확인 필요" };
  }
  if (lock.state === "stale" && lock.operation) return { kind: "clear", label: "잠금 해제", status: "중단된 작업의 잠금이 남아 있습니다" };
  if (lock.state === "active") {
    const control = run.execution_control;
    if (control?.can_stop && control.execution_id && ["running", "preparing"].includes(control.situation)
      && (!control.active_task_id || run.tasks.some((task) => task.id === control.active_task_id))
      && control.stop_phase !== "stopping") return { kind: "stop", label: "작업 중지", status: "작업 진행 중" };
    return { kind: "refresh", label: "다시 확인", status: control?.stop_phase === "stopping" ? "중지 요청 중" : "다른 작업 진행 중" };
  }
  return { kind: "refresh", label: "다시 확인", status: lock.state === "malformed" ? "잠금 정보 오류" : "잠금 소유자 확인 필요" };
}

/** One opened project/group. Reads and explicit approved actions never resume a run. */
export class RunLockRecoverySession {
  private active = true;
  private pending = false;
  private version = 0;
  private snapshot: RunLockRecoverySnapshot = { phase: "loading", message: "", error: "" };

  constructor(private readonly api: Pick<DesktopApi, "request" | "approve">,
    private readonly projectName: string, private readonly runId: string,
    private readonly publish: (snapshot: RunLockRecoverySnapshot) => void) {}

  dispose(): void { this.active = false; this.version++; }

  private update(snapshot: RunLockRecoverySnapshot): void {
    if (!this.active) return;
    this.snapshot = snapshot;
    this.publish(snapshot);
  }

  private async read(version: number): Promise<{ run: RunState; lock: RunLockStatus } | undefined> {
    const current = () => this.active && version === this.version;
    const params = { projectName: this.projectName, runId: this.runId };
    for (let attempt = 0; attempt < 2 && current(); attempt++) {
      const before = await this.api.request<RunState>("runs.get", params);
      if (!current()) return;
      const lock = await this.api.request<RunLockStatus>("locks.get", params);
      if (!current()) return;
      const run = await this.api.request<RunState>("runs.get", params);
      if (!current()) return;
      if (before.id !== this.runId || run.id !== this.runId || lock.run_id !== this.runId) {
        throw new Error("조회한 잠금의 작업 그룹이 일치하지 않습니다.");
      }
      if (before.updated_at === run.updated_at && JSON.stringify(before.main_operations) === JSON.stringify(run.main_operations)
        && run.execution_control?.lock_state === lock.state
        && (lock.state === "unlocked" || run.execution_control?.operation === lock.operation)) return { run, lock };
    }
    if (current()) throw new Error("조회 중 잠금 상태가 바뀌었습니다. 다시 확인해 주세요.");
  }

  async check(): Promise<RunState | undefined> {
    if (!this.active || this.pending || this.snapshot.phase === "acting") return;
    this.pending = true;
    const version = ++this.version;
    this.update({ ...this.snapshot, phase: "loading" });
    try {
      const result = await this.read(version);
      if (!result) return;
      this.update({ phase: "ready", ...result, message: "", error: "" });
      return result.run;
    } catch (cause) {
      if (this.active && version === this.version) this.update({ ...this.snapshot, phase: "error", message: "", error: String(cause) });
    } finally { this.pending = false; }
  }

  async act(kind: "clear" | "stop"): Promise<RunState | undefined> {
    if (!this.active || this.pending || this.snapshot.phase !== "ready" || !this.snapshot.run || !this.snapshot.lock
      || runLockAction(this.snapshot.run, this.snapshot.lock)?.kind !== kind) return;
    this.pending = true;
    const expected = this.snapshot;
    const version = ++this.version;
    const current = () => this.active && version === this.version;
    this.update({ ...this.snapshot, phase: "acting", message: "", error: "" });
    let message = "";
    let failure = "";
    try {
      const latest = await this.read(version);
      if (!latest || !current()) return;
      if (runLockAction(latest.run, latest.lock)?.kind !== kind || JSON.stringify(expected.lock) !== JSON.stringify(latest.lock)
        || expected.run?.updated_at !== latest.run.updated_at) {
        this.update({ phase: "ready", ...latest, message: "상태가 바뀌어 요청하지 않았습니다", error: "" });
        return latest.run;
      }
      const params = { projectName: this.projectName, runId: this.runId };
      if (kind === "clear") {
        const cleared = await this.api.approve<RunLockStatus>("locks.clear", params);
        if (!current()) return;
        if (cleared === null) message = "잠금 해제를 취소했습니다";
        else if (cleared.run_id !== this.runId || cleared.state !== "unlocked") throw new Error("잠금 해제 결과를 확인하지 못했습니다.");
        else message = "잠금 해제 응답을 받았습니다";
      } else {
        const control = latest.run.execution_control!;
        const task = latest.run.tasks.find((item) => item.id === control.active_task_id);
        const receipt = await this.api.request<{ phase: string }>("runs.requestStop", { ...params,
          requestId: crypto.randomUUID(), executionId: control.execution_id, scope: task ? "task" : "verification",
          ...(task ? { taskId: task.id, attemptId: task.last_attempt_id || "", invocationId: task.active_invocation_id || "" }
            : { attemptId: control.active_attempt_id, invocationId: control.active_invocation_id }) });
        if (!current()) return;
        message = receipt.phase === "stopped" ? "작업 중지를 확인했습니다" : "중지를 요청했습니다";
      }
    } catch (cause) {
      failure = String(cause);
      message = kind === "clear" ? "잠금 해제 실패" : "중지 요청 실패";
    } finally { this.pending = false; }
    if (!current()) return;
    try {
      const result = await this.read(version);
      if (!result || !current()) return;
      if (kind === "clear" && !failure && message === "잠금 해제 응답을 받았습니다" && result.lock.state === "unlocked") message = "잠금 해제됨";
      this.update({ phase: "ready", ...result, message, error: failure });
      return result.run;
    } catch (cause) {
      if (current()) this.update({ phase: "error", message, error: [failure, String(cause)].filter(Boolean).join("\n") });
    }
  }
}
