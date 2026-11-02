import type { RunState, WorkTask } from "./types";
import type { DesktopApi, RpcParams } from "../../shared/rpc";
import { mainAlreadyApplied, mainCompletionLabel, operationsSnapshotMatches, verifiedResult, type OperationsSnapshot } from "./integrationCompletion";
import { activeConflictPhase } from "./recoveryTaskPresentation";

export type ApplySummaryAction = "work" | "verify" | "main" | "upload";
export type ApplySummaryMethod = "runs.verifyAndRepair" | "runs.push" | "runs.merge";
type OperationsResult = { run: RunState; snapshot: OperationsSnapshot };

export function sendApplySummaryCommand(api: Pick<DesktopApi, "request" | "approve">,
  method: ApplySummaryMethod, params: RpcParams): Promise<RunState | null> {
  return method === "runs.verifyAndRepair" ? api.request<RunState>(method, params) : api.approve<RunState>(method, params);
}

export function applySummaryTitle(run: RunState | undefined): string {
  return run?.archive ? "보관 기록" : "반영·마무리";
}

export function applySummaryStatus(run: RunState | undefined, snapshot: OperationsSnapshot | undefined,
  projectName: string, busyAction = ""): string {
  if (!run) return "작업 그룹을 선택하세요";
  if (run.archive) return run.archive.cleanup_status === "completed" ? "기록 보관 완료" : "기록 보관 완료 · 정리 확인 필요";
  const ready = operationsSnapshotMatches(snapshot, projectName, run);
  const lock = ready && (!snapshot?.lock?.run_id || snapshot.lock.run_id === run.id) ? snapshot?.lock : undefined;
  if (lock?.state === "active" && ["verify", "verify-and-repair"].includes(lock.operation)
    && (run.active_step === "verify" || run.verification_progress_phase === "repairing")) {
    return run.execution_control?.stop_scope === "verification" && run.execution_control.stop_phase === "stopping"
      ? "검증 중지 중" : run.verification_progress_phase === "repairing" ? "검증 실패 수정 중" : "결과 검사 중";
  }
  if (["runs.verify", "runs.verifyAndRepair"].includes(busyAction)) return "결과 검사 상태 확인 중";
  if (busyAction === "runs.merge" && lock?.state !== "active") return "메인 적용 상태 확인 중";
  if (busyAction === "runs.push") return run.workspace_mode === "shared" ? "작업 브랜치 반영 중" : "메인 변경 업로드 중";
  if (!ready) return snapshot?.status === "error" ? "상태 확인 필요" : "최신 상태 확인 중";
  const conflictPhase = activeConflictPhase(run, snapshot, projectName);
  if (conflictPhase) return conflictPhase === "prepare" ? "충돌 해결안 생성 중"
    : conflictPhase === "verify" ? "결과 검사 중" : "충돌 해결 처리 중";
  if (lock?.state === "active") {
    if (lock.operation === "push" && run.workspace_mode === "shared" && !mainAlreadyApplied(run)) return "작업 브랜치 반영 중";
    if (["verify", "verify-and-repair"].includes(lock.operation)) return "검증 실행 상태 확인 중";
    return mainCompletionLabel(run, snapshot?.workspaces || [], lock);
  }
  if (run.active_step === "verify") return "검증 중단 · 다시 검사 필요";
  if (run.stage === "failed" && run.failed_step === "verify") return "결과 검사 실패";
  if (mainAlreadyApplied(run) || ["main_apply_interrupted", "main_apply_recoverable"].includes(run.integration_control?.reason_code || "")) {
    return mainCompletionLabel(run, snapshot?.workspaces || [], lock);
  }
  if (!lock || lock.state !== "unlocked") return "잠금 상태 확인 필요";
  if (run.integration_conflict && !["applied", "stale"].includes(run.integration_conflict.resolution_status)) return "충돌 해결 필요";
  const action = applySummaryAction(run, snapshot, projectName);
  if (action === "main") return run.workspace_mode === "shared" && run.integration_control?.remote_configured
    ? "작업 브랜치 반영 완료" : "결과 검사 통과";
  if (action === "work" && run.stage === "verified") return "결과 검사 통과 · 작업 브랜치 반영 대기";
  return run.integration_control?.reason || "반영 상태 확인 필요";
}

export function includedApplyTasks(run: RunState): WorkTask[] {
  return run.tasks.filter((task) => ["completed", "merged"].includes(task.status));
}

