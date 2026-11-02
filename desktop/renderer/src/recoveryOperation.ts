import { providerFailurePresentation } from "./providerFailure";

export type RecoveryOperationKind = "recovery_preview" | "recovery_apply";
export type RecoveryOperationStatus = "running" | "succeeded" | "failed" | "partial" | "interrupted";

export interface RecoveryPlan {
  run_id: string;
  baseline: string;
  worktree: string;
  fingerprint: string;
  failure: string;
  failed_tasks: { id: string; title: string; error: string; response: string }[];
  sources: { run_id: string; summary: string; commits: string[]; completed_tasks: string[]; pending_tasks: { title: string; expected_paths: string[] }[] }[];
}

export interface RecoveryOperation {
  request_id: string;
  run_id: string;
  action: RecoveryOperationKind;
  digest: string;
  phase: string;
  status: RecoveryOperationStatus;
  error: string;
  error_code: string;
  finished_at: string;
  result_revision: number;
  result_commit: string;
  result_ref: string;
  resume_request_id: string;
  lock_state: string;
  created_at: string;
  updated_at: string;
  result: Record<string, unknown> | null;
}

const phaseLabels: Record<string, string> = {
  requesting: "실행 엔진에 요청 전달 중",
  checking_failure: "실패 원인 확인 중",
  collecting_sources: "가져올 결과 확인 중",
  preview_ready: "복구안 준비됨",
  awaiting_approval: "복구 적용 확인 대기",
  validating_plan: "선택한 복구안 확인 중",
  integrating_commits: "선택한 결과 통합 중",
  replanning: "남은 작업 재계획 중",
  completed: "복구 적용 완료",
};

export function recoveryPhaseLabel(operation: RecoveryOperation): string {
  const providerFailure = providerFailurePresentation(operation.error);
  if (operation.status === "partial" && providerFailure) return `통합 결과 보존 · ${providerFailure.label}${providerFailure.kind === "capacity" ? "으로" : "로"} 재계획 실패`;
  if (operation.status === "failed" && providerFailure) return providerFailure.title;
  if (operation.status === "partial") return "결과 통합 완료 · 작업 재계획 실패";
  if (operation.status === "failed") return operation.action === "recovery_preview" ? "복구안 조회 실패" : "복구 적용 실패";
  if (operation.status === "interrupted") return "복구 요청 중단됨";
  if (operation.status === "succeeded") return operation.action === "recovery_preview" ? "복구안 준비됨" : "복구 적용 완료";
  return phaseLabels[operation.phase] || "복구 요청 처리 중";
}

export function recoveryElapsedSeconds(timestamp: string, now: number): number {
  const started = Date.parse(timestamp);
  if (!Number.isFinite(started)) return 0;
  return Math.max(0, Math.floor((now - started) / 1000));
}

export function recoveryDelayState(operation: RecoveryOperation, now: number): "normal" | "delayed" | "unconfirmed" {
  if (operation.status !== "running") return "normal";
  const elapsed = recoveryElapsedSeconds(operation.created_at, now);
  if (elapsed >= 60) return "unconfirmed";
  if (elapsed >= 15) return "delayed";
  return "normal";
}

export function recoveryPlanFromOperation(operation: RecoveryOperation): RecoveryPlan | undefined {
  if (operation.action !== "recovery_preview" || operation.status !== "succeeded" || !operation.result) return undefined;
  const result = operation.result as Partial<RecoveryPlan>;
  return typeof result.run_id === "string" && typeof result.fingerprint === "string" && Array.isArray(result.sources)
    ? result as RecoveryPlan
    : undefined;
}

export function recoveryResumeInput(operation: RecoveryOperation): { fingerprint: string; sourceIds: string[] } | undefined {
  if (operation.action !== "recovery_apply" || operation.status !== "partial" || !operation.result) return undefined;
  const fingerprint = operation.result.fingerprint;
  const sourceIds = operation.result.source_ids;
  return typeof fingerprint === "string" && Array.isArray(sourceIds) && sourceIds.every((item) => typeof item === "string")
    ? { fingerprint, sourceIds }
    : undefined;
}
