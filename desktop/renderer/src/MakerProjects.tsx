import { useEffect, useRef, useState, type FormEvent } from "react";
import { FolderOpen, Plus } from "lucide-react";
import { WorkDialog } from "./WorkDialog";
import { MainChangesDialog } from "./MainChangesDialog";
import { CodeStyleProfilePanel } from "./CodeStyleProfilePanel";
import { ProjectToolConnections } from "./ProjectToolConnections";
import type { GitInitialCommitPreview, GitRepositoryReadiness, ProjectCodeStylePreference, ProjectCodeStyleProfile, ProjectWorkspaceLocation, RegisteredProject } from "./types";

const errorText = (error: unknown) => error instanceof Error ? error.message : "설정을 변경하지 못했습니다.";

export function MakerProjects({ projects, initialProject, active, onChanged }: {
  projects: RegisteredProject[]; initialProject?: string; active: boolean; onChanged(): Promise<void>;
}) {
  const [name, setName] = useState(initialProject || "");
  const [registering, setRegistering] = useState(false);
  const project = projects.find(item => item.name === name) || projects[0];
  return <div className="maker-content maker-settings" hidden={!active}>
    <div className="maker-page-heading"><div><p className="maker-eyebrow">제작 환경</p><h1>프로젝트 관리</h1>
      <p>프로젝트 연결과 제작 환경을 한곳에서 관리합니다.</p></div><button className="maker-button maker-button--primary" onClick={() => setRegistering(true)}><Plus size={17} />기존 프로젝트 연결</button></div>
    {project ? <><label className="maker-run-picker">관리할 프로젝트<select value={project.name} onChange={event => setName(event.target.value)}>
      {projects.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>
      {projects.map(item => <div key={item.name} hidden={item.name !== project.name}><ProjectSettings project={item}
        active={active && item.name === project.name} onChanged={onChanged} /></div>)}</>
      : <section className="maker-empty"><FolderOpen size={32} /><h2>연결된 프로젝트가 없습니다</h2><p>새 프로젝트는 연결한 외부 앱에서 만들거나 기존 프로젝트 폴더를 연결할 수 있습니다.</p></section>}
    {registering ? <RegisterProject onClose={() => setRegistering(false)} onAdded={async () => { await onChanged(); setRegistering(false); }} /> : null}
  </div>;
}

function ProjectSettings({ project, active, onChanged }: { project: RegisteredProject; active: boolean; onChanged(): Promise<void> }) {
  const [source, setSource] = useState(project.planning_source_dir || "");
  const [dotnet, setDotnet] = useState(project.dotnet_executable || "");
  const [profile, setProfile] = useState<ProjectCodeStyleProfile>();
  const [preference, setPreference] = useState<ProjectCodeStylePreference>(project.code_style_preference);
  const [workspace, setWorkspace] = useState<ProjectWorkspaceLocation>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [changesOpen, setChangesOpen] = useState(false);
  const loaded = useRef(false);
  const preferenceLoaded = useRef(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!active || loaded.current) return;
    let alive = true;
    setLoading(true); setError("");
    void Promise.allSettled([
      window.orchestrator.request<ProjectCodeStyleProfile>("projects.codeStyleProfile", { projectName: project.name }),
      window.orchestrator.request<ProjectWorkspaceLocation>("projects.workspaceLocation", { projectName: project.name }),
    ]).then(([style, location]) => {
      if (!alive) return;
      if (style.status === "fulfilled") {
        setProfile(style.value);
        if (!preferenceLoaded.current) { setPreference(style.value.preference); preferenceLoaded.current = true; }
      }
      if (location.status === "fulfilled") setWorkspace(location.value);
      const failed = [style, location].filter(item => item.status === "rejected");
      setError(failed.map(item => item.status === "rejected" ? errorText(item.reason) : "").join(" · "));
      loaded.current = failed.length === 0;
      setLoading(false);
    });
    return () => { alive = false; };
  }, [project.name, active, reload]);
  async function change(action: () => Promise<unknown>, success: string) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try { if (await action() === null) return; await onChanged(); setNotice(success); }
    catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  async function choose(kind: "planningSource" | "dotnet") {
    try { const path = await window.orchestrator.selectPath(kind); if (path) { if (kind === "dotnet") setDotnet(path); else setSource(path); } }
    catch (cause) { setError(errorText(cause)); }
  }
  async function styleAction(save: boolean) {
    await change(async () => {
      const params = { projectName: project.name, preference, expectedRevision: profile?.preference_revision };
      const next = save ? await window.orchestrator.approve<ProjectCodeStyleProfile>("projects.updateCodeStylePreference", params)
        : await window.orchestrator.request<ProjectCodeStyleProfile>("projects.previewCodeStylePreference", params);
      if (next) { setProfile(next); if (save) setPreference(next.preference); }
      return next;
    }, save ? "코드 스타일을 저장했습니다. 새 작업부터 적용됩니다." : "적용할 규칙을 확인했습니다.");
  }
  return <div className="maker-form-stack">
    {error ? <div className="maker-notice maker-notice--error" role="alert"><p>{error}</p>
      {!loaded.current ? <button className="maker-button" onClick={() => setReload(value => value + 1)}>설정 다시 확인</button> : null}</div> : null}
    {notice ? <p className="maker-notice" role="status">{notice}</p> : null}
    <section className="maker-panel"><h2>{project.name}</h2><dl className="maker-key-values"><div><dt>프로젝트 폴더</dt><dd>{project.repo}</dd></div>
      <div><dt>작업 저장 위치</dt><dd>{workspace?.root || "확인 중"}</dd></div></dl>
      <div className="maker-actions"><button className="maker-button" onClick={() => setChangesOpen(true)}>원본 변경·동기화</button>
        <button className="maker-button maker-button--danger" disabled={busy} onClick={() => void change(() => window.orchestrator.approve("projects.remove", { projectName: project.name }), "프로젝트 연결을 해제했습니다.")}>프로젝트 연결 해제</button></div>
      <p className="maker-muted">연결을 해제해도 프로젝트 파일은 유지됩니다.</p></section>
    <section className="maker-panel"><h2>제작 환경</h2><div className="maker-form-stack">
      <label className="field"><span>기획 자료 폴더</span><input value={source} disabled={busy} onChange={event => setSource(event.target.value)} /></label>
      <div className="maker-actions"><button className="maker-button" disabled={busy} onClick={() => void choose("planningSource")}>폴더 선택</button>
        <button className="maker-button" disabled={busy} onClick={() => void change(() => window.orchestrator.request("projects.updatePlanningSource", { projectName: project.name, sourceRoot: source }), "기획 자료 위치를 저장했습니다.")}>자료 위치 저장</button></div>
      <details><summary>개발 도구와 코드 스타일</summary><div className="maker-form-stack">
        <label className="field"><span>.NET 실행 파일 · 비워 두면 자동 탐색</span><input value={dotnet} disabled={busy} onChange={event => setDotnet(event.target.value)} /></label>
        <div className="maker-actions"><button className="maker-button" disabled={busy} onClick={() => void choose("dotnet")}>실행 파일 선택</button>
          <button className="maker-button" disabled={busy} onClick={() => void change(() => window.orchestrator.request("projects.updateDotnet", { projectName: project.name, executable: dotnet }), "개발 도구 경로를 저장했습니다.")}>경로 저장</button></div>
        {preference ? <CodeStyleProfilePanel profile={profile} draft={preference} loading={loading} busy={busy} error="" message="" onChange={setPreference}
          onPreview={() => void styleAction(false)} onSave={() => void styleAction(true)} /> : <p>코드 스타일 설정을 확인하고 있습니다.</p>}
      </div></details></div></section>
    <ProjectToolConnections projectName={project.name} active={active} onChanged={onChanged} />
    {changesOpen ? <MainChangesDialog projectName={project.name} onClose={() => setChangesOpen(false)} onChanged={value => { setNotice(value); void onChanged().catch(cause => setError(errorText(cause))); }} onError={setError} /> : null}
  </div>;
}

