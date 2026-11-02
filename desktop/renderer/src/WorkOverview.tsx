import { useEffect, useRef, useState } from "react";
import { FolderKanban, RefreshCw } from "lucide-react";
import { WorkDialog } from "./WorkDialog";
import { filterProjectWork, initialWorkBucket, projectWork, workBucketLabels, workBuckets, type ProjectWorkFilter, type ProjectWorkSnapshot, type WorkBucket } from "./projectWorkPresentation";
import type { ActiveGroupSnapshot, RegisteredProject, RunSummary, RunState, RunExecutionControl } from "./types";

export function WorkOverview({ projects, active, history = false, visible = true, choosingNewWork = false, onCancelNewWork, onSelectProject, onNewWork, onOpen, onRegister, onCreate = onRegister }: {
  projects: RegisteredProject[]; active: ActiveGroupSnapshot;
  history?: boolean; visible?: boolean; choosingNewWork?: boolean; onCancelNewWork?(): void;
  onSelectProject(projectName: string): void; onNewWork(projectName: string): void;
  onOpen(projectName: string, runId: string, archived?: boolean, view?: "operations"): void; onRegister(): void; onCreate?(): void;
}) {
  const [snapshots, setSnapshots] = useState<Record<string, ProjectWorkSnapshot>>({});
  const [selected, setSelected] = useState("");
  const [expanded, setExpanded] = useState<Record<string, WorkBucket[]>>({});
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const [filter, setFilter] = useState<ProjectWorkFilter>("all");
  const [search, setSearch] = useState("");
  const [entry, setEntry] = useState<"choose" | "existing">("choose");
  const projectKey = JSON.stringify(projects.map((project) => project.name));
  const titleId = history ? "completed-records-title" : "work-overview-title";
  async function refresh() {
    if (inFlight.current) return;
    inFlight.current = true;
    const request = ++generation.current;
    setLoading(true);
    try {
      const results = await Promise.allSettled(projects.map(async (project) => {
        const current = await window.orchestrator.request<RunSummary[]>("runs.list", { projectName: project.name, scope: "active" });
        const archived = history ? await window.orchestrator.request<RunSummary[]>("runs.list", { projectName: project.name, scope: "archived" }) : [];
        const groups = history ? [...current.filter((run) => run.pipeline_complete), ...archived] : current;
        const candidates = groups.filter((run) => !run.archived && ["resumable", "attention_required"].includes(run.execution_situation));
        const details = await Promise.allSettled(candidates.map((run) => window.orchestrator.request<RunState>("runs.get", { projectName: project.name, runId: run.id })));
        const controls: Record<string, RunExecutionControl> = {};
        const controlErrors: Record<string, string> = {};
        details.forEach((result, index) => {
          const id = candidates[index].id;
          if (result.status === "fulfilled" && result.value.id === id && result.value.execution_control) controls[id] = result.value.execution_control;
          else controlErrors[id] = result.status === "rejected" ? String(result.reason) : "실행 제어 상태를 확인하지 못했습니다.";
        });
        return { name: project.name, groups, controls, controlErrors };
      }));
      if (request !== generation.current) return;
      setSnapshots((previous) => Object.fromEntries(results.map((result, index) => {
        const name = projects[index].name;
        return [name, result.status === "fulfilled"
          ? { ...result.value, controls: { ...Object.fromEntries(Object.keys(result.value.controlErrors)
            .filter((id) => previous[name]?.controls?.[id]).map((id) => [id, previous[name].controls![id]])), ...result.value.controls }, checkedAt: new Date().toISOString(), error: "" }
          : { ...previous[name], groups: previous[name]?.groups || [], checkedAt: previous[name]?.checkedAt || "",
            error: result.reason instanceof Error ? result.reason.message : String(result.reason) }];
      })));
    } finally {
      if (request === generation.current) { inFlight.current = false; setLoading(false); }
    }
  }
  useEffect(() => {
    inFlight.current = false;
    if (!visible) { setLoading(false); return; }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { generation.current++; inFlight.current = false; window.clearInterval(timer); };
  }, [projectKey, visible, history]);
  useEffect(() => {
    if (choosingNewWork) { setSelected(""); setEntry("choose"); }
  }, [choosingNewWork]);
  const cards = projectWork(projects, snapshots, active);
  const visibleCards = filterProjectWork(cards, filter, search);
  const current = cards.find((card) => card.name === selected);
  const currentExpanded = current ? expanded[current.name] ?? initialWorkBucket(current) : [];
  const counts = { attention: cards.filter((card) => card.error || card.counts.attention).length,
    running: cards.filter((card) => card.groups.some((item) => item.active)).length,
    waiting: cards.filter((card) => card.counts.waiting).length };
  return <section className="work-overview" aria-labelledby={titleId}>
    <header className="work-overview__heading"><div><h2 id={titleId} tabIndex={-1}>{history ? "완료한 작업" : "내 프로젝트"}</h2>
      <p>프로젝트 {cards.length}개 · 실행 중 {counts.running}개 · 확인 필요 {counts.attention}개</p></div>
      <button className="button button--quiet" type="button" disabled={loading} onClick={() => void refresh()}><RefreshCw size={15} aria-hidden="true" />{loading ? "확인 중…" : "현황 새로고침"}</button></header>
    {choosingNewWork && entry === "choose" ? <div className="new-work-entry">
      <button className="new-work-entry__card" type="button" onClick={() => setEntry("existing")}><FolderKanban size={24} aria-hidden="true" /><strong>기존 프로젝트 열기</strong><span>등록한 프로젝트나 작업하던 폴더에서 이어서 시작합니다.</span></button>
      <button className="new-work-entry__card" type="button" onClick={onCreate}><FolderKanban size={24} aria-hidden="true" /><strong>새 프로젝트 만들기</strong><span>사용할 폴더를 선택하고 만들고 싶은 프로그램을 알려주세요.</span></button>
      <button className="button button--quiet" type="button" onClick={onCancelNewWork}>취소</button>
    </div> : null}
    <div hidden={choosingNewWork && entry === "choose"}>
    {choosingNewWork && entry === "existing" ? <div className="project-selection-prompt"><div><p>이어서 작업할 프로젝트를 선택하세요.</p><button className="button button--secondary" type="button" onClick={onRegister}>폴더에서 프로젝트 열기</button></div>
      <button className="button button--quiet" type="button" onClick={onCancelNewWork}>선택 취소</button></div> : null}
    {!projects.length && !(choosingNewWork && entry === "existing") ? <div className="work-overview__empty"><p>프로젝트를 등록해 작업을 시작하세요.</p><button className="button button--primary" onClick={onRegister}>프로젝트 등록</button></div> : null}
    {projects.length ? <div className="project-work-filters"><div role="group" aria-label="프로젝트 필터">
      {([['all', '전체'], ['running', '실행 중'], ['attention', '확인 필요']] as const).map(([value, label]) => <button className="button button--quiet" type="button" key={value}
        aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div>
      <label className="project-work-search"><span className="sr-only">프로젝트 찾기</span><input type="search" value={search} placeholder="프로젝트 찾기" onChange={(event) => setSearch(event.target.value)} /></label>
    </div> : null}
    {projects.length && !visibleCards.length ? <p role="status">조건에 맞는 프로젝트가 없습니다. <button className="button button--quiet" type="button" onClick={() => { setFilter("all"); setSearch(""); }}>전체 보기</button></p> : null}
    <div className="project-work-grid">{visibleCards.map((card) => <button className="project-work-card" key={card.name} type="button" aria-haspopup="dialog"
      aria-label={`${card.name} · 프로젝트 선택·작업 현황`}
      onClick={() => {
        onSelectProject(card.name);
        if (card.groups.length) setExpanded((previous) => previous[card.name] ? previous : { ...previous, [card.name]: initialWorkBucket(card) });
        setSelected(card.name);
      }}>
      <span className="project-work-card__title"><FolderKanban size={18} aria-hidden="true" /><strong>{card.name}</strong></span>
      <span className="project-work-card__statuses">{card.unknown ? <span data-tone="danger">확인 불가</span> : null}{card.pending ? <span>조회 중</span> : workBuckets.filter((bucket) => card.counts[bucket]).map((bucket) => <span key={bucket} data-tone={bucket}>{workBucketLabels[bucket]} {card.counts[bucket]}개</span>)}</span>
      <span>{card.pending ? "작업 건수 조회 중" : card.unknown && !card.groups.length ? "작업 그룹·Task 건수 확인 불가"
        : `작업 그룹 ${card.groups.length}개 · 완료 Task ${card.completedTasks}/${card.totalTasks}${card.unknown ? " · 이전 조회 결과" : ""}`}</span>
      {card.unknown ? <span>마지막 목록 확인 · {card.checkedAt ? new Date(card.checkedAt).toLocaleString() : "확인 기록 없음"}</span> : null}
      <span className="project-work-card__action">작업 보기 →</span>
    </button>)}</div>
    </div>
    {current && (!choosingNewWork || entry === "existing") ? <WorkDialog title={`${current.name} · 작업 현황`} context={current.pending ? "작업 건수 조회 중" : current.unknown && !current.groups.length ? "작업 그룹·Task 건수 확인 불가"
      : `작업 그룹 ${current.groups.length}개 · 완료 Task ${current.completedTasks}/${current.totalTasks}${current.unknown ? " · 이전 조회 결과" : ""}`} onClose={() => setSelected("")}>
      {current.error ? <div role="alert"><p>최신 상태 확인 불가 · 이전 결과를 보존했습니다.</p><p>{current.error}</p><button className="button button--secondary" disabled={loading} onClick={() => void refresh()}>다시 확인</button></div> : null}
      {workBuckets.filter((bucket) => current.counts[bucket]).map((bucket) => <section className="project-work-bucket" key={bucket} data-bucket={bucket}>
        {bucket === "running" ? <h3 className="project-work-bucket__heading">실행 중 {current.counts.running}개</h3>
          : <button type="button" className="project-work-bucket__toggle" aria-expanded={currentExpanded.includes(bucket)}
          onClick={() => setExpanded((previous) => ({ ...previous, [current.name]: currentExpanded.includes(bucket)
            ? currentExpanded.filter((item) => item !== bucket) : [...currentExpanded, bucket] }))}>
          {currentExpanded.includes(bucket) ? "▾" : "▸"} {workBucketLabels[bucket]} {current.counts[bucket]}개</button>}
        <div hidden={bucket !== "running" && !currentExpanded.includes(bucket)}>{current.groups.filter((item) => item.bucket === bucket).map(({ run, reason }) => <div className="project-work-group" key={run.id}>
          <div><strong>{run.summary || run.id}</strong><p>{reason} · 완료 {run.completed_task_count}/{run.task_count}</p>{snapshots[current.name]?.controlErrors?.[run.id] ? <p role="alert">{snapshots[current.name].controlErrors?.[run.id]}</p> : null}</div>
          <button className={`button button--${bucket === "running" ? "primary" : "secondary"}`} type="button" onClick={() => { setSelected(""); onOpen(current.name, run.id, Boolean(run.archived)); }}>작업 열기</button>
        </div>)}</div>
      </section>)}
      {!current.groups.length ? <p>{current.pending ? "작업 그룹 조회 중" : current.error ? "작업 그룹 목록을 확인할 수 없습니다." : "등록된 작업 그룹이 없습니다."}</p> : null}
      <div className="project-work-actions"><button className={`button button--${current.groups.length ? "secondary" : "primary"}`} type="button"
        onClick={() => { setSelected(""); onNewWork(current.name); }}>이 프로젝트에서 새 작업</button></div>
    </WorkDialog> : null}
  </section>;
}
