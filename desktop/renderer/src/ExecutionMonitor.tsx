import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertCircle, ArrowDown, Copy, Maximize2, RefreshCw, Search, Square, X } from "lucide-react";
import type { RunState, WorkTask } from "./types";
import type { TaskLogState } from "./useTaskLog";
import { summarizeProgressLog } from "./progressLog";
import { failurePresentation } from "./failurePresentation";
import {
  durationLabel, monitorTasks, selectLogLines, taskActivityLabel, taskActivityTiming,
  taskIsActive, taskOutcome, taskReviewLabel, taskFailureEvidence,
} from "./executionActivity";

const operationLabels: Record<string, string> = {
  planning: "계획 작성", agent_execution: "작업 실행", verify: "통합 검증",
  merge: "Main 반영", push: "Push", deploy: "배포", work_push: "작업 브랜치 Push",
  main_apply: "Main 반영·Push",
};

function useActivityClock(active: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

function clockLabel(at: number | undefined): string {
  return at === undefined ? "아직 없음" : new Date(at).toLocaleTimeString("ko-KR", { hour12: false });
}

interface TaskActivityProps {
  task: WorkTask;
  progressText: string;
  activeOverride?: boolean;
  statusLabel?: string;
}

export function TaskActivityLine({ task, progressText, activeOverride, statusLabel }: TaskActivityProps) {
  const active = activeOverride ?? taskIsActive(task);
  const now = useActivityClock(active);
  const timing = taskActivityTiming(task, now);
  const text = active && timing.hasCurrentProgress ? progressText || taskOutcome(task) : taskOutcome(task);
  return <span className="task-activity-line" data-active={active} data-failed={task.status === "failed"}>
    <strong>{statusLabel || taskActivityLabel(task)}</strong>
    <span title={text}>{text}</span>
    {active && timing.quietSeconds !== undefined && timing.quietSeconds >= 60
      ? <small>{timing.eventQuietSeconds !== undefined && timing.eventQuietSeconds < 60
        ? `같은 단계의 응답을 받고 있습니다 · 활동 변화 ${durationLabel(timing.quietSeconds)} 전`
        : `새 활동 변화는 아직 확인되지 않았습니다 · ${durationLabel(timing.quietSeconds)} (중단 판정 아님)`}</small> : null}
  </span>;
}

interface ExecutionOverviewProps {
  run: RunState;
  progressText(task: WorkTask): string;
  onOpenLog(taskId: string): void;
  onStop?(task: WorkTask): void;
}

export function ExecutionOverview({ run, progressText, onOpenLog, onStop }: ExecutionOverviewProps) {
  const tasks = monitorTasks(run);
  const executionSituation = run.execution_control?.situation;
  const backendRunning = executionSituation === "running" || executionSituation === "preparing";
  const active = backendRunning ? tasks.filter(taskIsActive) : [];
  const done = run.tasks.filter((task) => task.status === "completed" || task.status === "merged").length;
  const blocked = run.tasks.filter((task) => task.status === "pending" && task.blocked_by.length).length;
  const now = useActivityClock(active.length > 0);
  const mainPushPending = run.stage === "failed" && run.integration_control?.status === "main_push_pending";
  const headline = executionSituation === "preparing" ? "다음 작업 준비 중"
    : active.length ? `현재 실행 ${active.length}개`
      : executionSituation === "resumable" ? "실행 중단 · 그룹 재개 가능"
        : executionSituation === "status_unknown" ? "실행 상태 확인 필요"
          : run.integration_control?.reason_code === "main_apply_recoverable" ? "Main 반영 중단 · 복구 승인 가능"
          : run.integration_control?.reason_code === "main_apply_interrupted" ? "Main 반영 중단 · 원본 확인 필요"
          : mainPushPending ? "Main Push 실패 · 재시도 확인 필요"
          : run.stage === "failed" ? "작업 그룹 실패 · 확인 필요"
      : tasks.length ? "확인이 필요한 작업"
        : run.active_step ? `그룹 작업 진행 · ${operationLabels[run.active_step] || run.active_step}`
          : done === run.tasks.length && done > 0 ? "작업 실행 완료 · 통합 상태는 상단에서 확인"
            : "실행 중인 작업 없음";
  return <section className="execution-overview" data-has-failure={run.stage === "failed" || tasks.some((task) => task.status === "failed")} aria-label="선택 그룹의 현재 작업">
    <header><div><Activity aria-hidden="true" size={16} /><strong>{headline}</strong></div>
      <span>완료 {done}/{run.tasks.length}{blocked ? ` · 선행 대기 ${blocked}` : ""}</span></header>
    {run.stage === "failed" ? <p className="execution-overview__error">{mainPushPending
      ? "작업은 완료됐고 로컬 Main에도 반영됐습니다. 통합·정리에서 원격 상태를 확인한 뒤 Main Push만 별도로 재시도하세요."
      : failurePresentation(run.failure_message || "", run.failed_step || "execute").title}</p> : null}
    {run.stage === "failed" && run.failure_message ? <details className="execution-failure-details"><summary>작업 그룹 오류 원문</summary><pre>{run.failure_message}</pre></details> : null}
    <div className="execution-overview__tasks">
      {tasks.map((task) => {
        const timing = taskActivityTiming(task, now);
        const storedActiveTask = taskIsActive(task);
        const activeTask = backendRunning && storedActiveTask;
        const interruptedTask = executionSituation === "resumable" && storedActiveTask;
        const failure = taskFailureEvidence(task);
        const issue = failure ? failurePresentation(failure.error, task.failed_action || failure.action || "execute") : undefined;
        const worktree = task.worktree || (run.workspace_mode === "shared" ? run.execution_worktree : "");
        return <article key={task.id} data-failed={task.status === "failed"}>
          <div className="execution-overview__copy">
            <strong>{task.title || task.id}</strong>
            {failure ? <section className="execution-failure" aria-label={`${task.title} 실패 근거`}>
              <strong>{issue?.title}</strong>
              <p>{issue?.description}</p>
            </section> : <TaskActivityLine task={task} progressText={progressText(task)} activeOverride={activeTask} statusLabel={interruptedTask ? "중단됨 · 재개 필요" : undefined} />}
            <span className="execution-overview__meta">
              실행 프로필 · {task.provider_id || "제공자 미기록"} · {task.effective_model || task.model || "모델 미기록"}
              {activeTask ? ` · 현재 단계 ${durationLabel(timing.elapsedSeconds)}` : ""} · {taskReviewLabel(task)}
            </span>
            {worktree ? <span className="execution-overview__path" title={worktree}>작업공간 · {worktree}</span> : null}
          </div>
          <div className="execution-overview__actions"><button type="button" className="button button--secondary" onClick={() => onOpenLog(task.id)}>{failure && failure.responseState !== "current" ? "실패 로그 열기" : "로그 열기"}</button>{activeTask && run.execution_control?.can_stop && onStop ? <button type="button" className="button button--danger" aria-label={`${task.title} 중지`} title="작업은 보존됩니다. 다음 작업은 자동으로 시작하지 않습니다." onClick={() => onStop(task)}><Square aria-hidden="true" size={13} />중지</button> : null}</div>
        </article>;
      })}
    </div>
    {!tasks.length ? <p>작업 행의 ‘로그’에서 기록을 바로 볼 수 있습니다. 선택한 작업은 자동으로 바뀌지 않습니다.</p> : null}
  </section>;
}

interface ExecutionLogViewerProps {
  run: RunState;
  task: WorkTask;
  state: TaskLogState;
  progressText: string;
  view?: LogViewState;
  visible?: boolean;
  onViewChange?(view: LogViewState): void;
}

export interface LogViewState {
  query: string;
  wrap: boolean;
  follow: boolean;
  top: number;
  left: number;
}

export const defaultLogView: LogViewState = { query: "", wrap: true, follow: true, top: 0, left: 0 };

export function ExecutionLogViewer({ run, task, state, progressText, view, visible = true, onViewChange }: ExecutionLogViewerProps) {
  const [localView, setLocalView] = useState(defaultLogView);
  const currentView = view || localView;
  const { query, wrap, follow } = currentView;
  const changeView = (changes: Partial<LogViewState>) => {
    if (onViewChange) onViewChange({ ...currentView, ...changes });
    else setLocalView((current) => ({ ...current, ...changes }));
  };
  const [expanded, setExpanded] = useState(false);
  const [copying, setCopying] = useState<"summary" | "raw">();
  const [copyResult, setCopyResult] = useState<{ text: string; error: boolean }>();
  const viewport = useRef<HTMLPreElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const expandButton = useRef<HTMLButtonElement>(null);
  const summarized = useMemo(() => summarizeProgressLog(state.value), [state.value]);
  const filtered = useMemo(() => selectLogLines(summarized.text, query), [summarized.text, query]);
  const visibleText = useMemo(() => filtered.lines.map((line) => line.text).join("\n"), [filtered]);
  const worktree = task.worktree || (run.workspace_mode === "shared" ? run.execution_worktree : "");
  const backendRunning = run.execution_control?.situation === "running" || run.execution_control?.situation === "preparing";
  const storedActiveTask = taskIsActive(task);
  const activeTask = backendRunning && storedActiveTask;
  const interruptedTask = run.execution_control?.situation === "resumable" && storedActiveTask;

  useEffect(() => {
    if (expanded && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [expanded]);
  useEffect(() => {
    if (!viewport.current || !visible) return;
    viewport.current.scrollTop = follow ? viewport.current.scrollHeight : currentView.top;
    viewport.current.scrollLeft = currentView.left;
  }, [state.value, query, follow, expanded, wrap, visible]);
  useEffect(() => { setCopyResult(undefined); }, [query, state.value]);

  const closeExpanded = () => {
    dialog.current?.close();
    setExpanded(false);
    window.requestAnimationFrame(() => expandButton.current?.focus());
  };
  const jumpToLatest = () => {
    changeView({ query: "", follow: true });
    if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
  };
  const copyLog = async (kind: "summary" | "raw") => {
    const value = kind === "summary" ? visibleText : state.value;
    if (!value || copying) return;
    setCopying(kind);
    setCopyResult(undefined);
    try {
      await navigator.clipboard.writeText(value);
      setCopyResult({ text: kind === "summary" ? "화면에 표시된 요약 로그를 복사했습니다." : "수신한 원문 로그를 복사했습니다.", error: false });
    } catch (error: unknown) {
      setCopyResult({ text: `로그 복사 실패: ${error instanceof Error ? error.message : String(error)}`, error: true });
    } finally { setCopying(undefined); }
  };

  const content = <>
    <header className="execution-log__heading">
      <div><span>{run.summary || run.id} / {task.id}</span><h3>{task.title || task.id}</h3></div>
      {expanded ? <button className="icon-button" type="button" aria-label="넓은 로그 닫기" onClick={closeExpanded}><X aria-hidden="true" size={17} /></button>
        : <button ref={expandButton} className="button button--quiet" type="button" onClick={() => setExpanded(true)}><Maximize2 aria-hidden="true" size={15} />넓게 보기</button>}
    </header>
    <TaskActivityLine task={task} progressText={progressText} activeOverride={activeTask} statusLabel={interruptedTask ? "중단됨 · 재개 필요" : undefined} />
    <details className="execution-log__context"><summary>모델 · 리뷰 · 작업공간</summary>
      <p>실행 프로필 · {task.provider_id || "제공자 미기록"} · {task.effective_model || task.model || "모델 미기록"} · {taskReviewLabel(task)}</p>
      <p>{worktree || "작업공간 미배정"}</p>
    </details>
    <div className="execution-log__toolbar">
      <label className="execution-log__search"><Search aria-hidden="true" size={15} />
        <span className="sr-only">현재 작업 로그 검색</span>
        <input type="search" value={query} placeholder="현재 작업 로그 검색" onChange={(event) => changeView({ query: event.target.value, follow: false, top: 0, left: 0 })} />
      </label>
      <button className="button button--quiet" type="button" disabled={state.loading} onClick={state.refresh}>
        <RefreshCw aria-hidden="true" size={15} />{state.loading ? "조회 중" : state.error ? "다시 조회" : "새로고침"}
      </button>
      <label><input type="checkbox" checked={wrap} onChange={(event) => changeView({ wrap: event.target.checked })} />줄바꿈</label>
      <label><input type="checkbox" checked={follow} onChange={(event) => changeView({ follow: event.target.checked })} />자동 스크롤</label>
      <button className="button button--quiet" type="button" onClick={jumpToLatest}><ArrowDown aria-hidden="true" size={15} />최신 로그</button>
      <button className="button button--quiet" type="button" disabled={!visibleText || Boolean(copying)} onClick={() => void copyLog("summary")}><Copy aria-hidden="true" size={15} />{copying === "summary" ? "복사 중" : "요약 복사"}</button>
      <button className="button button--quiet" type="button" disabled={!state.value || Boolean(copying)} onClick={() => void copyLog("raw")}><Copy aria-hidden="true" size={15} />{copying === "raw" ? "복사 중" : "원문 복사"}</button>
    </div>
    <div className="execution-log__status">
      <span>2초마다 조회 · 확인 {clockLabel(state.checkedAt)} · 내용 변경 {clockLabel(state.changedAt)}</span>
      <span>{query.trim() ? `검색 ${filtered.matched}줄` : `요약 ${filtered.total}줄 · 원문 ${summarized.originalLineCount}줄`} · {follow ? "최신 위치 따라가는 중" : "읽는 위치 유지 · 수신은 계속"}</span>
    </div>
    {state.error ? <div className="execution-log__error" role="alert"><AlertCircle aria-hidden="true" size={16} /><span>{state.error}<br />{state.checkedAt === undefined ? "아직 로그를 받지 못했습니다." : "아래 내용은 마지막으로 받은 로그입니다."}</span></div> : null}
    {copyResult ? <p role={copyResult.error ? "alert" : "status"}>{copyResult.text}</p> : null}
    <pre ref={viewport} className="execution-log__viewport" data-wrap={wrap} tabIndex={0} aria-label={`${task.title} 로그 본문`}
      onScroll={(event) => {
        if (!visible) return;
        const node = event.currentTarget;
        changeView({ top: node.scrollTop, left: node.scrollLeft,
          follow: follow && node.scrollHeight - node.scrollTop - node.clientHeight <= 48 });
      }}>
      {filtered.lines.length ? filtered.lines.map((line) => <span className="execution-log__line" key={line.number}><span className="execution-log__number" aria-hidden="true">{line.number}</span><span>{line.text || " "}</span></span>)
        : state.loading && state.checkedAt === undefined ? "로그 불러오는 중…"
          : state.error && !state.value ? "로그 조회에 실패했습니다. ‘다시 조회’를 눌러 주세요."
            : query.trim() ? "검색 결과가 없습니다. 검색어를 지우면 수신한 로그를 다시 볼 수 있습니다."
              : "아직 수신한 로그가 없습니다. 출력이 없는 작업을 실패로 판단하지 않습니다."}
    </pre>
    <p className="execution-log__scope">검색과 요약 복사는 현재 요약 범위에 적용됩니다. 원문 복사는 수신한 줄바꿈을 유지합니다. 기존 RPC/화면 로그 길이 제한은 유지됩니다.
      {filtered.omitted ? ` 표시 성능을 위해 일치하는 ${filtered.matched}줄 중 마지막 ${filtered.lines.length}줄만 표시합니다.` : ""}
      {activeTask && task.progress_phase === "verifying_command" ? " 검증 명령 출력은 명령 종료 후 도착할 수 있습니다." : ""}
    </p>
  </>;

  return <section className="execution-log" aria-label="작업 로그 작업창">
    {expanded ? <dialog ref={dialog} className="execution-log-dialog" aria-label={`${task.title} 넓은 로그`} onCancel={(event) => { event.preventDefault(); closeExpanded(); }}>{content}</dialog> : content}
  </section>;
}
