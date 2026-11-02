import { AlertCircle, CircleDot, ListChecks, MessageSquare, RefreshCw } from "lucide-react";
import type { RunState, WorkTask, TaskRetryContext } from "./types";
import type { RunNextAction } from "./runNextAction";
import { chatRecoveryTask } from "./chatTaskRecovery";
import { failurePresentation, isTaskScopeReview, isTaskVerificationTimeout } from "./failurePresentation";

export function currentChatFailure(run?: RunState): WorkTask | undefined {
  if (!run || run.active_step === "planning" || run.tasks.some(task => ["running", "reviewing", "revising"].includes(task.status))) return;
  return run.tasks.find(task => task.status === "failed");
}

export function ChatWorkStatus({ run, action, recovering, stopping }: {
  run?: RunState; action?: RunNextAction; recovering?: boolean; stopping?: boolean;
}) {
  const active = run?.tasks.find(task => task.id === run.execution_control?.active_task_id)
    || run?.tasks.find(task => ["running", "reviewing", "revising"].includes(task.status));
  const done = run?.tasks.filter(task => task.status === "completed").length || 0;
  return <div className="chat-work-status" data-tone={recovering || stopping ? "active" : action?.tone || "neutral"} role="status">
    <CircleDot aria-hidden="true" size={14} /><strong>{stopping ? "작업 중지 중" : recovering ? "복구 작업 중" : run ? action?.status || "상태 확인 중" : "새 작업 준비"}</strong>
    {run?.tasks.length ? <span>{done}/{run.tasks.length} 완료</span> : null}
    <span className="chat-work-status__task" title={active?.title}>{active?.title}</span>
  </div>;
}

