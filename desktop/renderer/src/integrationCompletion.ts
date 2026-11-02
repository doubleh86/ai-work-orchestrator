import type { RunArchive, RunLockStatus, RunState, WorkspaceStatus } from "./types";

export interface OperationsSnapshot {
  projectName: string;
  runId: string;
  runUpdatedAt: string;
  mainOperationsSignature: string;
  status: "loading" | "ready" | "error";
  workspaces: WorkspaceStatus[];
  lock?: RunLockStatus;
  checkedAt: string;
  error: string;
}

type OperationsMethod = "runs.get" | "workspaces.list" | "locks.get";
type OperationsRequest = <T>(method: OperationsMethod, params: { projectName: string; runId: string }) => Promise<T>;

export async function readConsistentOperations(
  projectName: string,
  runId: string,
  request: OperationsRequest,
): Promise<{ run: RunState; snapshot: OperationsSnapshot }> {
  const params = { projectName, runId };
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const before = await request<RunState>("runs.get", params);
    const [workspaces, lock] = await Promise.all([
      request<WorkspaceStatus[]>("workspaces.list", params),
      request<RunLockStatus>("locks.get", params),
    ]);
    const after = await request<RunState>("runs.get", params);
    if (before.id !== runId || after.id !== runId || lock.run_id !== runId || workspaces.some((workspace) => workspace.run_id !== runId)) {
      throw new Error("운영 상태 조회 결과의 작업 그룹이 일치하지 않습니다. 다시 확인해 주세요.");
    }
    const sameRevision = before.updated_at === after.updated_at;
    const sameOperation = JSON.stringify(before.main_operations) === JSON.stringify(after.main_operations);
    const sameLock = after.execution_control?.lock_state === lock.state
      && (lock.state !== "active" || after.execution_control?.operation === lock.operation);
    const sameWorkspaceStage = workspaces.every((workspace) => !workspace.run_stage || workspace.run_stage === after.stage);
    const sameWorkspaceLock = workspaces.every((workspace) => !workspace.reason.startsWith("run lock is ")
      || workspace.reason.startsWith(`run lock is ${lock.state}:`));
    if (sameRevision && sameOperation && sameLock && sameWorkspaceStage && sameWorkspaceLock) {
      return {
        run: after,
        snapshot: {
          projectName, runId, runUpdatedAt: after.updated_at,
          mainOperationsSignature: JSON.stringify(after.main_operations), status: "ready",
          workspaces, lock, checkedAt: new Date().toISOString(), error: "",
        },
      };
    }
  }
  throw new Error("운영 상태가 조회 중 바뀌었습니다. 최신 상태를 다시 확인해 주세요.");
}

export function operationsSnapshotMatches(
  snapshot: OperationsSnapshot | undefined,
  projectName: string,
  run: RunState | undefined,
): boolean {
  return Boolean(snapshot && run && snapshot.status === "ready"
    && snapshot.projectName === projectName && snapshot.runId === run.id
    && snapshot.runUpdatedAt === run.updated_at
    && snapshot.mainOperationsSignature === JSON.stringify(run.main_operations));
}

export function verifiedResult(run: RunState): boolean {
  const control = run.integration_control;
  const stopped = Boolean(run.verification_attempts?.at(-1)?.stop_reason)
    || run.execution_control?.stop_scope === "verification" && ["stopping", "stopped"].includes(run.execution_control.stop_phase);
  const mainMatches = control && (control.verified_main_head === control.current_main_head
    || run.workspace_mode === "shared" && run.stage === "work_branch_pushed"
      && control.current_main_head === control.verified_integration_head);
  return Boolean(!stopped && control?.status === "verified" && control.verified_main_head
    && mainMatches && control.verified_integration_head
    && control.verified_integration_head === control.current_integration_head);
}

