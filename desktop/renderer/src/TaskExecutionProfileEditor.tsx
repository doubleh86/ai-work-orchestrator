import { useEffect, useRef, useState } from "react";

import type { ProviderProfile, RunState, TaskProfileSelection, WorkTask } from "./types";

export function taskExecutionProfileSnapshot(task: WorkTask): Record<string, string> {
  return { agent_id: task.agent_id, model: task.model, reasoning_effort: task.reasoning_effort,
    last_attempt_id: task.last_attempt_id || "", status: task.status };
}

function selectionFor(task: WorkTask): TaskProfileSelection {
  return { agentId: task.agent_id, model: task.model, reasoningEffort: task.reasoning_effort };
}

function profileKey(agentId: string, model: string): string {
  return JSON.stringify([agentId, model]);
}

export function nextExecutionProfileBlockReason(run: RunState, task: WorkTask, busy: boolean): string {
  if (!["pending", "failed"].includes(task.status)) return "실패하거나 아직 시작하지 않은 작업만 변경할 수 있습니다.";
  if (!["executing", "failed"].includes(run.stage) || (run.stage === "failed" && run.failed_step !== "agent_execution")) {
    return "현재 단계에서는 다음 실행 모델을 변경할 수 없습니다.";
  }
  const control = run.execution_control;
  const activePending = task.status === "pending" && !task.active_action && run.stage === "executing"
    && (!run.active_step || run.active_step === "agent_execution") && control?.lock_state === "active"
    && ["running", "preparing"].includes(control.situation)
    && ["execute", "resume", "retry-task", "execute-task"].includes(control.operation);
  if (activePending) return busy ? "다른 요청을 처리 중입니다." : "";
  if (run.active_step || run.tasks.some((item) => item.active_action || ["running", "reviewing", "revising"].includes(item.status))
    || ["running", "preparing"].includes(control?.situation || "") || control?.lock_state === "active") {
    return "이 작업은 그룹이 멈춘 상태에서 변경할 수 있습니다. 실행 전 대기 작업은 실행 중에도 변경할 수 있습니다.";
  }
  if (!control || control.lock_state !== "unlocked" || !["ready", "resumable"].includes(control.situation)) {
    return "실행 상태를 먼저 확인해 주세요.";
  }
  return busy ? "다른 요청을 처리 중입니다." : "";
}

