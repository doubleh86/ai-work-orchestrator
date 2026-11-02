import type { ConflictOperationAttempt, IntegrationConflict, IntegrationConflictDetail, RecoveryTask, RunState } from "./types";
import { progressPhaseLabels } from "./progressLog";
import { operationsSnapshotMatches, type OperationsSnapshot } from "./integrationCompletion";

export type ActiveConflictPhase = "prepare" | "apply" | "verify";

export function activeConflictPhase(run: RunState | undefined, snapshot: OperationsSnapshot | undefined,
  projectName: string): ActiveConflictPhase | undefined {
  if (!run?.integration_conflict || !operationsSnapshotMatches(snapshot, projectName, run)
    || snapshot?.lock?.run_id !== run.id || snapshot.lock.state !== "active") return undefined;
  if (snapshot.lock.operation === "conflict-resolution-prepare") return "prepare";
  if (["conflict-resolution-apply", "conflict-resolution-cleanup", "conflict-resolution-verification-result"]
    .includes(snapshot.lock.operation)) return "apply";
  if (["verify", "verify-and-repair"].includes(snapshot.lock.operation)
    && (run.active_step === "verify" || run.verification_progress_phase === "repairing")) return "verify";
  return undefined;
}

export interface RecoveryTaskPresentation {
  label: string;
  detail: string;
  tone: string;
}

export function conflictDetailBasis(
  projectName: string, runId: string, conflictId: string, recoveryTaskId: string, runUpdatedAt: string, operationsCheckedAt: string,
): string {
  return [projectName, runId, conflictId, recoveryTaskId, runUpdatedAt, operationsCheckedAt].join("\u001f");
}

export function currentConflictDetail(
  detail: IntegrationConflictDetail | undefined, loadedBasis: string, expectedBasis: string,
): IntegrationConflictDetail | undefined {
  return loadedBasis === expectedBasis ? detail : undefined;
}

export function conflictRequestTiming(
  attempt: ConflictOperationAttempt | undefined, pending: PendingConflictRequest | undefined, now: number,
): string {
  const started = Date.parse(attempt?.created_at || pending?.startedAt || "");
  const finished = attempt && attempt.status !== "running";
  const end = finished ? Date.parse(attempt.updated_at || "") : now;
  if (!Number.isFinite(started) || !Number.isFinite(end) || end < started) {
    return finished ? "소요 시간 정보 없음" : "경과 확인 중";
  }
  const seconds = Math.floor((end - started) / 1000);
  const duration = seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
  return `${duration} ${finished ? "소요" : "경과"}`;
}

export function recoveryTaskPresentation(task: RecoveryTask, run: RunState): RecoveryTaskPresentation {
  if (task.superseded_by) return { label: "새 기준으로 대체됨", detail: "이전 시도와 로그를 보존했습니다.", tone: "neutral" };
  const status = task.conflict.resolution_status;
  const verificationSucceeded = task.verification_attempt_ids.some((attemptId) =>
    run.verification_attempts?.some((attempt) => attempt.id === attemptId && attempt.status === "succeeded"));
  if (status === "generating") return { label: "해결안 생성 중", detail: "저장된 생성 단계를 확인하는 중입니다.", tone: "active" };
  if (status === "candidate_ready") return { label: "검토 대기", detail: "양쪽 변경과 해결안을 확인한 뒤 적용하세요.", tone: "warning" };
  if (status === "applying") return { label: "적용·검증 중", detail: "승인한 후보를 적용하고 전체 검증 중입니다.", tone: "active" };
  if (status === "applied" && (run.stage === "verified" || verificationSucceeded)) return { label: "완료", detail: "해결안 적용과 전체 검증을 확인했습니다.", tone: "success" };
  if (status === "applied") return { label: "적용 완료·검증 확인 필요", detail: task.conflict.error || "전체 검증 결과를 확인하세요.", tone: "warning" };
  if (status === "failed") return { label: "실패", detail: task.conflict.error || "실패 기록을 확인한 뒤 다시 만드세요.", tone: "danger" };
  if (status === "stale") return { label: "기준 변경됨", detail: "최신 기준으로 새 해결안이 필요합니다.", tone: "warning" };
  if (status === "workspace_recovery_required") return { label: "작업공간 복구 필요", detail: task.conflict.abort_error || "원래 작업공간 복구를 확인하세요.", tone: "danger" };
  return { label: "해결안 필요", detail: "충돌 근거를 확인하고 해결안을 만드세요.", tone: "warning" };
}

