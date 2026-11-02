import { ArrowRight, Check } from "lucide-react";
import { taskActivityTiming, taskFailureEvidence, taskIsActive } from "./executionActivity";
import type { RunState, UsageSnapshot, WorkTask } from "./types";
import { AiBadge } from "./AiBadge";
import { providerFailurePresentation } from "./providerFailure";
import { providerRetryWait } from "./providerRetry";

export function executionOnTaskCards(run: RunState): boolean {
  const control = run.execution_control;
  return run.stage === "executing" && ["running", "preparing"].includes(control?.situation || "")
    && run.tasks.some(taskIsActive) && (!run.active_step || run.active_step === "agent_execution")
    && (!control?.dispatch_paused || control.stop_phase === "stopping");
}

export function TaskFlow({ run, selectedTaskId, onOpen, onStop, onRetry, onPlanning, onToggle, selectedTaskIds = [], planningTaskIds = [], busy = false, retryAllowed = false, usage, usageError, activity }: {
  run: RunState; selectedTaskId: string; onOpen(taskId: string): void;
  onStop?(task: WorkTask): void; onRetry?(taskId: string): void; onPlanning?(taskId: string): void;
  onToggle?(taskId: string): void; selectedTaskIds?: string[]; busy?: boolean; retryAllowed?: boolean;
  planningTaskIds?: string[];
  usage?: UsageSnapshot; usageError?: string;
  activity?(task: WorkTask): string;
}) {
  const labels: Record<string, string> = { completed: "완료", merged: "완료", running: "실행 중", reviewing: "검증·리뷰 중",
    revising: "수정 중", failed: "실패", stopped: "중지됨", pending: "대기", waiting: "확인 대기", excluded: "제외됨" };
  return <section className="task-flow" aria-label="작업 순서">
    {!run.tasks.length ? <p className="task-flow__empty" role="status">이 그룹에 표시할 작업이 없습니다.</p> : null}
    <ol className="task-flow__cards">{run.tasks.map((task, index) => {
      const planning = planningTaskIds.includes(task.id);
      const storedActive = taskIsActive(task);
      const active = storedActive && ["running", "preparing"].includes(run.execution_control?.situation || "");
      const interrupted = storedActive && run.execution_control?.situation === "resumable";
      const stopped = task.status === "stopped" || interrupted && run.execution_control?.stop_phase === "stopped";
      const nextTask = run.tasks[index + 1];
      const connectsNext = Boolean(nextTask && [...(nextTask.dependencies || []), ...(nextTask.conflict_dependencies || [])].includes(task.id));
      const canStop = active && run.execution_control?.can_stop && run.execution_control.execution_id
        && (!run.execution_control.active_task_id || run.execution_control.active_task_id === task.id)
        && run.execution_control.stop_phase !== "stopping";
      const stopping = active && run.execution_control?.stop_phase === "stopping"
        && (!run.execution_control.active_task_id || run.execution_control.active_task_id === task.id);
      const status = planning ? "현재 Task 수정 중" : stopping ? "중지 요청 중" : stopped ? "중지됨" : interrupted ? "중단됨 · 재개 필요" : storedActive && !active ? "실행 상태 확인 필요"
        : task.status === "failed" ? providerFailurePresentation(taskFailureEvidence(task)?.error || task.error)?.label || labels.failed
        : task.status === "pending" && task.readiness === "blocked" ? "앞 작업 대기" : labels[task.status] || task.status;
      const timing = active ? taskActivityTiming(task, Date.now()) : undefined;
      const retryWait = timing?.hasCurrentProgress ? providerRetryWait(task.progress_phase, task.progress_detail) : undefined;
      return <li key={task.id} className="task-flow-card-group">
      <button id={`task-row-${task.id}`} type="button" className="task-flow-card" data-selected={selectedTaskId === task.id}
        data-active={active} data-status={stopped ? "stopped" : task.status} aria-haspopup="dialog" onClick={() => onOpen(task.id)}>
        <span className="task-flow-card__number">{String(index + 1).padStart(2, "0")}</span><strong>{task.title}</strong>
        <span className="task-flow-card__status" role={planning ? "status" : undefined} data-running={active && !stopping && !planning}>
          {!planning && active && !stopping ? <span className="task-flow-card__running-dot" aria-hidden="true" />
            : !planning && ["completed", "merged"].includes(task.status) ? <Check aria-hidden="true" size={16} /> : null}
          {status}
        </span>
        {active ? <small className="task-flow-card__activity">{retryWait || activity?.(task) || "활동 보고 대기"}</small> : null}
        {!retryWait && (timing?.quietSeconds ?? 0) >= 60 ? <small>새 활동 없음 · 중단 미확인</small> : null}
      </button>
      <AiBadge compact provider={task.provider_id} requestedModel={task.model} effectiveModel={task.effective_model}
        requestedReasoning={task.reasoning_effort} effectiveReasoning={task.effective_reasoning_effort} planned={task.status === "pending"}
        usage={usage?.task_summaries?.find((item) => item.task_id === task.id)} usageKnown={Boolean(usage?.task_summaries)} usageError={usageError} />
      {onToggle || canStop && onStop || onPlanning || task.status === "failed" && onRetry && retryAllowed ? <div className="task-flow-card__actions">
        {onToggle ? <label><input type="checkbox" checked={selectedTaskIds.includes(task.id)} disabled={busy || planning} onChange={() => { if (!busy && !planning) onToggle(task.id); }} />선택</label> : null}
        {canStop && onStop ? <button className="button button--danger" type="button" aria-label={`${task.title} 중지`} onClick={() => onStop(task)}>작업 중지</button> : null}
        {task.status === "failed" && onRetry && retryAllowed ? <button className="button button--primary task-flow-card__retry" type="button" disabled={busy || planning}
          title={planning ? "AI가 Task 수정안을 처리하고 있습니다. 수정이 끝나면 다시 실행할 수 있습니다."
            : "현재 저장된 계획과 수정 지시로 이 작업만 다시 실행합니다. 미리보기의 미적용 변경은 포함하지 않습니다."}
          onClick={() => { if (!busy && !planning) onRetry(task.id); }}>{planning ? "현재 Task 수정 중" : "현재 계획 재실행"}</button> : null}
        {onPlanning ? <button className="button button--secondary" type="button" aria-label={`${task.title} ${task.status === "failed" ? "AI 도움 요청" : "AI 질문"}`}
          disabled={planning} onClick={() => { if (!planning) onPlanning(task.id); }}>{task.status === "failed" ? "AI 도움 요청" : "AI 질문"}</button> : null}
      </div> : null}
      {connectsNext ? <ArrowRight className="task-flow__arrow" aria-hidden="true" size={18} /> : null}
    </li>;
    })}</ol>
  </section>;
}