export function TaskExecutionProfileEditor({ task, run, options, busy, onSave, onSaved, onDirtyChange, onRefresh }: {
  task: WorkTask; run: RunState; options: ProviderProfile[]; busy: boolean;
  onSave(selection: TaskProfileSelection, expected: Record<string, string>): Promise<RunState>;
  onSaved?(run: RunState): void; onDirtyChange(dirty: boolean): void; onRefresh(): void;
}) {
  const [draft, setDraft] = useState(() => ({ selection: selectionFor(task), expected: taskExecutionProfileSnapshot(task) }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const mounted = useRef(false);
  const pending = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const selected = options.find((item) => item.agent_id === draft.selection.agentId && item.model === draft.selection.model);
  const conflict = JSON.stringify(taskExecutionProfileSnapshot(task)) !== JSON.stringify(draft.expected);
  const changed = draft.selection.agentId !== draft.expected.agent_id || draft.selection.model !== draft.expected.model
    || draft.selection.reasoningEffort !== draft.expected.reasoning_effort;
  const blocked = nextExecutionProfileBlockReason(run, task, busy);
  useEffect(() => {
    if (conflict && !changed && !saving) {
      setDraft({ selection: selectionFor(task), expected: taskExecutionProfileSnapshot(task) });
      setError(""); setSaved(false);
    }
  }, [conflict, changed, saving, task]);
  useEffect(() => { onDirtyChange(changed); return () => onDirtyChange(false); }, [changed, onDirtyChange]);
  const reset = () => {
    setDraft({ selection: selectionFor(task), expected: taskExecutionProfileSnapshot(task) });
    setError(""); setSaved(false);
  };
  const save = async () => {
    if (!mounted.current || pending.current || blocked || conflict || !changed || !selected) return;
    pending.current = true; setSaving(true); setError(""); setSaved(false);
    const selection = draft.selection;
    try {
      const updated = await onSave(selection, draft.expected);
      if (!mounted.current) return;
      const current = updated.tasks.find((item) => item.id === task.id);
      if (updated.id !== run.id || !current || current.agent_id !== selection.agentId || current.model !== selection.model
        || current.reasoning_effort !== selection.reasoningEffort) throw new Error("저장된 실행 모델을 확인하지 못했습니다.");
      setDraft({ selection: selectionFor(current), expected: taskExecutionProfileSnapshot(current) });
      setSaved(true); onSaved?.(updated);
    } catch (cause) {
      if (mounted.current) setError(`모델 저장 결과를 확인하지 못했습니다. ${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      pending.current = false;
      if (mounted.current) setSaving(false);
    }
  };
  return <section className="work-task-model work-task-next-model" aria-label="다음 실행 AI 설정">
    <h3>다음 실행 AI · 모델</h3>
    <div className="task-profile-controls task-profile-controls--editable"><div className="task-profile-editor-fields">
      <label><span className="task-profile-label">실행 모델</span><select aria-label={`${task.title} 다음 실행 모델`}
        value={selected ? profileKey(selected.agent_id, selected.model) : ""} disabled={Boolean(blocked) || saving || conflict || !options.length}
        onChange={(event) => {
          const next = options.find((item) => profileKey(item.agent_id, item.model) === event.target.value);
          if (next) { setDraft({ ...draft, selection: { agentId: next.agent_id, model: next.model, reasoningEffort: "" } }); setSaved(false); }
        }}>
        {!selected ? <option value="" disabled>{options.length ? `현재 설정 · ${task.model || "자동 선택"} · 다시 선택 필요` : "사용 가능한 모델 없음"}</option> : null}
        {options.map((item) => <option key={profileKey(item.agent_id, item.model)} value={profileKey(item.agent_id, item.model)}>
          {item.model || (item.provider_id === "codex" ? "자동 · gpt-6.1-sol" : "자동 선택")} · {item.provider_id === "codex" ? "Codex" : item.provider_id === "nvidia" ? "NVIDIA" : item.provider_id}
        </option>)}
      </select></label>
      <label><span className="task-profile-label">추론 강도</span><select aria-label={`${task.title} 다음 실행 추론 강도`}
        value={draft.selection.reasoningEffort} disabled={Boolean(blocked) || saving || conflict || !selected}
        onChange={(event) => { setDraft({ ...draft, selection: { ...draft.selection, reasoningEffort: event.target.value } }); setSaved(false); }}>
        <option value="">자동 선택</option>{selected?.reasoning_efforts.map((effort) => <option key={effort} value={effort}>{effort}</option>)}
      </select></label>
    </div></div>
    <p>{saving ? "모델을 저장하고 있습니다." : blocked || (task.status === "pending"
      ? "저장한 모델은 이 작업이 시작될 때 적용됩니다. 현재 실행 중인 작업은 그대로 진행합니다."
      : "저장한 모델은 다음 실행에 사용합니다. 재실행은 별도로 선택하세요.")}</p>
    {conflict ? <p role="alert">작업 상태 또는 저장된 모델이 변경됐습니다. 최신 설정을 확인한 뒤 다시 선택해 주세요.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {saved && !changed && !conflict ? <p role="status">다음 실행 모델을 저장했습니다.</p> : null}
    <div className="work-task-plan-actions">
      <button className="button button--primary" type="button" disabled={Boolean(blocked) || saving || conflict || !changed || !selected}
        onClick={() => void save()}>{saving ? "저장 중…" : "모델 변경 저장"}</button>
      {changed || conflict ? <button className="button button--secondary" type="button" disabled={saving} onClick={reset}>변경 취소</button> : null}
      {error || conflict || (!saving && blocked) ? <button className="button button--quiet" type="button" disabled={saving} onClick={onRefresh}>최신 상태 확인</button> : null}
    </div>
  </section>;
}
