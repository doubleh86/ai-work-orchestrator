import type { TaskProfileSelection } from "./planDrafts";
import type { ProviderProfile, RunState, UsageSnapshot, WorkTask } from "./types";
import { TaskExecutionProfileEditor } from "./TaskExecutionProfileEditor";
import { TaskDetailSummary } from "./TaskStatusOverview";
import { TaskRecordActions } from "./TaskRecordActions";

export function ChatTaskSettings({ projectName, run, task, options, busy, usage, usageError, onDirtyChange, onRefresh, onSave }: {
  projectName: string; run: RunState; task: WorkTask; options: ProviderProfile[]; busy: boolean;
  usage?: UsageSnapshot; usageError?: string; onDirtyChange(dirty: boolean): void; onRefresh(): void;
  onSave(selection: TaskProfileSelection, expected: Record<string, string>): Promise<RunState>;
}) {
  const editable = !run.archive && ["executing", "failed"].includes(run.stage) && ["pending", "failed"].includes(task.status);
  return <section className="chat-task-settings" aria-label="선택 작업의 실행 설정과 기록">
    <p className="chat-task-settings__target"><small>선택 작업</small><strong>{task.title}</strong></p>
    {editable ? <TaskExecutionProfileEditor key={task.id} task={task} run={run} options={options}
      busy={busy} onDirtyChange={onDirtyChange} onRefresh={onRefresh} onSave={onSave} /> : null}
    <details><summary>이 작업의 사용량·기록</summary>
      <TaskDetailSummary task={task} usage={usage} usageError={usageError} />
      <TaskRecordActions projectName={projectName} runId={run.id} taskId={task.id} />
    </details>
  </section>;
}
