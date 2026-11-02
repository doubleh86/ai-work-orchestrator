import { taskFailureEvidence } from "./executionActivity";
import type { RunState, WorkTask } from "./types";
import { failurePresentation, isTaskScopeReview } from "./failurePresentation";

export type RecoveryGuidanceAction = "task_detail" | "task_log" | "planning" | "operations" | "resume" | "refresh";

export interface RunRecoveryGuidance {
  location: string;
  cause: string;
  recommendation: string;
  effect: string;
  evidence: string;
  actionKind: RecoveryGuidanceAction;
  actionLabel: string;
  taskId: string;
}

export function runRecoveryAllowed(run: RunState): boolean {
  return !run.archive && run.stage === "failed" && run.workspace_mode === "shared"
    && run.execution_control?.lock_state === "unlocked"
    && !["running", "preparing", "status_unknown"].includes(run.execution_control.situation)
    && !run.tasks.some(task => task.active_action || ["running", "reviewing", "revising"].includes(task.status));
}

export function runRecoveryGuidance(run: RunState): RunRecoveryGuidance | undefined {
  const failedTask = run.tasks.find((task) => task.status === "failed");
  if (["main_apply_interrupted", "main_apply_recoverable"].includes(run.integration_control?.reason_code || "")) {
    const recoverable = Boolean(run.integration_control?.can_recover_main_apply);
    return guidance(
      "중단된 Main 반영",
      run.integration_control?.reason || "Main 반영의 저장 결과와 Git 원본을 확인해야 합니다.",
      recoverable
        ? "통합·정리에서 기존·현재 Main과 검증 commit을 확인한 뒤 복구를 별도 승인하세요."
        : "통합·정리에서 Main ref·index·작업 폴더를 확인하세요. 자동 복구할 수 없습니다.",
      "Main을 다시 적용하거나 잠금만 해제하지 않습니다. 원격 Main Push는 별도 승인입니다.",
      run.integration_control?.reason || "", "operations", recoverable ? "Main 복구 상태 확인" : "Main 원본 상태 확인",
    );
  }
  if (run.integration_control?.status === "main_push_pending" && run.stage === "failed") {
    const branchMismatch = run.integration_control.reason_code === "branch_mismatch";
    const failure = run.main_operations?.retry_main_push?.error || run.main_operations?.merge?.error || run.failure_message;
    return guidance(
      "Main 반영 완료 · Push 실패",
      cause(failure),
      branchMismatch
        ? "Main branch로 돌아온 뒤 통합·정리에서 원격 상태를 다시 확인하세요."
        : "통합·정리에서 로컬·원격 commit을 확인한 뒤 Main Push만 별도 승인으로 재시도하세요.",
      "로컬 Main을 다시 반영하거나 일반 그룹 재개로 되돌리지 않습니다.",
      [run.integration_control.reason, failure].filter(Boolean).join("\n\n"),
      "operations", branchMismatch ? "Main Push 상태 확인" : "Main Push 재시도 확인",
    );
  }
  if (run.integration_conflict && !["applied", "stale"].includes(run.integration_conflict.resolution_status)) {
    const conflict = run.integration_conflict;
    const blocked = conflict.abort_status !== "verified";
    return guidance(
      "최신 Main 통합 충돌",
      blocked ? conflict.abort_error || run.failure_message : `${conflict.files.length}개 파일에서 작업 결과와 최신 Main 변경이 충돌했습니다.`,
      blocked ? "작업공간 복구 상태를 먼저 확인하세요." : "통합·정리에서 AI 해결안을 만들고 작업/Main/후보 내용을 비교하세요.",
      blocked
        ? "작업공간을 자동 변경하지 않습니다."
        : "격리된 후보만 생성합니다. 검토한 후보 적용과 전체 재검증에는 별도 승인이 필요합니다.",
      conflict.error || run.failure_message,
      "operations",
      blocked ? "충돌·작업공간 상태 확인" : "Main 충돌 해결안 검토",
    );
  }
  if (run.stage === "failed" && run.failed_step === "planning") {
    return guidance(
      "기획 AI · 계획 생성", cause(run.failure_message),
      "기획 대화에서 오류와 요청 범위를 확인하세요.",
      "기획 화면으로 이동하며 계획 생성이나 작업 실행을 자동으로 다시 요청하지 않습니다.",
      run.failure_message, "planning", "기획 실패 확인",
    );
  }
  if (run.stage === "failed" && run.failed_step === "manual_completion") {
    return guidance(
      failedTask ? `${failedTask.title || failedTask.id} · 수동 완료 확인` : "수동 완료 확인",
      taskCause(failedTask, run.failure_message),
      "실패한 작업을 수동 작업 대기 상태로 복원한 뒤 완료 조건을 다시 확인하세요.",
      "상태만 수동 대기로 복원합니다. 작업을 완료 처리하거나 작업을 다시 실행하지 않습니다.",
      taskEvidence(failedTask, run.failure_message), "resume", "수동 대기 상태로 복원", failedTask?.id,
    );
  }
  if (run.stage === "failed" && run.failed_step === "agent_execution" && failedTask) {
    const failure = taskFailureEvidence(failedTask);
    if (isTaskScopeReview(failure?.error || failedTask.error)) return guidance(
      `${failedTask.title || failedTask.id} · 수정 범위 확인`, "수정 범위 확인이 필요합니다",
      "기획 대화에서 AI가 요청한 경로와 이유를 검토하고 계획 변경안을 확인하세요.",
      "기존 구현과 실패 기록을 유지합니다. 범위 변경을 확정하기 전 같은 작업을 다시 실행하지 않습니다.",
      taskEvidence(failedTask, run.failure_message), "planning", "수정 범위 논의", failedTask.id,
    );
    const responseMissing = failure?.responseState !== "current";
    return guidance(
      `${failedTask.title || failedTask.id} · ${taskActionLabel(failedTask)}`,
      taskCause(failedTask, run.failure_message),
      responseMissing
        ? "해당 작업 로그에서 이번 실패 지점을 확인한 뒤 필요하면 그 작업만 재시도하세요. 과거 응답은 현재 실패 원인으로 사용하지 않습니다."
        : "해당 작업의 오류와 이번 시도 응답을 확인한 뒤 필요하면 그 작업만 재시도하세요.",
      "개별 재시도는 선택한 작업의 구현·검증·리뷰 흐름만 다시 수행합니다. 다른 미완료 작업을 함께 재개하지 않습니다.",
      taskEvidence(failedTask, run.failure_message), responseMissing ? "task_log" : "task_detail",
      responseMissing ? `${failedTask.title || failedTask.id} 실패 로그 확인` : `${failedTask.title || failedTask.id} 실패 확인`, failedTask.id,
    );
  }
  if (run.stage === "failed" && run.failed_step === "agent_execution" && run.execution_control?.action === "resume") {
    return guidance(
      "작업 실행 중단", cause(run.failure_message),
      "완료된 작업은 유지하고 남은 작업부터 작업 그룹을 재개하세요.",
      "중단 상태를 복원한 뒤 준비된 남은 작업 실행을 이어갑니다.",
      run.failure_message, "resume", "작업 그룹 재개",
    );
  }
  if (run.stage === "failed" && run.failed_step === "verify") {
    return guidance(
      "통합 검증", cause(run.failure_message, "verify"),
      "검증 기록과 실패 명령을 확인한 뒤 전체 통합 검증을 다시 실행하세요.",
      "통합 검증 전체를 다시 실행합니다. 이 오류만으로 원인 작업을 특정하지 않습니다.",
      run.failure_message, "operations", "통합 검증 실패 확인",
    );
  }
  if (run.stage === "failed" && run.failed_step === "merge" && run.workspace_mode !== "shared") {
    return guidance(
      "Main 반영", cause(run.failure_message),
      "오류 원문과 통합 상태를 확인하세요. 이 작업공간 방식에서는 안전한 복원 경로가 제공되지 않습니다.",
      "상태 복원이나 Main 반영을 실행하지 않습니다.",
      run.failure_message, "operations", "Main 반영 실패 확인",
    );
  }
  if (run.stage === "failed" && ["merge", "push", "deploy"].includes(run.failed_step || "")) {
    const step = run.failed_step || "";
    const labels: Record<string, string> = { merge: "Main 반영", push: "Push", deploy: "배포" };
    return guidance(
      labels[step] || step, cause(run.failure_message),
      `${labels[step] || step}를 다시 요청할 수 있는 직전 상태로 복원하세요.`,
      `상태만 복원합니다. ${labels[step] || step} 작업과 승인을 자동으로 다시 수행하지 않습니다.`,
      run.failure_message, "resume", `${labels[step] || step} 재요청 상태로 복원`,
    );
  }
  if (run.execution_control?.situation === "attention_required" && run.execution_control.lock_state === "stale") {
    return guidance(
      "중단된 실행 잠금", cause(run.execution_control.reason),
      "통합·정리에서 잠금 소유 상태를 확인한 뒤 중단된 잠금만 해제하세요.",
      "잠금 해제만 수행하며 작업 실행이나 그룹 재개를 자동으로 시작하지 않습니다.",
      run.execution_control.reason, "operations", "잠금 상태 확인",
    );
  }
  if (run.execution_control?.situation === "status_unknown") {
    return guidance(
      "실행 상태 조회", cause(run.execution_control.reason),
      "현재 상태를 다시 조회한 뒤 가능한 행동을 판단하세요.",
      "조회만 수행하며 실행·재개·복구를 자동으로 요청하지 않습니다.",
      run.execution_control.reason, "refresh", "상태 다시 확인",
    );
  }
  if (run.stage === "failed") {
    return guidance(
      run.failed_step ? `지원되지 않은 실패 단계 · ${run.failed_step}` : "확인되지 않은 실패 단계",
      cause(run.failure_message), "오류 원문과 이벤트를 확인하세요.",
      "안전한 복구 동작이 확인되지 않아 자동 재시도나 성공 상태를 제안하지 않습니다.",
      run.failure_message, "operations", "실패 근거 확인",
    );
  }
  return undefined;
}