export function conflictResolutionSummary(
  conflict: IntegrationConflict, attempt: ConflictOperationAttempt | undefined, historical: boolean,
): RecoveryTaskPresentation {
  if (historical) return { label: "이전 해결 기록", detail: "새 기준으로 대체된 기록입니다. 이전 해결안과 로그만 확인할 수 있습니다.", tone: "neutral" };
  if (conflict.abort_status !== "verified" || conflict.abort_error) return {
    label: "작업공간 복구 확인 필요", detail: "원래 작업공간의 복구 상태를 확인한 뒤 충돌 해결을 진행하세요.", tone: "danger",
  };
  if (conflict.files.some((file) => !file.supported)) return {
    label: "직접 확인할 파일이 있습니다", detail: "자동 해결을 지원하지 않는 파일을 먼저 확인하세요. 파일별 비교에서 내용을 볼 수 있습니다.", tone: "warning",
  };
  if (conflict.resolution_status === "applied") {
    if (attempt?.action === "conflict_resolution_apply" && attempt.status === "succeeded" && attempt.phase === "succeeded") return {
      label: "충돌 해결·검증 완료", detail: "해결안 적용과 검증을 마쳤습니다. Main 반영은 별도로 진행하세요.", tone: "success",
    };
    const failed = attempt?.action === "conflict_resolution_apply" && attempt.phase === "verification_failed";
    return { label: failed ? "해결안 적용됨 · 검증 실패" : "해결안 적용됨 · 검증 확인 필요",
      detail: failed ? "해결안은 적용됐습니다. 검증 오류를 확인하고 필요한 내용을 수정한 뒤 다시 검증하세요."
        : "해결안은 적용됐습니다. 전체 검증 결과를 확인한 뒤 Main 반영을 진행하세요.", tone: "warning" };
  }
  const states: Record<string, RecoveryTaskPresentation> = {
    unresolved: { label: "AI 해결안 만들기", detail: "AI가 Main 변경과 작업 결과를 비교해 해결안을 만듭니다. 내용을 확인하고 적용하면 다시 검증합니다.", tone: "warning" },
    generating: { label: "AI 해결안 생성 중", detail: "양쪽 변경을 비교하고 있습니다. 완료되면 해결 내용을 확인하고 적용하세요.", tone: "active" },
    candidate_ready: { label: "해결안 확인 후 적용", detail: "AI 해결 설명을 확인한 뒤 적용하세요. 적용 후 전체 검증을 진행합니다.", tone: "warning" },
    applying: { label: "해결안 적용·검증 중", detail: "승인한 해결안을 적용하고 전체 검증을 진행하고 있습니다. 결과를 확인할 때까지 기다려 주세요.", tone: "active" },
    needs_decision: { label: "해결 방향 선택 필요", detail: "AI 해결 설명과 파일별 비교를 확인하고 유지할 동작을 결정한 뒤 해결안을 다시 만드세요.", tone: "warning" },
    stale: { label: "최신 기준으로 다시 만들기", detail: "Main 또는 작업 결과가 바뀌었습니다. 최신 변경을 기준으로 해결안을 다시 만드세요.", tone: "warning" },
    failed: { label: "해결안 생성 실패", detail: "오류 상세를 확인하고 원인을 해결한 뒤 다시 만드세요.", tone: "danger" },
    interrupted: { label: "충돌 해결 중단됨", detail: "현재 상태를 확인한 뒤 해결안을 다시 만드세요. 이전 시도는 상세에 보존됩니다.", tone: "warning" },
    workspace_recovery_required: { label: "작업공간 복구 필요", detail: "원래 작업공간의 복구 상태를 먼저 확인하세요.", tone: "danger" },
  };
  return states[conflict.resolution_status]
    || { label: "해결 상태 확인 필요", detail: "현재 처리 상태를 다시 확인한 뒤 진행하세요.", tone: "warning" };
}

export function candidateFileCopy(file: IntegrationConflictDetail["selected_file"] | undefined): string {
  if (!file) return "파일 상태를 확인하는 중입니다.";
  if (file.candidate_state === "ready") return file.candidate === "" ? "(빈 파일로 해결)" : file.candidate;
  if (file.candidate_state === "generating") return "해결안을 생성하고 있습니다.";
  if (file.candidate_state === "missing") return "후보에서 이 파일을 찾지 못했습니다.";
  if (file.candidate_state === "read_failed") return "해결안 파일을 읽지 못했습니다.";
  return file.candidate || "아직 해결안이 없습니다.";
}

export function conflictPhaseLabel(phase: string): string {
  return {
    preparing_workspace: "격리 작업공간 준비 중",
    generating: "AI 해결안 생성 중",
    checking_candidate: "후보 범위·내용 확인 중",
    candidate_ready: "해결안 검토 대기",
    validating_candidate: "승인 후보 확인 중",
    applying: "그룹 작업공간 적용 중",
    verifying: "전체 검증 중",
    verification_failed: "적용 완료·검증 실패",
    succeeded: "적용·검증 완료",
    failed: "해결 실패",
    unknown: "상태 확인 필요",
  }[phase] || phase;
}

export function attemptStatusLabel(status: string): string {
  return { running: "진행 중", succeeded: "성공", failed: "실패", interrupted: "중단", unknown: "확인 필요" }[status] || status;
}

export interface PendingConflictRequest {
  id: string;
  kind: "prepare" | "apply";
  startedAt: string;
}

export interface ConflictProgressPresentation {
  label: string;
  detail: string;
  delay: "normal" | "delayed" | "unconfirmed";
  activity?: { label: string; detail: string; lastEventAt: string; lastActivityAt: string };
}

