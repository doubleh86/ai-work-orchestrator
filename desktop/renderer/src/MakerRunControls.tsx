import { useCallback, useEffect, useRef, useState } from "react";
import { ApplySummarySession, applySummaryAction, applySummaryStatus, sendApplySummaryCommand, type ApplySummaryAction } from "./applySummaryFlow";
import { readConsistentOperations, type OperationsSnapshot } from "./integrationCompletion";
import { readRunExecutionAction, runExecutionActionAllowed } from "./runExecutionControl";
import { WorkDialog } from "./WorkDialog";
import { UsagePanel } from "./UsagePanel";
import { ConflictResolutionPanel } from "./ConflictResolutionPanel";
import { RecoveryDialog } from "./RecoveryDialog";
import { RunLockNotice } from "./RunLockNotice";
import type { ApprovedRpcMethod, RpcParams } from "../../shared/rpc";
import type { ProjectCapabilities, RunArchivePlan, RunState } from "./types";

const errorText = (error: unknown) => error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
const labels: Record<ApplySummaryAction, string> = { verify: "결과 검사", work: "작업 브랜치 반영", main: "원본에 반영", upload: "변경 업로드" };

export function MakerRunControls({ projectName, run, onUpdated, onDeleted }: {
  projectName: string; run: RunState; onUpdated(run: RunState): void; onDeleted(): void;
}) {
  const [snapshot, setSnapshot] = useState<OperationsSnapshot>();
  const [capabilities, setCapabilities] = useState<ProjectCapabilities>();
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [capabilitiesError, setCapabilitiesError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [records, setRecords] = useState(false);
  const [startRun, setStartRun] = useState<RunState>();
  const [stopping, setStopping] = useState(false);
  const [recovery, setRecovery] = useState(false);
  const [lockBlocking, setLockBlocking] = useState(false);
  const callbacks = useRef({ onUpdated, onDeleted }); callbacks.current = { onUpdated, onDeleted };
  const alive = useRef(true);
  const pending = useRef(false);
  const stopPending = useRef(false);
  const refreshPending = useRef(false);
  const session = useRef<ApplySummarySession | undefined>(undefined);
  const params = { projectName, runId: run.id };
  const read = useCallback(() => readConsistentOperations(projectName, run.id, (method, values) => window.orchestrator.request(method, values)), [projectName, run.id]);
  const refresh = useCallback(async () => {
    if (refreshPending.current) return;
    refreshPending.current = true;
    try {
      const result = await read();
      if (alive.current) { setSnapshot(result.snapshot); callbacks.current.onUpdated(result.run); setLoadError(""); }
    } catch (cause) { if (alive.current) { setSnapshot(undefined); setLoadError(errorText(cause)); } }
    finally { refreshPending.current = false; }
  }, [read]);
  useEffect(() => {
    alive.current = true;
    const current = new ApplySummarySession(projectName, {
      read, command: (method, extra) => sendApplySummaryCommand(window.orchestrator, method, { projectName, runId: run.id, ...extra }),
      current: () => alive.current,
      changed: result => { if (alive.current) { setSnapshot(result.snapshot); callbacks.current.onUpdated(result.run); } },
    });
    session.current = current;
    void window.orchestrator.request<ProjectCapabilities>("projects.capabilities", { projectName }).then(value => {
      if (alive.current) setCapabilities(value);
    }).catch(cause => { if (alive.current) setCapabilitiesError(errorText(cause)); });
    return () => { alive.current = false; current.dispose(); };
  }, [projectName, run.id, read]);
  useEffect(() => { void refresh(); }, [refresh, run.updated_at]);
  async function action(label: string, perform: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true; setBusy(label); setError(""); setNotice("");
    try { await perform(); }
    catch (cause) { if (alive.current) setError(errorText(cause)); }
    finally { pending.current = false; if (alive.current) { setBusy(""); void refresh(); } }
  }
  async function execute(method: "runs.execute" | "runs.resume", observed = run) {
    await action(method, async () => {
      const checked = await readRunExecutionAction(() => window.orchestrator.request<RunState>("runs.get", params), observed, method);
      if (!checked.allowed) throw Error("제작 상태나 계획이 바뀌었습니다. 최신 내용을 확인하고 다시 진행해 주세요.");
      const next = await window.orchestrator.request<RunState>(method, params);
      if (alive.current) callbacks.current.onUpdated(next);
    });
  }
  async function stop() {
    if (stopPending.current || !run.execution_control?.can_stop || !run.execution_control.execution_id) return;
    stopPending.current = true; setStopping(true); setError("");
    try {
      await window.orchestrator.request("runs.requestStop", { ...params, executionId: run.execution_control.execution_id,
        requestId: crypto.randomUUID(), scope: run.active_step === "verify" ? "verification" : "group" });
      if (alive.current) setNotice("중지를 요청했습니다. 종료를 확인하고 있어요.");
    } catch (cause) { if (alive.current) setError(errorText(cause)); }
    finally { stopPending.current = false; if (alive.current) { setStopping(false); void refresh(); } }
  }
  async function approved(method: ApprovedRpcMethod, extra: RpcParams = {}) {
    await action(method, async () => {
      const next = await window.orchestrator.approve<RunState>(method, { ...params, ...extra });
      if (next && alive.current) callbacks.current.onUpdated(next);
    });
  }
  async function apply(kind: ApplySummaryAction) {
    await action(kind, async () => {
      const result = await session.current?.perform(kind, run);
      if (alive.current && result === "completed") setNotice("처리 결과를 확인했습니다. 다음 단계는 별도로 선택해 주세요.");
    });
  }
  async function archive() {
    await action("archive", async () => {
      const plan = await window.orchestrator.request<RunArchivePlan>("runs.archivePlan", params);
      if (!plan.can_archive) throw Error(plan.block_reasons.join(" · ") || "현재는 보관할 수 없습니다.");
      const next = await window.orchestrator.approve<RunState>("runs.archive", { ...params, expectedRevision: plan.expected_revision,
        fingerprint: plan.fingerprint, cleanupTargetCount: plan.cleanup_targets.length, requestId: crypto.randomUUID() });
      if (next && alive.current) callbacks.current.onUpdated(next);
    });
  }
  const nextApply = applySummaryAction(run, snapshot, projectName);
  const unlocked = run.execution_control?.lock_state === "unlocked";
  const completed = run.tasks.filter(task => ["completed", "merged"].includes(task.status));
  return <section className="maker-panel maker-run-controls">
    <RunLockNotice projectName={projectName} runId={run.id} refreshKey={run.updated_at} busy={Boolean(busy)} activeOnCards
      onUpdated={value => { callbacks.current.onUpdated(value); void refresh(); }} onInspect={() => setRecords(true)} onBlocking={setLockBlocking} />
    <div className="maker-section-heading"><h2>작업 제어</h2><button className="maker-button" onClick={() => void refresh()}>상태 확인</button></div>
    {run.execution_control?.lock_state !== "active" ? <p className="maker-muted">{applySummaryStatus(run, snapshot, projectName, busy)}</p> : null}
    <div className="maker-actions">
      {runExecutionActionAllowed(run, "runs.execute") ? <button className="maker-button maker-button--primary" disabled={Boolean(busy) || lockBlocking} onClick={() => setStartRun(run)}>제작 시작</button> : null}
      {runExecutionActionAllowed(run, "runs.resume") ? <button className="maker-button maker-button--primary" disabled={Boolean(busy) || lockBlocking} onClick={() => void execute("runs.resume")}>이어서 제작</button> : null}
      {run.execution_control?.can_stop ? <button className="maker-button maker-button--danger" disabled={stopping || run.execution_control.stop_phase === "stopping"}
        onClick={() => void stop()}>제작 중지</button> : null}
      {nextApply ? <button className="maker-button maker-button--primary" disabled={Boolean(busy) || lockBlocking} onClick={() => void apply(nextApply)}>{labels[nextApply]}</button> : null}
    </div>
    {busy && run.execution_control?.lock_state !== "active" ? <p role="status">요청 확인 중…</p> : null}
    {loadError ? <p role="alert">상태 확인 실패 · {loadError}</p> : null}
    {error ? <p role="alert">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
    <details><summary>관리</summary><div className="maker-form-stack">
      <p>완료 작업 {completed.length}개</p>
      <button className="maker-button" onClick={() => setRecords(true)}>작업 기록</button>
      {capabilitiesError ? <p role="alert">배포 설정 확인 실패 · {capabilitiesError}</p> : null}
      {run.main_operations?.merge?.error || run.main_operations?.retry_main_push?.error ? <p role="alert">{run.main_operations.merge?.error || run.main_operations.retry_main_push?.error}</p> : null}
      <div className="maker-actions">
        {run.integration_control?.status === "main_push_pending" ? <button className="maker-button" disabled={Boolean(busy) || !unlocked} onClick={() => void approved("runs.retryMainPush")}>원본 업로드 다시 확인</button> : null}
        {run.integration_control?.can_recover_main_apply ? <button className="maker-button" disabled={Boolean(busy) || !unlocked} onClick={() => void approved("runs.recoverMainApply")}>중단된 원본 반영 복구</button> : null}
        {capabilities?.deployment_configured && run.stage === "pushed" ? <button className="maker-button" disabled={Boolean(busy) || !unlocked} onClick={() => void approved("runs.deploy")}>배포 승인</button> : null}
        {!run.archive ? <button className="maker-button" disabled={Boolean(busy) || !unlocked} onClick={() => void archive()}>기록 보관</button> : <>
          <button className="maker-button" onClick={() => void action("open", async () => { if (!await window.orchestrator.openArchiveFolder(projectName, run.id)) throw Error("보관 폴더를 열지 못했습니다."); })}>보관 폴더 열기</button>
          {run.archive.cleanup_status !== "completed" ? <button className="maker-button" disabled={Boolean(busy)} onClick={() => void approved("runs.retryArchiveCleanup", { fingerprint: run.archive?.fingerprint, requestId: crypto.randomUUID() })}>보류된 정리 다시 시도</button> : null}</>}
        <button className="maker-button maker-button--danger" disabled={Boolean(busy) || !unlocked} onClick={() => void action("delete", async () => {
          const result = await window.orchestrator.approve("runs.delete", params); if (result !== null && alive.current) callbacks.current.onDeleted();
        })}>작업 기록 삭제</button>
      </div>
      {run.archive ? <p>보관 상태 · {run.archive.cleanup_status}</p> : null}
      {run.stage === "failed" && run.failed_step === "agent_execution" ? <button className="maker-button" disabled={Boolean(busy)} onClick={() => setRecovery(true)}>실패 작업 복구안 확인</button> : null}
      {run.stage === "failed" && run.failed_step === "verify" && !run.archive ? <button className="maker-button" disabled={Boolean(busy) || !unlocked || lockBlocking}
        onClick={() => void action("repair", async () => {
          const next = await window.orchestrator.request<RunState>("runs.verifyAndRepair", { ...params, requestId: crypto.randomUUID() });
          if (alive.current) callbacks.current.onUpdated(next);
        })}>검사 실패를 AI로 수정하고 재검사</button> : null}
      {run.integration_conflict ? <ConflictResolutionPanel projectName={projectName} run={run} operationsSnapshot={snapshot}
        operationsCheckedAt={snapshot?.checkedAt} onUpdated={() => void refresh()} onVerify={() => void apply("verify")} verifyDisabled={Boolean(busy)} /> : null}
    </div></details>
    {startRun ? <WorkDialog title="제작을 시작할까요?" className="maker-dialog" onClose={() => setStartRun(undefined)}>
      <p>관제에서 정한 설정으로 {startRun.tasks.length}개 작업을 진행합니다.</p>
      <details><summary>배정된 작업 AI 보기</summary><ul>{[...new Set(startRun.tasks.map(task => `${task.provider_id || task.agent_id} · ${task.model || "기본 모델"}`))]
        .map(profile => <li key={profile}>{profile}</li>)}</ul></details>
      <button className="maker-button maker-button--primary" disabled={Boolean(busy) || lockBlocking} onClick={() => {
        setStartRun(undefined); void execute("runs.execute", startRun);
      }}>현재 설정으로 시작</button>
    </WorkDialog> : null}
    {records ? <WorkDialog title="작업 기록" className="maker-dialog maker-dialog--wide" onClose={() => setRecords(false)}>
      <details><summary>사용량</summary><UsagePanel projectName={projectName} runId={run.id} running={Boolean(run.active_step)} refreshKey={run.updated_at} /></details>
      <details><summary>검사 기록</summary>{run.verification_attempts?.length ? <ol className="maker-record-list">{run.verification_attempts.map(item => <li key={item.id}>
        <strong>{item.status} · {item.phase}</strong><p>{item.error}</p><small>{item.finished_at || item.started_at}</small>
        <pre>{item.passed_commands.map(command => command.join(" ")).join("\n")}</pre></li>)}</ol> : <p>검사 기록이 없습니다.</p>}</details>
      <details><summary>작업 이벤트와 작업공간</summary><p>{run.execution_worktree || "작업공간 준비 전"}</p>
        <ol className="maker-record-list">{run.events.map((event, index) => <li key={`${event.at}/${index}`}><time>{event.at}</time><strong>{event.kind}</strong><p>{event.message}</p></li>)}</ol></details>
    </WorkDialog> : null}
    {recovery ? <RecoveryDialog projectName={projectName} runId={run.id} runTitle={run.summary} onClose={() => setRecovery(false)} onApplied={value => callbacks.current.onUpdated(value)} /> : null}
  </section>;
}
