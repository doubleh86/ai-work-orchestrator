import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, MessageSquare, Play } from "lucide-react";
import type { RunNextAction } from "./runNextAction";
import type { RunState, WorkTask } from "./types";

export interface RunPreparationProps {
  run: RunState;
  action: RunNextAction;
  blocked: boolean;
  blockingAction?: ReactNode;
  busy: boolean;
  planDirty: boolean;
  draftConflict: boolean;
  draftErrorCount: number;
  invalidTaskIds: string[];
  settings: ReactNode;
  profileSummary(task: WorkTask): string;
  profileEditor(task: WorkTask): ReactNode;
  onAction(action: RunNextAction): void;
  onReset(): void;
  onReviewErrors(): void;
  onOpenTask(taskId: string): void;
  onDiscuss(): void;
}

/** 실행 전 요약만 담당한다. 저장·확정·실행은 기존 App의 명령 경로를 사용한다. */
export function RunPreparation(props: RunPreparationProps) {
  const { run, action, blocked, blockingAction, busy, planDirty, draftConflict, draftErrorCount, invalidTaskIds } = props;
  const [editingIds, setEditingIds] = useState<string[]>([]);
  const settingsRef = useRef<HTMLDetailsElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const wasDirty = useRef(planDirty);
  const editorId = useId();
  useEffect(() => {
    if (wasDirty.current && !planDirty && !draftConflict) setEditingIds([]);
    wasDirty.current = planDirty;
  }, [planDirty, draftConflict]);
  const invalid = new Set(invalidTaskIds);
  // 목록을 접어도 확인이 필요한 작업은 항상 노출한다.
  const visibleTasks = run.tasks.filter((task, index) => index < 3 || invalid.has(task.id));
  const remainingTasks = run.tasks.filter((task) => !visibleTasks.includes(task));
  const editorTasks = run.tasks.filter((task) => editingIds.includes(task.id) && task.status === "pending");
  const hasInvalid = invalidTaskIds.length > 0;
  const confirmationRequired = Boolean(planDirty || run.effort_control?.requires_plan_review
    || run.plan_revision && run.plan_revision !== run.plan_approved_revision);
  const ready = action.kind === "execute" && !confirmationRequired && !hasInvalid && !draftConflict && !draftErrorCount && !blocked && !action.disabled;
  const title = draftConflict ? "저장된 계획이 바뀌었어요"
    : blocked ? "현재 작업 상태를 확인해 주세요"
    : draftErrorCount ? "입력 내용을 확인해 주세요"
    : hasInvalid ? "실행 AI를 확인해 주세요"
    : planDirty ? "변경한 계획을 확정해 주세요"
    : ready ? "작업을 시작할 수 있어요" : action.status;
  const description = draftConflict ? "초안은 보존했습니다. 내용을 검토한 뒤 변경을 취소하면 최신 계획을 불러옵니다."
    : blocked ? "진행 중인 요청이나 잠금 상태를 확인한 뒤 다음 단계로 진행할 수 있어요."
    : draftErrorCount ? `입력 오류 ${draftErrorCount}건이 있어요. 해당 작업의 내용을 확인해 주세요.`
    : hasInvalid ? `${invalidTaskIds.length}개 작업의 모델을 사용할 수 없어요. 연결과 실행 모델을 확인해 주세요.`
    : planDirty ? "변경 내용을 저장하고 계획을 확정한 뒤 시작할 수 있어요."
    : ready ? "확정한 계획과 실행 설정으로 작업을 시작합니다." : action.description;
  const label = draftConflict ? "변경 검토 필요" : draftErrorCount ? "입력 오류 확인"
    : hasInvalid ? "실행 AI 확인" : action.label;
  const disabled = busy || blocked || draftConflict || (!hasInvalid && !draftErrorCount
    && (action.disabled || action.kind === "none" || action.kind === "execute" && confirmationRequired)) || !run.tasks.length;
  const openEditor = (ids: string[]) => {
    if (busy || blocked || draftConflict) return;
    setEditingIds(ids);
    window.requestAnimationFrame(() => {
      editorRef.current?.scrollIntoView({ block: "nearest" });
      editorRef.current?.querySelector<HTMLSelectElement>("select:not(:disabled)")?.focus({ preventScroll: true });
    });
  };
  const invoke = () => {
    if (disabled) return;
    if (draftErrorCount) { props.onReviewErrors(); return; }
    if (hasInvalid) { openEditor(invalidTaskIds); return; }
    if (action.kind === "effort" && settingsRef.current) settingsRef.current.open = true;
    props.onAction(action);
  };
  const row = (task: WorkTask) => <li key={task.id} className="run-preparation__task" data-invalid={invalid.has(task.id)}>
    <span className="run-preparation__number">{String(run.tasks.indexOf(task) + 1).padStart(2, "0")}</span>
    <button type="button" className="run-preparation__task-copy" onClick={() => props.onOpenTask(task.id)}>
      <strong>{task.title || "제목 없는 작업"}</strong><span>{props.profileSummary(task)}</span>
    </button>
    {invalid.has(task.id) ? <button type="button" className="button button--quiet" disabled={busy || blocked || draftConflict}
      onClick={() => openEditor([task.id])}>모델 확인</button> : null}
  </li>;
  return <section className="run-preparation" aria-label="작업 실행 준비">
    <header className="run-preparation__heading"><h2 id="tasks-workbench-title" tabIndex={-1}>{run.summary || "작업 그룹"}</h2>
      <p>작업 {run.tasks.length}개 · 실행 순서와 AI를 확인하세요</p></header>
    <section className="run-preparation__state" data-tone={ready ? "ready" : "review"} aria-label="다음 할 일">
      <div className="run-preparation__state-copy" role="status">{ready ? <CheckCircle2 size={18} aria-hidden="true" /> : <AlertCircle size={18} aria-hidden="true" />}
        <div><strong>{title}</strong><p>{description}</p></div></div>
      {editorTasks.length ? <div ref={editorRef} id={editorId} className="run-preparation__editors">
        {editorTasks.map((task) => <section key={task.id}><h3>{task.title || "제목 없는 작업"}</h3>{props.profileEditor(task)}</section>)}
        <button type="button" className="button button--quiet" onClick={() => setEditingIds([])}>편집 닫기</button>
      </div> : null}
      <div className="run-preparation__actions">
        {planDirty ? <button type="button" className="button button--quiet" disabled={busy || blocked} onClick={props.onReset}>변경 취소</button> : null}
        {!blocked ? <button type="button" className="button button--primary" disabled={disabled} onClick={invoke}
          aria-controls={hasInvalid ? editorId : undefined} aria-expanded={hasInvalid ? Boolean(editorTasks.length) : undefined}>
          {ready ? <Play size={15} aria-hidden="true" /> : null}{busy ? "처리 중" : label}</button> : null}
      </div>
      {blocked ? blockingAction : null}
    </section>
    <section className="run-preparation__tasks" aria-label="작업 순서"><h3>작업 순서</h3>
      <ol>{visibleTasks.map(row)}</ol>
      {remainingTasks.length ? <details className="run-preparation__remaining"><summary>나머지 작업 {remainingTasks.length}개</summary><ol>{remainingTasks.map(row)}</ol></details> : null}
      {!run.tasks.length ? <p role="status">계획에 작업이 없습니다. 채팅에서 작업을 요청하거나 실행 설정에서 추가하세요.</p> : null}
    </section>
    <details ref={settingsRef} className="run-preparation__settings"><summary>실행 설정</summary>
      <button type="button" className="button button--secondary" disabled={busy || blocked || draftConflict || !run.tasks.some(task => task.status === "pending")}
        onClick={() => openEditor(run.tasks.filter(task => task.status === "pending").map(task => task.id))}>작업별 실행 AI 편집</button>
      {props.settings}
    </details>
    <footer className="run-preparation__footer"><button type="button" className="button button--quiet" onClick={props.onDiscuss}>
      <MessageSquare size={16} aria-hidden="true" />채팅에서 이야기하기</button></footer>
  </section>;
}