export function conflictProgressPresentation(
  attempt: ConflictOperationAttempt | undefined,
  pending: PendingConflictRequest | undefined,
  now: number,
  lookupError = "",
  execution?: { state: "active"; phase: ActiveConflictPhase } | { state: "pending" | "unconfirmed" },
): ConflictProgressPresentation {
  const relevant = pending && attempt?.request_id !== pending.id ? undefined : attempt;
  if (execution?.state === "unconfirmed") return {
    label: "현재 실행 여부 확인 필요",
    detail: relevant?.phase ? `마지막 기록: ${conflictPhaseLabel(relevant.phase)}. 상태를 다시 확인한 뒤 진행하세요.`
      : "요청의 종료 결과를 확인하지 못했습니다. 상태를 다시 확인한 뒤 진행하세요.",
    delay: "unconfirmed",
  };
  const observed = relevant?.progress_observation;
  const observation = observed && observed.attempt_id === relevant?.request_id && observed.evidence_kind !== "local_phase"
    && observed.last_event_received_at ? observed : undefined;
  const activity = relevant?.action === "conflict_resolution_prepare" && relevant.status === "running" && relevant.phase === "generating"
    ? observation ? {
      label: progressPhaseLabels[observation.phase] || "AI 활동 수신",
      detail: observation.detail,
      lastEventAt: observation.last_event_received_at,
      lastActivityAt: observation.last_activity_changed_at,
    } : { label: "활동 정보 미수신", detail: "", lastEventAt: "", lastActivityAt: "" }
    : undefined;
  const startedAt = relevant?.created_at || pending?.startedAt || "";
  const elapsed = Math.max(0, Math.floor((now - Date.parse(startedAt)) / 1000));
  const quiet = Math.max(0, Math.floor((now - Date.parse(observation?.last_activity_changed_at || relevant?.updated_at || startedAt)) / 1000));
  const active = (pending && !relevant) || relevant?.status === "running";
  const delay = !active || !Number.isFinite(elapsed) ? "normal"
    : elapsed >= 60 ? "unconfirmed" : quiet >= 15 ? "delayed" : "normal";
  if (lookupError) return {
    label: "현재 처리 상태를 확인하지 못했습니다",
    detail: relevant?.phase ? `마지막 확인 단계: ${conflictPhaseLabel(relevant.phase)}` : "마지막 확인 상태를 보존했습니다.",
    delay, activity,
  };
  if (execution?.state === "active") return {
    label: execution.phase === "verify" ? "전체 검증 중"
      : execution.phase === "prepare" ? "AI 해결안 생성 중" : "충돌 해결 처리 중",
    detail: "현재 작업 그룹의 실행을 확인했습니다. 결과가 나오면 갱신합니다.",
    delay: Number.isFinite(quiet) && quiet >= 15 ? "delayed" : "normal",
    activity: execution.phase === "prepare" ? activity : undefined,
  };
  if (execution?.state === "pending") return {
    label: "요청 시작 확인 중",
    detail: "실행 엔진의 시작 기록과 현재 상태를 확인하고 있습니다.",
    delay,
  };
  if (pending && !relevant) return {
    label: pending.kind === "prepare" ? "생성을 요청했습니다 · 시작 확인 중" : "적용 승인·시작 확인 중",
    detail: delay === "unconfirmed" ? "60초 동안 시작·결과를 확인하지 못했습니다. 같은 요청을 다시 보내지 마세요."
      : delay === "delayed" ? "시작 확인이 늦어지고 있습니다. 상태 조회를 계속합니다." : "실행 엔진의 시작 기록을 확인하는 중입니다.",
    delay,
  };
  if (!relevant) return { label: "아직 해결안을 만들지 않았습니다", detail: "AI 생성은 명시적으로 시작합니다.", delay: "normal" };
  if (relevant.status === "running") return {
    label: conflictPhaseLabel(relevant.phase),
    detail: delay === "unconfirmed" ? "60초 동안 최종 결과를 확인하지 못했습니다. 상태 조회는 계속됩니다."
      : delay === "delayed" ? observation ? "새 활동 변화가 늦어지고 있습니다. 경과 시간만으로 중단을 판단하지 않습니다."
        : "새 단계 보고가 늦어지고 있습니다. 경과 시간만으로 중단을 판단하지 않습니다."
        : "저장된 실제 단계입니다.",
    delay, activity,
  };
  if (relevant.status === "succeeded") return {
    label: relevant.action === "conflict_resolution_prepare" ? "해결안 준비됨 · 내용을 검토해 주세요" : "해결안 적용·전체 검증 완료",
    detail: conflictPhaseLabel(relevant.phase), delay: "normal",
  };
  if (relevant.status === "failed") return {
    label: relevant.action === "conflict_resolution_prepare" ? "해결안 생성 실패" : relevant.phase === "verification_failed" ? "적용 완료 · 검증 실패" : "적용 실패",
    detail: relevant.error || conflictPhaseLabel(relevant.phase), delay: "normal",
  };
  return { label: attemptStatusLabel(relevant.status), detail: conflictPhaseLabel(relevant.phase), delay: "normal" };
}
