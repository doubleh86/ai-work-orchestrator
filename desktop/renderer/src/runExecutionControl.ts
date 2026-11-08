import type { IntegrationControl, RunExecutionControl, RunState } from "./types";

export type RunPrimaryActionKind = "run" | "refresh" | "planning" | "operations" | "none";

export interface RunExecutionPresentation {
  statusLabel: string;
  tone: "active" | "danger" | "neutral" | "success" | "warning";
  primaryKind: RunPrimaryActionKind;
  primaryMethod?: "runs.execute" | "runs.resume";
  primaryLabel: string;
  disabled: boolean;
  reason: string;
}

export function runRequestKey(projectName: string, runId: string): string {
  return JSON.stringify([projectName, runId]);
}

export function projectRunContext(
  current: { projectName: string; runId: string },
  projectName: string,
): { projectName: string; runId: string } {
  return current.projectName === projectName ? current : { projectName, runId: "" };
}

export function runContextMatches(
  selectedProjectName: string,
  selectedRunId: string,
  sourceProjectName: string,
  sourceRunId: string,
): boolean {
  return Boolean(sourceProjectName && sourceRunId)
    && selectedProjectName === sourceProjectName
    && selectedRunId === sourceRunId;
}

export function isRunStageMismatchError(message: string): boolean {
  return /\brun .+ is at '[^']+', expected one of:/.test(message)
    || /\brun .+ at '[^']+' has no resumable failure/.test(message);
}

export function runExecutionActionAllowed(run: RunState, method: "runs.execute" | "runs.resume"): boolean {
  const control = run.execution_control;
  if (run.archive || !control || control.lock_state !== "unlocked"
    || ["running", "preparing", "status_unknown", "attention_required", "unavailable"].includes(control.situation)) return false;
  if (method === "runs.execute") return run.stage === "planned" && control.action === "execute";
  return control.action === "resume" && (run.stage === "planned" || run.stage === "executing"
    || run.stage === "failed" && Boolean(run.failed_step));
}

export async function readRunExecutionAction(
  read: () => Promise<RunState>, observed: RunState, method: "runs.execute" | "runs.resume",
): Promise<{ run: RunState; allowed: boolean }> {
  const run = await read();
  if (run.id !== observed.id) throw new Error("조회 응답의 작업 그룹이 요청 대상과 다릅니다.");
  const signature = (state: RunState) => JSON.stringify([
    state.stage, state.failed_step, state.plan_revision, state.plan_approved_revision,
    state.tasks.map(task => [task.id, task.status, task.completed_commit]),
    state.execution_control?.action, state.execution_control?.situation, state.execution_control?.lock_state,
    state.execution_control?.execution_id, state.execution_control?.stop_phase,
  ]);
  return { run, allowed: signature(run) === signature(observed) && runExecutionActionAllowed(run, method) };
}

export function unknownRunExecutionControl(reason: string): RunExecutionControl {
  return {
    situation: "status_unknown",
    action: "none",
    reason,
    lock_state: "unknown",
    operation: "",
    active_task_id: "",
    active_task_title: "",
    execution_id: "",
    active_attempt_id: "",
    active_invocation_id: "",
    can_stop: false,
    stop_scope: "",
    stop_request_id: "",
    stop_phase: "",
    dispatch_paused: false,
    checked_at: new Date().toISOString(),
  };
}

export function unknownIntegrationControl(reason: string): IntegrationControl {
  return {
    status: "unknown",
    reason,
    reason_code: "query_failed",
    can_verify: false,
    can_apply_main: false,
    main_dirty: null,
    verified_main_head: "",
    current_main_head: "",
    verified_integration_head: "",
    current_integration_head: "",
    remote_configured: false,
    checked_at: new Date().toISOString(),
  };
}

export function shouldPollRunExecution(run: RunState | undefined, pendingAction: string): boolean {
  if (!run || pendingAction) return false;
  if (!run.execution_control) return Boolean(run.active_step);
  return ["running", "preparing"].includes(run.execution_control.situation);
}

