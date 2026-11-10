import { makerRunTitle } from "./makerPresentation";
import type { RunSummary } from "./types";

export function MakerRunPicker({ runs, selectedId, onSelect }: {
  runs: RunSummary[]; selectedId: string; onSelect(id: string, archived: boolean): void;
}) {
  const active = runs.filter(run => !run.archived);
  const archived = runs.filter(run => run.archived);
  const selectedActive = active.some(run => run.id === selectedId);
  const needsCleanup = archived.some(run => run.cleanup_status && run.cleanup_status !== "completed");
  const options = (items: RunSummary[]) => items.map((run, index) =>
    <option key={run.id} value={run.id}>{index + 1}. {makerRunTitle(run.summary) || "이름 없는 작업"}</option>);
  return <div className="maker-run-navigation">
    {active.length > 1 || active.length === 1 && !selectedActive ? <label className="maker-run-picker">작업 선택
      <select value={selectedActive ? selectedId : ""} onChange={event => onSelect(event.target.value, false)}>
        {!selectedActive ? <option value="" disabled>진행할 작업 선택</option> : null}{options(active)}
      </select></label> : null}
    {archived.length ? <details className="maker-archive-picker"><summary>보관함 ({archived.length}){needsCleanup ? " · 정리 확인 필요" : ""}</summary>
      <label className="maker-run-picker">보관 기록
        <select value={archived.some(run => run.id === selectedId) ? selectedId : ""} onChange={event => onSelect(event.target.value, true)}>
          <option value="" disabled>기록 선택</option>{options(archived)}
        </select></label>
    </details> : null}
  </div>;
}