export function mainAlreadyApplied(run: RunState): boolean {
  return ["merged", "pushed", "deployed"].includes(run.stage)
    || run.integration_control?.status === "applied"
    || run.integration_control?.status === "main_push_pending"
    || (["main_applied", "pushing", "confirming_remote"].includes(run.main_operations?.merge?.phase || "")
      && run.main_operations?.merge?.status !== "succeeded")
    || (run.tasks.length > 0 && run.main_operations?.push?.status === "failed"
      && run.tasks.every((task) => task.status === "merged"));
}

export function canRetryMainPush(run: RunState, lock?: RunLockStatus): boolean {
  return run.workspace_mode === "shared" && run.integration_control?.status === "main_push_pending"
    && run.integration_control.reason_code !== "branch_mismatch"
    && lock?.state === "unlocked";
}

export function mainCompletionLabel(run: RunState, workspaces: WorkspaceStatus[], lock?: RunLockStatus): string {
  const merge = run.main_operations?.merge;
  const push = run.main_operations?.push;
  const retry = run.main_operations?.retry_main_push;
  if (lock?.state === "active" && lock.operation === "retry-main-push") {
    if (retry?.phase === "cleaning_workspaces") return "Main Push 완료 · 작업공간 정리 중";
    return "Main Push 재시도 중";
  }
  if (lock?.state === "active" && lock.operation === "merge") {
    if (merge?.phase === "pushing") return "Main 반영 완료 · 원격 전송 중";
    if (merge?.phase === "cleaning_workspaces") return "Main Push 완료 · 작업공간 정리 중";
    return "Main 반영 처리 중";
  }
  if (lock?.state === "active" && lock.operation === "push") return "원격 Push 중";
  if (run.integration_control?.reason_code === "main_apply_interrupted") return "Main 반영 중단 · 원본 확인 필요";
  if (run.integration_control?.reason_code === "main_apply_recoverable") return "Main 반영 중단 · 복구 승인 가능";
  const workspaceCleaned = workspaces.length > 0 && workspaces.every((workspace) => workspace.state === "cleaned");
  if (retry?.status === "succeeded" && retry.phase === "cleanup_deferred" && !workspaceCleaned) return "Main Push 완료 · 작업공간 정리 보류";
  if (retry?.status === "succeeded" && (retry.phase === "cleanup_completed" || workspaceCleaned)) return "Main Push 완료";
  if (retry?.status === "failed") return "Main 반영 완료 · Push 재시도 실패";
  if (["pushing", "confirming_remote"].includes(merge?.phase || "") && merge?.status === "failed") return "Main 반영 완료 · Push 실패";
  if (run.integration_control?.status === "main_push_pending") return "Main 반영 완료 · Push 확인/재시도 필요";
  if (merge?.phase === "cleanup_deferred" && !workspaceCleaned) return run.stage === "pushed" ? "Main Push 완료 · 작업공간 정리 보류" : "Main 반영 완료 · 작업공간 정리 보류";
  if (run.stage === "pushed" || run.stage === "deployed") {
    if (run.workspace_mode === "shared" && merge?.phase !== "cleanup_completed" && retry?.phase !== "cleanup_completed" && !workspaceCleaned) return "Main Push 완료 · 작업공간 상태 확인 필요";
    return "Main Push 완료";
  }
  if (push?.status === "failed" && run.tasks.every((task) => task.status === "merged")) return "Main 반영 완료 · Push 실패";
  if (run.stage === "merged") {
    if (run.workspace_mode === "shared" && merge?.phase !== "cleanup_completed" && !workspaceCleaned) return "Main 반영 완료 · 작업공간 상태 확인 필요";
    return "로컬 Main 반영 완료";
  }
  if (workspaces.some((workspace) => workspace.state === "unsafe")) return "작업공간 상태 확인 필요";
  return "Main 반영 대기";
}

