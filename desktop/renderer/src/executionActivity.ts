import type { RunState, WorkTask } from "./types";
import { failurePresentation } from "./failurePresentation";

const terminalStatuses = new Set(["completed", "merged", "failed", "stopped", "cancelled"]);
const runningStatuses = new Set(["running", "reviewing", "revising"]);
const actionLabels: Record<string, string> = {
  execute: "구현 중", review: "리뷰 중", revise: "수정 중", verify: "검증 중",
};
const statusLabels: Record<string, string> = {
  pending: "대기", running: "실행 중", reviewing: "리뷰 중", revising: "수정 중",
  waiting: "수동 확인 필요", completed: "완료", failed: "실패", merged: "Main 반영",
  stopped: "사용자 중지", cancelled: "취소",
};
const reviewLabels: Record<string, string> = {
  pending: "리뷰 대기", running: "리뷰 중", reviewing: "리뷰 중", approved: "리뷰 승인",
  passed: "리뷰 통과", rejected: "수정 필요", changes_requested: "수정 필요",
  failed: "리뷰 실패", not_required: "리뷰 대상 아님",
};

export function taskIsActive(task: WorkTask): boolean {
  if (terminalStatuses.has(task.status) || task.status === "waiting") return false;
  return runningStatuses.has(task.status) || Boolean(task.active_action)
    || task.action_results.at(-1)?.status === "running";
}

export function taskActivityLabel(task: WorkTask): string {
  if (taskIsActive(task)) {
    const action = task.active_action
      || (task.action_results.at(-1)?.status === "running" ? task.action_results.at(-1)?.action : "");
    return (action && actionLabels[action]) || statusLabels[task.status] || task.status;
  }
  if (task.status === "pending" && task.blocked_by.length) return "선행 작업 대기";
  return statusLabels[task.status] || task.status;
}

export function taskReviewLabel(task: WorkTask): string {
  return reviewLabels[task.review_status] || task.review_status || "리뷰 상태 미기록";
}

export function taskOutcome(task: WorkTask): string {
  if (task.status === "failed") {
    const failure = taskFailureEvidence(task);
    return failurePresentation(failure?.error || "", task.failed_action || failure?.action || "execute").title;
  }
  if (task.status === "stopped") return "사용자가 중지했습니다. 변경과 로그를 보존했으며 그룹 재개 후 이어서 진행합니다.";
  if (task.status === "waiting") return task.error || "작업 결과를 확인한 뒤 수동 완료 여부를 결정하세요.";
  if (task.status === "pending") {
    return task.blocked_by.length ? `선행 작업: ${task.blocked_by.join(", ")}` : "아직 실행하지 않았습니다.";
  }
  if (terminalStatuses.has(task.status)) {
    const result = [...task.action_results].reverse().find((item) => item.worker_response.trim());
    return result?.worker_response.trim().split(/\r?\n/).find((line) => line.trim())
      || (task.status === "completed" ? "실행 완료 · 상세에서 변경 및 검증 결과를 확인하세요." : taskActivityLabel(task));
  }
  return "새 활동 보고를 기다리고 있습니다.";
}

export type FailureResponseState = "current" | "missing" | "previous_only";

export interface TaskFailureEvidence {
  error: string;
  response: string;
  action: string;
  responseState: FailureResponseState;
}

/** Only a result linked to the current failed attempt can explain this failure. */
export function taskFailureEvidence(task: WorkTask): TaskFailureEvidence | undefined {
  if (task.status !== "failed") return undefined;
  const latest = task.action_results.at(-1);
  const attemptStarted = Date.parse(task.last_attempt_started_at || "");
  const attemptFinished = Date.parse(task.last_attempt_finished_at || "");
  const resultStarted = Date.parse(latest?.started_at || "");
  const resultFinished = Date.parse(latest?.finished_at || "");
  const resultTime = Number.isFinite(resultFinished) ? resultFinished : resultStarted;
  const exactAttempt = Boolean(task.last_attempt_id || latest?.attempt_id)
    ? Boolean(task.last_attempt_id && latest?.attempt_id && task.last_attempt_id === latest.attempt_id)
    : Number.isFinite(attemptStarted)
      ? Number.isFinite(resultTime) && resultTime >= attemptStarted
      : Number.isFinite(attemptFinished) && Number.isFinite(resultFinished) && attemptFinished === resultFinished;
  const current = latest?.status === "failed"
    && (!task.failed_action || latest.action === task.failed_action)
    && exactAttempt;
  const response = current ? latest.worker_response.trim() : "";
  const previousResponseExists = !current && task.action_results.some((result) => result.worker_response.trim());
  return {
    error: task.error || (current ? latest.error : "") || "실패 상세가 기록되지 않았습니다.",
    response,
    action: current ? latest.action : "",
    responseState: response ? "current" : previousResponseExists ? "previous_only" : "missing",
  };
}

