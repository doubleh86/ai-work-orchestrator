import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Bell, Bot, Check, ChevronRight, Copy, FolderOpen, LayoutGrid, LoaderCircle, Play, Plus, RefreshCw, Settings2, Sparkles } from "lucide-react";
import { MakerWorkers } from "./MakerWorkers";
import { MakerProjects } from "./MakerProjects";
import { MakerNotifications } from "./MakerNotifications";
import { MakerRunControls } from "./MakerRunControls";
import { MakerTaskDetails } from "./MakerTaskDetails";
import { MakerProgress } from "./MakerProgress";
import type { StoredWorkNotification } from "../../shared/workNotifications";
import { WorkDialog } from "./WorkDialog";
import { UserChecks, type UserCheckInput } from "./UserChecks";
import { latestMakerRun, mcpConnectionPrompt, makerStage, readMcpConnectionGuide, type McpConnectionGuide } from "./makerPresentation";
import type { RegisteredProject, RunState, RunSummary } from "./types";

interface ProjectCard { project: RegisteredProject; runs: RunSummary[]; error: string }
interface Selection { project: string; runId: string }
interface ResultArtifact {
  status: string; can_launch: boolean; reason: string; kind?: "web" | "windows" | "macos" | "android";
  digest?: string; relative_path?: string; verification_scope?: "task" | "integration"; devices?: { id: string; name: string }[];
}
const message = (cause: unknown) => cause instanceof Error ? cause.message : "요청을 처리하지 못했습니다. 다시 시도해 주세요.";