export function RegisterProject({ onClose, onAdded }: { onClose(): void; onAdded(): Promise<void> }) {
  const [repo, setRepo] = useState("");
  const [name, setName] = useState("");
  const [readiness, setReadiness] = useState<GitRepositoryReadiness>();
  const [preview, setPreview] = useState<GitInitialCommitPreview>();
  const [selected, setSelected] = useState<string[]>([]);
  const [author, setAuthor] = useState({ name: "", email: "" });
  const [allowEmpty, setAllowEmpty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  async function inspect(path: string) {
    const current = ++generation.current;
    setReadiness(undefined); setPreview(undefined); setError(""); setBusy(true);
    try {
      const next = await window.orchestrator.request<GitRepositoryReadiness>("projects.inspectGitReadiness", { repo: path });
      if (current !== generation.current) return;
      setReadiness(next);
      if (next.kind === "unborn") {
        const initial = await window.orchestrator.request<GitInitialCommitPreview>("projects.previewInitialCommit", { repo: path });
        if (current !== generation.current) return;
        setPreview(initial); setSelected(initial.changes.filter(item => item.selected_by_default).map(item => item.path));
        setAuthor({ name: initial.author_name, email: initial.author_email }); setAllowEmpty(false);
      }
    } catch (cause) { if (current === generation.current) setError(errorText(cause)); }
    finally { if (current === generation.current) setBusy(false); }
  }
  useEffect(() => () => { generation.current++; }, []);
  async function choose() {
    try { const path = await window.orchestrator.selectPath("repository"); if (path) { setRepo(path); await inspect(path); } }
    catch (cause) { setError(errorText(cause)); }
  }
  async function prepare() {
    setBusy(true); setError("");
    try {
      const result = readiness?.kind === "not_initialized"
        ? await window.orchestrator.approve("projects.initializeGit", { repo, expectedKind: "not_initialized" })
        : await window.orchestrator.approve("projects.createInitialCommit", { repo, snapshotId: preview?.snapshot_id, selectedPaths: selected,
          message: "Initial commit", authorName: author.name, authorEmail: author.email, saveAuthor: true, allowEmpty });
      if (result !== null) await inspect(repo);
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || readiness?.kind !== "ready") return;
    setBusy(true); setError("");
    try { await window.orchestrator.request("projects.add", { name, repo }); await onAdded(); }
    catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <WorkDialog title="기존 프로젝트 연결" className="maker-dialog" onClose={() => { if (!busy) onClose(); }}>
    <form onSubmit={event => void submit(event)} className="maker-form-stack"><label className="field"><span>프로젝트 이름 · 비워 두면 폴더 이름 사용</span>
      <input value={name} disabled={busy} onChange={event => setName(event.target.value)} /></label>
      <label className="field"><span>프로젝트 폴더</span><input readOnly value={repo} /></label>
      <button className="maker-button" type="button" disabled={busy} onClick={() => void choose()}><FolderOpen size={16} />폴더 선택</button>
      {readiness?.diagnostics.map((item, index) => <p key={index} className="maker-muted">{item}</p>)}
      {readiness?.kind === "not_initialized" ? <><p>이 폴더에서 작업 기록을 관리하려면 Git 저장소를 준비해야 합니다.</p>
        <button className="maker-button" type="button" disabled={busy} onClick={() => void prepare()}>작업 기록 준비</button></> : null}
      {preview && readiness?.kind === "unborn" ? <fieldset disabled={busy}><legend>첫 작업 기준 만들기</legend>
        <label className="field"><span>작성자 이름</span><input value={author.name} onChange={event => setAuthor({ ...author, name: event.target.value })} /></label>
        <label className="field"><span>작성자 이메일</span><input value={author.email} onChange={event => setAuthor({ ...author, email: event.target.value })} /></label>
        <div className="maker-file-list">{preview.changes.map(item => <label key={item.path}><input type="checkbox" disabled={Boolean(item.exclusion_reason)} checked={selected.includes(item.path)}
          onChange={event => setSelected(event.target.checked ? [...selected, item.path] : selected.filter(path => path !== item.path))} />{item.path}{item.exclusion_reason ? ` · ${item.exclusion_reason}` : ""}</label>)}</div>
        <label><input type="checkbox" checked={allowEmpty} onChange={event => setAllowEmpty(event.target.checked)} />선택한 파일 없이 시작하기 허용</label>
        <button className="maker-button" type="button" disabled={busy || !selected.length && !allowEmpty} onClick={() => void prepare()}>첫 기준 저장 승인</button></fieldset> : null}
      {error ? <p role="alert">{error}</p> : null}<button className="maker-button maker-button--primary" disabled={busy || readiness?.kind !== "ready"} type="submit">{busy ? "확인 중…" : "프로젝트 연결"}</button>
    </form>
  </WorkDialog>;
}
