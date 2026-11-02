import type { DesktopApi } from "../../shared/rpc";
import type { PlanningApplyPreview, PlanningPreviewOperation, PlanningPreviewStatus, RunState } from "./types";
import { taskIsActive } from "./executionActivity";
import { isTaskScopeReview } from "./failurePresentation";

type RequestApi = Pick<DesktopApi, "request">;

export interface TaskPlanningTarget {
  projectName: string;
  runId: string;
  taskId?: string;
}

export function taskPlanningInProgress(requests: Record<string, TaskPlanningTarget>, projectName: string, runId: string, taskId?: string): boolean {
  return Object.values(requests).some((target) => target.projectName === projectName && target.runId === runId
    && (!taskId || !target.taskId || target.taskId === taskId));
}

export function planningApplyEntryBlocked(run: RunState | undefined): boolean {
  const pending = run?.planning_apply_requests?.at(-1);
  if (pending?.status === "queued" || pending?.status === "applying") return false;
  return Boolean(run && (run.tasks.some(taskIsActive) || run.active_step === "agent_execution" || run.active_step === "verify"
    || ["running", "preparing"].includes(run.execution_control?.situation || "")));
}

export function planningPreviewSurface(
  target: { projectName: string; runId: string; taskId?: string } | undefined,
  host: { projectName: string; runId: string; taskId?: string; taskDialogOpen: boolean },
): "none" | "task" | "dialog" {
  if (!target || target.projectName !== host.projectName || target.runId !== host.runId) return "none";
  return host.taskDialogOpen && host.taskId && (!target.taskId || target.taskId === host.taskId) ? "task" : "dialog";
}

export function openPlanningPreviewForMessage(
  message: string,
  repositoryIntent: RunState["repository_intent"],
  openPreview: () => void,
  run?: RunState,
): boolean {
  if (run?.project_chat_available && !run.archive && run.stage === "failed" && run.failed_step === "agent_execution"
    && run.tasks.some(task => task.status === "failed" && isTaskScopeReview(task.error || ""))) return false;
  const command = message.trim().replace(/\s+/gu, " ");
  const bareApply = /^반영(?:\s*해\s*(?:줘|주세요)|\s*해주세요|\s*해줘)?\s*[.!！~～]*$/u.test(command);
  const targetedApply = /^(?:tasks?|plans?|계획|플랜|태스크|테스크|작업\s*목록)\s*(?:에|으로)?\s*(?:반영|적용)(?:\s*해\s*(?:줘|주세요))?\s*[.!！~～]*$/iu.test(command);
  if (repositoryIntent === "new_project"
    || !(bareApply || targetedApply)) return false;
  openPreview();
  return true;
}

export class PlanningPreviewSession {
  private attempted = false;
  private pending?: Promise<void>;
  private disposed = false;
  private readVersion = 0;
  private generating = false;
  private restarting = false;
  private lastFailure = "";

  constructor(private api: RequestApi, private projectName: string, private runId: string,
    private requestId: string, private changed: (status: PlanningPreviewStatus) => void,
    private onGenerationStart?: () => () => void) {}

  check(): Promise<void> {
    return this.read((status) => {
      if (this.lastFailure && !this.generating && ["chat", "generating", "comparing"].includes(status.phase)) {
        this.attempted = false;
        this.lastFailure = "";
      }
      if (status.preview) this.attempted = true;
      this.changed(status.phase === "idle" && this.lastFailure
        ? { ...status, phase: "failed", error: this.lastFailure } : status);
      if (status.work_state === "idle" && status.phase === "idle" && status.can_generate && !this.attempted && !this.lastFailure) this.generate(status);
    });
  }

  async restart(): Promise<void> {
    if (this.generating || this.restarting || this.disposed) return;
    this.restarting = true;
    try {
      await this.read((status) => {
        this.changed(status);
        if (status.can_generate && ["idle", "interrupted"].includes(status.work_state)) this.generate(status);
      });
    } finally { this.restarting = false; }
  }

  private async read(received: (status: PlanningPreviewStatus) => void): Promise<void> {
    if (this.disposed) return;
    const version = ++this.readVersion;
    try {
      const status = await this.api.request<PlanningPreviewStatus>("runs.planningPreviewStatus", {
        projectName: this.projectName, runId: this.runId,
      });
      if (!this.disposed && version === this.readVersion) received(status);
    } catch (cause) {
      if (!this.disposed && version === this.readVersion) throw cause;
    }
  }

