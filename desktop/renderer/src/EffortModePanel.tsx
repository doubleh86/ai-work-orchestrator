import { useEffect, useId, useRef, useState } from "react";
import type { EffortMode, EffortModePreview, RunState } from "./types";

export const effortModeLabels: Record<EffortMode, string> = {
  economy: "절약", balanced: "균형", focused: "집중",
};

export function effortLimitLabel(effect: string): string {
  const split = effect.lastIndexOf(":");
  const code = effect.slice(split + 1);
  const messages: Record<string, string> = {
    legacy_profile_preserved: "이전 설정은 그대로 유지합니다. 작업 설정에서 직접 조정할 수 있습니다.",
    started_task_profile_locked: "이미 시작한 작업은 현재 실행 설정을 유지합니다.",
    reasoning_auto_adjustment_unsupported: "이 모델은 권장 추론 강도를 지원하지 않아 기존 강도를 유지합니다.",
    mode_profile_baseline_missing: "원래 추론 설정을 확인할 수 없습니다. 작업 설정을 먼저 확인하세요.",
    reviewer_unavailable: "필요한 리뷰어를 사용할 수 없습니다. 작업의 리뷰 설정을 먼저 확인하세요.",
  };
  return `${split >= 0 ? `${effect.slice(0, split)} · ` : ""}${messages[code] || effect}`;
}

export function effortPlanBlock(run: RunState, preview: EffortModePreview | undefined, mode: EffortMode, planDirty: boolean): string {
  const control = run.effort_control;
  if (planDirty) return "미저장 작업 편집을 먼저 저장하거나 취소하세요.";
  if (!control?.consistent) return "최신 작업 그룹 상태를 확인하세요.";
  if (!control.can_apply_plan) return "작업을 시작하지 않은 계획에서만 반영할 수 있습니다.";
  if (control.selected_mode !== mode) return "선택을 먼저 저장한 뒤 변경 비교를 확인하세요.";
  if (!preview || preview.mode !== mode || preview.policy_revision !== control.policy_revision
    || preview.plan_revision !== run.plan_revision) return "최신 변경 비교를 확인하세요.";
  if (!preview.can_apply) return "적용할 수 없는 설정이 있습니다. 아래 안내를 확인하세요.";
  return "";
}

function hasMissingReviewers(preview: EffortModePreview | undefined, reviewers: Record<string, string>): boolean {
  return Boolean(preview?.tasks.some((task) => task.review.policy_added
    && !task.reviewer_options.some((option) => option.agent_id === reviewers[task.task_id])));
}