export function runLockLabel(lock?: RunLockStatus): string {
  if (!lock) return "실행 상태 확인 필요";
  if (lock.state === "active") {
    const operations: Record<string, string> = {
      merge: "Main 반영 처리 중", push: "원격 Push 중", verify: "최종 검증 중",
      "retry-main-push": "Main Push 재시도 중",
      "verify-and-repair": "최종 검증·수정 중", "archive-cleanup": "보관 작업공간 정리 중",
    };
    return operations[lock.operation] || "실행 상태 확인 필요";
  }
  const states: Record<string, string> = {
    unlocked: "실행 잠금 없음", stale: "중단된 실행 감지", unverifiable: "잠금 확인 필요", malformed: "잠금 정보 오류",
  };
  return states[lock.state] || "실행 상태 확인 필요";
}

export function workspaceStateLabel(state: string): string {
  const states: Record<string, string> = {
    not_prepared: "미준비", active: "정리 대기", stale: "정리 가능", cleaned: "정리 완료", unsafe: "정리 보류",
  };
  return states[state] || "상태 확인 필요";
}

export function formatDurationLimit(seconds: number): string {
  const normalized = Math.max(0, seconds);
  const minutes = Math.floor(normalized / 60);
  return minutes ? `${minutes}분 ${normalized % 60}초` : `${normalized}초`;
}

export function workspaceReasonLabel(reason: string): string {
  const reasons: Record<string, string> = {
    "workspace has not reached a safely integrated run stage": "작업 그룹이 아직 정리 가능한 완료 상태가 아니어서 보류했습니다.",
    "workspace artifacts were already removed": "작업공간 정리를 완료했습니다.",
    "task workspace has not been prepared": "아직 준비된 작업공간이 없습니다.",
    "merged workspace can be removed safely": "안전하게 정리할 수 있습니다.",
    "worktree contains uncommitted changes": "작업공간에 커밋되지 않은 변경이 있어 정리를 보류했습니다.",
    "worktree path exists but Git does not own it": "Git이 작업공간 경로를 소유하지 않아 정리를 보류했습니다.",
    "workspace branch is not contained in main": "작업 브랜치가 Main에 포함되지 않아 정리를 보류했습니다.",
  };
  return reasons[reason] || "정리 상태 확인이 필요합니다.";
}

export function workspaceCleanupFailure(reason: string): string {
  if (/WinError (32|33)\b|sharing violation|being used by another process|다른 프로그램에서 사용 중|다른 프로세스가 파일을 사용/i.test(reason)) {
    return "다른 프로그램이 작업 폴더를 사용 중입니다. 해당 폴더를 닫고 다시 시도하세요.";
  }
  if (/uncommitted|미커밋|미추적 사용자 변경/i.test(reason)) return "보존해야 할 변경이 남아 있어 정리를 보류했습니다.";
  if (/ignored 파일|unapproved ignored files/i.test(reason)) {
    return "자동 삭제 범위 밖의 파일이 남아 있어 정리를 보류했습니다. 파일 보존 여부를 확인해야 합니다.";
  }
  if (/symlink|junction|linked worktree|Git marker|소유권|Git이 소유하지|not registered by Git|Git does not own/i.test(reason)) {
    return "앱이 만든 작업 폴더인지 확인할 수 없어 정리를 보류했습니다.";
  }
  if (/run lock is active|is already locked|실행 중|작업이 진행 중/i.test(reason)) return "작업이 진행 중입니다. 완료 후 다시 시도하세요.";
  if (/WinError 5\b|permission denied|access.*denied|접근.*거부|액세스.*거부|권한/i.test(reason)) {
    return "작업 폴더에 접근할 수 없어 정리하지 못했습니다.";
  }
  return "작업 폴더를 정리하지 못했습니다. 다시 시도해 주세요.";
}

export function archiveCleanupReason(archive: RunArchive | null | undefined): string {
  if (!archive || archive.cleanup_status === "completed") return "";
  if (archive.cleanup_status === "pending") return "작업 폴더 정리를 준비하고 있습니다.";
  if (archive.cleanup_status === "running") return "작업 폴더를 정리하고 있습니다.";
  const errors = archive.cleanup_targets
    .filter((target) => !["removed", "already_removed"].includes(target.status) && target.error)
    .map((target) => workspaceCleanupFailure(target.error));
  return [...new Set(errors)].join(" ") || workspaceCleanupFailure("");
}