function timeValue(value: string | undefined): number | undefined {
  const time = Date.parse(value || "");
  return Number.isFinite(time) ? time : undefined;
}

export interface ActivityTiming {
  elapsedSeconds?: number;
  phaseElapsedSeconds?: number;
  quietSeconds?: number;
  eventQuietSeconds?: number;
  lastEventAt?: string;
  lastActivityAt?: string;
  hasCurrentProgress: boolean;
}

/** Saved timestamps are evidence, not a heartbeat or an estimated completion time. */
export function taskActivityTiming(task: WorkTask, now: number): ActivityTiming {
  const latest = task.action_results.at(-1);
  const active = taskIsActive(task);
  const preparingTask = active && task.progress_phase === "preparing_task";
  const currentResultAttempt = !task.last_attempt_id || !latest?.attempt_id || latest.attempt_id === task.last_attempt_id;
  const currentResult = !preparingTask
    && (!active || (latest?.status === "running" && currentResultAttempt && (!task.active_action || latest.action === task.active_action)))
    ? latest
    : undefined;
  const betweenActions = active && !preparingTask && Boolean(latest) && !currentResult;
  const progress = timeValue(task.progress_updated_at);
  const observation = task.progress_observation;
  const currentObservation = active && observation
    && (task.last_attempt_id
      ? observation.attempt_id === task.last_attempt_id
      : !task.active_action || observation.attempt_id.endsWith(`:${task.active_action}`)) ? observation : undefined;
  const started = preparingTask ? progress : betweenActions ? undefined : timeValue(currentResult?.started_at || task.last_attempt_started_at);
  const finished = timeValue(currentResult?.finished_at || task.last_attempt_finished_at);
  const progressMatchesAttempt = !observation || Boolean(currentObservation);
  const hasCurrentProgress = active && !betweenActions && progress !== undefined
    && progressMatchesAttempt && (started === undefined || progress >= started);
  const lastEvent = timeValue(currentObservation?.last_event_received_at);
  const lastActivity = timeValue(currentObservation?.last_activity_changed_at);
  const phaseStarted = timeValue(currentObservation?.phase_started_at);
  const providerWaiting = task.progress_phase === "provider_retry_wait";
  const quietBase = lastActivity ?? (providerWaiting ? undefined : progress);
  const lastActivityAt = hasCurrentProgress
    ? currentObservation?.last_activity_changed_at || (providerWaiting ? undefined : task.progress_updated_at) : undefined;
  const end = active ? now : finished;
  return {
    elapsedSeconds: started !== undefined && end !== undefined
      ? Math.max(0, Math.floor((end - started) / 1000)) : undefined,
    phaseElapsedSeconds: hasCurrentProgress && phaseStarted !== undefined ? Math.max(0, Math.floor((now - phaseStarted) / 1000)) : undefined,
    quietSeconds: hasCurrentProgress && quietBase !== undefined
      ? Math.max(0, Math.floor((now - quietBase) / 1000)) : undefined,
    eventQuietSeconds: hasCurrentProgress && lastEvent !== undefined ? Math.max(0, Math.floor((now - lastEvent) / 1000)) : undefined,
    lastEventAt: hasCurrentProgress ? currentObservation?.last_event_received_at : undefined,
    lastActivityAt,
    hasCurrentProgress,
  };
}

export function durationLabel(seconds: number | undefined): string {
  if (seconds === undefined) return "시간 미기록";
  const safe = Math.max(0, Math.floor(seconds));
  return safe >= 3600
    ? `${Math.floor(safe / 3600)}시간 ${Math.floor(safe % 3600 / 60)}분`
    : `${Math.floor(safe / 60)}분 ${safe % 60}초`;
}

export function monitorTasks(run: RunState): WorkTask[] {
  const active = run.tasks.filter(taskIsActive);
  const needsAttention = run.tasks.filter((task) => ["failed", "stopped", "waiting"].includes(task.status));
  return [...active, ...needsAttention];
}

export interface LogLine { number: number; text: string; }
export interface LogSelection { lines: LogLine[]; matched: number; total: number; omitted: number; }

/** Literal search: no user-controlled regex and no HTML interpretation. */
export function selectLogLines(value: string, query: string, limit = 1500): LogSelection {
  const source = value ? value.split(/\r?\n/) : [];
  const keyword = query.trim().toLocaleLowerCase();
  const matches = source.flatMap((text, index) => !keyword || text.toLocaleLowerCase().includes(keyword)
    ? [{ number: index + 1, text }] : []);
  const size = Math.max(1, Math.floor(Number.isFinite(limit) ? limit : 1500));
  return { lines: matches.slice(-size), matched: matches.length, total: source.length,
    omitted: Math.max(0, matches.length - size) };
}