export function applySummaryAction(run: RunState, snapshot: OperationsSnapshot | undefined, projectName: string): ApplySummaryAction | undefined {
  const control = run.integration_control;
  const unresolvedConflict = run.integration_conflict
    && !["applied", "stale"].includes(run.integration_conflict.resolution_status);
  if (!operationsSnapshotMatches(snapshot, projectName, run) || snapshot?.lock?.state !== "unlocked"
    || snapshot.lock.run_id && snapshot.lock.run_id !== run.id
    || !control || run.archive || unresolvedConflict
    || run.active_step && !(run.active_step === "verify" && control.can_verify)) return undefined;
  const sharedRemote = run.workspace_mode === "shared" && control.remote_configured;
  if (control.can_apply_main && verifiedResult(run)) {
    if (!sharedRemote && run.stage === "verified") return "main";
    if (sharedRemote && run.stage === "work_branch_pushed" && run.pushed_work_branch_head === control.verified_integration_head
      && run.push_receipts.some((receipt) => receipt.scope === "work_branch"
        && receipt.local_commit === run.pushed_work_branch_head && receipt.remote_commit === receipt.local_commit)) return "main";
  }
  if (mainAlreadyApplied(run)) {
    return run.workspace_mode === "isolated" && run.stage === "merged" && control.remote_configured ? "upload" : undefined;
  }
  if (control.can_verify) return sharedRemote ? "work" : "verify";
  return sharedRemote && run.stage === "verified" && verifiedResult(run) ? "work" : undefined;
}

function targetSignature(run: RunState): string {
  return JSON.stringify([run.id, run.repo_path, run.workspace_mode, run.execution_branch, run.main_branch, run.base_commit,
    run.plan_revision, run.plan_approved_revision, run.tasks.map((task) => [task.id, task.status, task.completed_commit]),
    run.integration_control?.remote_configured]);
}

function sameObservedRun(before: RunState, after: RunState): boolean {
  return before.updated_at === after.updated_at && before.stage === after.stage
    && JSON.stringify(before.main_operations) === JSON.stringify(after.main_operations)
    && targetSignature(before) === targetSignature(after)
    && before.integration_control?.current_main_head === after.integration_control?.current_main_head
    && before.integration_control?.current_integration_head === after.integration_control?.current_integration_head;
}

/** Owns only the open UI request; existing public commands own execution and approval. */
export class ApplySummarySession {
  private disposed = false;
  private pending = false;

  constructor(private projectName: string, private dependencies: {
    read(): Promise<OperationsResult>;
    command(method: ApplySummaryMethod, extra: Record<string, unknown>): Promise<RunState | null>;
    current(): boolean;
    changed(result: OperationsResult): void;
  }) {}

  dispose(): void { this.disposed = true; }
  isPending(): boolean { return this.pending; }
  private current(): boolean { return !this.disposed && this.dependencies.current(); }

  async perform(action: ApplySummaryAction, observed: RunState): Promise<"completed" | "cancelled" | "disposed" | "pending"> {
    if (this.pending) return "pending";
    if (!this.current()) return "disposed";
    this.pending = true;
    try {
      let result = await this.dependencies.read();
      if (!this.current()) return "disposed";
      this.dependencies.changed(result);
      if (!sameObservedRun(observed, result.run) || applySummaryAction(result.run, result.snapshot, this.projectName) !== action) {
        throw new Error("반영 대상이나 상태가 바뀌었습니다. 내용을 다시 확인한 뒤 진행하세요.");
      }
      if ((action === "work" || action === "verify") && !verifiedResult(result.run)) {
        if (!result.run.integration_control?.can_verify) throw new Error("지금은 결과를 검사할 수 없습니다. 상태를 다시 확인하세요.");
        const signature = targetSignature(result.run);
        const verified = await this.dependencies.command("runs.verifyAndRepair", {});
        if (!this.current()) return "disposed";
        if (!verified) return "cancelled";
        result = await this.dependencies.read();
        if (!this.current()) return "disposed";
        this.dependencies.changed(result);
        if (!sameObservedRun(verified, result.run) || targetSignature(result.run) !== signature) {
          throw new Error("검사 중 반영 대상이나 상태가 바뀌었습니다. 내용을 다시 확인하세요.");
        }
        if (result.run.stage !== "verified" || !verifiedResult(result.run)) {
          throw new Error("결과 검사를 통과하지 못했습니다. 실패 내용을 확인한 뒤 다시 시도하세요.");
        }
      }
      if (action === "verify") return "completed";
      if (!this.current()) return "disposed";
      if (applySummaryAction(result.run, result.snapshot, this.projectName) !== action) {
        throw new Error("현재 상태에서는 이 반영을 진행할 수 없습니다. 다시 확인하세요.");
      }
      const updated = await this.dependencies.command(action === "main" ? "runs.merge" : "runs.push", {
        workspaceMode: result.run.workspace_mode,
        ...(action === "main" ? { remoteConfigured: result.run.integration_control?.remote_configured } : {}),
      });
      if (!this.current()) return "disposed";
      if (!updated) return "cancelled";
      const latest = await this.dependencies.read();
      if (!this.current()) return "disposed";
      this.dependencies.changed(latest);
      // Main is never chained here. Its button is derived from the new authoritative snapshot.
      return "completed";
    } finally { this.pending = false; }
  }
}