  private generate(status: PlanningPreviewStatus): void {
    if (this.generating || this.disposed) return;
    this.attempted = true;
    this.generating = true;
    this.lastFailure = "";
    const finishEditing = this.onGenerationStart?.();
    this.changed({ ...status, phase: "generating", can_apply: false });
    this.pending = this.api.request<PlanningApplyPreview>("runs.previewPlanningApply", {
      projectName: this.projectName, runId: this.runId, requestId: this.requestId,
    }).then(() => {
      this.generating = false;
      if (!this.disposed) return this.check();
    }).catch(async (cause: unknown) => {
      this.generating = false;
      if (this.disposed) return;
      this.lastFailure = cause instanceof Error ? cause.message : String(cause);
      try { await this.check(); }
      catch (readError) {
        if (!this.disposed) this.changed({ ...status, phase: "check_required", preview: null, can_generate: false,
          work_state: "unknown", active_operations: [], can_apply: false,
          error: `변경안 요청 결과와 상태를 확인하지 못했습니다. ${String(readError)}` });
      }
    }).finally(() => finishEditing?.());
  }

  generation(): Promise<void> | undefined { return this.pending; }
  stopAutomaticGeneration(): void { this.attempted = true; }
  invalidate(): void { this.readVersion += 1; }
  dispose(): void { this.disposed = true; this.invalidate(); }
}

export function previewRetryTask(run: RunState | undefined, preview: PlanningApplyPreview): string {
  if (run?.stage !== "failed" || run.failed_step !== "agent_execution" || preview.status !== "applied") return "";
  if (run.execution_control?.action !== "resume" || run.execution_control.situation !== "resumable") return "";
  if (!preview.actual || preview.actual.modified !== 1 || preview.actual.added !== 0 || preview.actual.excluded !== 0) return "";
  const changed = preview.changes.filter((item) => item.kind !== "unchanged");
  if (changed.length !== 1 || changed[0].kind !== "modified") return "";
  const target = run.tasks.find((task) => task.id === changed[0].task_id);
  return target?.status === "failed" ? target.id : "";
}

export function previewPhaseLabel(status: PlanningPreviewStatus | undefined): string {
  if (status && !["idle", "active", "unknown", "interrupted"].includes(status.work_state)) return "작업 상태 확인 필요";
  if (status?.work_state === "active") return "현재 그룹 작업 진행 중";
  if (status?.work_state === "unknown") return "작업 상태 확인 필요";
  const labels: Record<PlanningPreviewStatus["phase"], string> = {
    idle: "저장된 변경안 상태 확인 완료", chat: "기획 AI 응답 대기", generating: "변경안 작성 중",
    comparing: "작성된 변경 내용 비교 중", ready: "반영 전 확인", applied: "계획 반영 완료 · 실행 별도",
    failed: "변경안 작성 실패", check_required: "기획 작업 상태 확인 필요", interrupted: "기획 작업 중단 확인",
  };
  return status ? labels[status.phase] : "저장된 변경안 상태 확인 중";
}

export function previewOperationLabel(operation: PlanningPreviewOperation): string {
  const task = operation.task_title || operation.task_id;
  const labels: Record<PlanningPreviewOperation["kind"], string> = {
    planning_chat: "AI 작업 진행 중 · 기획 답변 작성 중",
    preview_generation: "AI 작업 진행 중 · 변경안 작성 중",
    preview_comparison: "작성 결과 비교 중",
    task_execute: `Task 실행 중 · ${task}`, task_review: `Task 리뷰 중 · ${task}`,
    task_verify: `Task 검증 중 · ${task}`, plan_apply: "확인한 계획 반영 중",
    run_verify: "그룹 통합 검증 중", run_operation: "현재 그룹 작업 진행 중",
  };
  return labels[operation.kind];
}

export function previewApplyTiming(status: PlanningPreviewStatus | undefined): string {
  if (!status || status.work_state === "unknown" || status.work_state === "interrupted") return "작업 상태 확인 필요";
  if (status.work_state === "active") return "현재 작업 종료 후 확인";
  if (status.phase === "applied") return "반영 완료";
  if (status.work_state !== "idle") return "작업 상태 확인 필요";
  if (status.phase === "ready" && status.can_apply && status.preview?.can_apply && !status.preview.stale) return "지금";
  return status.preview?.stale ? "새 변경안 확인 필요" : "변경안 재검토 필요";
}

export function previewElapsed(startedAt: string, now: number): number | undefined {
  const started = Date.parse(startedAt);
  return Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 1000)) : undefined;
}
