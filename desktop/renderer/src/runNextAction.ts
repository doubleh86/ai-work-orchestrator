import type { RunState, WorkTask } from "./types";
import { runExecutionPresentation } from "./runExecutionControl";
import { runRecoveryGuidance } from "./runRecoveryGuidance";
import { waitingPromptAction } from "./waitingPrompt";
import { isTaskScopeReview } from "./failurePresentation";

export type RunNextActionKind =
  | "confirm_plan"
  | "effort"
  | "execute"
  | "resume"
  | "retry"
  | "verify"
  | "refresh"
  | "result"
  | "task_log"
  | "task_detail"
  | "planning"
  | "operations"
  | "none";

export interface RunNextAction {
  status: string;
  description: string;
  label: string;
  kind: RunNextActionKind;
  taskId: string;
  tone: "active" | "danger" | "neutral" | "success" | "warning";
  disabled: boolean;
}

export function runNextAction(
  run: RunState,
  options: { planDirty: boolean; pendingAction: string },
): RunNextAction {
  const execution = runExecutionPresentation(run, options.pendingAction);
  const activeTask = taskById(run.tasks, run.execution_control?.active_task_id)
    || run.tasks.find((task) => ["running", "reviewing", "revising"].includes(task.status));
  const waitingTask = run.tasks.find((task) => task.status === "waiting");
  const failedTask = run.tasks.find((task) => task.status === "failed");
  const blockedTask = run.tasks.find((task) => task.status === "pending" && task.readiness === "blocked");
  const planApproved = !run.plan_revision || run.plan_approved_revision === run.plan_revision;
  const mergeWaiting = run.stage === "ready_to_merge";

  const planningFailure = run.stage === "failed" && run.failed_step === "planning";
  if (run.active_step === "planning" || run.stage === "needs_clarification" || planningFailure) {
    return action(
      run.stage === "needs_clarification" ? "답변 필요" : planningFailure ? "기획 확인 필요" : "기획 진행 중",
      run.stage === "needs_clarification" ? "계획을 이어가려면 기획 AI의 질문에 답변해 주세요." : execution.reason,
      "기획 AI로 이동", "planning", "", planningFailure ? "danger" : "warning",
    );
  }
  if (run.stage === "planned" && run.effort_control?.requires_plan_review && !options.planDirty) {
    return action(
      "작업 강도 반영 필요", "저장한 강도와 계획 설정이 다릅니다. 변경 비교를 확인하고 계획에 반영한 뒤 확정하세요.",
      "강도 변경 확인", "effort", "", "warning",
    );
  }
  if (run.stage === "planned" && (!planApproved || options.planDirty)) {
    return action(
      options.planDirty ? "변경 내용 재확정 필요" : "계획 검토 필요",
      options.planDirty
        ? "변경을 저장한 뒤 계획을 확정합니다. 확정 후 작업 실행은 별도로 시작합니다."
        : "실행할 작업과 완료 조건을 확인한 뒤 계획을 확정하세요. 확정만으로 작업을 실행하지 않습니다.",
      options.planDirty ? "변경 저장 후 계획 확정" : "계획 확정", "confirm_plan", "", "warning",
    );
  }
  if (execution.primaryKind === "refresh") {
    return action(mergeWaiting ? "병합 대기 · 상태 확인 필요" : "상태 확인 필요", execution.reason, "상태 다시 확인", "refresh", "", "warning");
  }
  if (run.execution_control?.situation === "running") {
    return action(
      run.active_step === "verify" ? "통합 검증 중" : "작업 진행 중",
      activeTask ? `${activeTask.title} 작업을 진행하고 있습니다. 완료되면 결과를 확인할 수 있습니다.` : execution.reason,
      "", "none", activeTask?.id || "", "active", true,
    );
  }
  if (run.execution_control?.situation === "unavailable" && ["executing", "failed"].includes(run.stage)
    && run.integration_control?.status !== "main_push_pending") {
    return action("실행·복구 보류", execution.reason, "상태 다시 확인", "refresh", "", "warning");
  }
  const waiting = !options.planDirty && !options.pendingAction ? waitingPromptAction(run) : null;
  if (waiting && run.waiting_prompt) {
    const labels = { retry: "이 Task 재시도", resume: "남은 Task 계속", verify: "반영 내용 확인", operations: "반영 내용 확인" };
    return action(run.stage === "ready_to_merge" ? "병합 대기" : "다음 단계 선택 대기", run.waiting_prompt.question,
      labels[waiting], waiting === "verify" ? "operations" : waiting, run.waiting_prompt.task_id, "warning");
  }
  const recovery = runRecoveryGuidance(run);
  if (recovery) {
    return action(
      run.stage === "failed" ? isTaskScopeReview(failedTask?.error || "") ? "수정 범위 확인 대기" : "실패 · 복구 확인 필요"
        : mergeWaiting ? "병합 대기 · 상태 확인 필요" : "상태 확인 필요",
      recovery.cause, recovery.actionLabel === "작업 그룹 재개" ? "작업 계속" : recovery.actionLabel, recovery.actionKind, recovery.taskId,
      run.stage === "failed" ? "danger" : "warning",
    );
  }
  if (run.execution_control?.situation === "preparing" || options.pendingAction) {
    return action("다음 작업 준비 중", execution.reason, "실행 상태 확인 중", "none", "", "active", true);
  }
  if (waitingTask) {
    return action(
      "사용자 수동 작업 대기", `${waitingTask.title}의 필요한 수동 작업과 완료 조건을 확인하세요.`,
      `${waitingTask.title} 확인`, "task_detail", waitingTask.id, "warning",
    );
  }
  if (execution.primaryMethod === "runs.resume") {
    return action("그룹 재개 가능", execution.reason, "작업 계속", "resume", "", "warning");
  }
  if (blockedTask && !run.tasks.some((task) => task.status === "pending" && task.readiness === "ready")) {
    return action(
      "선행 작업 대기", `${blockedTask.title}보다 먼저 끝나야 하는 작업을 확인하세요.`,
      "선행 작업 보기", "task_detail", blockedTask.id, "warning",
    );
  }
  if (execution.primaryMethod === "runs.execute") {
    return action(
      "작업 그룹 실행 가능",
      run.workspace_mode === "shared"
        ? "선행 조건을 충족한 작업부터 공유 작업공간에서 순서대로 이어서 실행합니다."
        : "선행 조건을 충족한 작업부터 이어서 실행합니다.",
      "작업 시작", "execute", "", "neutral",
    );
  }
  const integration = run.integration_control;
  if (integration?.status === "unknown") {
    return action(mergeWaiting ? "병합 대기 · 상태 확인 필요" : "프로젝트 상태 확인 필요", integration.reason, "상태 다시 확인", "refresh", "", "warning");
  }
  if (integration?.status === "stale") {
    if (!integration.can_verify) {
      return action(mergeWaiting ? "병합 대기 · 재검증 보류" : "재검증 보류", integration.reason, "Main으로 돌아온 뒤 상태 확인", "refresh", "", "warning");
    }
    return action(mergeWaiting ? "병합 대기 · 재검증 필요" : "재검증 필요", integration.reason, "반영 내용 확인", "operations", "", "warning");
  }
  if (integration?.status === "needs_verification") {
    if (!integration.can_verify && integration.reason_code === "branch_mismatch") {
      return action(mergeWaiting ? "병합 대기 · 통합 검증 보류" : "통합 검증 보류", integration.reason, "Main으로 돌아온 뒤 상태 확인", "refresh", "", "warning");
    }
    return action("병합 대기", integration.reason, "반영 내용 확인", "operations", "", "success");
  }
  if (integration?.status === "apply_blocked") {
    return action("검사 통과 · 프로젝트 적용 보류", integration.reason,
      integration.reason_code === "branch_mismatch" ? "Main으로 돌아온 뒤 상태 확인" : "Main 정리 후 상태 다시 확인",
      "refresh", "", "warning");
  }
  if (integration?.status === "verified") {
    return action("결과 검사 통과", integration.reason, "반영 내용 확인", "operations", "", "success");
  }
  if (["pushed", "deployed"].includes(run.stage) || run.stage === "merged" && run.integration_control?.remote_configured === false) {
    return action(run.stage === "deployed" ? "배포 완료" : run.stage === "pushed" ? "프로젝트 적용·업로드 완료" : "로컬 프로젝트 적용 완료",
      "완료한 범위와 결과를 확인할 수 있습니다.", "완료 결과 보기", "result", "", "success");
  }
  if (["ready_to_merge", "verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(run.stage)
    || execution.primaryKind === "operations") {
    const verificationReady = run.stage === "ready_to_merge";
    return action(
      verificationReady ? "병합 대기" : run.stage === "verified" ? "결과 검사 통과" : "프로젝트 적용 확인",
      verificationReady ? "만드는 작업을 마쳤습니다. 결과 검사와 프로젝트 적용은 아직 남아 있습니다."
        : run.stage === "verified" ? "검증 결과와 반영 대상을 확인하세요." : execution.reason,
      "반영 내용 확인",
      "operations", "", ["ready_to_merge", "verified"].includes(run.stage) ? "success" : execution.tone,
    );
  }
  return action(execution.statusLabel, execution.reason, execution.primaryLabel, "none", "", execution.tone, true);
}

function taskById(tasks: WorkTask[], id: string | undefined): WorkTask | undefined {
  return id ? tasks.find((task) => task.id === id) : undefined;
}

function action(
  status: string,
  description: string,
  label: string,
  kind: RunNextActionKind,
  taskId: string,
  tone: RunNextAction["tone"],
  disabled = false,
): RunNextAction {
  return { status, description, label, kind, taskId, tone, disabled };
}