export function EffortModePanel({ projectName, run, planDirty, draftMode, onDraftMode, onUpdated }: {
  projectName: string; run: RunState; planDirty: boolean; draftMode?: EffortMode;
  onDraftMode?(mode: EffortMode): void; onUpdated(run: RunState): void;
}) {
  const control = run.effort_control;
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<EffortMode>(draftMode || control?.pending_execution_mode || control?.selected_mode || "balanced");
  const [preview, setPreview] = useState<EffortModePreview>();
  const [reviewers, setReviewers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const alive = useRef(true);
  const generation = useRef(0);
  const receipt = useRef<{ key: string; id: string } | undefined>(undefined);
  const latest = useRef({ run, planDirty, mode });
  latest.current = { run, planDirty, mode };
  const fieldId = useId();
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; generation.current += 1; };
  }, []);

  async function refresh(): Promise<RunState> {
    const updated = await window.orchestrator.request<RunState>("runs.get", { projectName, runId: run.id });
    if (alive.current) onUpdated(updated);
    return updated;
  }

  async function compare() {
    if (pending.current || !control?.consistent) return;
    pending.current = true;
    const token = ++generation.current;
    setBusy("preview"); setError(""); setNotice(""); setPreview(undefined);
    try {
      const result = await window.orchestrator.request<EffortModePreview>("runs.previewEffortMode", {
        projectName, runId: run.id, mode, expectedRevision: control.policy_revision,
      });
      if (alive.current && token === generation.current) { setPreview(result); setReviewers({}); }
    } catch (cause) { if (alive.current) setError(String(cause)); }
    finally { pending.current = false; if (alive.current) setBusy(""); }
  }

  async function mutate(action: "select" | "reserve" | "cancel" | "apply") {
    const current = latest.current;
    const policy = current.run.effort_control;
    if (pending.current || !policy?.consistent) return;
    if (action === "select" && (!policy.can_select_plan || current.planDirty)) return;
    if (action === "reserve" && !policy.can_reserve) return;
    if (action === "cancel" && !policy.can_cancel_reservation) return;
    if (action === "apply" && (effortPlanBlock(current.run, preview, current.mode, current.planDirty)
      || hasMissingReviewers(preview, reviewers))) return;
    pending.current = true;
    generation.current += 1;
    const key = `${action}:${current.mode}:${policy.policy_revision}`;
    if (!receipt.current || receipt.current.key !== key) receipt.current = { key, id: crypto.randomUUID() };
    const requestId = receipt.current.id;
    setBusy(action); setError(""); setNotice("");
    try {
      if (action === "apply") {
        await window.orchestrator.request("runs.applyEffortModeToPlan", {
          projectName, runId: run.id, mode: current.mode, expectedPolicyRevision: policy.policy_revision,
          expectedPlanRevision: current.run.plan_revision, reviewerAgentIds: reviewers,
        });
      } else if (action === "cancel") {
        await window.orchestrator.request("runs.cancelEffortReservation", {
          projectName, runId: run.id, expectedPolicyRevision: policy.policy_revision, requestId,
        });
      } else {
        await window.orchestrator.request("runs.setEffortMode", {
          projectName, runId: run.id, mode: current.mode, target: action === "select" ? "planning" : "next_execution",
          expectedPolicyRevision: policy.policy_revision, requestId,
        });
      }
      const updated = await refresh();
      if (alive.current) {
        setPreview(undefined);
        setNotice(action === "apply" ? updated.plan_revision !== current.run.plan_revision
          ? "계획에 반영했습니다. 바뀐 작업을 확인하고 계획을 확정하세요."
          : "계획 설정을 확인했습니다. 변경할 항목이 없습니다."
          : action === "select" ? "선택을 저장했습니다. 변경 비교를 확인한 뒤 계획에 반영하세요."
          : action === "reserve" ? "다음 실행에 예약했습니다. 현재 실행과 재개는 기존 강도를 유지합니다."
          : "다음 실행 예약을 취소했습니다.");
      }
    } catch (cause) {
      try {
        const updated = await refresh();
        if (!alive.current) return;
        setPreview(undefined);
        if (action !== "apply" && updated.effort_control?.last_mutation?.request_id === requestId) {
          setNotice("응답은 유실됐지만 저장 기록을 확인했습니다. 최신 설정을 확인하세요.");
        } else setError(`변경 결과를 확인하세요. 최신 상태를 조회했습니다. ${String(cause)}`);
      } catch (refreshError) {
        if (alive.current) setError(`변경 결과를 확인하지 못했습니다. 상태 다시 확인 후 진행하세요. ${String(cause)} · ${String(refreshError)}`);
      }
    } finally { pending.current = false; if (alive.current) setBusy(""); }
  }

  const block = effortPlanBlock(run, preview, mode, planDirty);
  const reviewerMissing = hasMissingReviewers(preview, reviewers);
  const previewCurrent = Boolean(control && preview && preview.mode === mode
    && preview.policy_revision === control.policy_revision && preview.plan_revision === run.plan_revision);
  const manualCount = run.tasks.filter((task) => task.profile_source === "manual").length;
  return <section className="effort-mode-panel" aria-label="작업 강도">
    <div className="effort-mode-panel__summary">
      <strong>작업 강도 · {control ? control.selected_mode ? effortModeLabels[control.selected_mode] : "기존 작업 설정" : "상태 확인 필요"}</strong>
      {manualCount ? <span>수동 설정 유지 · 작업 {manualCount}개</span> : null}
      {control?.current_policy ? <span>{control.current_binding_status === "started" ? "현재 실행" : control.current_binding_status === "finished" ? "마지막 실행" : "실행 준비"} · {effortModeLabels[control.current_policy.mode]}</span> : null}
      {control?.pending_execution_mode ? <span>다음 실행 예약 · {effortModeLabels[control.pending_execution_mode]}</span> : null}
      <button id="effort-mode-change" className="button button--quiet" type="button" aria-expanded={open} aria-controls={fieldId} onClick={() => setOpen(!open)}>{open ? "설정 접기" : "강도 변경"}</button>
    </div>
    {open ? <div id={fieldId} className="effort-mode-panel__editor">
      <h3>{control?.can_select_plan ? "계획의 작업 강도" : control?.can_reserve ? "다음 실행의 작업 강도" : "작업 강도 확인"}</h3>
      <p>절약은 추론을 낮추고, 균형은 기획 추천을 사용합니다. 집중은 별도 리뷰를 제안하며, 직접 선택해 계획에 반영해야 추가됩니다. 수동 설정·필수 리뷰·검증은 유지합니다.</p>
      <fieldset disabled={Boolean(busy) || !control?.consistent}><legend>작업 강도 선택</legend>
        {(["economy", "balanced", "focused"] as const).map((value) => <label key={value}>
          <input type="radio" name={fieldId} value={value} checked={mode === value} onChange={() => {
            generation.current += 1; setMode(value); onDraftMode?.(value); setPreview(undefined); setReviewers({}); setNotice("");
          }} />{effortModeLabels[value]}
        </label>)}
      </fieldset>
      {control && mode !== (control.can_select_plan ? control.selected_mode : control.pending_execution_mode) ? <p role="status">미저장 선택 · {effortModeLabels[mode]}</p> : null}
      {control?.reason ? <p role="alert">{control.reason}</p> : null}
      <div className="effort-mode-panel__actions">
        <button className="button button--secondary" type="button" disabled={Boolean(busy) || !control?.consistent} onClick={() => void compare()}>{busy === "preview" ? "비교 중" : "변경 비교"}</button>
        <button className="button button--quiet" type="button" disabled={Boolean(busy)} onClick={() => void refresh().catch((cause: unknown) => setError(String(cause)))}>상태 다시 확인</button>
        {control?.can_select_plan ? <button className="button button--secondary" type="button" disabled={Boolean(busy) || planDirty || mode === control.selected_mode} onClick={() => void mutate("select")}>{busy === "select" ? "저장 중" : "선택 저장"}</button> : null}
        {control?.can_reserve ? <button className="button button--secondary" type="button" disabled={Boolean(busy) || mode === control.pending_execution_mode} onClick={() => void mutate("reserve")}>{busy === "reserve" ? "예약 중" : "다음 실행에 예약"}</button> : null}
        {control?.pending_execution_mode ? <button className="button button--quiet" type="button" disabled={Boolean(busy) || !control.can_cancel_reservation} onClick={() => void mutate("cancel")}>{busy === "cancel" ? "취소 중" : "예약 취소"}</button> : null}
      </div>
      <p>선택 저장만으로 작업 설정은 바뀌지 않습니다. 예약은 새 실행을 시작할 때 사용하며 계획 재검토가 필요할 수 있습니다. 현재 실행·재개는 기존 강도를 유지합니다.</p>
      <p>미저장 선택은 그룹·프로젝트를 옮겨도 앱 세션에서 유지됩니다. 앱을 종료하면 사라집니다.</p>
      {preview && !previewCurrent ? <p role="status">설정이나 계획이 바뀌었습니다. 변경 비교를 다시 확인하세요.</p> : null}
      {previewCurrent && preview ? <>
        {preview.planning_reasoning ? <p>기획 추론 · {run.planning_reasoning_effort || "기본"} → {preview.planning_reasoning.reasoning_effort || "기본"}</p> : null}
        <div className="effort-mode-panel__table">
          <table>
            <caption>{effortModeLabels[preview.mode]} 적용 예상 · 실제 반영 전</caption>
            <thead><tr><th>작업</th><th>추론·실행 모델</th><th>설정 출처</th><th>리뷰</th></tr></thead>
            <tbody>{preview.tasks.map((task) => <tr key={task.task_id}>
              <th scope="row">{run.tasks.find((item) => item.id === task.task_id)?.title || task.task_id}</th>
              <td>
                {task.current_reasoning_effort || "기본"} → {task.reasoning.reasoning_effort || "기본"}
                {task.reasoning.provider_id ? <small>{task.reasoning.provider_id} · {task.reasoning.model || "기본 모델"}</small> : null}
                {task.reasoning.selection_reason ? <small>{task.reasoning.selection_reason}</small> : null}
              </td>
              <td>{task.reasoning.profile_source === "manual" ? "수동 설정 유지"
                : task.reasoning.profile_source === "legacy" ? "기존 설정 유지" : "자동"}</td>
              <td>{task.review.policy_added ? task.reviewer_options.length ? <label>리뷰 추가
                <select aria-label={`${task.task_id} 리뷰어 선택`} value={reviewers[task.task_id] || ""}
                  disabled={Boolean(busy)} onChange={(event) => setReviewers({ ...reviewers, [task.task_id]: event.target.value })}>
                  <option value="">리뷰어 선택</option>
                  {task.reviewer_options.map((item) => <option key={item.agent_id} value={item.agent_id}>
                    {item.agent_id} · {item.provider_id} · {item.model || "기본 모델"}{item.provider_id === task.reasoning.provider_id ? " · 별도 리뷰" : ""}
                  </option>)}
                </select>
              </label> : <span>추가 가능한 리뷰 AI가 없습니다. AI 연결·리뷰 설정을 확인하세요.</span>
                : task.review.policy_removed ? "모드가 추가한 리뷰 제거" : task.review.required ? "필수 리뷰 유지"
                : task.current_reviewer_agent_id ? "리뷰 유지" : "추가 없음"}</td>
            </tr>)}</tbody>
          </table>
        </div>
        {preview.unsupported_effects.length ? <details><summary>자동 변경 제한 {preview.unsupported_effects.length}건</summary>
          <ul>{preview.unsupported_effects.map((item, index) => <li key={index}>{effortLimitLabel(item)}</li>)}</ul>
        </details> : null}
        <p>{block || (reviewerMissing ? "추가할 리뷰의 리뷰어를 선택하세요." : preview.requires_plan_review ? "반영 후 변경된 계획을 다시 확정해야 합니다." : "현재 작업 설정과 비교를 확인했습니다.")}</p>
        <button className="button button--primary" type="button" disabled={Boolean(busy || block || reviewerMissing)} onClick={() => void mutate("apply")}>{busy === "apply" ? "반영 중" : "계획에 반영"}</button>
      </> : planDirty ? <p role="status">{block}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {error ? <p className="error-text" role="alert">{error}</p> : null}
    </div> : null}
  </section>;
}
