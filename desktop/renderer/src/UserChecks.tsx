import { useState } from "react";
import type { PlannedUserCheck, RunState, UserCheckOutcome } from "./types";

export interface UserCheckInput {
  checkId: string;
  expectedCommit: string;
  expectedRevision: number;
  outcome: UserCheckOutcome;
  note: string;
}

const statusLabels = {
  pending: "기준 작업 대기", waiting: "확인 대기", passed: "통과", failed: "실패", deferred: "보류",
} satisfies Record<PlannedUserCheck["status"], string>;

export function UserChecks({ run, busy, onRecord }: {
  run: RunState;
  busy: boolean;
  onRecord?(input: UserCheckInput): Promise<void>;
}) {
  if (!run.planned_user_checks?.length) return null;
  const canRecord = Boolean(onRecord && !run.archive && run.plan_revision && run.plan_revision === run.plan_approved_revision
    && run.execution_control?.lock_state === "unlocked");
  const taskTitles = new Map(run.tasks.map(task => [task.id, task.title]));
  return <section className="user-checks" aria-labelledby="user-checks-title">
    <h3 id="user-checks-title" tabIndex={-1}>사용자 확인</h3>
    {run.planned_user_checks.map(check => <UserCheckCard key={`${check.check_id}:${check.reference_commit}`} check={check}
      anchor={taskTitles.get(check.after_task_id)} targets={check.blocks_task_ids.map(id => taskTitles.get(id) || id)}
      revision={run.plan_revision} canRecord={canRecord} busy={busy} onRecord={onRecord} />)}
  </section>;
}

function UserCheckCard({ check, anchor, targets, revision, canRecord, busy, onRecord }: {
  check: PlannedUserCheck;
  anchor?: string;
  targets: string[];
  revision: number;
  canRecord: boolean;
  busy: boolean;
  onRecord?(input: UserCheckInput): Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  async function save(outcome: UserCheckOutcome) {
    if (!onRecord || !check.reference_commit || !canRecord || busy || saving || !note.trim()) return;
    setSaving(true);
    setError("");
    try {
      await onRecord({ checkId: check.check_id, expectedCommit: check.reference_commit, expectedRevision: revision, outcome, note: note.trim() });
      setNote("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "사용자 확인을 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return <article className="user-check-card">
    <header><h4>{check.title}</h4><span>{statusLabels[check.status]}</span></header>
    <p>{check.instructions}</p>
    <ul aria-label="완료 기준">{check.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>
    <p className="muted-copy">{anchor ? `${anchor} 결과` : "계획 기준"} {check.reference_commit
      ? <code title={check.reference_commit}>{check.reference_commit.slice(0, 12)}</code> : "커밋 대기"}</p>
    {targets.length || check.required_for_integration ? <p className="muted-copy">통과 후 진행 · {[
      ...targets, ...(check.required_for_integration ? ["통합 검증"] : []),
    ].join(", ")}</p> : null}
    {check.note ? <p className="user-check-card__note">{check.note}</p> : null}
    {canRecord && check.reference_commit && check.status !== "passed" ? <details>
      <summary>확인 결과 기록</summary>
      <label className="field"><span>확인 환경과 결과</span><textarea maxLength={1800} rows={2} value={note}
        disabled={busy || saving} onChange={event => setNote(event.target.value)} /></label>
      <div className="task-record-actions__buttons">
        {(["failed", "deferred", "passed"] as const).map(outcome => <button key={outcome} type="button"
          className={`button button--${outcome === "passed" ? "primary" : "secondary"}`}
          disabled={busy || saving || !note.trim()} onClick={() => void save(outcome)}>{statusLabels[outcome]} 기록</button>)}
      </div>
      {error ? <p role="alert">{error}</p> : null}
    </details> : null}
  </article>;
}