export function MakerApp() {
  const [cards, setCards] = useState<ProjectCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<Selection>();
  const [loadedRun, setRun] = useState<RunState>();
  const [runContext, setRunContext] = useState("");
  const selectedKey = selection ? `${selection.project}/${selection.runId}` : "";
  const selectionRef = useRef(selectedKey);
  selectionRef.current = selectedKey;
  const run = runContext === selectedKey ? loadedRun : undefined;
  const [runError, setRunError] = useState("");
  const [runReadAt, setRunReadAt] = useState(0);
  const [dialog, setDialog] = useState<"connection" | "plan">();
  const [page, setPage] = useState<"projects" | "workers" | "manage" | "notifications">("projects");
  const [taskId, setTaskId] = useState("");
  const [saving, setSaving] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const main = useRef<HTMLElement>(null);
  const runReadVersion = useRef(0);
  const loadProjects = useCallback(async () => {
    const projects = await window.orchestrator.request<RegisteredProject[]>("projects.list");
    const next = await Promise.all(projects.map(async project => {
      try { return { project, runs: await window.orchestrator.request<RunSummary[]>("runs.list", { projectName: project.name, scope: "all" }), error: "" }; }
      catch (cause) { return { project, runs: [], error: message(cause) }; }
    }));
    return next;
  }, []);
  useEffect(() => {
    if (page !== "projects") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const next = await loadProjects(); if (active) { setCards(next); setError(""); } }
      catch (cause) { if (active) setError(message(cause)); }
      finally { if (active) { setLoading(false); timer = setTimeout(() => void poll(), 5000); } }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [loadProjects, page]);
  useEffect(() => {
    setRun(undefined); setRunError(""); setRunReadAt(0);
    if (!selection || page !== "projects") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const version = ++runReadVersion.current;
      try {
        const next = await window.orchestrator.request<RunState>("runs.get", {
          projectName: selection!.project, runId: selection!.runId, includeUserChecks: true,
        });
        if (active && version === runReadVersion.current) { setRun(next); setRunContext(`${selection!.project}/${selection!.runId}`); setRunError(""); setRunReadAt(Date.now()); }
      } catch (cause) { if (active && version === runReadVersion.current) setRunError(message(cause)); }
      finally { if (active) timer = setTimeout(() => void poll(), 3000); }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [selection, page]);
  useEffect(() => { main.current?.scrollTo({ top: 0 }); heading.current?.focus({ preventScroll: true }); }, [selection, page]);
  function openNotification(item: StoredWorkNotification) {
    if (!item.project_name || !item.run_id) { setPage("notifications"); return; }
    setPage("projects"); setSelection({ project: item.project_name, runId: item.run_id });
    setTaskId(item.target_kind === "task" ? item.target_id : "");
    setDialog(item.summary_code === "plan_confirmation_required" ? "plan" : undefined);
  }
  useEffect(() => {
    const stopNotifications = window.orchestrator.onNotificationOpen(openNotification);
    const stopSettings = window.orchestrator.onOpenProjectSettings(() => setPage("manage"));
    const stopAuth = window.orchestrator.onOpenCodexAuth(() => setPage("workers"));
    return () => { stopNotifications(); stopSettings(); stopAuth(); };
  }, []);
  async function refreshProjects() {
    try { setCards(await loadProjects()); setError(""); }
    catch (cause) { setError(message(cause)); throw cause; }
  }
  function acceptRun(next: RunState) {
    const context = selectedKey;
    if (selectionRef.current !== context || next.id !== selection?.runId || !context) return;
    const version = ++runReadVersion.current;
    setRun(current => ({ ...next, planned_user_checks: next.planned_user_checks ?? current?.planned_user_checks }));
    setRunReadAt(Date.now());
    void window.orchestrator.request<RunState>("runs.get", { projectName: selection.project, runId: next.id, includeUserChecks: true })
      .then(value => { if (selectionRef.current === context && version === runReadVersion.current) { setRun(value); setRunError(""); setRunReadAt(Date.now()); } })
      .catch(cause => { if (selectionRef.current === context && version === runReadVersion.current) setRunError(message(cause)); });
  }

  async function record(input: UserCheckInput) {
    if (!selection) return;
    const selected = selection;
    setSaving(true);
    try {
      await window.orchestrator.request("runs.recordUserCheck", { projectName: selected.project, runId: selected.runId, ...input });
      const next = await window.orchestrator.request<RunState>("runs.get", { projectName: selected.project, runId: selected.runId, includeUserChecks: true });
      if (selectionRef.current === `${selected.project}/${selected.runId}`) setRun(next);
    } finally { setSaving(false); }
  }
  const selectedCard = cards.find(card => card.project.name === selection?.project);
  const finishedTasks = new Set(run?.tasks.filter(task => ["completed", "merged"].includes(task.status)).map(task => task.id));
  return <>
    <div className="maker-shell">
      <aside className="maker-sidebar">
        <a className="maker-brand" href="#maker-main" onClick={() => { setPage("projects"); setSelection(undefined); setTaskId(""); }}><span><Sparkles size={20} /></span>Orchestrator</a>
        <button className="maker-button maker-button--primary" onClick={() => setDialog("connection")}><Plus size={18} />새 채팅</button>
        <nav aria-label="제작 메뉴"><button className={page === "projects" && !selection ? "is-current" : ""} onClick={() => { setPage("projects"); setSelection(undefined); setTaskId(""); }}><LayoutGrid size={18} />내 프로젝트</button>
          <button className={page === "workers" ? "is-current" : ""} onClick={() => setPage("workers")}><Bot size={18} />작업 AI</button>
          <button className={page === "notifications" ? "is-current" : ""} onClick={() => setPage("notifications")}><Bell size={18} />작업 알림</button>
          <button className={page === "manage" ? "is-current" : ""} onClick={() => setPage("manage")}><Settings2 size={18} />프로젝트 관리</button>
        </nav>
        <div className="maker-project-nav"><p>프로젝트</p>{cards.map(card => <button key={card.project.name}
          className={selection?.project === card.project.name ? "is-current" : ""} onClick={() => {
            const latest = latestMakerRun(card.runs);
            if (latest) { setPage("projects"); setTaskId(""); setSelection({ project: card.project.name, runId: latest.id }); }
            else setDialog("connection");
          }}><FolderOpen size={16} /><span>{card.project.name}</span></button>)}</div>
        <div className="maker-sidebar-bottom"><div className="maker-connection"><span className="maker-client-icon"><Sparkles size={18} /></span>
          <div><strong>외부 앱에서 기획·제어</strong><small>MCP 연결 프롬프트로 시작</small></div></div>
          <button onClick={() => setDialog("connection")}><Settings2 size={17} />MCP 연결</button></div>
      </aside>
      <main ref={main} id="maker-main" className="maker-main">
        <header className="maker-topbar"><span>내가 만드는 소프트웨어</span><button className="maker-button" onClick={() => setDialog("connection")}>MCP 연결 프롬프트<ChevronRight size={16} /></button></header>
        {error ? <div className="maker-notice maker-notice--error" role="alert">프로젝트를 불러오지 못했습니다. {error}<span>자동으로 다시 확인하고 있습니다.</span></div> : null}
        <MakerWorkers active={page === "workers"} />
        <MakerProjects projects={cards.map(card => card.project)} initialProject={selection?.project} active={page === "manage"} onChanged={refreshProjects} />
        <MakerNotifications active={page === "notifications"} onOpen={openNotification} />
        {page === "projects" ? <>
        {!selection ? <div className="maker-content">
          <div className="maker-page-heading"><div><p className="maker-eyebrow">생각을 실제로</p><h1 ref={heading} tabIndex={-1}>제작 현황과 결과를 한눈에</h1><p>Codex·Claude 등의 앱에서 기획하고, 오케스트레이터의 작업 AI들이 제작합니다.</p></div></div>
          <section className="maker-hero"><div className="maker-hero-icon"><Sparkles size={30} /></div><div><h2>새 채팅에서 만들 내용을 정하세요</h2><p>MCP 연결 프롬프트를 외부 앱의 새 채팅에 붙여 넣으세요.<br />계획을 전달하면 태스크 생성과 작업 AI 모델 배정 후 알려드립니다.</p>
            <button className="maker-button maker-button--primary" onClick={() => setDialog("connection")}>MCP 설치·연결 프롬프트 복사<Copy size={18} /></button></div>
            <ol className="maker-steps"><li><span>1</span>연결 프롬프트 복사</li><li><span>2</span>외부 앱에서 기획</li><li><span>3</span>태스크·모델 준비 알림</li></ol></section>
          <div className="maker-section-heading"><h2>내 프로젝트</h2><span>{cards.length}개</span></div>
          {loading ? <p className="maker-empty" role="status"><LoaderCircle size={22} />프로젝트를 불러오고 있어요.</p> : !cards.length && !error ? <section className="maker-empty"><FolderOpen size={36} /><h3>새 채팅에서 첫 프로젝트를 시작하세요</h3><p>기획을 전달받으면 태스크와 배정된 작업 AI를 여기에 표시합니다.</p></section> : null}
          <div className="maker-card-grid">{cards.map(card => <ProjectTile key={card.project.name} card={card} onOpen={runId => { setTaskId(""); setSelection({ project: card.project.name, runId }); }} onStart={() => setDialog("connection")} />)}</div>
        </div> : <div className="maker-content">
          <button className="maker-back" onClick={() => { setPage("projects"); setSelection(undefined); setTaskId(""); }}><ArrowLeft size={16} />프로젝트 목록</button>
          <div className="maker-page-heading"><div><p className="maker-eyebrow">내 프로젝트</p><h1 ref={heading} tabIndex={-1}>{selection.project}</h1><p>{run?.summary || "제작 내용을 확인하고 있어요."}</p></div><p className="maker-muted">수정·추가 요청은 연결한 외부 앱에서 이야기하세요.</p></div>
          {selectedCard && selectedCard.runs.length > 1 ? <label className="maker-run-picker">작업 선택<select value={selection.runId} onChange={event => setSelection({ project: selection.project, runId: event.target.value })}>{selectedCard.runs.map(item => <option key={item.id} value={item.id}>{item.summary || item.id}{item.archived ? " · 보관됨" : ""}</option>)}</select></label> : null}
          {runError ? <p className="maker-notice maker-notice--error" role="alert">현재 상태를 확인하지 못했습니다. {runError}</p> : null}
          {!run ? <p className="maker-empty" role="status">제작 상태를 불러오고 있어요.</p> : <>
            <MakerProgress run={run} checkedAt={runReadAt} readError={Boolean(runError)} completedCount={finishedTasks.size} onReviewPlan={() => setDialog("plan")} />
            {run.failure_message ? <details className="maker-failure-detail"><summary>문제 내용 보기</summary><p>{run.failure_message}</p></details> : null}
            <MakerRunControls key={`${selection.project}/${run.id}`} projectName={selection.project} run={run} onUpdated={acceptRun}
              onDeleted={() => { setSelection(undefined); setTaskId(""); void refreshProjects().catch(() => {}); }} />
            <div className="maker-workspace"><div className="maker-result-column"><ResultPanel key={`${selection.project}/${run.id}/${run.stage}/${run.verified_integration_head}/${run.tasks.map(task => task.completed_commit).join(",")}`} selection={selection} />
              <div className="maker-panel"><UserChecks run={run} busy={saving || Boolean(runError)} onRecord={record} />{!run.planned_user_checks?.length ? <div className="maker-check-empty"><Check size={20} /><div><h3>직접 확인</h3><p>결과를 실행해 보고 원하는 대로 동작하는지 확인하세요. 고칠 점은 AI에게 이야기할 수 있어요.</p></div></div> : null}</div></div>
              <section className="maker-panel maker-progress"><div className="maker-section-heading"><h2>만들어지는 과정</h2><small>자동 갱신</small></div><ol>{run.tasks.map(task => <li key={task.id} data-status={task.status}><button className="maker-task-open" onClick={() => setTaskId(task.id)} aria-haspopup="dialog"><span className="maker-task-marker">{finishedTasks.has(task.id) ? <Check size={15} /> : task.status === "running" ? <LoaderCircle size={15} /> : ""}</span><div><strong>{task.title}</strong><p>{({ completed: "완료", merged: "완료", running: "진행 중", failed: "확인 필요", pending: "대기 중", excluded: "이번 작업에서 제외", blocked: "이전 작업 대기" } as Record<string, string>)[task.status] || "진행 준비 중"}</p><small>{task.provider_id || task.agent_id} · {task.model || "기본 모델"}</small></div><ChevronRight size={16} /></button></li>)}</ol>{!run.tasks.length ? <p>AI와 계획을 정리하면 여기에 제작 과정이 표시됩니다.</p> : null}</section></div>
          </>}
        </div>}
        </> : null}
      </main>
      {taskId && run && selection && page === "projects" && run.tasks.some(task => task.id === taskId) ? <MakerTaskDetails
        key={`${selection.project}/${run.id}/${taskId}`} projectName={selection.project} run={run} task={run.tasks.find(task => task.id === taskId)!}
        onUpdated={acceptRun} onClose={() => setTaskId("")} /> : null}
      {dialog === "connection" ? <ConnectionDialog onClose={() => setDialog(undefined)} /> : null}
      {dialog === "plan" && run && selection ? <PlanDialog key={`${selection.project}/${run.id}/${run.plan_revision}`} selection={selection} run={run} onClose={() => setDialog(undefined)} onConfirmed={next => {
        if (selectionRef.current === `${selection.project}/${selection.runId}`) setRun(next);
      }} /> : null}
    </div>

  </>;
}

export function ProjectTile({ card, onOpen, onStart }: { card: ProjectCard; onOpen(runId: string): void; onStart(): void }) {
  const latest = latestMakerRun(card.runs);
  return <article className="maker-project-card"><div className="maker-project-visual"><FolderOpen size={40} /><span>{latest ? makerStage(latest) : "시작 준비"}</span></div><div className="maker-project-body"><h3>{card.project.name}</h3><p>{card.error || latest?.summary || "AI와 만들 내용을 정리해 주세요."}</p>{latest ? <><div className="maker-card-progress"><span>{latest.completed_task_count} / {latest.task_count} 작업 완료</span><progress value={latest.completed_task_count} max={Math.max(1, latest.task_count)} aria-label="제작 진행" /></div><button className="maker-button" onClick={() => onOpen(latest.id)}>프로젝트 열기<ArrowRight size={16} /></button></> : <button className="maker-button" onClick={onStart}>MCP 연결 프롬프트<ArrowRight size={16} /></button>}</div></article>;
}

function PlanDialog({ selection, run, onClose, onConfirmed }: { selection: Selection; run: RunState; onClose(): void; onConfirmed(run: RunState): void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(run.plan_revision === run.plan_approved_revision);
  async function confirm() {
    setBusy(true); setError("");
    try {
      await window.orchestrator.request("runs.confirmPlan", { projectName: selection.project, runId: run.id, expectedRevision: run.plan_revision });
      const next = await window.orchestrator.request<RunState>("runs.get", { projectName: selection.project, runId: run.id, includeUserChecks: true });
      onConfirmed(next); setConfirmed(next.plan_revision === next.plan_approved_revision);
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  return <WorkDialog title="제작 계획 확인" className="maker-dialog" onClose={() => { if (!busy) onClose(); }}><p>{run.summary}</p><ol className="maker-plan-list">{run.tasks.map(task => <li key={task.id}><h3>{task.title}</h3><p>{task.description}</p><ul>{task.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul><p className="maker-muted">작업 AI · {task.provider_id || task.agent_id}{task.model ? ` / ${task.model}` : ""}</p></li>)}</ol>{error ? <p role="alert">{error}</p> : null}{confirmed ? <p role="status">계획이 확정됐습니다. 대화 중인 AI에게 제작 시작을 요청하세요.</p> : <button className="maker-button maker-button--primary" disabled={busy || Boolean(run.archive)} onClick={() => void confirm()}>{busy ? "계획 확인 중…" : "이 계획으로 확정"}</button>}</WorkDialog>;
}

function ConnectionDialog({ onClose }: { onClose(): void }) {
  const [guide, setGuide] = useState<McpConnectionGuide>();
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [showPrompt, setShowPrompt] = useState(false);
  useEffect(() => {
    let active = true;
    void window.orchestrator.request<unknown>("connections.externalGuide").then(value => {
      const next = readMcpConnectionGuide(value);
      if (active) setGuide(next);
    }).catch(cause => { if (active) setError(message(cause)); });
    return () => { active = false; };
  }, []);
  const prompt = guide ? mcpConnectionPrompt(guide) : "";
  async function copy() {
    if (!prompt) return;
    setFeedback(""); setError("");
    try {
      await navigator.clipboard.writeText(prompt);
      setFeedback("연결 프롬프트를 복사했습니다. Codex·Claude 등의 새 채팅에 붙여 넣으세요.");
    } catch {
      setShowPrompt(true);
      setError("복사하지 못했습니다. 아래 연결 프롬프트를 선택해 직접 복사해 주세요.");
    }
  }
  return <WorkDialog title="MCP 설치·연결 프롬프트" className="maker-dialog" onClose={onClose}>
    <p>아래 프롬프트를 복사해 Codex·Claude 등의 새 채팅에 붙여 넣으세요.</p>
    <ol className="maker-connect-steps"><li>외부 앱에서 MCP 연결을 마칩니다.</li>
      <li>그 채팅에서 무엇을 만들지 정하고 오케스트레이터에 전달합니다.</li>
      <li>태스크 생성과 작업 AI 모델 배정이 끝나면 알림을 확인합니다.</li></ol>
    <button className="maker-button maker-button--primary" disabled={!guide} onClick={() => void copy()}>
      <Copy size={17} />MCP 설치·연결 프롬프트 복사</button>
    {!guide && !error ? <p role="status">연결 정보를 준비하고 있어요.</p> : null}
    <p role="status">{feedback}</p>{error ? <p role="alert">{error}</p> : null}
    <p className="maker-muted">오케스트레이터는 여러 작업 AI와 모델을 함께 사용합니다. 작업 AI 설정은 ‘작업 AI’에서 관리하세요.</p>
    {guide ? <details open={showPrompt} onToggle={event => setShowPrompt(event.currentTarget.open)}>
      <summary>연결 프롬프트 보기</summary><textarea className="maker-prompt-text" aria-label="MCP 설치·연결 프롬프트"
        readOnly rows={9} value={prompt} /></details> : null}
  </WorkDialog>;
}

export function ResultPanel({ selection, clientName = "연결한 AI 앱" }: { selection: Selection; clientName?: string }) {
  const [artifact, setArtifact] = useState<ResultArtifact>();
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [deviceId, setDeviceId] = useState("");
  const active = useRef(true);
  const launching = useRef(false);
  const params = { projectName: selection.project, runId: selection.runId };
  const load = useCallback(async () => {
    try { const next = await window.orchestrator.request<ResultArtifact>("runs.resultArtifact", { projectName: selection.project, runId: selection.runId }); if (active.current) { setArtifact(next); setError(""); } }
    catch (cause) { if (active.current) { setArtifact(undefined); setError(message(cause)); } }
  }, [selection.project, selection.runId]);
  useEffect(() => { active.current = true; void load(); return () => { active.current = false; }; }, [load]);
  async function launch() {
    if (!artifact?.can_launch || !artifact.digest || launching.current) return;
    launching.current = true;
    setBusy(true); setError(""); setFeedback("");
    try {
      const result = await window.orchestrator.request<{ status: string }>("runs.launchResult", { ...params, expectedDigest: artifact.digest, deviceId });
      if (active.current) setFeedback(result.status === "started" ? "앱 실행을 시작했습니다. 열린 창에서 직접 확인해 주세요." : "실행을 요청했습니다. 브라우저나 기기에서 결과를 확인해 주세요.");
    } catch (cause) { if (active.current) setError(message(cause)); }
    finally { launching.current = false; if (active.current) { setBusy(false); void load(); } }
  }
  const names = { web: "웹 결과물", windows: "Windows 앱", macos: "Mac 앱", android: "Android 앱" };
  const needsDevice = artifact?.kind === "android" && (artifact.devices?.length ?? 0) > 1 && !deviceId;
  return <section className="maker-panel maker-result">
    <div className="maker-section-heading"><h2>결과 실행</h2>
      <button className="maker-icon-button" disabled={busy} aria-label="결과 새로 확인" onClick={() => void load()}><RefreshCw size={16} /></button></div>
    <div className="maker-result-stage"><span className="maker-result-icon"><Play size={32} /></span>
      <h3>{artifact?.kind ? names[artifact.kind] : "만든 결과를 여기서 실행해요"}</h3>
      <p>{artifact?.reason || (error ? "결과 정보를 다시 확인해 주세요." : "실행할 결과를 확인하고 있어요.")}</p>
      {error ? <p role="alert">{error}</p> : null}
      {artifact?.verification_scope === "task" ? <p>제작 중인 결과입니다. 직접 확인을 마치면 다음 제작 단계로 진행할 수 있어요.</p> : null}
      {artifact?.can_launch && artifact.kind === "android" ? <label>실행할 휴대폰
        <select value={deviceId} disabled={busy} onChange={event => setDeviceId(event.target.value)}>
          <option value="">{artifact.devices?.length === 1 ? artifact.devices[0].name : "기기를 선택하세요"}</option>
          {artifact.devices?.map(device => <option key={device.id} value={device.id}>{device.name}</option>)}
        </select></label> : null}
      {artifact?.can_launch ? <button className="maker-button maker-button--primary" disabled={busy || Boolean(needsDevice)}
        onClick={() => void launch()}><Play size={17} />{busy ? "실행 준비 중…" : "결과 실행하기"}</button>
        : artifact || error ? <p>{clientName}에서 이 프로젝트의 실행할 결과물을 준비해 달라고 요청하세요.</p> : null}
    </div>
    <p role="status">{feedback}</p><p className="maker-muted">웹은 브라우저에서, PC 앱은 별도 창에서 열립니다.
      Android 앱은 선택한 기기에 설치하고 실행합니다.</p>
  </section>;
}