function guidance(
  location: string,
  causeText: string,
  recommendation: string,
  effect: string,
  evidence: string,
  actionKind: RecoveryGuidanceAction,
  actionLabel: string,
  taskId = "",
): RunRecoveryGuidance {
  return { location, cause: cause(causeText), recommendation, effect, evidence: evidence || causeText, actionKind, actionLabel, taskId };
}

function cause(value: string, action = ""): string {
  return failurePresentation(value, action).title;
}

function taskCause(task: WorkTask | undefined, fallback: string): string {
  const evidence = task ? taskFailureEvidence(task) : undefined;
  return failurePresentation(evidence?.error || task?.error || fallback, task?.failed_action || evidence?.action || "execute").title;
}

function taskEvidence(task: WorkTask | undefined, fallback: string): string {
  if (!task) return fallback;
  const evidence = taskFailureEvidence(task);
  if (!evidence) return task.error || fallback;
  const response = evidence.response
    ? `이번 시도 응답:\n${evidence.response}`
    : evidence.responseState === "previous_only"
      ? "이번 실패 시도의 응답 기록 없음 · 과거 시도 응답은 현재 근거에서 제외"
      : "이번 실패 시도의 응답 기록 없음";
  return [evidence.error, response].filter(Boolean).join("\n\n");
}

function taskActionLabel(task: WorkTask): string {
  const labels: Record<string, string> = { execute: "구현", revise: "수정", review: "리뷰", verify: "검증" };
  return labels[task.failed_action || ""] || "작업 실행";
}