export function runExecutionPresentation(
  run: RunState,
  pendingAction: string,
): RunExecutionPresentation {
  const control = run.execution_control;
  if (pendingAction) {
    if (control?.situation === "running") {
      return presentation("실행 중", "active", "none", "작업 실행 중", true, control.reason);
    }
    if (control?.situation === "preparing") {
      return presentation("다음 작업 준비 중", "active", "none", "다음 작업 준비 중", true, control.reason);
    }
    return presentation(
      "실행 시작 확인 중",
      "active",
      "none",
      "실행 시작 확인 중",
      true,
      "최신 실행 상태와 요청 가능 여부를 확인하고 있습니다.",
    );
  }
  if (!control) {
    return presentation(
      "상태 확인 필요",
      "warning",
      "refresh",
      "상태 다시 확인",
      false,
      "실행 가능 여부를 아직 확인하지 못했습니다.",
    );
  }
  if (control.lock_state !== "unlocked" && !["running", "preparing"].includes(control.situation)) {
    return control.lock_state === "stale"
      ? presentation("중단된 실행 확인 필요", "warning", "operations", "잠금 상태 확인", false, control.reason)
      : presentation("상태 확인 필요", "warning", "refresh", "상태 다시 확인", false, control.reason);
  }
  if (control.action === "execute" && runExecutionActionAllowed(run, "runs.execute")) {
    return {
      ...presentation("실행 준비", "neutral", "run", "준비된 작업 실행", false, control.reason),
      primaryMethod: "runs.execute",
    };
  }
  if (control.action === "resume" && runExecutionActionAllowed(run, "runs.resume")) {
    return {
      ...presentation(run.stage === "failed" ? "실패 · 재개 가능" : "재개 가능", "warning", "run", "그룹 재개", false, control.reason),
      primaryMethod: "runs.resume",
    };
  }
  if (control.situation === "running") {
    return presentation(
      "실행 중",
      "active",
      "none",
      control.active_task_title ? `${control.active_task_title} 실행 중` : "그룹 실행 중",
      true,
      control.reason,
    );
  }
  if (control.situation === "preparing") {
    return presentation("다음 작업 준비 중", "active", "none", "다음 작업 준비 중", true, control.reason);
  }
  if (control.situation === "waiting_user_check") {
    return presentation("사용자 확인 대기", "warning", "none", "사용자 확인 대기", true, control.reason);
  }
  if (run.stage === "executing" && control.situation === "resumable" && control.action === "none"
    && run.tasks.some((task) => task.status === "deferred")) {
    return presentation("수동 검증 보류", "warning", "none", "보류 작업 보기", true, control.reason);
  }
  if (control.situation === "status_unknown") {
    return presentation("상태 확인 필요", "warning", "refresh", "상태 다시 확인", false, control.reason);
  }
  if (control.situation === "tasks_complete"
    || ["ready_to_merge", "verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(run.stage)) {
    const applied = ["merged", "pushed", "deployed"].includes(run.stage);
    return presentation(applied ? "병합 완료" : "병합 대기", "success", "operations", "통합·정리로 이동", false, control.reason);
  }
  if (control.situation === "attention_required" && run.stage === "failed" && run.failed_step === "planning") {
    return presentation("기획 확인 필요", "danger", "planning", "기획에서 확인", false, control.reason);
  }
  const failure = run.stage === "failed";
  return presentation(
    failure ? "확인 필요" : "실행할 수 없음",
    failure ? "danger" : "neutral",
    "none",
    failure ? "실패 근거 확인" : "실행할 수 없음",
    true,
    control.reason,
  );
}

function presentation(
  statusLabel: string,
  tone: RunExecutionPresentation["tone"],
  primaryKind: RunPrimaryActionKind,
  primaryLabel: string,
  disabled: boolean,
  reason: string,
): RunExecutionPresentation {
  return { statusLabel, tone, primaryKind, primaryLabel, disabled, reason };
}