export function ChatWorkActivity({ run, action, busy, repairing, recovering, stopping, recoveryElapsed, recoveryDisabled, recovery, onRefreshRecovery, onCancelRecovery, onAction, onDiscuss, onRecover, onTasks }: {
  run: RunState; action?: RunNextAction; busy: boolean; repairing: boolean;
  recovering?: boolean; stopping?: boolean; recoveryElapsed?: number; recoveryDisabled?: boolean;
  onAction(action: RunNextAction): void; onDiscuss(taskId: string): void; onTasks(): void;
  onRecover?(taskId: string): void;
  recovery?: TaskRetryContext["recovery"]; onRefreshRecovery?(): void; onCancelRecovery?(): void;
}) {
  if ((recovering || stopping) && !run.archive) return <section className="planning-chat-activity" data-inline="true" role="status" aria-label={stopping ? "중지 진행" : "복구 진행"}>
    <div className="chat-work-activity__heading"><RefreshCw className="spin" aria-hidden="true" size={18} />
      <strong>{stopping ? "작업을 멈추고 있습니다" : "복구 작업 중입니다"}</strong><span>{recoveryElapsed || 0}초 경과</span></div>
    {stopping && onCancelRecovery ? <button className="button button--quiet" type="button" onClick={onCancelRecovery}>복구 예약 취소</button> : null}
  </section>;
  if (repairing || run.archive) return null;
  const failed = currentChatFailure(run);
  const active = run.tasks.find(task => ["running", "reviewing", "revising"].includes(task.status));
  const repair = active ? [...run.events].reverse().find(event => event.kind === "task_repair" && event.message.startsWith(`${active.id} `)) : undefined;
  const repairCount = repair?.message.match(/자동 수정합니다 · (\d+)\/(\d+)/);
  const complete = run.tasks.length > 0 && run.tasks.every(task => task.status === "completed");
  const issue = failed?.error || (run.stage === "failed" ? run.failure_message : "");
  const recoverable = failed ? chatRecoveryTask(run, failed.id) : undefined;
  const scopeReview = isTaskScopeReview(issue || "") || recovery?.reason_code === "task_scope_review_required";
  const failure = issue ? failurePresentation(scopeReview ? "task_scope_review_required:" : issue, failed?.failed_action || "") : undefined;
  const verificationTimeout = !scopeReview && Boolean(failed && issue && isTaskVerificationTimeout(issue, failed.failed_action || ""));
  const repeatedTimeout = verificationTimeout && recovery?.kind === "diagnose";
  if (complete && !failed && !issue) return null;
  const title = scopeReview ? "수정 범위를 확인해 주세요" : failed ? "작업이 멈췄어요"
    : issue ? "작업을 진행하지 못했어요" : active && repairCount ? "자동 수정 시도가 기록됐어요"
      : run.stage === "planned" ? "작업 계획이 준비됐어요" : "작업 알림";
  if (!failed && !issue && !repairCount && run.stage !== "planned"
    && (!action || action.kind === "none" || action.kind === "planning")) return null;
  return <section className="chat-work-activity" data-tone={failed || issue ? "warning" : "neutral"}
    aria-label="현재 작업 알림">
    <div className="chat-work-activity__heading">{failed || issue ? <AlertCircle aria-hidden="true" size={18} />
      : <ListChecks aria-hidden="true" size={18} />}<strong>{title}</strong></div>
    {failed ? <p>{failed.title}</p> : null}
    {failure && !scopeReview ? <p>{failure.title}</p> : null}
    {scopeReview && failure ? <p>{failure.description}</p> : null}
    {verificationTimeout && recovery?.will_change && recovery.can_execute ? <p>{recovery.current_limits.map((value, index) =>
      value !== recovery.proposed_limits[index] ? `${index ? "전체" : "명령"} ${value}초 → ${recovery.proposed_limits[index]}초` : "").filter(Boolean).join(" · ")}</p> : null}
    {verificationTimeout && recovery && !recovery.will_change ? <p>현재 한도 · 명령 {recovery.current_limits[0]}초 · 전체 {recovery.current_limits[1]}초</p> : null}
    {repairCount && active && !failed ? <p>자동 수정 시도 {repairCount[1]}/{repairCount[2]} · {active.title}</p> : null}
    {run.stage === "planned" ? <><ol>{run.tasks.slice(0, 3).map(task => <li key={task.id}>{task.title}</li>)}</ol>
      {run.tasks.length > 3 ? <p>그 외 {run.tasks.length - 3}개 작업</p> : null}</> : null}
    {issue ? <details><summary>오류 상세</summary><pre>{issue}</pre></details> : null}
    <div className="chat-work-activity__actions">
      {recoverable && onRecover && !repeatedTimeout && !scopeReview ? <button className="button button--primary" type="button" disabled={busy || repairing || recoveryDisabled || (verificationTimeout && !recovery) || recovery?.can_execute === false}
        onClick={() => onRecover(recoverable.id)}><RefreshCw aria-hidden="true" size={15} />
        {verificationTimeout ? !recovery ? "복구 가능 상태 확인 중" : recovery.kind === "verify_with_timeout_adjustment" ? "검증 한도 보완 후 계속"
          : recovery.kind === "verify" ? recovery.history_known ? "변경된 조건으로 검증" : "검증 다시 확인" : "상태 확인 필요" : "수정하고 계속"}</button> : null}
      {verificationTimeout && onRefreshRecovery ? <button className="button button--quiet" type="button" disabled={busy} onClick={onRefreshRecovery}>상태 다시 확인</button> : null}
      {failed ? <button className="button button--secondary" type="button" disabled={busy || repairing}
        onClick={() => onDiscuss(failed.id)}><MessageSquare aria-hidden="true" size={15} />{scopeReview ? "수정 범위 논의" : repeatedTimeout ? "지연 원인 물어보기" : "원인 물어보기"}</button>
        : run.stage === "planned" ? <button className="button button--primary" type="button" onClick={onTasks}>계획·실행 확인</button>
            : action && action.kind !== "none" && action.kind !== "planning" ? <button className="button button--secondary" type="button"
              disabled={busy || action.disabled} onClick={() => onAction(action)}>{action.label}</button> : null}
    </div>
  </section>;
}
