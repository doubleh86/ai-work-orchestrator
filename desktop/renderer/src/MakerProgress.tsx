import { useEffect, useState } from "react";
import { makerStage } from "./makerPresentation";
import { progressPhaseLabels } from "./progressLog";
import { runExecutionActionAllowed } from "./runExecutionControl";
import type { RunState } from "./types";

export interface MakerProgressState {
  label: string;
  detail: string;
  tone: "active" | "warning" | "error" | "neutral";
  elapsed?: number;
  activityAge?: number;
  eventAge?: number;
}

function age(value: string | undefined, now: number): number | undefined {
  const time = Date.parse(value || "");
  return Number.isFinite(time) && time <= now ? Math.floor((now - time) / 1000) : undefined;
}

export function makerProgress(run: RunState, now: number, checkedAt: number, readError = false): MakerProgressState {
  const control = run.execution_control;
  const state = (label: string, detail = "", tone: MakerProgressState["tone"] = "neutral"): MakerProgressState => ({ label, detail, tone });
  if (readError || !checkedAt || checkedAt > now || now - checkedAt >= 15_000) return state("상태 확인 지연", "상태 확인을 눌러 주세요.", "warning");
  const checkedAge = control?.checked_at ? age(control.checked_at, now) : undefined;
  if (control?.checked_at && (checkedAge === undefined || checkedAge >= 15)) {
    return state("상태 확인 지연", "상태 확인을 눌러 주세요.", "warning");
  }
  if (control?.lock_state === "stale") return state("중단된 실행 확인 필요", "상태를 확인한 뒤 이어서 진행하세요.", "warning");
  if (control?.situation === "status_unknown" || ["unverifiable", "malformed", "unknown"].includes(control?.lock_state || "")) {
    return state("실행 여부 확인 필요", "현재 실행 상태를 확인하지 못했어요.", "warning");
  }
  if (control?.stop_phase === "stopping") return state("중지 확인 중", control.active_task_title);
  if (control?.stop_phase === "stopped" && control.lock_state === "unlocked") return state("제작이 중지됐어요",
    runExecutionActionAllowed(run, "runs.resume") ? "이어서 제작할 수 있어요." : "다음 작업을 위해 상태를 확인하세요.");
  if (run.stage === "failed") return state("작업에 문제가 생겼어요", "관제 AI에 문제 확인을 요청하세요.", "error");
  if (control?.situation === "waiting_user_check") return state("직접 확인을 기다려요", "아래 확인 항목을 기록해 주세요.", "warning");
  if (control?.lock_state === "unlocked" && control.situation === "resumable" && run.stage === "executing") {
    return state("제작이 멈춰 있어요", runExecutionActionAllowed(run, "runs.resume") ? "이어서 제작할 수 있어요." : "확인할 항목을 확인해 주세요.");
  }
  if (control?.lock_state === "active" && ["running", "preparing"].includes(control.situation)) {
    if (run.active_step === "verify") {
      const attempt = run.verification_attempts?.at(-1);
      const elapsed = attempt?.status === "running" ? age(attempt.started_at, now) : undefined;
      const changed = elapsed !== undefined ? age(run.verification_progress_updated_at, now) : undefined;
      const activityAge = changed !== undefined && elapsed !== undefined && changed <= elapsed ? changed : undefined;
      const delayed = (activityAge ?? elapsed ?? 0) >= 90;
      return { label: delayed ? "검사 결과 대기 중" : "결과 검사 중", detail: delayed ? "새 진행 변화가 없어요. 중단으로 확정된 상태는 아니에요." : "결과가 나오면 갱신해요.",
        tone: delayed ? "warning" : "active", elapsed, activityAge };
    }
    const task = control.active_task_id ? run.tasks.find(item => item.id === control.active_task_id)
      : run.tasks.find(item => item.active_action || ["running", "reviewing", "revising"].includes(item.status));
    const attempt = control.active_attempt_id || task?.last_attempt_id;
    const invocation = control.active_invocation_id || task?.active_invocation_id;
    const currentTask = !control.active_attempt_id || control.active_attempt_id === task?.last_attempt_id;
    const observation = task?.progress_observation;
    const observed = currentTask && observation && attempt && observation.attempt_id === attempt
      && (!invocation || observation.invocation_id === invocation)
      && ["provider_event", "activity_change", "retry_wait"].includes(observation.evidence_kind)
      && age(observation.last_event_received_at, now) !== undefined ? observation : undefined;
    const elapsed = currentTask ? age(task?.last_attempt_started_at, now) : undefined;
    const activityAge = observed ? age(observed.last_activity_changed_at, now) : undefined;
    const eventAge = observed ? age(observed.last_event_received_at, now) : undefined;
    const quiet = activityAge ?? elapsed;
    const delayed = quiet !== undefined && quiet >= 90;
    const label = observed?.evidence_kind === "retry_wait" ? "AI 응답 재시도 대기" : delayed ? "새 활동 대기 중" : observed ? progressPhaseLabels[observed.phase] || "작업 중"
      : control.situation === "preparing" ? "다음 작업 준비 중" : "작업 중";
    return { label, detail: delayed ? "실행은 확인됐어요. 중단으로 확정된 상태는 아니에요."
      : control.active_task_title || task?.title || "활동 정보를 확인하고 있어요.",
      tone: delayed ? "warning" : "active", elapsed, activityAge, eventAge };
  }
  if (run.stage === "executing" || run.active_step) return state("실행 여부 확인 필요", "상태 확인을 눌러 주세요.", "warning");
  return state(makerStage(run), run.stage === "planned" ? "시작 전에 현재 설정을 확인하세요." : "");
}

function duration(seconds: number): string {
  return seconds < 60 ? `${seconds}초` : seconds < 3600 ? `${Math.floor(seconds / 60)}분 ${seconds % 60}초`
    : `${Math.floor(seconds / 3600)}시간 ${Math.floor(seconds % 3600 / 60)}분`;
}

export function MakerProgress({ run, checkedAt, readError, completedCount, onReviewPlan }: {
  run: RunState; checkedAt: number; readError: boolean; completedCount: number; onReviewPlan(): void;
}) {
  const [, refreshClock] = useState(0);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    function tick() { refreshClock(value => value + 1); timer = setTimeout(tick, 1000); }
    timer = setTimeout(tick, 1000);
    return () => clearTimeout(timer);
  }, []);
  const view = makerProgress(run, Date.now(), checkedAt, readError);
  const timing = [view.elapsed !== undefined ? `현재 작업 ${duration(view.elapsed)}` : "",
    view.activityAge !== undefined ? `마지막 활동 ${duration(view.activityAge)} 전`
      : view.tone === "active" || view.elapsed !== undefined ? "활동 시각 정보 없음" : "",
    view.eventAge !== undefined && view.eventAge !== view.activityAge ? `최근 신호 ${duration(view.eventAge)} 전` : ""].filter(Boolean).join(" · ");
  return <section className="maker-status maker-live-status" data-tone={view.tone} aria-label="제작 상태">
    <span className="maker-status-dot" aria-hidden="true" />
    <div><strong role="status">{view.label}</strong>{view.detail ? <p>{view.detail}</p> : null}
      {timing ? <p>{timing}</p> : null}
    </div>
    {run.stage === "planned" ? <button className="maker-button" disabled={readError} onClick={onReviewPlan}>
      {run.plan_revision === run.plan_approved_revision ? "확정한 계획 보기" : "제작 계획 확인"}</button> : null}
    <span>{completedCount} / {run.tasks.length} 작업 완료</span>
  </section>;
}
