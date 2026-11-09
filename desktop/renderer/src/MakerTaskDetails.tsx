import { useEffect, useRef, useState } from "react";
import { WorkDialog } from "./WorkDialog";
import { currentTaskResult } from "./taskResults";
import { TaskExecutionProfileEditor } from "./TaskExecutionProfileEditor";
import type { ProviderProfile, RunState, TaskProfileSelection, WorkTask } from "./types";
import type { RpcMethod, RpcParams } from "../../shared/rpc";

export function makerTaskPlan(task: WorkTask, selected?: ProviderProfile, reasoning?: string): Record<string, unknown> {
  return { id: task.id, title: task.title, description: task.description, capabilities: task.capabilities,
    depends_on: task.dependencies, is_prerequisite: task.is_prerequisite, acceptance_criteria: task.acceptance_criteria,
    expected_paths: task.expected_paths, forbidden_paths: task.forbidden_paths, verify_commands: task.verify_commands,
    risk_level: task.risk_level, provider_id: selected?.provider_id || task.provider_id, model: selected?.model ?? task.model,
    reasoning_effort: reasoning ?? task.reasoning_effort };
}

export function MakerTaskDetails({ projectName, run, task, onUpdated, onClose }: {
  projectName: string; run: RunState; task: WorkTask; onUpdated(run: RunState): void; onClose(): void;
}) {
  const [profiles, setProfiles] = useState<ProviderProfile[]>([]);
  const [profileError, setProfileError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [note, setNote] = useState("");
  const [dirty, setDirty] = useState(false);
  const [closeReview, setCloseReview] = useState(false);
  const pending = useRef(false);
  const alive = useRef(true);
  const callbacks = useRef(onUpdated); callbacks.current = onUpdated;
  const params = { projectName, runId: run.id, taskId: task.id };
  const capabilitiesKey = JSON.stringify(task.capabilities);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let current = true;
    setProfileError(""); setProfiles([]);
    void window.orchestrator.request<ProviderProfile[]>("providers.execution", { projectName, capabilities: task.capabilities })
      .then(value => { if (current) setProfiles(value); }).catch(cause => { if (current) setProfileError(String(cause)); });
    return () => { current = false; };
  }, [projectName, task.id, capabilitiesKey]);
  async function refresh() {
    const next = await window.orchestrator.request<RunState>("runs.get", { projectName, runId: run.id, includeUserChecks: true });
    if (alive.current) callbacks.current(next);
  }
  async function request(method: RpcMethod, extra: RpcParams = {}) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const next = await window.orchestrator.request<RunState>(method, { ...params, ...extra });
      if (alive.current) { callbacks.current(next); setNotice("처리 결과를 저장했습니다."); setNote(""); }
    } catch (cause) { if (alive.current) setError(cause instanceof Error ? cause.message : "요청을 처리하지 못했습니다."); }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  async function nextProfile(selection: TaskProfileSelection, expected: Record<string, string>) {
    if (pending.current) throw Error("다른 요청을 처리하고 있습니다.");
    pending.current = true; setBusy(true);
    try {
      const next = await window.orchestrator.request<RunState>("tasks.updateExecutionProfile", { ...params,
        agentId: selection.agentId, model: selection.model, reasoningEffort: selection.reasoningEffort, expectedProfile: expected });
      if (alive.current) callbacks.current(next);
      return next;
    } finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  const result = currentTaskResult(task);
  const statusLabel = task.status === "pending" && task.readiness === "blocked" ? "이전 작업 대기" : ({
    pending: "대기 중", running: "작업 중", completed: "작업 완료", merged: "반영 완료", failed: "확인이 필요해요",
    waiting: "직접 확인이 필요해요", deferred: "확인 보류", blocked: "이전 작업 대기", excluded: "이번 작업에서 제외",
  } as Record<string, string>)[task.status] || "상태 확인 필요";
  const canRecord = run.stage === "executing" && !run.archive && !run.active_step
    && run.execution_control?.lock_state === "unlocked" && run.execution_control.situation === "resumable";
  const version = { expectedCommit: task.started_commit, expectedRevision: run.plan_revision };
  return <WorkDialog title={task.title} context={run.summary} className="maker-dialog maker-dialog--wide" onClose={() => {
    if (busy) return; if (dirty) setCloseReview(true); else onClose();
  }}>
    <section className="maker-task-overview" aria-label="작업 현황"><strong role="status">{statusLabel}</strong>
      <span>{task.provider_id || task.agent_id} · {task.model || "기본 모델"}</span></section>
    {result ? <p>{result.manual_verification_note ? "직접 확인한 결과가 저장되었습니다."
      : result.verification_status === "passed" ? "작업 검증을 통과했습니다." : "검증 기록을 확인해 주세요."}</p>
      : ["completed", "merged"].includes(task.status) ? <p role="status">완료 결과 기록을 확인하지 못했습니다.</p> : null}
    {error ? <p role="alert">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
    {closeReview ? <div className="maker-notice" role="alert"><p>저장하지 않은 모델 변경이 있습니다.</p><div className="maker-actions">
      <button className="maker-button" onClick={() => setCloseReview(false)}>계속 편집</button><button className="maker-button" onClick={onClose}>변경 취소하고 닫기</button></div></div> : null}
    <details><summary>작업 AI·모델 변경</summary><div className="maker-form-stack">
      {profileError ? <p role="alert">{profileError}</p> : null}
      {run.stage === "planned" && !run.archive ? <PlannedTaskModel key={`${task.id}/${run.plan_revision}`} run={run} task={task} profiles={profiles}
        busy={busy} onDirty={setDirty} onSave={(profile, reasoning) => request("runs.updatePlan", { expectedRevision: run.plan_revision,
          tasks: run.tasks.map(item => makerTaskPlan(item, item.id === task.id ? profile : undefined, item.id === task.id ? reasoning : undefined)) })} />
        : <TaskExecutionProfileEditor run={run} task={task} options={profiles} busy={busy} onSave={nextProfile}
          onDirtyChange={setDirty} onRefresh={() => void refresh().catch(cause => setError(String(cause)))} />}
    </div></details>
    {task.error ? <p role="alert">작업에서 확인할 문제가 있습니다. 연결한 외부 앱에서 이 작업을 확인해 달라고 요청하세요.</p> : null}
    {task.status === "failed" && !run.archive && run.execution_control?.lock_state === "unlocked" ? <button className="maker-button" disabled={busy || dirty}
      onClick={() => void request("tasks.retry")}>현재 설정으로 이 작업 다시 실행</button> : null}
    {task.status === "pending" && !run.archive && ["executing", "failed"].includes(run.stage) && run.execution_control?.lock_state === "unlocked" ?
      <button className="maker-button" disabled={busy || dirty || task.readiness === "blocked"} onClick={() => void request("tasks.execute")}>이 작업 실행</button> : null}
    {task.status === "waiting" && canRecord && task.started_commit ? <section className="maker-form-stack"><h3>직접 확인한 결과</h3>
      <label className="field"><span>확인 환경과 결과</span><textarea rows={3} maxLength={4000} value={note} disabled={busy} onChange={event => setNote(event.target.value)} /></label>
      <div className="maker-actions"><button className="maker-button maker-button--primary" disabled={busy || !note.trim()} onClick={() => void request("tasks.completeManualVerification", { ...version, note: note.trim() })}>검증 결과 저장</button>
        <button className="maker-button" disabled={busy || dirty} onClick={() => void request("tasks.handoffToAi", version)}>코드 작업을 AI에 맡기기</button>
        {run.workspace_mode === "shared" ? <button className="maker-button" disabled={busy} onClick={() => void request("tasks.deferManual")}>미검증으로 보류</button> : null}
        <button className="maker-button" disabled={busy} onClick={() => void request("tasks.complete")}>직접 수정한 변경 제출</button></div></section> : null}
    {task.status === "deferred" && canRecord ? <button className="maker-button" disabled={busy} onClick={() => void request("tasks.resumeManual")}>직접 확인 다시 열기</button> : null}
    <details><summary>작업 내용</summary>
      <div className="maker-form-stack">
        <section><h3>작업 설명</h3><p>{task.description}</p></section>
        <section><h3>완료 기준</h3><ul>{task.acceptance_criteria.map((item, index) => <li key={index}>{item}</li>)}</ul></section>
        {result ? <section><h3>작업 결과</h3><p>{result.manual_verification_note || result.self_report || "결과 요약이 없습니다."}</p></section> : null}
      </div>
    </details>
  </WorkDialog>;
}

export function PlannedTaskModel({ run, task, profiles, busy, onDirty, onSave }: {
  run: RunState; task: WorkTask; profiles: ProviderProfile[]; busy: boolean; onDirty(dirty: boolean): void;
  onSave(profile: ProviderProfile, reasoning: string): Promise<void>;
}) {
  const [choice, setChoice] = useState(JSON.stringify([task.agent_id, task.model]));
  const [reasoning, setReasoning] = useState(task.reasoning_effort);
  const selected = profiles.find(item => JSON.stringify([item.agent_id, item.model]) === choice);
  const dirty = choice !== JSON.stringify([task.agent_id, task.model]) || reasoning !== task.reasoning_effort;
  useEffect(() => { onDirty(dirty); }, [dirty, onDirty]);
  return <div className="maker-form-stack"><label className="field"><span>이 작업을 수행할 AI·모델</span><select value={choice} disabled={busy || run.execution_control?.lock_state !== "unlocked"}
    onChange={event => { setChoice(event.target.value); setReasoning(""); }}>
    {!selected ? <option value={choice}>{task.provider_id}/{task.model || task.agent_id} · 사용 가능한 모델 확인 필요</option> : null}
    {profiles.map(item => <option key={`${item.agent_id}/${item.model}`} value={JSON.stringify([item.agent_id, item.model])}>{item.provider_id} · {item.model || item.agent_id}</option>)}</select></label>
    <label className="field"><span>추론 강도</span><select value={reasoning} disabled={busy || !selected} onChange={event => setReasoning(event.target.value)}><option value="">자동 선택</option>
      {selected?.reasoning_efforts.map(value => <option key={value}>{value}</option>)}</select></label>
    <p className="maker-muted">모델 변경을 저장하면 제작 계획을 다시 확인해야 합니다. 다른 태스크의 설정은 유지됩니다.</p>
    <button className="maker-button" disabled={busy || !dirty || !selected || run.execution_control?.lock_state !== "unlocked"} onClick={() => { if (selected) void onSave(selected, reasoning); }}>모델 변경 저장</button>
  </div>;
}
